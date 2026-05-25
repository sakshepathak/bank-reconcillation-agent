from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import Contact
from api.schemas.models import ContactCreate, ContactResponse, ContactUpdate
from api.deps import get_db

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_resp(c: Contact) -> ContactResponse:
    return ContactResponse(
        id=c.id,
        full_name=c.full_name,
        company=c.company,
        contact_type=c.contact_type,
        email=c.email,
        phone=c.phone,
        address=c.address,
        notes=c.notes,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/", response_model=list[ContactResponse])
def list_contacts(
    contact_type: str | None = None,
    db: Session = Depends(get_db),
):
    q = select(Contact)
    if contact_type:
        q = q.where(Contact.contact_type == contact_type)
    return [_to_resp(c) for c in db.exec(q).all()]


@router.post("/", response_model=ContactResponse, status_code=201)
def create_contact(body: ContactCreate, db: Session = Depends(get_db)):
    now = _now()
    contact = Contact(**body.model_dump(), created_at=now, updated_at=now)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return _to_resp(contact)


@router.patch("/{contact_id}", response_model=ContactResponse)
def update_contact(contact_id: int, body: ContactUpdate, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    contact.updated_at = _now()
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return _to_resp(contact)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
