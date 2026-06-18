"""
Phase 3 (overpayment/prepayment): allocating a held credit to bills/invoices, and
removing allocations.

The non-negotiables from the brief, each pinned by a test:
  • partial use leaves a remainder; allocation moves NO bank money
  • credit smaller / equal / bigger than the bill all behave
  • a credit can split across several bills and never over-spend
  • can't apply more than the credit's remaining or the bill's owing
  • currency mismatch is blocked; wrong target type is blocked
  • removing an allocation is the exact inverse
  • you can't unreconcile a credit that's been allocated (until it's removed)
  • one org can never see/allocate another org's credit
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


def _setup(client, email="u@u.com", org="Co") -> int:
    with _allow_registration():
        r = client.post("/api/v1/auth/register", json={
            "email": email, "password": "password1", "name": "U", "org_name": org})
    assert r.status_code == 200, r.text
    return client.post("/api/v1/bank-accounts/", json={"name": "Checking"}).json()["id"]


def _ooo(client, acc_id) -> float:
    acc = next(a for a in client.get("/api/v1/bank-accounts/").json() if a["id"] == acc_id)
    return acc["ooo_balance"]


def _bill(client, name, amount, number, issue="2026-04-01", currency="GBP", status="awaiting_payment") -> int:
    body = {"number": number, "contact_name": name, "issue_date": issue, "currency": currency,
            "status": status, "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}]}
    r = client.post("/api/v1/bills/", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bill_row(client, bill_id) -> dict:
    return next(b for b in client.get("/api/v1/bills/").json() if b["id"] == bill_id)


def _line_out(client, acc, desc, spent, date="2026-04-28") -> int:
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc, "lines": [{"date": date, "description": desc, "spent": spent}]})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _book_overpayment(client, line, bill) -> int:
    """Book an overpayment; return the credit id."""
    r = client.post(f"/api/v1/statement-lines/{line}/book-credit",
                    json={"kind": "overpayment", "document_ids": [bill]})
    assert r.status_code == 200, r.text
    return r.json()["matched_credit_id"]


def _credit(client, cid) -> dict:
    r = client.get(f"/api/v1/credits/{cid}")
    assert r.status_code == 200, r.text
    return r.json()


def _allocate(client, cid, target_id, amount, target_type="bill"):
    return client.post(f"/api/v1/credits/{cid}/allocate",
                       json={"target_type": target_type, "target_id": target_id, "amount": amount})


def _overpay_800(client, acc, supplier="Acme"):
    """Set up an 800 credit against `supplier` (paid 2000 on a 1200 bill)."""
    bill = _bill(client, supplier, 1200.0, "BILL-OP")
    line = _line_out(client, acc, supplier.upper(), 2000.0)
    return _book_overpayment(client, line, bill), line


# ── Partial use + balance is untouched by allocation ─────────────────────────

def test_partial_allocation_leaves_remainder_and_moves_no_bank_money(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)
    bal_after_booking = _ooo(client, acc)        # already moved by the 2000 payment

    target = _bill(client, "Acme", 500.0, "BILL-2")
    r = _allocate(client, cid, target, 500.0)
    assert r.status_code == 200, r.text

    cn = _credit(client, cid)
    assert cn["allocated_amount"] == 500.0 and cn["outstanding"] == 300.0
    assert cn["status"] == "awaiting_payment"          # partly used
    assert _bill_row(client, target)["status"] == "paid"
    # Allocation is AP-to-AP — the bank balance must not move.
    assert abs(_ooo(client, acc) - bal_after_booking) < 0.001


def test_credit_smaller_equal_and_bigger_than_the_bill(client):
    acc = _setup(client)

    # equal: 800 credit, 800 bill → bill paid, credit fully used
    cid_eq, _ = _overpay_800(client, acc, "EqCo")
    bill_eq = _bill(client, "EqCo", 800.0, "EQ")
    assert _allocate(client, cid_eq, bill_eq, 800.0).status_code == 200
    assert _credit(client, cid_eq)["outstanding"] == 0.0
    assert _credit(client, cid_eq)["status"] == "paid"
    assert _bill_row(client, bill_eq)["status"] == "paid"

    # bigger: 800 credit, 600 bill → bill paid, 200 credit remains
    cid_big, _ = _overpay_800(client, acc, "BigCo")
    bill_small = _bill(client, "BigCo", 600.0, "SMALL")
    assert _allocate(client, cid_big, bill_small, 600.0).status_code == 200
    assert _credit(client, cid_big)["outstanding"] == 200.0
    assert _bill_row(client, bill_small)["status"] == "paid"

    # smaller: 800 credit, 1000 bill → credit fully used, bill still owes 200
    cid_sm, _ = _overpay_800(client, acc, "SmCo")
    bill_big = _bill(client, "SmCo", 1000.0, "BIG")
    assert _allocate(client, cid_sm, bill_big, 800.0).status_code == 200
    assert _credit(client, cid_sm)["status"] == "paid"
    row = _bill_row(client, bill_big)
    assert row["status"] != "paid" and row["outstanding"] == 200.0


# ── Never over-spend ─────────────────────────────────────────────────────────

def test_cannot_allocate_more_than_remaining_credit(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)
    bill = _bill(client, "Acme", 2000.0, "BILL-2")
    # 900 > 800 available
    assert _allocate(client, cid, bill, 900.0).status_code == 409
    # spend 500, then 400 more would exceed the remaining 300
    assert _allocate(client, cid, bill, 500.0).status_code == 200
    assert _allocate(client, cid, bill, 400.0).status_code == 409
    assert _credit(client, cid)["outstanding"] == 300.0     # unchanged by the rejected call


def test_cannot_allocate_more_than_the_bill_owes(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)
    small_bill = _bill(client, "Acme", 300.0, "BILL-2")
    assert _allocate(client, cid, small_bill, 500.0).status_code == 409   # bill only owes 300


def test_credit_splits_across_several_bills_summing_to_original(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)
    b1 = _bill(client, "Acme", 500.0, "B1")
    b2 = _bill(client, "Acme", 300.0, "B2")
    assert _allocate(client, cid, b1, 500.0).status_code == 200
    assert _allocate(client, cid, b2, 300.0).status_code == 200
    cn = _credit(client, cid)
    assert cn["outstanding"] == 0.0 and cn["status"] == "paid"
    assert sum(a["amount"] for a in cn["allocations"]) == 800.0     # to the cent, nothing lost


# ── Blocks ───────────────────────────────────────────────────────────────────

def test_currency_mismatch_is_blocked(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)                  # credit is GBP
    usd_bill = _bill(client, "Acme", 500.0, "USD-1", currency="USD")
    r = _allocate(client, cid, usd_bill, 500.0)
    assert r.status_code == 422 and "currenc" in r.json()["detail"].lower()


def test_payable_credit_cannot_target_an_invoice(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)
    # target_type invoice on a payable (supplier) credit
    r = _allocate(client, cid, 999, 100.0, target_type="invoice")
    assert r.status_code == 422


# ── Remove allocation = exact inverse ────────────────────────────────────────

def test_remove_allocation_restores_credit_and_reopens_bill(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)
    bill = _bill(client, "Acme", 500.0, "BILL-2")
    _allocate(client, cid, bill, 500.0)
    alloc_id = _credit(client, cid)["allocations"][0]["id"]

    r = client.delete(f"/api/v1/credits/{cid}/allocations/{alloc_id}")
    assert r.status_code == 200, r.text
    cn = _credit(client, cid)
    assert cn["outstanding"] == 800.0 and cn["allocated_amount"] == 0.0
    assert cn["status"] == "awaiting_payment"
    assert cn["allocations"] == []
    row = _bill_row(client, bill)
    assert row["status"] != "paid" and row["paid_amount"] == 0.0


# ── Interaction with unreconcile (Phase 2 guard) ─────────────────────────────

def test_cannot_unreconcile_a_credit_that_has_been_allocated(client):
    acc = _setup(client)
    cid, line = _overpay_800(client, acc)
    bill = _bill(client, "Acme", 500.0, "BILL-2")
    _allocate(client, cid, bill, 500.0)

    # The source line booked a credit that's now partly allocated → blocked.
    assert client.post(f"/api/v1/statement-lines/{line}/unreconcile").status_code == 409

    # Remove the allocation, and unreconcile is allowed again.
    alloc_id = _credit(client, cid)["allocations"][0]["id"]
    client.delete(f"/api/v1/credits/{cid}/allocations/{alloc_id}")
    assert client.post(f"/api/v1/statement-lines/{line}/unreconcile").status_code == 200


# ── Tenant isolation ─────────────────────────────────────────────────────────

def test_one_org_cannot_see_or_touch_another_orgs_credit(client):
    acc = _setup(client)
    cid, _ = _overpay_800(client, acc)
    assert _credit(client, cid)["id"] == cid              # visible to its own org

    # Spin up a second org — the session switches to it.
    assert client.post("/api/v1/orgs/", json={"name": "Other Co"}).status_code == 201
    assert client.get(f"/api/v1/credits/{cid}").status_code == 404
    assert client.get("/api/v1/credits/").json() == []
    assert _allocate(client, cid, 1, 100.0).status_code == 404
