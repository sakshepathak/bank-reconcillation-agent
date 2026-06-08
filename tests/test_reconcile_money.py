"""
Money & balance correctness for the reconcile actions in
api/routers/statement_lines.py — the highest-risk area in an accounting app.

These pin down the behaviour the Reconcile screen depends on:
  - Matching a bank line to an invoice/bill updates paid_amount, and flips the
    document to PAID only when it is *fully* paid.
  - A bank account's balance_difference (the number the screen drives to zero)
    hits 0 exactly when a line is reconciled, and returns when it's unreconciled.
  - Unreconcile reverses the money side effects exactly.
  - A line can't be reconciled twice without unreconciling first.
  - Invoice VAT / total arithmetic is correct on create.

Balances are asserted through GET /bank-accounts (which DERIVES them from the
statement lines) and GET /invoices|/bills (paid_amount, outstanding), so these
test the numbers the UI actually shows — not internal fields. Monetary values
use pytest.approx because amounts are floats (see the float caveat in
test_matching.py).
"""
from __future__ import annotations

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _register(client, email="a@b.com"):
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": "password1", "name": "A", "org_name": "Acme",
    })
    assert r.status_code == 200, r.text


def _account_id(client, name="Main"):
    r = client.post("/api/v1/bank-accounts/", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _import_line(client, account_id, *, received=0.0, spent=0.0,
                 date="2026-05-10", desc="Acme Corp"):
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": account_id,
        "lines": [{"date": date, "description": desc,
                   "received": received, "spent": spent}],
    })
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _make_invoice(client, *, number="INV-1", unit_price=100.0, tax_rate=0.0,
                  status="awaiting_payment", contact="Acme Corp"):
    r = client.post("/api/v1/invoices/", json={
        "number": number, "contact_name": contact, "issue_date": "2026-05-01",
        "status": status,
        "lines": [{"description": "Work", "quantity": 1,
                   "unit_price": unit_price, "tax_rate": tax_rate}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _make_bill(client, *, number="BILL-1", unit_price=50.0,
               status="awaiting_payment", contact="Supplier Ltd"):
    r = client.post("/api/v1/bills/", json={
        "number": number, "contact_name": contact, "issue_date": "2026-05-01",
        "status": status,
        "lines": [{"description": "Service", "quantity": 1, "unit_price": unit_price}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _account(client, account_id):
    r = client.get(f"/api/v1/bank-accounts/{account_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _invoice(client, invoice_id):
    r = client.get(f"/api/v1/invoices/{invoice_id}")
    assert r.status_code == 200, r.text
    return r.json()


def _bill(client, bill_id):
    r = client.get(f"/api/v1/bills/{bill_id}")
    assert r.status_code == 200, r.text
    return r.json()


# ── Matching an invoice (money in) ─────────────────────────────────────────────

def test_match_invoice_full_payment_marks_paid_and_clears_difference(client):
    _register(client)
    acc = _account_id(client)
    line_id = _import_line(client, acc, received=100.0)
    inv = _make_invoice(client, unit_price=100.0)

    # Before: the imported line is pending, so the whole 100 is unreconciled.
    before = _account(client, acc)
    assert before["balance_difference"] == pytest.approx(100.0)
    assert before["pending_count"] == 1

    r = client.post(f"/api/v1/statement-lines/{line_id}/match-invoice",
                    json={"invoice_id": inv["id"]})
    assert r.status_code == 200, r.text

    paid = _invoice(client, inv["id"])
    assert paid["paid_amount"] == pytest.approx(100.0)
    assert paid["outstanding"] == pytest.approx(0.0)
    assert paid["status"] == "paid"

    after = _account(client, acc)
    assert after["ooo_balance"] == pytest.approx(100.0)
    assert after["balance_difference"] == pytest.approx(0.0)
    assert after["pending_count"] == 0


def test_match_invoice_partial_payment_leaves_outstanding(client):
    _register(client)
    acc = _account_id(client)
    line_id = _import_line(client, acc, received=40.0)
    inv = _make_invoice(client, unit_price=100.0)

    r = client.post(f"/api/v1/statement-lines/{line_id}/match-invoice",
                    json={"invoice_id": inv["id"]})
    assert r.status_code == 200, r.text

    paid = _invoice(client, inv["id"])
    assert paid["paid_amount"] == pytest.approx(40.0)
    assert paid["outstanding"] == pytest.approx(60.0)
    assert paid["status"] == "awaiting_payment"   # NOT paid — only partly covered

    # The bank line itself is fully reconciled, so the account difference clears.
    after = _account(client, acc)
    assert after["ooo_balance"] == pytest.approx(40.0)
    assert after["balance_difference"] == pytest.approx(0.0)


def test_unreconcile_reverses_invoice_match_exactly(client):
    _register(client)
    acc = _account_id(client)
    line_id = _import_line(client, acc, received=100.0)
    inv = _make_invoice(client, unit_price=100.0)

    client.post(f"/api/v1/statement-lines/{line_id}/match-invoice",
                json={"invoice_id": inv["id"]})

    r = client.post(f"/api/v1/statement-lines/{line_id}/unreconcile")
    assert r.status_code == 200, r.text

    # Invoice money is fully restored.
    inv_after = _invoice(client, inv["id"])
    assert inv_after["paid_amount"] == pytest.approx(0.0)
    assert inv_after["outstanding"] == pytest.approx(100.0)
    assert inv_after["status"] == "awaiting_payment"

    # Account is back to fully-unreconciled.
    after = _account(client, acc)
    assert after["ooo_balance"] == pytest.approx(0.0)
    assert after["balance_difference"] == pytest.approx(100.0)
    assert after["pending_count"] == 1

    # The line is pending again with no link.
    line = r.json()
    assert line["status"] == "pending"
    assert line["matched_invoice_id"] is None
    assert line["reconciled_at"] is None


# ── Matching a bill (money out) ────────────────────────────────────────────────

def test_match_bill_full_payment(client):
    _register(client)
    acc = _account_id(client)
    bill = _make_bill(client, unit_price=50.0)
    line_id = _import_line(client, acc, spent=50.0, desc="Supplier Ltd")

    r = client.post(f"/api/v1/statement-lines/{line_id}/match-bill",
                    json={"bill_id": bill["id"]})
    assert r.status_code == 200, r.text

    paid = _bill(client, bill["id"])
    assert paid["paid_amount"] == pytest.approx(50.0)
    assert paid["outstanding"] == pytest.approx(0.0)
    assert paid["status"] == "paid"

    # Money out → the app-side balance goes negative by the spend.
    after = _account(client, acc)
    assert after["ooo_balance"] == pytest.approx(-50.0)
    assert after["balance_difference"] == pytest.approx(0.0)


# ── Guard: a line can't be reconciled twice ───────────────────────────────────

def test_cannot_reconcile_a_line_twice(client):
    _register(client)
    acc = _account_id(client)
    line_id = _import_line(client, acc, received=100.0)
    inv = _make_invoice(client, unit_price=100.0)

    first = client.post(f"/api/v1/statement-lines/{line_id}/match-invoice",
                        json={"invoice_id": inv["id"]})
    assert first.status_code == 200

    # Second attempt on the same (now MATCHED) line is rejected.
    second = client.post(f"/api/v1/statement-lines/{line_id}/match-invoice",
                         json={"invoice_id": inv["id"]})
    assert second.status_code == 409

    # Unreconcile frees it, then it can be matched again.
    assert client.post(f"/api/v1/statement-lines/{line_id}/unreconcile").status_code == 200
    again = client.post(f"/api/v1/statement-lines/{line_id}/match-invoice",
                        json={"invoice_id": inv["id"]})
    assert again.status_code == 200


# ── Pure arithmetic: VAT on invoice create ────────────────────────────────────

def test_invoice_vat_total_on_create(client):
    _register(client)
    inv = _make_invoice(client, unit_price=100.0, tax_rate=0.20)
    # subtotal 100, 20% VAT = 20, total 120.
    assert inv["subtotal"] == pytest.approx(100.0)
    assert inv["tax_total"] == pytest.approx(20.0)
    assert inv["total"] == pytest.approx(120.0)
    assert inv["outstanding"] == pytest.approx(120.0)


# ── The core invariant: difference = net of still-pending lines ───────────────

def test_balance_difference_is_net_of_pending_lines(client):
    _register(client)
    acc = _account_id(client)
    _import_line(client, acc, received=100.0, desc="Customer")
    _import_line(client, acc, spent=30.0, desc="Supplier")

    a = _account(client, acc)
    # Bank says net +70; nothing is reconciled yet, so the whole 70 is the gap.
    assert a["statement_balance"] == pytest.approx(70.0)
    assert a["ooo_balance"] == pytest.approx(0.0)
    assert a["balance_difference"] == pytest.approx(70.0)
    assert a["pending_count"] == 2
