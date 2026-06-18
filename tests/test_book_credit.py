"""
Phase 2 (overpayment/prepayment): booking a credit during reconciliation, and
unreconciling it.

  • Overpayment — a money-out line that exceeds the bill it settles: the bill is
    paid in full and the remainder is booked as a supplier credit.
  • Prepayment  — a money-out line with no bill yet: the whole amount becomes a
    supplier credit against the chosen contact.
  • Customer side (money in) produces a receivable credit.

The headline guarantee: booking moves the FULL line through the bank balance, and
unreconciling reverses everything with no drift and deletes the credit. Credits
are inspected directly via the test engine (no read API until Phase 4).
"""
import os
from contextlib import contextmanager

from sqlmodel import Session, select

from memory.models import CreditNote, DocumentStatus, CreditKind, CreditDirection


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


def _bill(client, name, amount, number, issue, due=None) -> int:
    body = {"number": number, "contact_name": name, "issue_date": issue,
            "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}]}
    if due:
        body["due_date"] = due
    r = client.post("/api/v1/bills/", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bill_row(client, bill_id) -> dict:
    return next(b for b in client.get("/api/v1/bills/").json() if b["id"] == bill_id)


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


def _credits(test_engine) -> list:
    with Session(test_engine) as db:
        return db.exec(select(CreditNote)).all()


def _status(client, line_id) -> str:
    return client.get(f"/api/v1/statement-lines/{line_id}").json()["status"]


def _book(client, line, **body):
    return client.post(f"/api/v1/statement-lines/{line}/book-credit", json=body)


# ── Overpayment ──────────────────────────────────────────────────────────────

def test_overpayment_settles_bill_and_books_credit(client, test_engine):
    acc = _setup(client)
    bal0 = _ooo(client, acc)
    bill = _bill(client, "Correct Limited", 1200.0, "BILL-1", "2026-04-01")
    line = _line_out(client, acc, "CORRECT LIMITED", 2000.0, "2026-04-28")

    r = _book(client, line, kind="overpayment", document_ids=[bill])
    assert r.status_code == 200, r.text

    # Bill paid in full; line matched; the full 2,000 cleared the bank.
    assert _bill_row(client, bill)["status"] == "paid"
    assert _bill_row(client, bill)["paid_amount"] == 1200.0
    assert _status(client, line) == "matched"
    assert abs(_ooo(client, acc) - (bal0 - 2000.0)) < 0.001

    credits = _credits(test_engine)
    assert len(credits) == 1
    cn = credits[0]
    assert cn.kind == CreditKind.OVERPAYMENT
    assert cn.direction == CreditDirection.PAYABLE
    assert cn.original_amount == 800.0 and cn.allocated_amount == 0.0
    assert cn.status == DocumentStatus.AWAITING_PAYMENT
    assert cn.contact_name == "Correct Limited"
    assert cn.source_statement_line_id == line
    assert r.json()["matched_credit_id"] == cn.id


def test_overpayment_unreconcile_is_balance_neutral_and_deletes_credit(client, test_engine):
    acc = _setup(client)
    bal0 = _ooo(client, acc)
    bill = _bill(client, "Correct Limited", 1200.0, "BILL-1", "2026-04-01")
    line = _line_out(client, acc, "CORRECT LIMITED", 2000.0, "2026-04-28")
    _book(client, line, kind="overpayment", document_ids=[bill])

    u = client.post(f"/api/v1/statement-lines/{line}/unreconcile")
    assert u.status_code == 200, u.text
    assert "overpayment" in u.json()["reverted_label"].lower()

    assert _bill_row(client, bill)["paid_amount"] == 0.0
    assert _bill_row(client, bill)["status"] != "paid"          # bill reopened
    assert abs(_ooo(client, acc) - bal0) < 0.001                # balance restored
    assert _credits(test_engine) == []                          # credit deleted
    assert _status(client, line) == "pending"


def test_overpayment_rejected_when_payment_not_above_documents(client):
    acc = _setup(client)
    # 1,000 against a 1,200 bill is an underpayment — not an overpayment.
    under_bill = _bill(client, "Acme", 1200.0, "BILL-1", "2026-04-01")
    under_line = _line_out(client, acc, "ACME", 1000.0, "2026-04-28")
    assert _book(client, under_line, kind="overpayment", document_ids=[under_bill]).status_code == 422

    # Exactly 1,200 is a normal full match — not an overpayment either.
    exact_bill = _bill(client, "Acme", 1200.0, "BILL-2", "2026-04-01")
    exact_line = _line_out(client, acc, "ACME", 1200.0, "2026-04-28")
    assert _book(client, exact_line, kind="overpayment", document_ids=[exact_bill]).status_code == 422


# ── Prepayment ───────────────────────────────────────────────────────────────

def test_prepayment_books_full_line_credit(client, test_engine):
    acc = _setup(client)
    bal0 = _ooo(client, acc)
    line = _line_out(client, acc, "CORRECT LIMITED ADVANCE", 800.0, "2026-04-28")

    r = _book(client, line, kind="prepayment", contact_name="Correct Limited")
    assert r.status_code == 200, r.text
    assert _status(client, line) == "matched"
    assert abs(_ooo(client, acc) - (bal0 - 800.0)) < 0.001

    cn = _credits(test_engine)[0]
    assert cn.kind == CreditKind.PREPAYMENT
    assert cn.direction == CreditDirection.PAYABLE
    assert cn.original_amount == 800.0
    assert cn.contact_name == "Correct Limited"


def test_prepayment_unreconcile_reverts_cleanly(client, test_engine):
    acc = _setup(client)
    bal0 = _ooo(client, acc)
    line = _line_out(client, acc, "ADVANCE", 800.0, "2026-04-28")
    _book(client, line, kind="prepayment", contact_name="Acme")

    client.post(f"/api/v1/statement-lines/{line}/unreconcile")
    assert abs(_ooo(client, acc) - bal0) < 0.001
    assert _credits(test_engine) == []
    assert _status(client, line) == "pending"


def test_prepayment_requires_a_contact(client):
    acc = _setup(client)
    line = _line_out(client, acc, "MYSTERY", 800.0, "2026-04-28")
    assert _book(client, line, kind="prepayment").status_code == 422


def test_customer_money_in_books_a_receivable_credit(client, test_engine):
    acc = _setup(client)
    line = _line_in(client, acc, "BIG BUYER ADVANCE", 500.0, "2026-04-28")
    r = _book(client, line, kind="prepayment", contact_name="Big Buyer")
    assert r.status_code == 200, r.text

    cn = _credits(test_engine)[0]
    assert cn.direction == CreditDirection.RECEIVABLE
    assert cn.kind == CreditKind.PREPAYMENT
    assert cn.original_amount == 500.0


# ── Guards ───────────────────────────────────────────────────────────────────

def test_double_click_does_not_book_two_credits(client, test_engine):
    acc = _setup(client)
    bill = _bill(client, "Acme", 1200.0, "BILL-1", "2026-04-01")
    line = _line_out(client, acc, "ACME", 2000.0, "2026-04-28")

    assert _book(client, line, kind="overpayment", document_ids=[bill]).status_code == 200
    # Second identical click: line is already reconciled.
    assert _book(client, line, kind="overpayment", document_ids=[bill]).status_code == 409
    assert len(_credits(test_engine)) == 1


def test_unknown_kind_is_rejected(client):
    acc = _setup(client)
    line = _line_out(client, acc, "X", 800.0, "2026-04-28")
    assert _book(client, line, kind="refund", contact_name="Acme").status_code == 422
