"""
Reset a user's password from the command line.

This is the v1 "forgot password" path. No email reset / token flow yet —
you run this script locally and pick a new password.

Usage:
    py -3.13 scripts/reset_password.py             # interactive — lists users, prompts for choice
    py -3.13 scripts/reset_password.py <email>     # skip the list, just reset this user

Also invalidates any active sessions for that user (forces re-login).
"""
from __future__ import annotations

import getpass
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlmodel import select

from memory.db import get_session
from memory.models import User, UserSession


_MIN_PASSWORD_LEN = 8
_MAX_PASSWORD_BYTES = 72


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_password(label: str) -> str:
    try:
        return getpass.getpass(f"{label}: ")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)


def _hash_password(plain: str) -> str:
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _pick_user(email_arg: str | None) -> User:
    with get_session() as s:
        users = list(s.exec(select(User)).all())
        if not users:
            print("ERROR: No users in DB. Run scripts/create_first_user.py first.")
            sys.exit(2)

        if email_arg:
            target = email_arg.strip().lower()
            for u in users:
                if u.email == target:
                    return u
            print(f"ERROR: No user found with email {email_arg!r}.")
            print("Existing users:")
            for u in users:
                print(f"  - {u.email}")
            sys.exit(3)

        # Interactive — show users + prompt for email.
        print("Users in DB:")
        for u in users:
            mark = "" if u.is_active else "  (deactivated)"
            print(f"  - {u.email}  ({u.name}){mark}")
        print()
        chosen = input("Email of user to reset: ").strip().lower()
        for u in users:
            if u.email == chosen:
                return u
        print(f"ERROR: '{chosen}' not in the list.")
        sys.exit(3)


def main() -> int:
    email_arg = sys.argv[1] if len(sys.argv) > 1 else None

    user = _pick_user(email_arg)
    print()
    print(f"Resetting password for: {user.email}  (id={user.id}, name={user.name!r})")
    print()

    while True:
        password = _read_password(f"New password (min {_MIN_PASSWORD_LEN} chars)")
        if len(password) < _MIN_PASSWORD_LEN:
            print(f"  -> Must be at least {_MIN_PASSWORD_LEN} characters.")
            continue
        if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
            print(f"  -> Too long (bcrypt limit is {_MAX_PASSWORD_BYTES} bytes).")
            continue
        confirm = _read_password("Confirm")
        if password != confirm:
            print("  -> Passwords don't match.")
            continue
        break

    new_hash = _hash_password(password)
    del password, confirm

    # Re-read inside its own session and update — keeps the txn small.
    with get_session() as s:
        target = s.get(User, user.id)
        if target is None:
            print(f"ERROR: User id={user.id} vanished between fetch and update.")
            return 4
        target.password_hash = new_hash
        target.updated_at = _now_iso()
        s.add(target)

        # Invalidate every active session for this user — forces re-login
        # everywhere they're currently signed in.
        revoked = s.exec(
            select(UserSession).where(UserSession.user_id == user.id)
        ).all()
        for sess in revoked:
            s.delete(sess)

    print()
    print("=" * 60)
    print("Password reset successful.")
    print(f"  User:                {user.email}")
    print(f"  Sessions invalidated: {len(revoked)}")
    print("=" * 60)
    print()
    print("You can now log in with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
