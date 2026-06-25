"""
Phase 3 (split / partial payment): a bank line that part-pays ONE bill/invoice.

The document is left PARTIALLY PAID (remainder still owing) and keeps status
awaiting_payment; the line reuses the single-match storage so unreconcile reverses
it with no drift; partial-targets is VENDOR-GATED (never a cross-vendor partial);
and a partially-paid document cannot be deleted until the line is unreconciled.
"""
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


def _setup(client) -> int:
    with _allow_registration():
        r = client.post("/api/v1/auth/register", json={
            "email": "u@u.com", "password": "password1", "name": "U", "org_name": "Co",
        })
    assert r.status_code == 200, r.text
    return client.post("/api/v1/bank-accounts/", json={"name": "Checking"}).json()["id"]


def _ooo(client, acc_id) -> float:
    acc = next(a for a in client.get("/api/v1/bank-accounts/").json() if a["id"] == acc_id)
    return acc["ooo_balance"]


def _status(client, line_id) -> str:
    return client.get(f"/api/v1/statement-lines/{line_id}").json()["status"]


def _bill(client, name, amount, number, issue, status="awaiting_payment") -> int:
    r = client.post("/api/v1/bills/", json={
        "number": number, "contact_name": name, "issue_date": issue, "status": status,
        "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bill_row(client, bill_id) -> dict:
    return next(b for b in client.get("/api/v1/bills/").json() if b["id"] == bill_id)


def _invoice(client, name, amount, number, issue, status="awaiting_payment") -> int:
    r = client.post("/api/v1/invoices/", json={
        "number": number, "contact_name": name, "issue_date": issue, "status": status,
        "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _invoice_row(client, inv_id) -> dict:
    return next(i for i in client.get("/api/v1/invoices/").json() if i["id"] == inv_id)


def _line_out(client, acc, desc, spent, date) -> int:
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc, "lines": [{"date": date, "description": desc, "spent": spent}]})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _line_in(client, acc, desc, received, date) -> int:
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc, "lines": [{"date": date, "description": desc, "received": received}]})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _match_partial(client, line, target_type, target_id):
    return client.post(f"/api/v1/statement-lines/{line}/match-partial",
                       json={"target_type": target_type, "target_id": target_id})


def _partial_targets(client, line) -> list:
    r = client.get(f"/api/v1/statement-lines/{line}/partial-targets")
    assert r.status_code == 200, r.text
    return r.json()


# ── Core: a partial part-pays a bill, leaving a remainder ─────────────────────

def test_partial_part_pays_bill_and_leaves_remainder(client):
    acc = _setup(client)
    bal0 = _ooo(client, acc)
    bill = _bill(client, "Inkwell Print Co", 1000.0, "BILL-1", "2026-04-01")
    line = _line_out(client, acc, "INKWELL PRINT CO", 400.0, "2026-04-12")

    r = _match_partial(client, line, "bill", bill)
    assert r.status_code == 200, r.text

    row = _bill_row(client, bill)
    assert row["paid_amount"] == 400.0
    assert row["outstanding"] == 600.0
    assert row["status"] == "awaiting_payment"               # stays open
    assert _status(client, line) == "matched"
    assert abs(_ooo(client, acc) - (bal0 - 400.0)) < 0.001    # full line cleared the bank


def test_partial_unreconcile_restores_everything(client):
    acc = _setup(client)
    bal0 = _ooo(client, acc)
    bill = _bill(client, "Inkwell Print Co", 1000.0, "BILL-1", "2026-04-01")
    line = _line_out(client, acc, "INKWELL PRINT CO", 400.0, "2026-04-12")
    _match_partial(client, line, "bill", bill)

    u = client.post(f"/api/v1/statement-lines/{line}/unreconcile")
    assert u.status_code == 200, u.text
    row = _bill_row(client, bill)
    assert row["paid_amount"] == 0.0
    assert row["status"] == "awaiting_payment"
    assert abs(_ooo(client, acc) - bal0) < 0.001
    assert _status(client, line) == "pending"


def test_remaining_half_settles_in_a_second_payment(client):
    acc = _setup(client)
    bill = _bill(client, "Inkwell Print Co", 1000.0, "BILL-1", "2026-04-01")
    line1 = _line_out(client, acc, "INKWELL PRINT CO", 400.0, "2026-04-12")
    assert _match_partial(client, line1, "bill", bill).status_code == 200

    # The remaining 600 is now an exact match a later payment settles in full.
    line2 = _line_out(client, acc, "INKWELL PRINT CO", 600.0, "2026-04-20")
    r = client.post(f"/api/v1/statement-lines/{line2}/match-bill", json={"bill_id": bill})
    assert r.status_code == 200, r.text
    row = _bill_row(client, bill)
    assert row["paid_amount"] == 1000.0
    assert row["status"] == "paid"


# ── Vendor gating (the user's rule: only ever suggest the SAME vendor) ─────────

def test_partial_targets_only_offer_the_named_vendor(client):
    acc = _setup(client)
    mine = _bill(client, "Acme Supplies", 1000.0, "BILL-1", "2026-04-01")
    _bill(client, "Globex Other", 1000.0, "BILL-2", "2026-04-01")     # different vendor
    line = _line_out(client, acc, "ACME SUPPLIES", 400.0, "2026-04-12")

    ids = [t["id"] for t in _partial_targets(client, line)]
    assert ids == [mine]                       # only the named vendor's bill, never Globex


# ── Guards ───────────────────────────────────────────────────────────────────

def test_partial_rejects_full_and_overpayment(client):
    acc = _setup(client)
    bill = _bill(client, "Acme", 500.0, "BILL-1", "2026-04-01")
    exact = _line_out(client, acc, "ACME", 500.0, "2026-04-12")
    assert _match_partial(client, exact, "bill", bill).status_code == 422   # full → normal match
    over = _line_out(client, acc, "ACME", 700.0, "2026-04-12")
    assert _match_partial(client, over, "bill", bill).status_code == 422    # over → overpayment


def test_cannot_delete_a_partially_paid_bill(client):
    acc = _setup(client)
    bill = _bill(client, "Inkwell Print Co", 1000.0, "BILL-1", "2026-04-01")
    line = _line_out(client, acc, "INKWELL PRINT CO", 400.0, "2026-04-12")
    assert _match_partial(client, line, "bill", bill).status_code == 200

    # Void-guard: a reconciled line settled part of it → cannot delete.
    assert client.delete(f"/api/v1/bills/{bill}").status_code == 409

    # After unreconciling the line, deletion is allowed again.
    client.post(f"/api/v1/statement-lines/{line}/unreconcile")
    assert client.delete(f"/api/v1/bills/{bill}").status_code == 204


# ── Money-in (invoice) direction ──────────────────────────────────────────────

def test_partial_part_pays_an_invoice(client):
    acc = _setup(client)
    bal0 = _ooo(client, acc)
    inv = _invoice(client, "Castlebridge University", 9000.0, "INV-1", "2026-03-10")
    line = _line_in(client, acc, "CASTLEBRIDGE UNIVERSITY", 4500.0, "2026-03-30")

    r = _match_partial(client, line, "invoice", inv)
    assert r.status_code == 200, r.text
    row = _invoice_row(client, inv)
    assert row["paid_amount"] == 4500.0 and row["outstanding"] == 4500.0
    assert row["status"] == "awaiting_payment"
    assert abs(_ooo(client, acc) - (bal0 + 4500.0)) < 0.001   # money in raises the balance
