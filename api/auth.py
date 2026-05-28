"""
Auth helpers — password hashing and session lifecycle.

Step 3 of the multi-tenant refactor. Adds the machinery (this file +
api/routers/auth.py + new deps in api/deps.py) but does NOT enforce auth
on existing endpoints — that comes in Step 5.

Sessions are server-side: a row in `user_session` per active session, the
token lives in an httpOnly cookie. Sliding renewal on every authenticated
request, lazy cleanup when an expired token is seen.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from sqlmodel import Session, select

from memory.models import Organization, User, UserOrgMembership, UserSession


# ── Constants ────────────────────────────────────────────────────────────────
COOKIE_NAME = "session_token"
SESSION_DURATION_DAYS = 30
BCRYPT_ROUNDS = 12
# bcrypt only uses the first 72 bytes of input. We enforce a max so callers
# don't silently lose tail characters of long passwords.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LEN = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_iso(days: int = SESSION_DURATION_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """bcrypt with cost 12 (~250ms per hash). Returns the stored hash string."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, stored_hash: str) -> bool:
    """Constant-time check. Returns False on any decode/length error rather than raising."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── Session lifecycle ────────────────────────────────────────────────────────

def create_session(db: Session, user_id: int, current_org_id: Optional[int]) -> UserSession:
    """Insert a new session row with a fresh random token. Caller sets cookie."""
    sess = UserSession(
        token=secrets.token_hex(32),                  # 64 hex chars, ~256 bits of entropy
        user_id=user_id,
        current_org_id=current_org_id,
        expires_at=_expiry_iso(),
        created_at=_now_iso(),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def get_session_by_token(db: Session, token: str) -> Optional[UserSession]:
    """
    Look up a session by token. Returns None if missing or expired.
    Expired rows are deleted on read (lazy cleanup) so the table doesn't grow
    indefinitely without a separate cleanup job.
    """
    sess = db.get(UserSession, token)
    if not sess:
        return None
    try:
        expires_dt = datetime.fromisoformat(sess.expires_at)
    except ValueError:
        # Corrupt timestamp — treat as expired and delete.
        db.delete(sess)
        db.commit()
        return None
    if expires_dt < datetime.now(timezone.utc):
        db.delete(sess)
        db.commit()
        return None
    return sess


def renew_session(db: Session, sess: UserSession) -> None:
    """Sliding renewal — push expires_at forward on each authenticated request."""
    sess.expires_at = _expiry_iso()
    db.add(sess)
    db.commit()


def delete_session(db: Session, token: str) -> None:
    """Idempotent logout — does nothing if the token isn't found."""
    sess = db.get(UserSession, token)
    if sess:
        db.delete(sess)
        db.commit()


# ── User / org helpers ───────────────────────────────────────────────────────

def get_user_memberships(db: Session, user_id: int) -> list[UserOrgMembership]:
    """All (user_id, org_id, role) rows for this user, ordered by org_id."""
    return list(db.exec(
        select(UserOrgMembership)
        .where(UserOrgMembership.user_id == user_id)
        .order_by(UserOrgMembership.org_id)
    ).all())


def user_is_member_of(db: Session, user_id: int, org_id: int) -> bool:
    return db.exec(
        select(UserOrgMembership).where(
            UserOrgMembership.user_id == user_id,
            UserOrgMembership.org_id == org_id,
        )
    ).first() is not None


def build_org_summaries(db: Session, memberships: list[UserOrgMembership]) -> list[dict]:
    """Hydrate (id, name, role) for each membership. Skips memberships whose org was deleted."""
    out: list[dict] = []
    for m in memberships:
        org = db.get(Organization, m.org_id)
        if org:
            out.append({"id": org.id, "name": org.name, "role": m.role})
    return out
