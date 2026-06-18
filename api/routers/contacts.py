import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import (
    Bill, Contact, CreditNote, DocumentStatus, Invoice, VendorAlias, VendorPaymentProfile,
)
from api.schemas.models import (
    AliasResponse,
    ContactCreate,
    ContactCreditSummary,
    ContactDetailResponse,
    ContactDocSummary,
    ContactPaymentTimingResponse,
    ContactResponse,
    ContactUpdate,
)
from api.deps import get_db, get_current_org_id
from engine.reconcile_rules import timing_stats

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
    credits = db.exec(
        select(CreditNote)
        .where(CreditNote.org_id == org_id, CreditNote.contact_id == contact_id)
        .order_by(CreditNote.id.desc())
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
        credits=[
            ContactCreditSummary(
                id=c.id,
                kind=c.kind.value if hasattr(c.kind, "value") else str(c.kind),
                direction=c.direction.value if hasattr(c.direction, "value") else str(c.direction),
                currency=c.currency,
                original_amount=round(c.original_amount, 2),
                outstanding=round(c.original_amount - c.allocated_amount, 2),
                status=c.status.value if hasattr(c.status, "value") else str(c.status),
                issue_date=c.issue_date,
            )
            for c in credits
        ],
    )


@router.get("/{contact_id}/payment-timing", response_model=ContactPaymentTimingResponse)
def get_payment_timing(
    contact_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Learned payment-timing summary for this contact — how many days after a
    document's issue date they typically pay, passively learned from past
    reconciliations (VendorPaymentProfile). Returns a "still learning" shape
    (typical_days=None) until enough payments are observed.
    """
    contact = _load_contact_for_org(db, contact_id, org_id)

    # Profiles are keyed "id:<contact_id>" when documents carried a contact_id
    # (the common case), else "name:<normalised name>". Prefer the id-key; fall
    # back to the name-key for history learned before a contact link existed.
    prof = db.exec(
        select(VendorPaymentProfile).where(
            VendorPaymentProfile.org_id == org_id,
            VendorPaymentProfile.vendor_key == f"id:{contact_id}",
        )
    ).first()
    if prof is None:
        name_key = f"name:{(contact.full_name or '').strip().lower()}"
        prof = db.exec(
            select(VendorPaymentProfile).where(
                VendorPaymentProfile.org_id == org_id,
                VendorPaymentProfile.vendor_key == name_key,
            )
        ).first()

    try:
        lags = json.loads(prof.recent_lags or "[]") if prof else []
        if not isinstance(lags, list):
            lags = []
    except (json.JSONDecodeError, TypeError):
        lags = []

    return ContactPaymentTimingResponse(
        contact_id=contact_id,
        observations=(prof.n if prof else 0),
        recent_lags=[max(0, int(x)) for x in lags if x is not None],
        updated_at=(prof.updated_at if prof else None),
        **timing_stats(lags),
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
