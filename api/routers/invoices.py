"""Invoice CRUD with line items + status transitions."""
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from memory.models import Invoice, InvoiceLine, DocumentStatus
from api.schemas.models import (
    InvoiceCreate, InvoiceResponse, InvoiceUpdate, InvoiceLineResponse,
)
from api.deps import get_db, get_current_org_id
from engine.contacts import upsert_contact
from engine.file_store import save_upload
from mcp_server.tools.invoice_extractor import extract_invoice

_ALLOWED_MIMES = {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp"}

_TRANSIENT_ERROR_HINTS = (
    "rate", "429", "timeout", "unavailable", "503", "502", "504",
    "deadline", "overload", "exhausted",
)


async def _extract_with_retry(contents: bytes, filename: str, mime: str, doc_type: str):
    """
    Up to 3 attempts on transient errors with growing backoff (2s, 5s).
    The underlying LLM layer also has Gemini → OpenRouter fallback, so a
    single file can get up to 6 LLM tries before we give up.
    """
    import asyncio
    backoffs = [2.0, 5.0]
    last = None
    for attempt in range(3):
        result = await asyncio.to_thread(extract_invoice, contents, filename, mime, doc_type)
        if not result.error:
            return result
        last = result
        err_low = result.error.lower()
        is_transient = any(h in err_low for h in _TRANSIENT_ERROR_HINTS)
        if not is_transient or attempt >= 2:
            return result
        await asyncio.sleep(backoffs[attempt])
    return last

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


def _load_invoice_for_org(db: Session, invoice_id: int, org_id: int) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.org_id != org_id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.get("/", response_model=list[InvoiceResponse])
def list_invoices(
    status: str | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(Invoice).where(Invoice.org_id == org_id)
    if status:
        q = q.where(Invoice.status == status)
    invs = db.exec(q).all()
    out = []
    for inv in invs:
        lines = db.exec(
            select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id, InvoiceLine.org_id == org_id)
        ).all()
        out.append(_to_resp(inv, lines))
    return out


@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    inv = _load_invoice_for_org(db, invoice_id, org_id)
    lines = db.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id, InvoiceLine.org_id == org_id)
    ).all()
    return _to_resp(inv, lines)


@router.post("/", response_model=InvoiceResponse, status_code=201)
def create_invoice(
    body: InvoiceCreate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    now = _now()
    # If no contact_id supplied, auto-upsert one from the typed contact_name.
    contact_id = body.contact_id
    if contact_id is None and body.contact_name.strip():
        contact_id = upsert_contact(
            db, org_id=org_id, name=body.contact_name, contact_type="customer",
        ).id
    inv = Invoice(
        org_id=org_id,
        number=body.number, contact_id=contact_id, contact_name=body.contact_name,
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
            org_id=org_id,
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
def update_invoice(
    invoice_id: int,
    body: InvoiceUpdate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    inv = _load_invoice_for_org(db, invoice_id, org_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        data["status"] = DocumentStatus(data["status"])
    for k, v in data.items():
        setattr(inv, k, v)
    inv.updated_at = _now()
    db.add(inv)
    db.commit()
    db.refresh(inv)
    lines = db.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id, InvoiceLine.org_id == org_id)
    ).all()
    return _to_resp(inv, lines)


@router.delete("/{invoice_id}", status_code=204)
def delete_invoice(
    invoice_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    inv = _load_invoice_for_org(db, invoice_id, org_id)
    lines = db.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id, InvoiceLine.org_id == org_id)
    ).all()
    for l in lines:
        db.delete(l)
    db.delete(inv)
    db.commit()


@router.post("/upload", response_model=InvoiceResponse, status_code=201)
async def upload_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Accept a PDF/image of a sales invoice. The LLM extractor pulls out
    customer, date, amount and currency, then a draft Invoice is created
    with a single line item containing the extracted total. The user
    reviews and refines the lines before approving.
    """
    contents = await file.read()
    mime = (file.content_type or "").lower()
    if mime not in _ALLOWED_MIMES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {mime or 'unknown'}. Use PDF, PNG, JPG or WEBP.",
        )

    filename = file.filename or "upload.pdf"
    file_hash, storage_path = save_upload(contents, filename, mime)

    # Sync LLM call, run in thread pool + auto-retry transient failures
    result = await _extract_with_retry(contents, filename, mime, "sales")
    if result.error:
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract data from {filename}: {result.error}",
        )

    now = _now()
    customer_name = (result.vendor or "Unknown customer").strip()
    contact = upsert_contact(db, org_id=org_id, name=customer_name, contact_type="customer")
    inv = Invoice(
        org_id=org_id,
        number=result.invoice_id or f"INV-PDF-{file_hash[:8].upper()}",
        contact_id=contact.id,
        contact_name=customer_name,
        issue_date=result.date or now[:10],
        currency=(result.currency or "GBP").upper(),
        status=DocumentStatus.DRAFT,
        notes=(
            f"Imported from {filename} "
            f"(confidence {result.confidence:.0%}, file {storage_path})"
        ),
        subtotal=result.amount,
        tax_total=0.0,
        total=result.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    line = InvoiceLine(
        org_id=org_id,
        invoice_id=inv.id,
        description=f"Extracted from {filename} — please verify",
        quantity=1.0,
        unit_price=result.amount,
        tax_rate=0.0,
        line_total=result.amount,
    )
    db.add(line)
    db.commit()
    db.refresh(line)

    return _to_resp(inv, [line])
