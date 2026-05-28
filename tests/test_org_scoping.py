"""
Cross-tenant isolation tests for Step 5 (org_id scoping on every router).

The core question these tests answer: if Alice is logged into org A,
can she see or mutate anything that belongs to Bob's org B? Every
test answers "no" — by ID lookup, by list, by reconcile action.

Pattern: register Alice (creates org A + auto-login), create some data,
then register Bob (with ALLOW_REGISTRATION=true) which creates org B
and switches the cookie. Bob then probes Alice's data.

There's a subtle TestClient quirk: cookies persist across requests, so
each switch between Alice/Bob clears them and re-logs-in via /login.
"""
from __future__ import annotations

import os
from contextlib import contextmanager


# ── Fixture helpers ──────────────────────────────────────────────────────────

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
    """Register and stay logged in. Returns the /me response."""
    payload = {"email": email, "password": "password1", "name": email.split("@")[0], "org_name": org_name}
    if allow:
        with _allow_registration():
            r = client.post("/api/v1/auth/register", json=payload)
    else:
        r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _login_as(client, email: str):
    """Drop current cookies and log in as another existing user."""
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password1"})
    assert r.status_code == 200, r.text
    return r.json()


def _make_two_orgs(client) -> tuple[dict, dict]:
    """Returns (alice_me, bob_me). After this call, the client is logged in as Bob."""
    alice = _register(client, "alice@a.com", "Acme")
    # Stay logged in as Alice so the caller can set up Alice's data first.
    return alice, None  # bob lazy-created on demand


def _make_bob(client) -> dict:
    """Add Bob with his own org, leave the client logged in as Bob."""
    client.cookies.clear()
    bob = _register(client, "bob@b.com", "Beta", allow=True)
    return bob


# ── Bank accounts ─────────────────────────────────────────────────────────────

def test_bank_account_invisible_across_orgs(client):
    """Bob cannot see, fetch, patch, reset, or delete Alice's bank account."""
    _register(client, "alice@a.com", "Acme")
    r = client.post("/api/v1/bank-accounts/", json={"name": "Acme Current"})
    assert r.status_code == 201
    acc_id = r.json()["id"]

    _make_bob(client)

    # List → empty
    r = client.get("/api/v1/bank-accounts/")
    assert r.status_code == 200
    assert r.json() == []

    # Direct fetch by id → 404
    assert client.get(f"/api/v1/bank-accounts/{acc_id}").status_code == 404
    # Patch → 404
    assert client.patch(f"/api/v1/bank-accounts/{acc_id}", json={"name": "HACKED"}).status_code == 404
    # Reset → 404
    assert client.post(f"/api/v1/bank-accounts/{acc_id}/reset").status_code == 404
    # Delete → 404
    assert client.delete(f"/api/v1/bank-accounts/{acc_id}").status_code == 404

    # Verify Alice's account is untouched.
    _login_as(client, "alice@a.com")
    r = client.get(f"/api/v1/bank-accounts/{acc_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Current"


# ── Invoices ─────────────────────────────────────────────────────────────────

def _make_invoice(client, contact_name: str = "Cust", number: str = "INV-1") -> int:
    r = client.post(
        "/api/v1/invoices/",
        json={
            "number": number, "contact_name": contact_name,
            "issue_date": "2026-05-01", "lines": [
                {"description": "Work", "quantity": 1, "unit_price": 100.0},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_invoice_invisible_across_orgs(client):
    _register(client, "alice@a.com", "Acme")
    inv_id = _make_invoice(client)

    _make_bob(client)
    assert client.get("/api/v1/invoices/").json() == []
    assert client.get(f"/api/v1/invoices/{inv_id}").status_code == 404
    assert client.patch(f"/api/v1/invoices/{inv_id}", json={"notes": "hacked"}).status_code == 404
    assert client.delete(f"/api/v1/invoices/{inv_id}").status_code == 404

    # Alice still sees it intact.
    _login_as(client, "alice@a.com")
    r = client.get(f"/api/v1/invoices/{inv_id}")
    assert r.status_code == 200
    assert r.json()["notes"] is None


# ── Bills ────────────────────────────────────────────────────────────────────

def _make_bill(client, contact_name: str = "Supp", number: str = "BILL-1") -> int:
    r = client.post(
        "/api/v1/bills/",
        json={
            "number": number, "contact_name": contact_name,
            "issue_date": "2026-05-01", "lines": [
                {"description": "Service", "quantity": 1, "unit_price": 50.0},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_bill_invisible_across_orgs(client):
    _register(client, "alice@a.com", "Acme")
    bill_id = _make_bill(client)

    _make_bob(client)
    assert client.get("/api/v1/bills/").json() == []
    assert client.get(f"/api/v1/bills/{bill_id}").status_code == 404
    assert client.patch(f"/api/v1/bills/{bill_id}", json={"notes": "x"}).status_code == 404
    assert client.delete(f"/api/v1/bills/{bill_id}").status_code == 404


# ── Contacts ─────────────────────────────────────────────────────────────────

def test_contact_invisible_across_orgs(client):
    _register(client, "alice@a.com", "Acme")
    r = client.post("/api/v1/contacts/", json={"full_name": "Big Corp", "contact_type": "customer"})
    assert r.status_code == 201
    contact_id = r.json()["id"]

    _make_bob(client)
    assert client.get("/api/v1/contacts/").json() == []
    assert client.patch(f"/api/v1/contacts/{contact_id}", json={"full_name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/contacts/{contact_id}").status_code == 404


# ── Aliases ──────────────────────────────────────────────────────────────────

def test_alias_invisible_across_orgs(client):
    _register(client, "alice@a.com", "Acme")
    r = client.post(
        "/api/v1/aliases/",
        json={"alias": "AMZN MKTPL", "canonical_name": "Amazon", "confidence": 1.0},
    )
    assert r.status_code == 201
    alias_id = r.json()["id"]

    _make_bob(client)
    assert client.get("/api/v1/aliases/").json() == []
    assert client.delete(f"/api/v1/aliases/{alias_id}").status_code == 404


# ── Statement lines + reconcile across orgs ──────────────────────────────────

def _seed_account_and_line(client, *, received: float = 100.0) -> tuple[int, int]:
    r = client.post("/api/v1/bank-accounts/", json={"name": "Main"})
    assert r.status_code == 201
    acc_id = r.json()["id"]

    r = client.post(
        "/api/v1/statement-lines/import",
        json={
            "bank_account_id": acc_id,
            "lines": [
                {"date": "2026-05-10", "description": "Cust payment", "received": received},
            ],
        },
    )
    assert r.status_code == 201, r.text
    line_id = r.json()[0]["id"]
    return acc_id, line_id


def test_statement_line_invisible_across_orgs(client):
    _register(client, "alice@a.com", "Acme")
    _, line_id = _seed_account_and_line(client)

    _make_bob(client)
    assert client.get("/api/v1/statement-lines/").json() == []
    assert client.get(f"/api/v1/statement-lines/{line_id}").status_code == 404
    assert client.get(f"/api/v1/statement-lines/{line_id}/suggestions").status_code == 404
    # Reconcile actions all 404 against the foreign line
    assert client.post(
        f"/api/v1/statement-lines/{line_id}/match-invoice", json={"invoice_id": 1}
    ).status_code == 404
    assert client.post(
        f"/api/v1/statement-lines/{line_id}/discuss", json={"note": "hi"}
    ).status_code == 404
    assert client.post(f"/api/v1/statement-lines/{line_id}/unreconcile").status_code == 404


def test_cannot_match_line_to_foreign_invoice(client):
    """Alice has a statement line; Bob has an invoice; Alice tries to match across."""
    # Alice setup
    _register(client, "alice@a.com", "Acme")
    _, line_id = _seed_account_and_line(client)

    # Bob creates a foreign invoice
    _make_bob(client)
    bob_inv_id = _make_invoice(client, contact_name="BobsCust", number="BOB-1")

    # Alice tries to attach Bob's invoice to her line — 404 on the cross-tenant invoice
    _login_as(client, "alice@a.com")
    r = client.post(
        f"/api/v1/statement-lines/{line_id}/match-invoice",
        json={"invoice_id": bob_inv_id},
    )
    assert r.status_code == 404
    # Alice's line is still pending — the reconcile attempt left no side effects.
    r = client.get(f"/api/v1/statement-lines/{line_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert r.json()["matched_invoice_id"] is None


def test_cannot_transfer_to_foreign_account(client):
    """Alice has two bank accounts; Bob has one. Alice cannot transfer to Bob's."""
    _register(client, "alice@a.com", "Acme")
    alice_acc, alice_line = _seed_account_and_line(client)

    _make_bob(client)
    r = client.post("/api/v1/bank-accounts/", json={"name": "Bob Main"})
    assert r.status_code == 201
    bob_acc_id = r.json()["id"]

    _login_as(client, "alice@a.com")
    r = client.post(
        f"/api/v1/statement-lines/{alice_line}/transfer",
        json={"to_account_id": bob_acc_id},
    )
    assert r.status_code == 404


# ── Journal entries ──────────────────────────────────────────────────────────

def test_journal_entry_invisible_across_orgs(client):
    _register(client, "alice@a.com", "Acme")
    r = client.post(
        "/api/v1/journal-entries/",
        json={
            "date": "2026-05-15", "description": "Bank fee",
            "amount": -10.0, "tax_rate": 0.0, "currency": "GBP",
        },
    )
    assert r.status_code == 201, r.text
    entry_id = r.json()["id"]

    _make_bob(client)
    assert client.get("/api/v1/journal-entries/").json() == []
    assert client.delete(f"/api/v1/journal-entries/{entry_id}").status_code == 404


# ── Suggestions / exceptions don't leak cross-tenant candidates ──────────────

def test_suggestions_only_return_same_org_invoices(client):
    """Statement line in org A should never see invoices from org B as candidates."""
    _register(client, "alice@a.com", "Acme")
    _, alice_line = _seed_account_and_line(client, received=100.0)
    # No invoice in Alice's org → suggestions empty
    r = client.get(f"/api/v1/statement-lines/{alice_line}/suggestions")
    assert r.status_code == 200
    assert r.json() == []

    # Bob creates a matching invoice in his org
    _make_bob(client)
    _make_invoice(client, contact_name="Cust payment", number="BOB-INV")

    # Back to Alice — suggestions still empty (no candidates in her org)
    _login_as(client, "alice@a.com")
    r = client.get(f"/api/v1/statement-lines/{alice_line}/suggestions")
    assert r.status_code == 200
    assert r.json() == []


def test_bulk_approve_queue_isolated(client):
    _register(client, "alice@a.com", "Acme")
    _seed_account_and_line(client)

    _make_bob(client)
    r = client.get("/api/v1/exceptions/bulk-approve-queue?min_score=0.0")
    assert r.status_code == 200
    assert r.json() == []


def test_duplicates_isolated(client):
    _register(client, "alice@a.com", "Acme")
    _make_invoice(client, contact_name="Same", number="A1")
    _make_invoice(client, contact_name="Same", number="A2")

    _make_bob(client)
    r = client.get("/api/v1/exceptions/duplicates")
    assert r.status_code == 200
    assert r.json() == []


# ── Dashboard / runs / matches don't leak ─────────────────────────────────────

def test_dashboard_isolated(client):
    """Alice has a contact; Bob's dashboard should not count it."""
    _register(client, "alice@a.com", "Acme")
    client.post("/api/v1/contacts/", json={"full_name": "Acme Cust", "contact_type": "customer"})

    _make_bob(client)
    r = client.get("/api/v1/dashboard/stats")
    assert r.status_code == 200
    assert r.json()["total_contacts"] == 0


def test_runs_list_isolated(client):
    """No runs in Bob's org even if Alice had recon records."""
    _register(client, "alice@a.com", "Acme")
    # Runs are populated by the matching engine — we just confirm an empty list
    # in Bob's org doesn't accidentally include Alice's (when she has any).
    _make_bob(client)
    r = client.get("/api/v1/runs/")
    assert r.status_code == 200
    assert r.json() == []


# ── Org dependency itself ────────────────────────────────────────────────────

def test_unauthenticated_request_to_scoped_endpoint_401(client):
    """No session at all → 401 from require_user via get_current_org_id."""
    for path in [
        "/api/v1/invoices/",
        "/api/v1/bills/",
        "/api/v1/bank-accounts/",
        "/api/v1/statement-lines/",
        "/api/v1/contacts/",
        "/api/v1/aliases/",
        "/api/v1/journal-entries/",
        "/api/v1/dashboard/stats",
        "/api/v1/runs/",
        "/api/v1/exceptions/duplicates",
    ]:
        r = client.get(path)
        assert r.status_code == 401, f"{path} returned {r.status_code}"
