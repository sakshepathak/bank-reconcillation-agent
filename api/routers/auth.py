"""
Auth router — login, logout, register, me, org-switch.

The endpoints exposed here ARE the auth surface. Existing routers don't use
them yet (Step 5 wires enforcement on org-scoped endpoints). For now the auth
machinery is fully working in isolation — verifiable via curl or tests.

Endpoints (all under /api/v1/auth/):
  GET  /register-enabled   — frontend probe: should the register form show?
  POST /register           — create first user (or extra users if ALLOW_REGISTRATION=true)
  POST /login              — email + password, sets session cookie
  POST /logout             — clears session
  GET  /me                 — who am I + which orgs + which is current
  PUT  /current-org        — switch to a different org you're a member of
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from memory.models import Organization, User, UserOrgMembership, UserSession
from config.settings import settings
from api.auth import (
    COOKIE_NAME,
    MAX_PASSWORD_BYTES,
    MIN_PASSWORD_LEN,
    SESSION_DURATION_DAYS,
    build_org_summaries,
    create_session,
    delete_session,
    get_user_memberships,
    hash_password,
    user_is_member_of,
    verify_password,
)
from api.deps import get_db, get_optional_session, require_user

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=MIN_PASSWORD_LEN)
    name: str = Field(default="User", min_length=1)
    org_name: str = Field(default="My Business", min_length=1)


class OrgSummary(BaseModel):
    id: int
    name: str
    role: str


class AuthMeResponse(BaseModel):
    user_id: int
    email: str
    name: str
    current_org_id: Optional[int]
    orgs: list[OrgSummary]


class SwitchOrgRequest(BaseModel):
    org_id: int


class RegisterEnabledResponse(BaseModel):
    enabled: bool


# ── Helpers ──────────────────────────────────────────────────────────────────

def _allow_registration_env() -> bool:
    return settings.ALLOW_REGISTRATION


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        # secure=True in production over HTTPS. Locally we're on http://, so False.
        secure=False,
        samesite="lax",
        max_age=SESSION_DURATION_DAYS * 24 * 3600,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


def _validate_email(email: str) -> str:
    """Per design doc Q3: just check for @. Returns the normalized (lowercased) email."""
    email = email.strip().lower()
    if "@" not in email or len(email) < 3:
        raise HTTPException(status_code=400, detail="Invalid email format")
    return email


def _validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters",
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Password is too long (max {MAX_PASSWORD_BYTES} bytes)",
        )


def _me_response(db: Session, user: User, current_org_id: Optional[int]) -> AuthMeResponse:
    memberships = get_user_memberships(db, user.id)
    summaries = build_org_summaries(db, memberships)
    return AuthMeResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        current_org_id=current_org_id,
        orgs=[OrgSummary(**s) for s in summaries],
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/register-enabled", response_model=RegisterEnabledResponse)
def register_enabled(db: Session = Depends(get_db)) -> RegisterEnabledResponse:
    """Frontend probe: should the register form show?

    Enabled when either no user exists yet (so the first account can always be
    bootstrapped through the UI) OR registration is explicitly allowed via the
    ALLOW_REGISTRATION flag. This keeps the probe honest with what /register
    actually accepts.
    """
    user_exists = db.exec(select(User)).first() is not None
    return RegisterEnabledResponse(enabled=(not user_exists) or _allow_registration_env())


@router.post("/register", response_model=AuthMeResponse)
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> AuthMeResponse:
    """
    Create a user + an org + an admin membership. Auto-logs the new user in.
    Refuses if any user already exists, unless ALLOW_REGISTRATION=true.
    """
    email = _validate_email(body.email)
    _validate_password_strength(body.password)

    # Registration gate: the first user can always bootstrap an account; after
    # that, /register is only open when ALLOW_REGISTRATION is set. Matches the
    # README's production guidance (lock the box down with the flag and create
    # the first user via scripts/create_first_user.py). The default flag is
    # True, so this changes nothing for local dev — it only closes the endpoint
    # on a box that has explicitly set ALLOW_REGISTRATION=false.
    if not _allow_registration_env() and db.exec(select(User)).first() is not None:
        raise HTTPException(status_code=403, detail="Registration is disabled")

    if db.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    now = _now_iso()
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name.strip() or "User",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.flush()  # need user.id without ending the transaction

    org = Organization(
        name=body.org_name.strip() or "My Business",
        currency="GBP",
        tax_treatment="exclusive",
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    db.flush()  # need org.id

    db.add(UserOrgMembership(
        user_id=user.id,
        org_id=org.id,
        role="admin",
        created_at=now,
    ))
    db.commit()

    sess = create_session(db, user.id, org.id)
    _set_session_cookie(response, sess.token)

    return _me_response(db, user, current_org_id=org.id)


@router.post("/login", response_model=AuthMeResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthMeResponse:
    """
    Email + password. Sets the session cookie. Returns the same shape as /me.
    Same error for wrong email and wrong password — don't leak whether an
    address is registered.
    """
    email = body.email.strip().lower()
    user = db.exec(select(User).where(User.email == email)).first()
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    memberships = get_user_memberships(db, user.id)
    current_org_id = memberships[0].org_id if memberships else None

    sess = create_session(db, user.id, current_org_id)
    _set_session_cookie(response, sess.token)

    return _me_response(db, user, current_org_id=current_org_id)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session_token: Optional[str] = Cookie(None, alias=COOKIE_NAME),
    db: Session = Depends(get_db),
) -> Response:
    """Idempotent — succeeds even if there's no session."""
    if session_token:
        delete_session(db, session_token)
    _clear_session_cookie(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=AuthMeResponse)
def me(
    user: User = Depends(require_user),
    sess: Optional[UserSession] = Depends(get_optional_session),
    db: Session = Depends(get_db),
) -> AuthMeResponse:
    """Who am I? Returns current user + all their orgs + which org is selected."""
    current_org_id = sess.current_org_id if sess else None
    return _me_response(db, user, current_org_id=current_org_id)


@router.put("/current-org", response_model=AuthMeResponse)
def switch_org(
    body: SwitchOrgRequest,
    user: User = Depends(require_user),
    sess: UserSession = Depends(get_optional_session),
    db: Session = Depends(get_db),
) -> AuthMeResponse:
    """Switch the session's current org. 403 if user isn't a member of the target."""
    if not user_is_member_of(db, user.id, body.org_id):
        raise HTTPException(status_code=403, detail="You are not a member of that organization")

    sess.current_org_id = body.org_id
    db.add(sess)
    db.commit()

    return _me_response(db, user, current_org_id=body.org_id)
