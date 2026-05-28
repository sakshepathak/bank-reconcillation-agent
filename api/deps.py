"""FastAPI dependencies — DB session + auth (added in Step 3)."""
from typing import Generator, Optional

from fastapi import Cookie, Depends, HTTPException, status
from sqlmodel import Session

from memory.db import engine
from memory.models import User, UserSession
from api.auth import COOKIE_NAME, get_session_by_token, renew_session


def get_db() -> Generator[Session, None, None]:
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# ── Auth dependencies (Step 3) ───────────────────────────────────────────────
# These are BUILT but NOT YET APPLIED to existing endpoints. Step 5 wires
# them onto routers that need org-scoped access.

def get_optional_session(
    session_token: Optional[str] = Cookie(None, alias=COOKIE_NAME),
    db: Session = Depends(get_db),
) -> Optional[UserSession]:
    """
    Returns the current session if the cookie is valid, else None.
    Does NOT raise — callers that require auth use require_user instead.
    Renews the session (sliding window) when found.
    """
    if not session_token:
        return None
    sess = get_session_by_token(db, session_token)
    if sess is not None:
        renew_session(db, sess)
    return sess


def get_optional_user(
    sess: Optional[UserSession] = Depends(get_optional_session),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """The User row for the current session, or None. Deactivated users are treated as logged out."""
    if not sess:
        return None
    user = db.get(User, sess.user_id)
    if user and user.is_active:
        return user
    return None


def require_user(
    user: Optional[User] = Depends(get_optional_user),
) -> User:
    """401 if no valid session or user is deactivated."""
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def get_current_org_id(
    sess: Optional[UserSession] = Depends(get_optional_session),
    user: User = Depends(require_user),
) -> int:
    """
    Resolves the org the current session is acting on. 401 if not authenticated,
    400 if the session has no current_org_id (user has no orgs / hasn't picked one).
    Every org-scoped endpoint depends on this to get the org filter — the auth
    surface itself (login/register/me) does NOT.
    """
    if not sess or sess.current_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No organization selected for this session",
        )
    return sess.current_org_id
