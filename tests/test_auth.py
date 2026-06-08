"""
End-to-end tests for the auth surface introduced in Step 3.

Each test runs against a fresh in-memory SQLite (see conftest.py) so they
don't depend on each other and don't touch your real DB.
"""
from __future__ import annotations

import pytest

from config.settings import settings as app_settings


@pytest.fixture
def registration_locked(monkeypatch):
    """Simulate a locked-down production box (ALLOW_REGISTRATION=false).

    We flip the attribute on the live settings object, NOT os.environ —
    settings is parsed once at import, so changing the environment afterwards
    has no effect. This is the seam that actually drives the endpoint, and
    monkeypatch auto-restores it when the test finishes.
    """
    monkeypatch.setattr(app_settings, "ALLOW_REGISTRATION", False)


# ── register-enabled probe ────────────────────────────────────────────────────

def test_register_enabled_true_when_no_users(client):
    r = client.get("/api/v1/auth/register-enabled")
    assert r.status_code == 200
    assert r.json() == {"enabled": True}


def test_register_enabled_false_after_first_user_when_locked(client, registration_locked):
    """Locked-down box: once the first user exists, the register form hides."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    r = client.get("/api/v1/auth/register-enabled")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_register_enabled_true_after_first_user_when_open(client):
    """Default (registration open): the form stays available even after the
    first user, so you can keep adding accounts."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    r = client.get("/api/v1/auth/register-enabled")
    assert r.status_code == 200
    assert r.json() == {"enabled": True}


# ── register ──────────────────────────────────────────────────────────────────

def test_register_creates_user_org_membership_and_logs_in(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "Alice@Example.com", "password": "password1", "name": "Alice", "org_name": "Acme"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == "alice@example.com"   # lowercased
    assert data["name"] == "Alice"
    assert data["current_org_id"] is not None
    assert len(data["orgs"]) == 1
    assert data["orgs"][0]["name"] == "Acme"
    assert data["orgs"][0]["role"] == "admin"
    # Cookie was set
    assert any(c.name == "session_token" for c in client.cookies.jar)


def test_register_allows_first_user_even_when_locked(client, registration_locked):
    """Bootstrap: the very first account can always be created through the UI,
    even on a locked-down box, so you're never shut out of an empty system."""
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    assert r.status_code == 200, r.text


def test_register_rejects_second_user_when_locked(client, registration_locked):
    """With registration locked, a SECOND account cannot be created via the API."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    client.cookies.clear()  # emulate a different visitor
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "b@b.com", "password": "password1", "name": "B", "org_name": "Beta"},
    )
    assert r.status_code == 403, r.text


def test_register_allows_second_user_when_open(client):
    """Default (registration open): anyone can create another account."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    client.cookies.clear()
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "b@b.com", "password": "password1", "name": "B", "org_name": "Beta"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "b@b.com"


def test_register_rejects_duplicate_email(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    client.cookies.clear()
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password2", "name": "X", "org_name": "Y"},
    )
    assert r.status_code == 409


def test_register_rejects_short_password(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "short", "name": "A", "org_name": "Acme"},
    )
    # Pydantic min_length validation kicks in first (422). Either is acceptable.
    assert r.status_code in (400, 422)


def test_register_rejects_bad_email(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "no-at-sign", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    assert r.status_code == 400


# ── login ─────────────────────────────────────────────────────────────────────

def test_login_succeeds_with_correct_credentials(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "password1"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "a@b.com"
    assert any(c.name == "session_token" for c in client.cookies.jar)


def test_login_rejects_wrong_password(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "WRONG-password"})
    assert r.status_code == 401


def test_login_does_not_leak_email_existence(client):
    """Same error for wrong email and wrong password — no enumeration."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    client.cookies.clear()
    r1 = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "wrong"})
    r2 = client.post("/api/v1/auth/login", json={"email": "nobody@x.com", "password": "wrong"})
    assert r1.status_code == 401 and r2.status_code == 401
    assert r1.json() == r2.json()


# ── me ────────────────────────────────────────────────────────────────────────

def test_me_requires_auth(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_returns_user_and_orgs(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "Alice", "org_name": "Acme"},
    )
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == "a@b.com"
    assert data["name"] == "Alice"
    assert len(data["orgs"]) == 1
    assert data["orgs"][0]["name"] == "Acme"
    assert data["current_org_id"] == data["orgs"][0]["id"]


# ── logout ────────────────────────────────────────────────────────────────────

def test_logout_clears_session(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    # After logout, /me should be 401 again
    client.cookies.clear()
    r2 = client.get("/api/v1/auth/me")
    assert r2.status_code == 401


def test_logout_is_idempotent_without_session(client):
    """Calling logout with no cookie set should still succeed."""
    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 204


# ── current-org switch ───────────────────────────────────────────────────────

def test_switch_org_requires_membership(client):
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    # Try switching to an org that doesn't exist / user isn't in
    r = client.put("/api/v1/auth/current-org", json={"org_id": 999})
    assert r.status_code == 403


def test_switch_org_succeeds_for_member(client):
    """Create user with one org, add them to a second org directly via DB, then switch."""
    # Register the first user + first org
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@b.com", "password": "password1", "name": "A", "org_name": "Acme"},
    )
    me = client.get("/api/v1/auth/me").json()
    first_org_id = me["current_org_id"]

    # Insert a second org + membership using the same engine as the test client
    from datetime import datetime, timezone
    from sqlmodel import Session
    from memory.models import Organization, UserOrgMembership
    from api.deps import get_db
    from api.main import app

    # Pull the overridden get_db, walk one yield to grab the test session
    db_gen = app.dependency_overrides[get_db]()
    db: Session = next(db_gen)
    now = datetime.now(timezone.utc).isoformat()
    new_org = Organization(name="Beta", currency="GBP", tax_treatment="exclusive",
                           created_at=now, updated_at=now)
    db.add(new_org)
    db.flush()
    db.add(UserOrgMembership(user_id=me["user_id"], org_id=new_org.id, role="admin",
                             created_at=now))
    db.commit()
    new_org_id = new_org.id
    # Drain the generator (commits + closes)
    try:
        next(db_gen)
    except StopIteration:
        pass

    # Now switch
    r = client.put("/api/v1/auth/current-org", json={"org_id": new_org_id})
    assert r.status_code == 200, r.text
    assert r.json()["current_org_id"] == new_org_id
    assert len(r.json()["orgs"]) == 2
