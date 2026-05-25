"""Bank account CRUD + balance summary."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func

from memory.models import BankAccount, StatementLine, StatementLineStatus
from api.schemas.models import (
    BankAccountCreate, BankAccountResponse, BankAccountUpdate,
)
from api.deps import get_db

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


def _pending_count(db: Session, bank_account_id: int) -> int:
    q = (
        select(func.count(StatementLine.id))
        .where(StatementLine.bank_account_id == bank_account_id)
        .where(StatementLine.status == StatementLineStatus.PENDING)
    )
    return db.exec(q).one() or 0


@router.get("/", response_model=list[BankAccountResponse])
def list_accounts(active_only: bool = True, db: Session = Depends(get_db)):
    q = select(BankAccount)
    if active_only:
        q = q.where(BankAccount.is_active == True)
    rows = db.exec(q).all()
    return [_to_resp(b, _pending_count(db, b.id)) for b in rows]


@router.get("/{account_id}", response_model=BankAccountResponse)
def get_account(account_id: int, db: Session = Depends(get_db)):
    b = db.get(BankAccount, account_id)
    if not b:
        raise HTTPException(status_code=404, detail="Bank account not found")
    return _to_resp(b, _pending_count(db, b.id))


@router.post("/", response_model=BankAccountResponse, status_code=201)
def create_account(body: BankAccountCreate, db: Session = Depends(get_db)):
    b = BankAccount(**body.model_dump(), created_at=_now())
    db.add(b)
    db.commit()
    db.refresh(b)
    return _to_resp(b, 0)


@router.patch("/{account_id}", response_model=BankAccountResponse)
def update_account(account_id: int, body: BankAccountUpdate, db: Session = Depends(get_db)):
    b = db.get(BankAccount, account_id)
    if not b:
        raise HTTPException(status_code=404, detail="Bank account not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(b, k, v)
    db.add(b)
    db.commit()
    db.refresh(b)
    return _to_resp(b, _pending_count(db, b.id))


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)):
    """Soft delete — sets is_active=False to preserve historical lines."""
    b = db.get(BankAccount, account_id)
    if not b:
        raise HTTPException(status_code=404, detail="Bank account not found")
    b.is_active = False
    db.add(b)
    db.commit()
