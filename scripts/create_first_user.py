"""
First-user bootstrap — creates the initial User + Organization + Membership.

Run this ONCE after Step 1, before login is wired up in Step 3:

    py -3.13 scripts/create_first_user.py

Refuses to run if any user already exists, unless ALLOW_REGISTRATION=true.

This is the CLI-only path to creating an account. Once Step 3+ are in place,
new users will be created via the registration flow in the web UI (gated by
the same ALLOW_REGISTRATION env var).
"""
from __future__ import annotations

import getpass
import os
import sys
from datetime import datetime, timezone

# Ensure project root on sys.path when this file is run directly.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlmodel import select

from memory.db import engine, get_session
from memory.models import Organization, User, UserOrgMembership


_MIN_PASSWORD_LEN = 8
# bcrypt only uses the first 72 bytes of input. Reject longer to make this
# behaviour explicit instead of silently truncating.
_MAX_PASSWORD_BYTES = 72
_ALLOW_REGISTRATION = os.environ.get("ALLOW_REGISTRATION", "").lower() == "true"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prompt(question: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{question}{suffix}: ").strip()
    return value or (default or "")


def _read_password(label: str) -> str:
    try:
        return getpass.getpass(f"{label}: ")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)


def _hash_password(plain: str) -> str:
    # Import locally so the rest of the script can give a helpful error if
    # the dep isn't installed yet. bcrypt cost 12 ≈ 250ms per hash.
    import bcrypt
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _check_tables_exist() -> None:
    """Confirm Step 1 has run (the four tables we depend on are present)."""
    from sqlalchemy import inspect

    required = {"organization", "user", "user_org_membership"}
    existing = set(inspect(engine).get_table_names())
    missing = required - existing
    if missing:
        print(f"ERROR: Required tables not found: {sorted(missing)}")
        print("Fix: start the app once (uvicorn api.main:app) — init_db will")
        print("     create them — then re-run this script.")
        sys.exit(2)


def _check_no_existing_user() -> None:
    with get_session() as s:
        existing = s.exec(select(User)).first()
    if existing and not _ALLOW_REGISTRATION:
        print(f"ERROR: A user already exists ({existing.email}).")
        print("Refusing to create another to avoid accidental account sprawl.")
        print("If you really want to add a second user, re-run with:")
        print("    ALLOW_REGISTRATION=true py -3.13 scripts/create_first_user.py")
        sys.exit(3)


def _validate_email(email: str) -> str | None:
    if "@" not in email or len(email) < 3:
        return "Email must contain '@' and be at least 3 characters."
    return None


def main() -> int:
    print("=" * 60)
    print("First-user bootstrap — Bank Reconciliation")
    print("=" * 60)
    print()

    _check_tables_exist()
    _check_no_existing_user()

    while True:
        email = _prompt("Your email").lower()
        err = _validate_email(email)
        if err:
            print(f"  -> {err}")
            continue
        break

    name = _prompt("Your name (display)", default="User")
    org_name = _prompt("Business name", default="My Business")

    while True:
        password = _read_password(f"Password (min {_MIN_PASSWORD_LEN} chars)")
        if len(password) < _MIN_PASSWORD_LEN:
            print(f"  -> Password must be at least {_MIN_PASSWORD_LEN} characters.")
            continue
        if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
            print(f"  -> Password is too long (bcrypt limit is {_MAX_PASSWORD_BYTES} bytes).")
            continue
        confirm = _read_password("Confirm password")
        if password != confirm:
            print("  -> Passwords don't match. Try again.")
            continue
        break

    now = _now()
    password_hash = _hash_password(password)
    # Drop plaintext password references promptly.
    del password, confirm

    with get_session() as s:
        # Defensive duplicate check (covers the ALLOW_REGISTRATION=true case).
        if s.exec(select(User).where(User.email == email)).first():
            print(f"ERROR: A user with email '{email}' already exists.")
            return 4

        user = User(
            email=email,
            password_hash=password_hash,
            name=name,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        s.add(user)
        s.flush()  # populate user.id without ending the transaction

        org = Organization(
            name=org_name,
            currency="GBP",
            tax_treatment="exclusive",
            created_at=now,
            updated_at=now,
        )
        s.add(org)
        s.flush()  # populate org.id

        membership = UserOrgMembership(
            user_id=user.id,
            org_id=org.id,
            role="admin",
            created_at=now,
        )
        s.add(membership)

    print()
    print("=" * 60)
    print("Success.")
    print(f"  User:    id={user.id}  email={user.email}  name={user.name}")
    print(f"  Org:     id={org.id}  name={org.name}  currency={org.currency}")
    print(f"  Role:    admin (in org {org.id})")
    print("=" * 60)
    print()
    print("Next: Step 3 wires login. Until then, the app behaves as before —")
    print("nothing in the running UI will use these records yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
