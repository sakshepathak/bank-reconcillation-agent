"""
Tests for POST /api/v1/orgs and friends — the "add a new business to an
existing logged-in user" flow that powers the "+ Add new organisation"
entry in the OrgSwitcher.

Critical invariants under test:
  • Unauthenticated callers get 401 (no leaking the create endpoint).
  • Creating an org auto-adds an admin membership for the calling user
    AND switches the session's current_org_id so the next request is
    scoped to the new org.
  • The new org is genuinely isolated from data in other orgs.
  • Listing/reading/editing the current org all respect membership.
  • Switch-org works between orgs the user owns.
"""
from __future__ import annotations

import os
from contextlib import contextmanager


@contextmanager
def _allow_registration():
    prev = os.environ.get("ALLOW_REGISTRATION")
    os.environ["ALLOW_REGISTRATION"] = "true"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("ALLOW_REGISTRATION", None)
        else:
            os.environ["ALLOW_REGISTRATION"] = prev


def _register(client, email: str, org_name: str, *, allow: bool = False):
    payload = {"email": email, "password": "password1",
               "name": email.split("@")[0], "org_name": org_name}
    if allow:
        with _allow_registration():
            r = client.post("/api/v1/auth/register", json=payload)
    else:
        r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# ── POST /orgs ───────────────────────────────────────────────────────────────

def test_post_orgs_requires_auth(client):
    r = client.post("/api/v1/orgs/", json={"name": "Anon Biz"})
    assert r.status_code == 401


def test_post_orgs_creates_and_auto_switches(client):
    """Alice registers (gets org A). Then creates org B via POST /orgs.
    Her session should now be scoped to B, and /auth/me should list both."""
    _register(client, "alice@a.com", "Acme")
    me_before = client.get("/api/v1/auth/me").json()
    first_org_id = me_before["current_org_id"]
    assert len(me_before["orgs"]) == 1

    r = client.post("/api/v1/orgs/", json={
        "name": "Beta UK Ltd",
        "country": "GB",
        "currency": "GBP",
        "industry": "Consulting",
        "vat_registered": True,
        "vat_number": "GB123456789",
        "tax_treatment": "exclusive",
        "financial_year_end_day": 5,
        "financial_year_end_month": 4,
    })
    assert r.status_code == 201, r.text
    new_org = r.json()
    assert new_org["name"] == "Beta UK Ltd"
    assert new_org["country"] == "GB"
    assert new_org["currency"] == "GBP"
    assert new_org["vat_registered"] is True
    assert new_org["vat_number"] == "GB123456789"
    assert new_org["financial_year_end_day"] == 5
    assert new_org["financial_year_end_month"] == 4
    assert new_org["role"] == "admin"
    assert new_org["id"] != first_org_id

    # /auth/me now reflects both orgs and the session switched to the new one.
    me_after = client.get("/api/v1/auth/me").json()
    assert me_after["current_org_id"] == new_org["id"]
    assert {o["id"] for o in me_after["orgs"]} == {first_org_id, new_org["id"]}


def test_post_orgs_minimum_payload_defaults_uk(client):
    """Only `name` required; other fields default to UK values."""
    _register(client, "alice@a.com", "Acme")
    r = client.post("/api/v1/orgs/", json={"name": "Solo Trader"})
    assert r.status_code == 201, r.text
    org = r.json()
    assert org["country"] == "GB"
    assert org["currency"] == "GBP"
    assert org["financial_year_end_day"] == 5
    assert org["financial_year_end_month"] == 4
    assert org["vat_registered"] is False
    assert org["vat_number"] is None


def test_post_orgs_isolates_from_existing_org(client):
    """A bill created in org A must not appear in org B's list."""
    _register(client, "alice@a.com", "Acme")
    # Make a bill in org A (auto-switches to A).
    bill_a = client.post("/api/v1/bills/", json={
        "number": "BILL-A", "contact_name": "Supplier A",
        "issue_date": "2026-05-01", "lines": [
            {"description": "Stuff", "quantity": 1, "unit_price": 50.0},
        ],
    })
    assert bill_a.status_code == 201

    # Create org B and auto-switch.
    client.post("/api/v1/orgs/", json={"name": "Beta"})
    bills_in_b = client.get("/api/v1/bills/").json()
    assert bills_in_b == []   # Alice in org B cannot see her org A's bill

    # Switch back to A to confirm the bill is still there.
    me = client.get("/api/v1/auth/me").json()
    org_a = next(o for o in me["orgs"] if o["name"] == "Acme")
    client.put("/api/v1/auth/current-org", json={"org_id": org_a["id"]})
    bills_in_a = client.get("/api/v1/bills/").json()
    assert len(bills_in_a) == 1


def test_post_orgs_rejects_empty_name(client):
    _register(client, "alice@a.com", "Acme")
    r = client.post("/api/v1/orgs/", json={"name": ""})
    assert r.status_code == 422


def test_post_orgs_validates_country_and_currency_length(client):
    _register(client, "alice@a.com", "Acme")
    r = client.post("/api/v1/orgs/", json={
        "name": "Bad", "country": "BAD", "currency": "BAD",
    })
    assert r.status_code == 422


def test_post_orgs_does_not_require_allow_registration(client):
    """Unlike /auth/register, the add-org endpoint works regardless of
    the ALLOW_REGISTRATION env flag — that flag is for bootstrapping users."""
    _register(client, "alice@a.com", "Acme")
    # Default env (no ALLOW_REGISTRATION) — should still succeed.
    assert os.environ.get("ALLOW_REGISTRATION", "").lower() != "true"
    r = client.post("/api/v1/orgs/", json={"name": "Org Without Env"})
    assert r.status_code == 201


# ── GET /orgs ────────────────────────────────────────────────────────────────

def test_list_my_orgs_returns_all_memberships(client):
    _register(client, "alice@a.com", "Acme")
    client.post("/api/v1/orgs/", json={"name": "Beta"})
    client.post("/api/v1/orgs/", json={"name": "Gamma"})

    r = client.get("/api/v1/orgs/")
    assert r.status_code == 200
    names = sorted(o["name"] for o in r.json())
    assert names == ["Acme", "Beta", "Gamma"]
    # All admin since the user created them.
    assert all(o["role"] == "admin" for o in r.json())


def test_list_my_orgs_does_not_leak_other_users_orgs(client):
    _register(client, "alice@a.com", "Acme")
    client.cookies.clear()
    _register(client, "bob@b.com", "Beta", allow=True)
    r = client.get("/api/v1/orgs/")
    assert r.status_code == 200
    names = [o["name"] for o in r.json()]
    assert names == ["Beta"]


# ── GET / PATCH /orgs/current ────────────────────────────────────────────────

def test_get_current_org(client):
    _register(client, "alice@a.com", "Acme UK Ltd")
    r = client.get("/api/v1/orgs/current")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Acme UK Ltd"
    assert body["role"] == "admin"


def test_patch_current_org_updates_fields(client):
    _register(client, "alice@a.com", "OldName")
    r = client.patch("/api/v1/orgs/current", json={
        "name": "NewName Ltd",
        "industry": "SaaS",
        "vat_registered": True,
        "vat_number": "GB999999999",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "NewName Ltd"
    assert body["industry"] == "SaaS"
    assert body["vat_registered"] is True
    assert body["vat_number"] == "GB999999999"


def test_patch_current_org_normalizes_country_and_currency(client):
    _register(client, "alice@a.com", "Acme")
    r = client.patch("/api/v1/orgs/current", json={"country": "gb", "currency": "gbp"})
    assert r.status_code == 200
    assert r.json()["country"] == "GB"
    assert r.json()["currency"] == "GBP"
