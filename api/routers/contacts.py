from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import Bill, Contact, DocumentStatus, Invoice, VendorAlias
from api.schemas.models import (
    AliasResponse,
    ContactCreate,
    ContactDetailResponse,
    ContactDocSummary,
    ContactResponse,
    ContactUpdate,
)
from api.deps import get_db, get_current_org_id

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


def _invoice_to_summary(inv: Invoice) -> ContactDocSummary:
    status_val = inv.status.value if hasattr(inv.status, "value") else str(inv.status)
    return ContactDocSummary(
        id=inv.id,
        number=inv.number,
        issue_date=inv.issue_date,
        total=inv.total,
        outstanding=round(inv.total - inv.paid_amount, 2),
        currency=inv.currency,
        status=status_val,
    )


def _bill_to_summary(b: Bill) -> ContactDocSummary:
    status_val = b.status.value if hasattr(b.status, "value") else str(b.status)
    return ContactDocSummary(
        id=b.id,
        number=b.number,
        issue_date=b.issue_date,
        total=b.total,
        outstanding=round(b.total - b.paid_amount, 2),
        currency=b.currency,
        status=status_val,
    )


def _load_contact_for_org(db: Session, contact_id: int, org_id: int) -> Contact:
    c = db.get(Contact, contact_id)
    if not c or c.org_id != org_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    return c


@router.get("/", response_model=list[ContactResponse])
def list_contacts(
    contact_type: str | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(Contact).where(Contact.org_id == org_id)
    if contact_type:
        q = q.where(Contact.contact_type == contact_type)
    return [_to_resp(c) for c in db.exec(q).all()]


@router.get("/{contact_id}/detail", response_model=ContactDetailResponse)
def get_contact_detail(
    contact_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Everything the Contact detail page needs in one round-trip:
    the contact row, their open and historical invoices and bills,
    and the aliases that resolve to them.
    """
    contact = _load_contact_for_org(db, contact_id, org_id)

    invoices = db.exec(
        select(Invoice)
        .where(Invoice.org_id == org_id, Invoice.contact_id == contact_id)
        .order_by(Invoice.issue_date.desc())
    ).all()
    bills = db.exec(
        select(Bill)
        .where(Bill.org_id == org_id, Bill.contact_id == contact_id)
        .order_by(Bill.issue_date.desc())
    ).all()
    aliases = db.exec(
        select(VendorAlias)
        .where(VendorAlias.org_id == org_id, VendorAlias.contact_id == contact_id)
        .order_by(VendorAlias.created_at.desc())
    ).all()

    return ContactDetailResponse(
        contact=_to_resp(contact),
        invoices=[_invoice_to_summary(i) for i in invoices],
        bills=[_bill_to_summary(b) for b in bills],
        aliases=[
            AliasResponse(
                id=a.id, alias=a.alias, canonical_name=a.canonical_name,
                contact_id=a.contact_id, confidence=a.confidence,
                source=a.source, created_at=a.created_at,
            )
            for a in aliases
        ],
    )


@router.post("/", response_model=ContactResponse, status_code=201)
def create_contact(
    body: ContactCreate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    now = _now()
    contact = Contact(**body.model_dump(), org_id=org_id, created_at=now, updated_at=now)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return _to_resp(contact)


@router.patch("/{contact_id}", response_model=ContactResponse)
def update_contact(
    contact_id: int,
    body: ContactUpdate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    contact = _load_contact_for_org(db, contact_id, org_id)
    data = body.model_dump(exclude_unset=True)
    name_changed = "full_name" in data and data["full_name"] != contact.full_name
    for field, value in data.items():
        setattr(contact, field, value)
    contact.updated_at = _now()
    db.add(contact)

    if name_changed:
        # Refresh the denormalized cache on every alias pointing to this contact.
        # Without this, the matching engine keeps matching to the OLD name.
        for a in db.exec(
            select(VendorAlias).where(
                VendorAlias.org_id == org_id,
                VendorAlias.contact_id == contact_id,
            )
        ).all():
            a.canonical_name = contact.full_name
            db.add(a)

    db.commit()
    db.refresh(contact)
    return _to_resp(contact)


@router.delete("/{contact_id}", status_code=204)
def delete_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    contact = _load_contact_for_org(db, contact_id, org_id)

    # Unlink (but keep) aliases that pointed here — the alias text is still
    # useful for matching, even without a contact link. Same goes for invoices
    # and bills: blank the FK rather than orphan a row with a dangling pointer.
    for a in db.exec(
        select(VendorAlias).where(
            VendorAlias.org_id == org_id, VendorAlias.contact_id == contact_id,
        )
    ).all():
        a.contact_id = None
        db.add(a)
    for i in db.exec(
        select(Invoice).where(
            Invoice.org_id == org_id, Invoice.contact_id == contact_id,
        )
    ).all():
        i.contact_id = None
        db.add(i)
    for b in db.exec(
        select(Bill).where(
            Bill.org_id == org_id, Bill.contact_id == contact_id,
        )
    ).all():
        b.contact_id = None
        db.add(b)

    db.delete(contact)
    db.commit()
