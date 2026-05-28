"""Bill CRUD with line items + status transitions (mirror of invoices)."""
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from memory.models import Bill, BillLine, DocumentStatus
from api.schemas.models import (
    BillCreate, BillResponse, BillUpdate, BillLineResponse,
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
    """3 attempts with 2s / 5s backoff on transient errors."""
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

router = APIRouter(prefix="/bills", tags=["bills"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_totals(lines: list[BillLine]) -> tuple[float, float, float]:
    subtotal = sum(l.line_total for l in lines)
    tax_total = sum(l.line_total * l.tax_rate for l in lines)
    return round(subtotal, 2), round(tax_total, 2), round(subtotal + tax_total, 2)


def _line_to_resp(l: BillLine) -> BillLineResponse:
    return BillLineResponse(
        id=l.id, bill_id=l.bill_id, description=l.description,
        quantity=l.quantity, unit_price=l.unit_price, tax_rate=l.tax_rate,
        line_total=l.line_total, account_code=l.account_code,
    )


def _to_resp(b: Bill, lines: list[BillLine]) -> BillResponse:
    return BillResponse(
        id=b.id, number=b.number, contact_id=b.contact_id,
        contact_name=b.contact_name, reference=b.reference,
        issue_date=b.issue_date, due_date=b.due_date,
        subtotal=b.subtotal, tax_total=b.tax_total, total=b.total,
        paid_amount=b.paid_amount,
        outstanding=round(b.total - b.paid_amount, 2),
        currency=b.currency,
        status=b.status.value if hasattr(b.status, "value") else str(b.status),
        notes=b.notes,
        lines=[_line_to_resp(l) for l in lines],
        created_at=b.created_at, updated_at=b.updated_at,
    )


def _load_bill_for_org(db: Session, bill_id: int, org_id: int) -> Bill:
    b = db.get(Bill, bill_id)
    if not b or b.org_id != org_id:
        raise HTTPException(status_code=404, detail="Bill not found")
    return b


@router.get("/", response_model=list[BillResponse])
def list_bills(
    status: str | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(Bill).where(Bill.org_id == org_id)
    if status:
        q = q.where(Bill.status == status)
    bills = db.exec(q).all()
    out = []
    for b in bills:
        lines = db.exec(
            select(BillLine).where(BillLine.bill_id == b.id, BillLine.org_id == org_id)
        ).all()
        out.append(_to_resp(b, lines))
    return out


@router.get("/{bill_id}", response_model=BillResponse)
def get_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    b = _load_bill_for_org(db, bill_id, org_id)
    lines = db.exec(
        select(BillLine).where(BillLine.bill_id == bill_id, BillLine.org_id == org_id)
    ).all()
    return _to_resp(b, lines)


@router.post("/", response_model=BillResponse, status_code=201)
def create_bill(
    body: BillCreate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    now = _now()
    contact_id = body.contact_id
    if contact_id is None and body.contact_name.strip():
        contact_id = upsert_contact(
            db, org_id=org_id, name=body.contact_name, contact_type="supplier",
        ).id
    b = Bill(
        org_id=org_id,
        number=body.number, contact_id=contact_id, contact_name=body.contact_name,
        reference=body.reference, issue_date=body.issue_date, due_date=body.due_date,
        currency=body.currency, notes=body.notes,
        status=DocumentStatus(body.status),
        created_at=now, updated_at=now,
    )
    db.add(b)
    db.commit()
    db.refresh(b)

    line_objs: list[BillLine] = []
    for ln in body.lines:
        line_total = round(ln.quantity * ln.unit_price, 2)
        l = BillLine(
            org_id=org_id,
            bill_id=b.id, description=ln.description, quantity=ln.quantity,
            unit_price=ln.unit_price, tax_rate=ln.tax_rate, line_total=line_total,
            account_code=ln.account_code,
        )
        db.add(l)
        line_objs.append(l)

    subtotal, tax_total, total = _compute_totals(line_objs)
    b.subtotal, b.tax_total, b.total = subtotal, tax_total, total
    db.add(b)
    db.commit()
    db.refresh(b)
    for l in line_objs:
        db.refresh(l)
    return _to_resp(b, line_objs)


@router.patch("/{bill_id}", response_model=BillResponse)
def update_bill(
    bill_id: int,
    body: BillUpdate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    b = _load_bill_for_org(db, bill_id, org_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        data["status"] = DocumentStatus(data["status"])
    for k, v in data.items():
        setattr(b, k, v)
    b.updated_at = _now()
    db.add(b)
    db.commit()
    db.refresh(b)
    lines = db.exec(
        select(BillLine).where(BillLine.bill_id == bill_id, BillLine.org_id == org_id)
    ).all()
    return _to_resp(b, lines)


@router.delete("/{bill_id}", status_code=204)
def delete_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    b = _load_bill_for_org(db, bill_id, org_id)
    lines = db.exec(
        select(BillLine).where(BillLine.bill_id == bill_id, BillLine.org_id == org_id)
    ).all()
    for l in lines:
        db.delete(l)
    db.delete(b)
    db.commit()


@router.post("/upload", response_model=BillResponse, status_code=201)
async def upload_bill(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Accept a PDF/image of a supplier bill. The LLM extractor pulls out
    supplier, date, amount and currency, then a draft Bill is created
    with a single line item containing the extracted total. The PDF is
    stored on disk and referenced via `source_file_path` so the user can
    view it back later.
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

    result = await _extract_with_retry(contents, filename, mime, "purchase")
    if result.error:
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract data from {filename}: {result.error}",
        )

    now = _now()
    supplier_name = (result.vendor or "Unknown supplier").strip()
    contact = upsert_contact(db, org_id=org_id, name=supplier_name, contact_type="supplier")
    b = Bill(
        org_id=org_id,
        number=result.invoice_id,
        contact_id=contact.id,
        contact_name=supplier_name,
        issue_date=result.date or now[:10],
        currency=(result.currency or "GBP").upper(),
        status=DocumentStatus.DRAFT,
        notes=(
            f"Imported from {filename} "
            f"(confidence {result.confidence:.0%})"
        ),
        source_file_path=storage_path,
        subtotal=result.amount,
        tax_total=0.0,
        total=result.amount,
        created_at=now,
        updated_at=now,
    )
    db.add(b)
    db.commit()
    db.refresh(b)

    line = BillLine(
        org_id=org_id,
        bill_id=b.id,
        description=f"Extracted from {filename} — please verify",
        quantity=1.0,
        unit_price=result.amount,
        tax_rate=0.0,
        line_total=result.amount,
        account_code=None,
    )
    db.add(line)
    db.commit()
    db.refresh(line)

    return _to_resp(b, [line])
