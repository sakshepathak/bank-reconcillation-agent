"""
Phase 4 (overpayment/prepayment): when a bill/invoice that has credit applied to
it is deleted or voided, the credit must come back — the money is still ours until
it's genuinely used. Also: a contact's held credits surface on its detail page.
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
            "email": "u@u.com", "password": "password1", "name": "U", "org_name": "Co"})
    assert r.status_code == 200, r.text
    return client.post("/api/v1/bank-accounts/", json={"name": "Checking"}).json()["id"]


def _bill(client, name, amount, number, status="awaiting_payment") -> int:
    body = {"number": number, "contact_name": name, "issue_date": "2026-04-01",
            "status": status, "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}]}
    r = client.post("/api/v1/bills/", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bill_row(client, bill_id) -> dict:
    return next(b for b in client.get("/api/v1/bills/").json() if b["id"] == bill_id)


def _line_out(client, acc, desc, spent) -> int:
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc, "lines": [{"date": "2026-04-28", "description": desc, "spent": spent}]})
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _book_overpayment(client, line, bill) -> int:
    r = client.post(f"/api/v1/statement-lines/{line}/book-credit",
                    json={"kind": "overpayment", "document_ids": [bill]})
    assert r.status_code == 200, r.text
    return r.json()["matched_credit_id"]


def _credit(client, cid) -> dict:
    return client.get(f"/api/v1/credits/{cid}").json()


def _allocate(client, cid, target_id, amount):
    return client.post(f"/api/v1/credits/{cid}/allocate",
                       json={"target_type": "bill", "target_id": target_id, "amount": amount})


def _overpay_800(client, acc, supplier="Acme") -> int:
    bill = _bill(client, supplier, 1200.0, "BILL-OP")
    line = _line_out(client, acc, supplier.upper(), 2000.0)
    return _book_overpayment(client, line, bill)


def test_deleting_a_bill_restores_allocated_credit(client):
    acc = _setup(client)
    cid = _overpay_800(client, acc)
    bill = _bill(client, "Acme", 500.0, "BILL-2")
    _allocate(client, cid, bill, 500.0)
    assert _credit(client, cid)["outstanding"] == 300.0

    assert client.delete(f"/api/v1/bills/{bill}").status_code == 204

    cn = _credit(client, cid)
    assert cn["outstanding"] == 800.0 and cn["allocated_amount"] == 0.0
    assert cn["status"] == "awaiting_payment"
    assert cn["allocations"] == []

    # …and the restored credit is reusable on a different bill.
    bill2 = _bill(client, "Acme", 800.0, "BILL-3")
    assert _allocate(client, cid, bill2, 800.0).status_code == 200
    assert _credit(client, cid)["status"] == "paid"


def test_voiding_a_bill_restores_allocated_credit(client):
    acc = _setup(client)
    cid = _overpay_800(client, acc)
    bill = _bill(client, "Acme", 500.0, "BILL-2")
    _allocate(client, cid, bill, 500.0)

    r = client.patch(f"/api/v1/bills/{bill}", json={"status": "voided"})
    assert r.status_code == 200, r.text

    cn = _credit(client, cid)
    assert cn["outstanding"] == 800.0 and cn["allocations"] == []
    assert _bill_row(client, bill)["status"] == "voided"


def test_contact_detail_lists_held_credits(client):
    acc = _setup(client)
    bill = _bill(client, "Acme", 1200.0, "BILL-OP")
    contact_id = _bill_row(client, bill)["contact_id"]
    line = _line_out(client, acc, "ACME", 2000.0)
    _book_overpayment(client, line, bill)

    detail = client.get(f"/api/v1/contacts/{contact_id}/detail").json()
    assert len(detail["credits"]) == 1
    c = detail["credits"][0]
    assert c["kind"] == "overpayment"
    assert c["direction"] == "payable"
    assert c["outstanding"] == 800.0
    assert c["status"] == "awaiting_payment"
