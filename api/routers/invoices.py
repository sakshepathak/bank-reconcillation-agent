"""Invoice CRUD with line items + status transitions."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import Invoice, InvoiceLine, DocumentStatus
from api.schemas.models import (
    InvoiceCreate, InvoiceResponse, InvoiceUpdate, InvoiceLineResponse,
)
from api.deps import get_db

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_totals(lines: list[InvoiceLine]) -> tuple[float, float, float]:
    subtotal = sum(l.line_total for l in lines)
    tax_total = sum(l.line_total * l.tax_rate for l in lines)
    return round(subtotal, 2), round(tax_total, 2), round(subtotal + tax_total, 2)


def _line_to_resp(l: InvoiceLine) -> InvoiceLineResponse:
    return InvoiceLineResponse(
        id=l.id, invoice_id=l.invoice_id, description=l.description,
        quantity=l.quantity, unit_price=l.unit_price, tax_rate=l.tax_rate,
        line_total=l.line_total, service_id=l.service_id,
    )


def _to_resp(inv: Invoice, lines: list[InvoiceLine]) -> InvoiceResponse:
    return InvoiceResponse(
        id=inv.id, number=inv.number, contact_id=inv.contact_id,
        contact_name=inv.contact_name, reference=inv.reference,
        issue_date=inv.issue_date, due_date=inv.due_date,
        subtotal=inv.subtotal, tax_total=inv.tax_total, total=inv.total,
        paid_amount=inv.paid_amount,
        outstanding=round(inv.total - inv.paid_amount, 2),
        currency=inv.currency,
        status=inv.status.value if hasattr(inv.status, "value") else str(inv.status),
        notes=inv.notes, sent=inv.sent,
        lines=[_line_to_resp(l) for l in lines],
        created_at=inv.created_at, updated_at=inv.updated_at,
    )


@router.get("/", response_model=list[InvoiceResponse])
def list_invoices(status: str | None = None, db: Session = Depends(get_db)):
    q = select(Invoice)
    if status:
        q = q.where(Invoice.status == status)
    invs = db.exec(q).all()
    out = []
    for inv in invs:
        lines = db.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).all()
        out.append(_to_resp(inv, lines))
    return out


@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    lines = db.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)).all()
    return _to_resp(inv, lines)


@router.post("/", response_model=InvoiceResponse, status_code=201)
def create_invoice(body: InvoiceCreate, db: Session = Depends(get_db)):
    now = _now()
    inv = Invoice(
        number=body.number, contact_id=body.contact_id, contact_name=body.contact_name,
        reference=body.reference, issue_date=body.issue_date, due_date=body.due_date,
        currency=body.currency, notes=body.notes,
        status=DocumentStatus(body.status),
        created_at=now, updated_at=now,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    line_objs: list[InvoiceLine] = []
    for ln in body.lines:
        line_total = round(ln.quantity * ln.unit_price, 2)
        l = InvoiceLine(
            invoice_id=inv.id, description=ln.description, quantity=ln.quantity,
            unit_price=ln.unit_price, tax_rate=ln.tax_rate, line_total=line_total,
            service_id=ln.service_id,
        )
        db.add(l)
        line_objs.append(l)

    subtotal, tax_total, total = _compute_totals(line_objs)
    inv.subtotal, inv.tax_total, inv.total = subtotal, tax_total, total
    db.add(inv)
    db.commit()
    db.refresh(inv)
    for l in line_objs:
        db.refresh(l)
    return _to_resp(inv, line_objs)


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
def update_invoice(invoice_id: int, body: InvoiceUpdate, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        data["status"] = DocumentStatus(data["status"])
    for k, v in data.items():
        setattr(inv, k, v)
    inv.updated_at = _now()
    db.add(inv)
    db.commit()
    db.refresh(inv)
    lines = db.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)).all()
    return _to_resp(inv, lines)


@router.delete("/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    lines = db.exec(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)).all()
    for l in lines:
        db.delete(l)
    db.delete(inv)
    db.commit()
