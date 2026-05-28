"""
End-to-end "Add new organisation" flow tests.

Simulates exactly what the browser does:
  1. Register Alice → she's on org A.
  2. Seed org A with data (bills, invoices, contacts, aliases, bank account).
  3. POST /api/v1/orgs/ to create org B.
  4. Backend auto-switches her session to B.
  5. Every list endpoint must return empty for org B (no leak from A).
  6. Switch back to A → every list endpoint must restore A's data.

The point of these tests is to catch any backend-side leak that the
frontend cache trick can't paper over. The frontend `removeQueries` in
auth-context.tsx protects against a stale-cache leak; these tests protect
against a missing-`WHERE org_id` leak.
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


def _register_alice(client) -> dict:
    r = client.post("/api/v1/auth/register", json={
        "email": "alice@a.com", "password": "password1",
        "name": "Alice", "org_name": "Acme",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _seed_org_with_data(client) -> dict[str, int]:
    """Create one of every kind of org-scoped row. Returns a dict of ids."""
    ids: dict[str, int] = {}

    r = client.post("/api/v1/bank-accounts/", json={"name": "Acme Current"})
    assert r.status_code == 201
    ids["bank_account"] = r.json()["id"]

    r = client.post("/api/v1/contacts/", json={
        "full_name": "Acme Customer", "contact_type": "customer",
    })
    assert r.status_code == 201
    ids["contact"] = r.json()["id"]

    r = client.post("/api/v1/invoices/", json={
        "number": "INV-1", "contact_name": "Acme Customer",
        "issue_date": "2026-05-01", "lines": [
            {"description": "Work", "quantity": 1, "unit_price": 100.0},
        ],
    })
    assert r.status_code == 201
    ids["invoice"] = r.json()["id"]

    r = client.post("/api/v1/bills/", json={
        "number": "BILL-1", "contact_name": "Acme Supplier",
        "issue_date": "2026-05-02", "lines": [
            {"description": "Stuff", "quantity": 1, "unit_price": 50.0},
        ],
    })
    assert r.status_code == 201
    ids["bill"] = r.json()["id"]

    r = client.post("/api/v1/aliases/", json={
        "alias": "ACME PAYMENT", "canonical_name": "Acme Customer", "confidence": 1.0,
    })
    assert r.status_code == 201
    ids["alias"] = r.json()["id"]

    r = client.post("/api/v1/journal-entries/", json={
        "date": "2026-05-03", "description": "Coffee",
        "amount": -5.0, "tax_rate": 0.0, "currency": "GBP",
    })
    assert r.status_code == 201
    ids["journal"] = r.json()["id"]

    r = client.post(
        "/api/v1/statement-lines/import",
        json={
            "bank_account_id": ids["bank_account"],
            "lines": [{"date": "2026-05-04", "description": "ACME PAYMENT", "received": 100.0}],
        },
    )
    assert r.status_code == 201
    ids["statement_line"] = r.json()[0]["id"]

    return ids


def _assert_empty_for_current_org(client) -> None:
    """Every list endpoint must return [] / zero counts in the active org."""
    assert client.get("/api/v1/bank-accounts/").json() == []
    assert client.get("/api/v1/contacts/").json() == []
    assert client.get("/api/v1/invoices/").json() == []
    assert client.get("/api/v1/bills/").json() == []
    assert client.get("/api/v1/aliases/").json() == []
    assert client.get("/api/v1/journal-entries/").json() == []
    assert client.get("/api/v1/statement-lines/").json() == []
    assert client.get("/api/v1/runs/").json() == []
    assert client.get("/api/v1/exceptions/duplicates").json() == []
    # bulk-approve-queue accepts min_score; 0.0 floor shows everything.
    assert client.get("/api/v1/exceptions/bulk-approve-queue?min_score=0.0").json() == []
    # Dashboard counters should also be zero.
    stats = client.get("/api/v1/dashboard/stats").json()
    assert stats["total_contacts"] == 0
    assert stats["total_transactions"] == 0
    assert stats["total_runs"] == 0


def _assert_alice_org_a_data_intact(client, ids: dict[str, int]) -> None:
    """After switching back to org A, all the seeded data is still there."""
    bas = client.get("/api/v1/bank-accounts/").json()
    assert any(b["id"] == ids["bank_account"] for b in bas)

    cs = client.get("/api/v1/contacts/").json()
    assert any(c["id"] == ids["contact"] for c in cs)

    invs = client.get("/api/v1/invoices/").json()
    assert any(i["id"] == ids["invoice"] for i in invs)

    bills = client.get("/api/v1/bills/").json()
    assert any(b["id"] == ids["bill"] for b in bills)

    aliases = client.get("/api/v1/aliases/").json()
    assert any(a["id"] == ids["alias"] for a in aliases)

    journals = client.get("/api/v1/journal-entries/").json()
    assert any(j["id"] == ids["journal"] for j in journals)

    lines = client.get("/api/v1/statement-lines/").json()
    assert any(l["id"] == ids["statement_line"] for l in lines)


# ── The single test that exercises the whole flow ───────────────────────────

def test_add_new_org_flow_creates_fresh_isolated_org(client):
    """
    The end-to-end flow the user described:
      register Alice → seed org A → click "+ Add new organisation" →
      submit form → land on dashboard scoped to a fresh empty org B →
      switch back to A → org A data is untouched.
    """
    me = _register_alice(client)
    org_a_id = me["current_org_id"]

    ids = _seed_org_with_data(client)

    # Sanity check: data is visible in org A right now.
    _assert_alice_org_a_data_intact(client, ids)

    # The Onboarding form submission, in HTTP terms.
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
    org_b = r.json()
    org_b_id = org_b["id"]
    assert org_b_id != org_a_id

    # The session has been auto-switched. /auth/me reflects org B.
    me_after = client.get("/api/v1/auth/me").json()
    assert me_after["current_org_id"] == org_b_id

    # Org B is genuinely fresh — every list endpoint empty.
    _assert_empty_for_current_org(client)

    # Switch back to org A — original data is intact (no leak the other way).
    r = client.put("/api/v1/auth/current-org", json={"org_id": org_a_id})
    assert r.status_code == 200
    _assert_alice_org_a_data_intact(client, ids)


def test_two_users_two_orgs_no_cross_leak(client):
    """Bob's data must never appear in Alice's org and vice versa, even after
    each adds an extra org of their own."""
    _register_alice(client)
    alice_bill = client.post("/api/v1/bills/", json={
        "number": "BILL-ALICE", "contact_name": "Alice Supplier",
        "issue_date": "2026-05-01", "lines": [
            {"description": "x", "quantity": 1, "unit_price": 10.0},
        ],
    }).json()
    client.post("/api/v1/orgs/", json={"name": "Alice Side Project"})
    # Alice now has 2 orgs, currently on the new one (empty).
    assert client.get("/api/v1/bills/").json() == []

    # Bob registers, creates his own extra org.
    client.cookies.clear()
    with _allow_registration():
        r = client.post("/api/v1/auth/register", json={
            "email": "bob@b.com", "password": "password1",
            "name": "Bob", "org_name": "Bob Co",
        })
    assert r.status_code == 200
    client.post("/api/v1/orgs/", json={"name": "Bob Side Project"})

    # Bob in his new org — never sees Alice's bills no matter which org he picks.
    me = client.get("/api/v1/auth/me").json()
    for org in me["orgs"]:
        client.put("/api/v1/auth/current-org", json={"org_id": org["id"]})
        bills = client.get("/api/v1/bills/").json()
        # Should NEVER contain Alice's bill, regardless of which Bob-org we're on.
        assert all(b["id"] != alice_bill["id"] for b in bills), \
            f"Alice's bill leaked into Bob's org {org['name']}!"


def test_create_org_does_not_pollute_other_users_membership(client):
    """When Alice creates a new org, Bob must not become a member of it."""
    _register_alice(client)
    client.post("/api/v1/orgs/", json={"name": "Alice Private"})

    client.cookies.clear()
    with _allow_registration():
        r = client.post("/api/v1/auth/register", json={
            "email": "bob@b.com", "password": "password1",
            "name": "Bob", "org_name": "Bob Co",
        })
    assert r.status_code == 200

    bob_orgs = client.get("/api/v1/orgs/").json()
    bob_org_names = [o["name"] for o in bob_orgs]
    assert "Alice Private" not in bob_org_names
    assert bob_org_names == ["Bob Co"]
