"""Bank account CRUD + balance summary + reset / hard-delete with cascade."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func

from memory.models import (
    BankAccount, StatementLine, StatementLineStatus,
    Invoice, Bill, JournalEntry, DocumentStatus,
)
from api.schemas.models import (
    BankAccountCreate, BankAccountResponse, BankAccountUpdate,
)
from api.deps import get_db, get_current_org_id

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_resp(b: BankAccount, pending_count: int) -> BankAccountResponse:
    return BankAccountResponse(
        id=b.id,
        name=b.name,
        account_number=b.account_number,
        bank_name=b.bank_name,
        currency=b.currency,
        statement_balance=b.statement_balance,
        ooo_balance=b.ooo_balance,
        balance_difference=b.statement_balance - b.ooo_balance,
        pending_count=pending_count,
        last_imported_at=b.last_imported_at,
        is_active=b.is_active,
        created_at=b.created_at,
    )


def _pending_count(db: Session, bank_account_id: int, org_id: int) -> int:
    q = (
        select(func.count(StatementLine.id))
        .where(StatementLine.bank_account_id == bank_account_id)
        .where(StatementLine.org_id == org_id)
        .where(StatementLine.status == StatementLineStatus.PENDING)
    )
    return db.exec(q).one() or 0


def _load_account_for_org(db: Session, account_id: int, org_id: int) -> BankAccount:
    b = db.get(BankAccount, account_id)
    if not b or b.org_id != org_id:
        raise HTTPException(status_code=404, detail="Bank account not found")
    return b


@router.get("/", response_model=list[BankAccountResponse])
def list_accounts(
    active_only: bool = True,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(BankAccount).where(BankAccount.org_id == org_id)
    if active_only:
        q = q.where(BankAccount.is_active == True)
    rows = db.exec(q).all()
    return [_to_resp(b, _pending_count(db, b.id, org_id)) for b in rows]


@router.get("/{account_id}", response_model=BankAccountResponse)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    b = _load_account_for_org(db, account_id, org_id)
    return _to_resp(b, _pending_count(db, b.id, org_id))


@router.post("/", response_model=BankAccountResponse, status_code=201)
def create_account(
    body: BankAccountCreate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    b = BankAccount(**body.model_dump(), org_id=org_id, created_at=_now())
    db.add(b)
    db.commit()
    db.refresh(b)
    return _to_resp(b, 0)


@router.patch("/{account_id}", response_model=BankAccountResponse)
def update_account(
    account_id: int,
    body: BankAccountUpdate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    b = _load_account_for_org(db, account_id, org_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    db.add(b)
    db.commit()
    db.refresh(b)
    return _to_resp(b, _pending_count(db, b.id, org_id))


def _reverse_line_side_effects(line: StatementLine, db: Session, org_id: int) -> None:
    """
    Roll back whatever a reconciled line did to its linked invoice/bill/
    journal entry / paired transfer account. Mirrors the existing
    unreconcile endpoint — same logic, but without touching the line
    itself (caller is about to delete it).

    PENDING lines have no side effects; this is a no-op for them.

    All linked rows are verified to be in the same org. Foreign rows
    (cross-tenant pointers — shouldn't ever happen but defence in depth)
    are ignored rather than touched.
    """
    if line.status == StatementLineStatus.PENDING:
        return

    amount = line.received - line.spent  # signed: + received, − spent

    if line.matched_invoice_id:
        inv = db.get(Invoice, line.matched_invoice_id)
        if inv and inv.org_id == org_id:
            inv.paid_amount = round(inv.paid_amount - amount, 2)
            if inv.paid_amount < inv.total - 0.005 and inv.status == DocumentStatus.PAID:
                inv.status = DocumentStatus.AWAITING_PAYMENT
            inv.updated_at = _now()
            db.add(inv)

    elif line.matched_bill_id:
        bill = db.get(Bill, line.matched_bill_id)
        if bill and bill.org_id == org_id:
            bill.paid_amount = round(bill.paid_amount - abs(amount), 2)
            if bill.paid_amount < bill.total - 0.005 and bill.status == DocumentStatus.PAID:
                bill.status = DocumentStatus.AWAITING_PAYMENT
            bill.updated_at = _now()
            db.add(bill)

    elif line.matched_journal_id:
        j = db.get(JournalEntry, line.matched_journal_id)
        if j and j.org_id == org_id:
            db.delete(j)

    elif line.transfer_to_account_id:
        # The original transfer moved `amount` into the OTHER account's ooo_balance
        # (we credited -amount there). Reverse that.
        other = db.get(BankAccount, line.transfer_to_account_id)
        if other and other.org_id == org_id:
            other.ooo_balance = round(other.ooo_balance + amount, 2)
            db.add(other)


def _wipe_account_data(acc: BankAccount, db: Session, org_id: int) -> int:
    """
    Strip an account back to a clean slate. Reverses every line's side
    effects on invoices/bills/journal entries, then deletes the lines
    themselves and zeros both balances.

    Returns the number of statement lines removed.
    """
    lines = db.exec(
        select(StatementLine).where(
            StatementLine.bank_account_id == acc.id,
            StatementLine.org_id == org_id,
        )
    ).all()
    for line in lines:
        _reverse_line_side_effects(line, db, org_id)
        db.delete(line)

    acc.statement_balance = 0.0
    acc.ooo_balance = 0.0
    acc.last_imported_at = None
    db.add(acc)
    return len(lines)


@router.post("/{account_id}/reset")
def reset_account(
    account_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Wipe all imported statement lines, zero both balances. Reverses
    any side effects from past reconciliations — invoices and bills
    that were marked PAID flip back to AWAITING_PAYMENT, journal
    entries created inline are deleted, transfer-paired accounts get
    their balance restored.

    The account row itself is kept.
    """
    acc = _load_account_for_org(db, account_id, org_id)
    removed = _wipe_account_data(acc, db, org_id)
    db.commit()
    return {"ok": True, "lines_removed": removed}


@router.delete("/{account_id}", status_code=204)
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Hard delete with cascade. Equivalent to /reset followed by
    removing the account row. Use this only when you really want
    to forget the account ever existed.
    """
    acc = _load_account_for_org(db, account_id, org_id)
    _wipe_account_data(acc, db, org_id)
    db.delete(acc)
    db.commit()
