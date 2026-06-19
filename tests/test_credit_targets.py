"""
Allocating a held credit must find its eligible bills/invoices for ALL the ways a
credit can come to exist — most importantly a PREPAYMENT booked by typing a vendor
name (which used to be saved with contact_id=None and could then never be matched
to that vendor's bills).

The backend is the single source of truth: GET /credits/{id}/targets returns
exactly the documents allocate_credit will accept. These tests pin that contract.

Rules under test:
  • prepayment booked by name resolves to a real contact and is allocatable
  • targets list == what allocate accepts (same contact, currency, open, owing)
  • a credit with a NULL contact_id (legacy data) still matches by name
  • different contact / currency / paid / fully-allocated are excluded
  • targets is org-scoped
"""
import os
from contextlib import contextmanager

from sqlmodel import Session

from memory.models import CreditNote


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


def _setup(client, email="t@t.com", org="Co") -> int:
    with _allow_registration():
        r = client.post("/api/v1/auth/register", json={
            "email": email, "password": "password1", "name": "T", "org_name": org})
    assert r.status_code == 200, r.text
    return client.post("/api/v1/bank-accounts/", json={"name": "Checking"}).json()["id"]


def _bill(client, name, amount, number, currency="GBP", status="awaiting_payment") -> int:
    r = client.post("/api/v1/bills/", json={
        "number": number, "contact_name": name, "issue_date": "2026-04-01",
        "currency": currency, "status": status,
        "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _invoice(client, name, amount, number, currency="GBP", status="awaiting_payment") -> int:
    r = client.post("/api/v1/invoices/", json={
        "number": number, "contact_name": name, "issue_date": "2026-04-01",
        "currency": currency, "status": status,
        "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _line_out(client, acc, desc, spent, date="2026-04-28") -> int:
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc, "lines": [{"date": date, "description": desc, "spent": spent}]})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _line_in(client, acc, desc, received, date="2026-04-28") -> int:
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc, "lines": [{"date": date, "description": desc, "received": received}]})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _book_prepayment(client, line, contact_name) -> int:
    """Book a prepayment by NAME only (no contact_id) — the path that used to orphan
    the credit. Returns the credit id."""
    r = client.post(f"/api/v1/statement-lines/{line}/book-credit",
                    json={"kind": "prepayment", "contact_name": contact_name})
    assert r.status_code == 200, r.text
    return r.json()["matched_credit_id"]


def _targets(client, cid) -> list[dict]:
    r = client.get(f"/api/v1/credits/{cid}/targets")
    assert r.status_code == 200, r.text
    return r.json()


def _target_ids(client, cid) -> set[int]:
    return {t["id"] for t in _targets(client, cid)}


def _credit(client, cid) -> dict:
    return client.get(f"/api/v1/credits/{cid}").json()


def _allocate(client, cid, target_id, amount, target_type="bill"):
    return client.post(f"/api/v1/credits/{cid}/allocate",
                       json={"target_type": target_type, "target_id": target_id, "amount": amount})


# ── The reported bug: prepayment booked by name, then allocate ───────────────

def test_prepayment_booked_by_name_is_allocatable_end_to_end(client):
    """The exact symptom: a prepayment booked by typing 'abc' must list, and
    apply to, the open 'abc' bill — not show 'no matching bills'."""
    acc = _setup(client)
    bill = _bill(client, "abc", 8500.0, "BILL-ABC")
    line = _line_out(client, acc, "Payroll May 2026", 8500.0)
    cid = _book_prepayment(client, line, "abc")

    # Booking now resolves the typed name to a real contact id.
    assert _credit(client, cid)["contact_id"] is not None

    # The dialog's source of truth offers exactly that bill.
    assert bill in _target_ids(client, cid)

    # And the allocation goes through end-to-end.
    r = _allocate(client, cid, bill, 8500.0)
    assert r.status_code == 200, r.text
    assert _credit(client, cid)["outstanding"] == 0.0
    assert next(b for b in client.get("/api/v1/bills/").json() if b["id"] == bill)["status"] == "paid"


def test_prepayment_with_null_contact_id_still_matches_by_name(client, test_engine):
    """Legacy credits saved before the fix have contact_id=None. The name fallback
    must still surface the matching bill and allow allocation."""
    acc = _setup(client)
    bill = _bill(client, "abc", 8500.0, "BILL-ABC")
    line = _line_out(client, acc, "Payroll", 8500.0)
    cid = _book_prepayment(client, line, "abc")

    # Simulate the legacy orphaned row: blank out the contact_id directly.
    with Session(test_engine) as db:
        cn = db.get(CreditNote, cid)
        cn.contact_id = None
        db.add(cn)
        db.commit()
    assert _credit(client, cid)["contact_id"] is None

    # Fallback: matched by normalized contact_name even with no id.
    assert bill in _target_ids(client, cid)
    assert _allocate(client, cid, bill, 8500.0).status_code == 200


# ── targets == what allocate accepts ─────────────────────────────────────────

def test_targets_excludes_other_contact_currency_and_paid(client):
    acc = _setup(client)
    line = _line_out(client, acc, "ACME", 1000.0)
    cid = _book_prepayment(client, line, "Acme")

    ok = _bill(client, "Acme", 500.0, "OK")            # eligible
    usd = _bill(client, "Acme", 500.0, "USD", currency="USD")   # wrong currency
    other = _bill(client, "Zeta", 500.0, "OTHER")      # different contact

    ids = _target_ids(client, cid)
    assert ok in ids
    assert usd not in ids
    assert other not in ids

    # Excluded docs are also refused by allocate — the two layers agree.
    assert _allocate(client, cid, usd, 100.0).status_code == 422
    assert _allocate(client, cid, other, 100.0).status_code == 422

    # Once the eligible bill is fully paid it drops out of the target list.
    assert _allocate(client, cid, ok, 500.0).status_code == 200
    assert ok not in _target_ids(client, cid)


def test_targets_empty_when_credit_fully_allocated(client):
    acc = _setup(client)
    line = _line_out(client, acc, "ACME", 800.0)
    cid = _book_prepayment(client, line, "Acme")
    bill = _bill(client, "Acme", 800.0, "B1")
    assert _allocate(client, cid, bill, 800.0).status_code == 200
    assert _credit(client, cid)["status"] == "paid"
    assert _targets(client, cid) == []


# ── receivable side (invoices) ───────────────────────────────────────────────

def test_receivable_prepayment_targets_invoices(client):
    acc = _setup(client)
    line = _line_in(client, acc, "FROM CUSTOMER", 600.0)
    cid = _book_prepayment(client, line, "Globex")
    inv = _invoice(client, "Globex", 600.0, "INV-1")

    assert inv in _target_ids(client, cid)
    assert _allocate(client, cid, inv, 600.0, target_type="invoice").status_code == 200
    assert _credit(client, cid)["outstanding"] == 0.0


# ── org scoping ──────────────────────────────────────────────────────────────

def test_targets_are_org_scoped(client):
    acc = _setup(client)
    line = _line_out(client, acc, "ACME", 500.0)
    cid = _book_prepayment(client, line, "Acme")

    # Switch to a second org — the first org's credit must be invisible.
    assert client.post("/api/v1/orgs/", json={"name": "Other Co"}).status_code == 201
    assert client.get(f"/api/v1/credits/{cid}/targets").status_code == 404
