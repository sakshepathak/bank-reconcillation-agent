"""
Statement line management — the heart of the Reconcile screen.

Reconcile actions (Xero-style):
  Match    → link statement line to an Invoice or Bill, update paid_amount
  Create   → spawn a JournalEntry, link it
  Transfer → mark as cross-account transfer
  Discuss  → attach a note, leave pending
  Unreconcile → undo any of the above

Every reconcile action updates the corresponding BankAccount.ooo_balance so
the invariant `statement_balance == ooo_balance` (once all lines are
reconciled) is maintained.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import (
    BankAccount, StatementLine, StatementLineStatus,
    Invoice, Bill, JournalEntry, DocumentStatus,
)
from api.schemas.models import (
    StatementLineResponse, StatementImportRequest,
    MatchInvoiceRequest, MatchBillRequest, CreateEntryRequest,
    TransferRequest, DiscussRequest,
)
from api.deps import get_db

router = APIRouter(prefix="/statement-lines", tags=["statement-lines"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_resp(s: StatementLine) -> StatementLineResponse:
    return StatementLineResponse(
        id=s.id, bank_account_id=s.bank_account_id, date=s.date,
        description=s.description, reference=s.reference,
        spent=s.spent, received=s.received, balance_after=s.balance_after,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        matched_invoice_id=s.matched_invoice_id,
        matched_bill_id=s.matched_bill_id,
        matched_journal_id=s.matched_journal_id,
        transfer_to_account_id=s.transfer_to_account_id,
        discussion=s.discussion, suggested_score=s.suggested_score,
        imported_at=s.imported_at, reconciled_at=s.reconciled_at,
    )


def _net_amount(s: StatementLine) -> float:
    """Signed: +ve if money in, -ve if money out."""
    return s.received - s.spent


def _apply_balance(db: Session, account_id: int, delta: float) -> None:
    """Adjust the OOO balance of a bank account by the given signed delta."""
    acc = db.get(BankAccount, account_id)
    if acc:
        acc.ooo_balance = round(acc.ooo_balance + delta, 2)
        db.add(acc)


def _require_pending(line: StatementLine) -> None:
    if line.status != StatementLineStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Line is already {line.status.value}. Unreconcile first.",
        )


# ── List / read ──────────────────────────────────────────────────────────────

@router.get("/", response_model=list[StatementLineResponse])
def list_lines(
    bank_account_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = select(StatementLine)
    if bank_account_id is not None:
        q = q.where(StatementLine.bank_account_id == bank_account_id)
    if status:
        q = q.where(StatementLine.status == status)
    q = q.order_by(StatementLine.date.desc())
    return [_to_resp(s) for s in db.exec(q).all()]


@router.get("/{line_id}", response_model=StatementLineResponse)
def get_line(line_id: int, db: Session = Depends(get_db)):
    s = db.get(StatementLine, line_id)
    if not s:
        raise HTTPException(status_code=404, detail="Statement line not found")
    return _to_resp(s)


# ── Bulk import ──────────────────────────────────────────────────────────────

@router.post("/import", response_model=list[StatementLineResponse], status_code=201)
def import_lines(body: StatementImportRequest, db: Session = Depends(get_db)):
    acc = db.get(BankAccount, body.bank_account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Bank account not found")

    now = _now()
    created = []
    for ln in body.lines:
        s = StatementLine(
            bank_account_id=body.bank_account_id,
            date=ln.date, description=ln.description, reference=ln.reference,
            spent=ln.spent, received=ln.received, balance_after=ln.balance_after,
            status=StatementLineStatus.PENDING,
            imported_at=now,
        )
        db.add(s)
        created.append(s)

    # Update the bank's recorded statement_balance to the latest line's running balance
    if body.lines and body.lines[-1].balance_after is not None:
        acc.statement_balance = body.lines[-1].balance_after
    acc.last_imported_at = now
    db.add(acc)

    db.commit()
    for s in created:
        db.refresh(s)
    return [_to_resp(s) for s in created]


# ── Reconcile actions ────────────────────────────────────────────────────────

@router.post("/{line_id}/match-invoice", response_model=StatementLineResponse)
def match_invoice(line_id: int, body: MatchInvoiceRequest, db: Session = Depends(get_db)):
    s = db.get(StatementLine, line_id)
    if not s:
        raise HTTPException(status_code=404, detail="Statement line not found")
    _require_pending(s)

    inv = db.get(Invoice, body.invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    amount = _net_amount(s)  # invoice payment = received from customer (positive)
    s.matched_invoice_id = inv.id
    s.status = StatementLineStatus.MATCHED
    s.reconciled_at = _now()

    inv.paid_amount = round(inv.paid_amount + amount, 2)
    if inv.paid_amount >= inv.total - 0.005:
        inv.status = DocumentStatus.PAID
    inv.updated_at = _now()

    _apply_balance(db, s.bank_account_id, amount)

    db.add(s); db.add(inv)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/match-bill", response_model=StatementLineResponse)
def match_bill(line_id: int, body: MatchBillRequest, db: Session = Depends(get_db)):
    s = db.get(StatementLine, line_id)
    if not s:
        raise HTTPException(status_code=404, detail="Statement line not found")
    _require_pending(s)

    bill = db.get(Bill, body.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    amount = _net_amount(s)  # bill payment = spent on supplier (negative line)
    abs_amount = abs(amount)
    s.matched_bill_id = bill.id
    s.status = StatementLineStatus.MATCHED
    s.reconciled_at = _now()

    bill.paid_amount = round(bill.paid_amount + abs_amount, 2)
    if bill.paid_amount >= bill.total - 0.005:
        bill.status = DocumentStatus.PAID
    bill.updated_at = _now()

    _apply_balance(db, s.bank_account_id, amount)

    db.add(s); db.add(bill)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/create-entry", response_model=StatementLineResponse)
def create_entry(line_id: int, body: CreateEntryRequest, db: Session = Depends(get_db)):
    s = db.get(StatementLine, line_id)
    if not s:
        raise HTTPException(status_code=404, detail="Statement line not found")
    _require_pending(s)

    amount = _net_amount(s)
    j = JournalEntry(
        date=s.date, contact_id=body.contact_id, contact_name=body.contact_name,
        account_code=body.account_code, description=body.description,
        amount=amount, tax_rate=body.tax_rate, created_at=_now(),
    )
    db.add(j); db.commit(); db.refresh(j)

    s.matched_journal_id = j.id
    s.status = StatementLineStatus.MANUAL
    s.reconciled_at = _now()

    _apply_balance(db, s.bank_account_id, amount)

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/transfer", response_model=StatementLineResponse)
def transfer(line_id: int, body: TransferRequest, db: Session = Depends(get_db)):
    s = db.get(StatementLine, line_id)
    if not s:
        raise HTTPException(status_code=404, detail="Statement line not found")
    _require_pending(s)

    to_acc = db.get(BankAccount, body.to_account_id)
    if not to_acc:
        raise HTTPException(status_code=404, detail="Target account not found")

    amount = _net_amount(s)
    s.transfer_to_account_id = body.to_account_id
    s.status = StatementLineStatus.TRANSFER
    s.reconciled_at = _now()

    # Both sides move — source by amount, destination by -amount
    _apply_balance(db, s.bank_account_id, amount)
    _apply_balance(db, body.to_account_id, -amount)

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/discuss", response_model=StatementLineResponse)
def discuss(line_id: int, body: DiscussRequest, db: Session = Depends(get_db)):
    s = db.get(StatementLine, line_id)
    if not s:
        raise HTTPException(status_code=404, detail="Statement line not found")
    s.discussion = body.note
    # Discussing doesn't reconcile — keep PENDING unless already resolved
    if s.status == StatementLineStatus.PENDING:
        s.status = StatementLineStatus.DISCUSSED
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/unreconcile", response_model=StatementLineResponse)
def unreconcile(line_id: int, db: Session = Depends(get_db)):
    """Undo any reconcile action, restoring the line to PENDING."""
    s = db.get(StatementLine, line_id)
    if not s:
        raise HTTPException(status_code=404, detail="Statement line not found")
    if s.status == StatementLineStatus.PENDING:
        return _to_resp(s)

    amount = _net_amount(s)

    # Reverse any side effects of the original action
    if s.matched_invoice_id:
        inv = db.get(Invoice, s.matched_invoice_id)
        if inv:
            inv.paid_amount = round(inv.paid_amount - amount, 2)
            if inv.paid_amount < inv.total - 0.005 and inv.status == DocumentStatus.PAID:
                inv.status = DocumentStatus.AWAITING_PAYMENT
            inv.updated_at = _now()
            db.add(inv)
        _apply_balance(db, s.bank_account_id, -amount)

    elif s.matched_bill_id:
        bill = db.get(Bill, s.matched_bill_id)
        if bill:
            bill.paid_amount = round(bill.paid_amount - abs(amount), 2)
            if bill.paid_amount < bill.total - 0.005 and bill.status == DocumentStatus.PAID:
                bill.status = DocumentStatus.AWAITING_PAYMENT
            bill.updated_at = _now()
            db.add(bill)
        _apply_balance(db, s.bank_account_id, -amount)

    elif s.matched_journal_id:
        j = db.get(JournalEntry, s.matched_journal_id)
        if j:
            db.delete(j)
        _apply_balance(db, s.bank_account_id, -amount)

    elif s.transfer_to_account_id:
        _apply_balance(db, s.bank_account_id, -amount)
        _apply_balance(db, s.transfer_to_account_id, amount)

    s.matched_invoice_id = None
    s.matched_bill_id = None
    s.matched_journal_id = None
    s.transfer_to_account_id = None
    s.status = StatementLineStatus.PENDING
    s.reconciled_at = None

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)
