"""Journal entry CRUD — for manual ledger entries from the Reconcile 'Create' tab."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import JournalEntry
from api.schemas.models import JournalEntryCreate, JournalEntryResponse
from api.deps import get_db

router = APIRouter(prefix="/journal-entries", tags=["journal-entries"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_resp(j: JournalEntry) -> JournalEntryResponse:
    return JournalEntryResponse(
        id=j.id, date=j.date, contact_id=j.contact_id,
        contact_name=j.contact_name, account_code=j.account_code,
        description=j.description, amount=j.amount,
        tax_rate=j.tax_rate, currency=j.currency, created_at=j.created_at,
    )


@router.get("/", response_model=list[JournalEntryResponse])
def list_entries(db: Session = Depends(get_db)):
    return [_to_resp(j) for j in db.exec(select(JournalEntry)).all()]


@router.post("/", response_model=JournalEntryResponse, status_code=201)
def create_entry(body: JournalEntryCreate, db: Session = Depends(get_db)):
    j = JournalEntry(**body.model_dump(), created_at=_now())
    db.add(j)
    db.commit()
    db.refresh(j)
    return _to_resp(j)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    j = db.get(JournalEntry, entry_id)
    if not j:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    db.delete(j)
    db.commit()
