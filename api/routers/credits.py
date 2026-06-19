"""
Credits — overpayments & prepayments held against a contact.

A credit is a contra AP/AR balance booked during reconciliation (see
statement_lines.book_credit). This router lets the user SEE credits and CONSUME
them by allocating the outstanding amount to a future bill/invoice — Xero's
"Allocate outstanding credit?" → "Less Overpayment / Amount Due" flow.

Allocation is a pure AP-to-AP / AR-to-AR reallocation: it moves the target
document's paid_amount but **never** touches the bank balance (no cash moves —
that already happened when the credit was booked). Removing an allocation is the
exact inverse. Both are atomic and audited.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import (
    CreditNote, CreditAllocation, CreditDirection, DocumentStatus,
    Bill, Invoice, AuditLog, AuditAction, User,
)
from api.schemas.models import (
    CreditResponse, CreditAllocationResponse, AllocateCreditRequest,
    CreditTargetResponse,
)
from api.deps import get_db, get_current_org_id, require_user
from engine.contacts import _normalize as _normalize_name

router = APIRouter(prefix="/credits", tags=["credits"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outstanding(cn: CreditNote) -> float:
    return round(cn.original_amount - cn.allocated_amount, 2)


def _enum(v) -> str:
    return v.value if hasattr(v, "value") else str(v)


def _norm_ccy(c: str | None) -> str:
    """Currency codes compare case-/whitespace-insensitively ('gbp' == ' GBP ')."""
    return (c or "").strip().upper()


def _same_vendor(cn: CreditNote, doc) -> bool:
    """
    Does this credit belong to the same contact as this bill/invoice?

    The single source of truth for "same vendor", shared by the eligible-targets
    listing and allocate_credit so the UI can never offer a document the POST
    would reject (and vice-versa). Prefer contact_id when BOTH sides have one;
    otherwise — or when the ids differ but the names match (duplicate contact
    rows for one vendor, or a credit booked by name with no id) — fall back to a
    normalized-name match. This is the same identity rule the matcher uses
    elsewhere (see statement_lines._vendor_key_parts).
    """
    doc_cid = getattr(doc, "contact_id", None)
    if cn.contact_id is not None and doc_cid is not None and cn.contact_id == doc_cid:
        return True
    cn_name = _normalize_name(cn.contact_name or "")
    doc_name = _normalize_name(getattr(doc, "contact_name", "") or "")
    return bool(cn_name) and cn_name == doc_name


def _is_allocatable(cn: CreditNote, doc) -> bool:
    """Every rule allocate_credit enforces, in one place: open status, something
    owing, currency match, same vendor. Amount caps are checked per-request."""
    if doc.status in (DocumentStatus.PAID, DocumentStatus.VOIDED):
        return False
    if round(doc.total - doc.paid_amount, 2) <= 0.005:
        return False
    if _norm_ccy(cn.currency) != _norm_ccy(doc.currency):
        return False
    return _same_vendor(cn, doc)


def _load_credit_for_org(db: Session, credit_id: int, org_id: int) -> CreditNote:
    cn = db.get(CreditNote, credit_id)
    if not cn or cn.org_id != org_id:
        raise HTTPException(status_code=404, detail="Credit not found")
    return cn


def _doc_label(db: Session, org_id: int, target_type: str, target_id: int) -> str:
    if target_type == "bill":
        b = db.get(Bill, target_id)
        if b and b.org_id == org_id:
            return f"{b.number or f'Bill #{b.id}'} · {b.contact_name}"
    else:
        inv = db.get(Invoice, target_id)
        if inv and inv.org_id == org_id:
            return f"{inv.number} · {inv.contact_name}"
    return f"{target_type} #{target_id}"


def _to_resp(db: Session, org_id: int, cn: CreditNote) -> CreditResponse:
    allocs = db.exec(
        select(CreditAllocation)
        .where(CreditAllocation.credit_note_id == cn.id, CreditAllocation.org_id == org_id)
        .order_by(CreditAllocation.id)
    ).all()
    return CreditResponse(
        id=cn.id,
        contact_id=cn.contact_id,
        contact_name=cn.contact_name,
        direction=_enum(cn.direction),
        kind=_enum(cn.kind),
        issue_date=cn.issue_date,
        currency=cn.currency,
        original_amount=round(cn.original_amount, 2),
        allocated_amount=round(cn.allocated_amount, 2),
        outstanding=_outstanding(cn),
        status=_enum(cn.status),
        source_statement_line_id=cn.source_statement_line_id,
        created_at=cn.created_at,
        allocations=[
            CreditAllocationResponse(
                id=a.id, target_type=a.target_type, target_id=a.target_id,
                target_label=_doc_label(db, org_id, a.target_type, a.target_id),
                amount=round(a.amount, 2), created_at=a.created_at,
            )
            for a in allocs
        ],
    )


def _log_credit_audit(
    db: Session, *, org_id: int, actor: User, action: AuditAction,
    cn: CreditNote, amount: float, target_type: str | None = None,
    target_id: int | None = None, target_label: str = "", detail: str = "",
) -> None:
    """Append one immutable audit row for a credit action. Credit actions aren't
    tied to a bank line, so the statement-line snapshot fields stay blank."""
    db.add(AuditLog(
        org_id=org_id,
        created_at=_now(),
        actor_id=getattr(actor, "id", None),
        actor_name=(getattr(actor, "name", "") or getattr(actor, "email", "") or "—"),
        action=action.value,
        statement_line_id=cn.source_statement_line_id,
        bank_account_id=None,
        line_date=cn.issue_date,
        line_description=f"{_enum(cn.kind)} · {cn.contact_name}",
        amount=round(amount, 2),
        currency=cn.currency,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        detail=detail,
    ))


def reverse_allocations_for_target(
    db: Session, *, org_id: int, target_type: str, target_id: int,
    actor: User | None = None, reason: str = "",
) -> float:
    """
    Reverse every credit allocation made against a bill/invoice — used when that
    document is voided or deleted, so the money (still ours) comes back as available
    credit. Restores each credit's outstanding balance and deletes the allocation
    rows. Does NOT change the target's paid_amount (the caller is deleting/voiding
    the document). Runs inside the caller's transaction. Returns the amount restored.
    """
    allocs = db.exec(
        select(CreditAllocation).where(
            CreditAllocation.org_id == org_id,
            CreditAllocation.target_type == target_type,
            CreditAllocation.target_id == target_id,
        )
    ).all()
    now = _now()
    restored = 0.0
    for a in allocs:
        cn = db.get(CreditNote, a.credit_note_id)
        if cn and cn.org_id == org_id:
            cn.allocated_amount = round(cn.allocated_amount - a.amount, 2)
            if cn.allocated_amount < 0:
                cn.allocated_amount = 0.0
            if cn.status != DocumentStatus.VOIDED:
                cn.status = DocumentStatus.AWAITING_PAYMENT
            cn.updated_at = now
            db.add(cn)
            if actor is not None:
                _log_credit_audit(
                    db, org_id=org_id, actor=actor, action=AuditAction.REMOVE_ALLOCATION,
                    cn=cn, amount=a.amount, target_type=target_type, target_id=target_id,
                    target_label=_doc_label(db, org_id, target_type, target_id),
                    detail=(f"Credit restored ({reason})" if reason else "Credit restored"),
                )
            restored = round(restored + a.amount, 2)
        db.delete(a)
    return restored


# ── Read ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[CreditResponse])
def list_credits(
    direction: str | None = None,      # payable | receivable
    status: str | None = None,         # awaiting_payment | paid | voided
    contact_id: int | None = None,
    currency: str | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """All credits for the org, newest first. Filterable by direction/status/
    contact/currency — used by the Credits sub-tabs and the bill 'apply credit' prompt."""
    q = select(CreditNote).where(CreditNote.org_id == org_id)
    if direction:
        q = q.where(CreditNote.direction == direction)
    if status:
        q = q.where(CreditNote.status == status)
    if contact_id is not None:
        q = q.where(CreditNote.contact_id == contact_id)
    if currency:
        q = q.where(CreditNote.currency == currency)
    q = q.order_by(CreditNote.id.desc())
    return [_to_resp(db, org_id, cn) for cn in db.exec(q).all()]


@router.get("/{credit_id}", response_model=CreditResponse)
def get_credit(
    credit_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    return _to_resp(db, org_id, _load_credit_for_org(db, credit_id, org_id))


@router.get("/{credit_id}/targets", response_model=list[CreditTargetResponse])
def list_credit_targets(
    credit_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Every open bill/invoice this credit can be applied to — the exact set
    allocate_credit would accept, computed by the SAME rules (_is_allocatable).
    The Allocate dialog renders this directly instead of re-deriving eligibility
    client-side, so the two can never disagree. A voided or fully-allocated
    credit has no targets (empty list).
    """
    cn = _load_credit_for_org(db, credit_id, org_id)
    if cn.status == DocumentStatus.VOIDED or _outstanding(cn) <= 0.005:
        return []

    # A payable (supplier) credit applies to bills; a receivable to invoices.
    is_payable = cn.direction == CreditDirection.PAYABLE
    Model = Bill if is_payable else Invoice
    want = "bill" if is_payable else "invoice"

    docs = db.exec(select(Model).where(Model.org_id == org_id)).all()
    targets = [
        CreditTargetResponse(
            target_type=want,
            id=d.id,
            number=d.number,
            contact_id=d.contact_id,
            contact_name=d.contact_name,
            issue_date=d.issue_date,
            due_date=d.due_date,
            total=round(d.total, 2),
            paid_amount=round(d.paid_amount, 2),
            outstanding=round(d.total - d.paid_amount, 2),
            currency=d.currency,
            status=_enum(d.status),
        )
        for d in docs
        if _is_allocatable(cn, d)
    ]
    # Oldest first — you typically clear the longest-owing document first.
    targets.sort(key=lambda t: (t.issue_date or "", t.id))
    return targets


# ── Allocate / remove ────────────────────────────────────────────────────────

@router.post("/{credit_id}/allocate", response_model=CreditResponse)
def allocate_credit(
    credit_id: int,
    body: AllocateCreditRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(require_user),
):
    """
    Apply some of a credit's outstanding balance to an open bill/invoice. No cash
    moves — the target's paid_amount goes up (flipping it to Paid if fully covered)
    and the credit's outstanding goes down. Capped at both the credit's remaining
    balance and the document's amount owing, so neither can be over-applied.
    """
    cn = _load_credit_for_org(db, credit_id, org_id)
    if cn.status == DocumentStatus.VOIDED:
        raise HTTPException(status_code=409, detail="This credit has been voided")

    outstanding = _outstanding(cn)
    if outstanding <= 0.005:
        raise HTTPException(status_code=409, detail="This credit is fully allocated")

    # A payable (supplier) credit applies to bills; a receivable to invoices.
    want = "bill" if cn.direction == CreditDirection.PAYABLE else "invoice"
    if body.target_type != want:
        raise HTTPException(
            status_code=422,
            detail=f"A {cn.direction.value} credit can only be applied to a {want}",
        )

    Model = Bill if want == "bill" else Invoice
    target = db.get(Model, body.target_id)
    if not target or target.org_id != org_id:
        raise HTTPException(status_code=404, detail=f"{want.capitalize()} not found")
    if target.status in (DocumentStatus.PAID, DocumentStatus.VOIDED):
        raise HTTPException(status_code=409, detail=f"{want.capitalize()} is not open for payment")
    if _norm_ccy(cn.currency) != _norm_ccy(target.currency):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot apply a {cn.currency} credit to a {target.currency} {want} — currencies must match",
        )
    if not _same_vendor(cn, target):
        raise HTTPException(status_code=422, detail=f"That {want} belongs to a different contact")

    target_outstanding = round(target.total - target.paid_amount, 2)
    if target_outstanding <= 0.005:
        raise HTTPException(status_code=409, detail=f"{want.capitalize()} is already fully paid")

    amount = round(body.amount, 2)
    if amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be positive")
    if amount > outstanding + 0.005:
        raise HTTPException(status_code=409, detail=f"Only {outstanding:.2f} {cn.currency} of credit remains")
    if amount > target_outstanding + 0.005:
        raise HTTPException(status_code=409, detail=f"{want.capitalize()} only has {target_outstanding:.2f} owing")

    now = _now()
    db.add(CreditAllocation(
        org_id=org_id, credit_note_id=cn.id,
        target_type=want, target_id=target.id, amount=amount, created_at=now,
    ))

    cn.allocated_amount = round(cn.allocated_amount + amount, 2)
    cn.status = DocumentStatus.PAID if _outstanding(cn) <= 0.005 else DocumentStatus.AWAITING_PAYMENT
    cn.updated_at = now

    target.paid_amount = round(target.paid_amount + amount, 2)
    if target.paid_amount >= target.total - 0.005:
        target.status = DocumentStatus.PAID
    target.updated_at = now

    # Money can't be conjured: a credit can never end up over-allocated.
    if round(cn.allocated_amount, 2) > round(cn.original_amount, 2) + 0.01:
        raise HTTPException(status_code=500, detail="Allocation would over-spend the credit")

    label = _doc_label(db, org_id, want, target.id)
    _log_credit_audit(
        db, org_id=org_id, actor=user, action=AuditAction.ALLOCATE_CREDIT, cn=cn,
        amount=amount, target_type=want, target_id=target.id, target_label=label,
        detail=f"Allocated {amount:.2f} {cn.currency} of {_enum(cn.kind)} to {label}",
    )

    db.add(cn); db.add(target)
    db.commit()
    db.refresh(cn)
    return _to_resp(db, org_id, cn)


@router.delete("/{credit_id}/allocations/{allocation_id}", response_model=CreditResponse)
def remove_allocation(
    credit_id: int,
    allocation_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(require_user),
):
    """
    Reverse a single allocation — the exact inverse of allocate: the target's
    paid_amount drops (re-opening it if it was Paid) and the credit's outstanding
    is restored. Atomic. (Xero's "remove the allocation" before a credit can be
    voided.)
    """
    cn = _load_credit_for_org(db, credit_id, org_id)
    alloc = db.get(CreditAllocation, allocation_id)
    if not alloc or alloc.org_id != org_id or alloc.credit_note_id != cn.id:
        raise HTTPException(status_code=404, detail="Allocation not found")

    now = _now()
    Model = Bill if alloc.target_type == "bill" else Invoice
    target = db.get(Model, alloc.target_id)
    if target and target.org_id == org_id:
        target.paid_amount = round(target.paid_amount - alloc.amount, 2)
        if target.paid_amount < target.total - 0.005 and target.status == DocumentStatus.PAID:
            target.status = DocumentStatus.AWAITING_PAYMENT
        target.updated_at = now
        db.add(target)

    cn.allocated_amount = round(cn.allocated_amount - alloc.amount, 2)
    if cn.allocated_amount < 0:
        cn.allocated_amount = 0.0
    if cn.status != DocumentStatus.VOIDED:
        cn.status = DocumentStatus.AWAITING_PAYMENT   # has outstanding again
    cn.updated_at = now

    label = _doc_label(db, org_id, alloc.target_type, alloc.target_id)
    _log_credit_audit(
        db, org_id=org_id, actor=user, action=AuditAction.REMOVE_ALLOCATION, cn=cn,
        amount=alloc.amount, target_type=alloc.target_type, target_id=alloc.target_id,
        target_label=label, detail=f"Removed allocation of {alloc.amount:.2f} {cn.currency} from {label}",
    )

    db.delete(alloc)
    db.add(cn)
    db.commit()
    db.refresh(cn)
    return _to_resp(db, org_id, cn)
