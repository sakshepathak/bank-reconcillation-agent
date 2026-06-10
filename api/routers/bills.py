"""Bill CRUD with line items + status transitions (mirror of invoices)."""
import asyncio
import re
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
from mcp_server.tools.invoice_extractor import extract_invoice, extract_multi_from_file

_ALLOWED_MIMES = {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp"}


def _parse_date(raw: str, fallback) -> str | None:
    """ISO YYYY-MM-DD stored as-is. Other formats auto-detect dayfirst."""
    import re as _re
    raw = raw.strip()
    if _re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw
    try:
        import pandas as _pd
        dayfirst = not bool(_re.match(r'^\d{4}', raw))
        return _pd.to_datetime(raw, dayfirst=dayfirst).strftime('%Y-%m-%d')
    except Exception:
        return fallback

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
    if "total" in data:
        new_total = float(data["total"])
        data["subtotal"] = new_total
        data["tax_total"] = 0.0
        lines_to_update = db.exec(
            select(BillLine).where(BillLine.bill_id == bill_id, BillLine.org_id == org_id)
        ).all()
        if len(lines_to_update) == 1:
            lines_to_update[0].unit_price = new_total
            lines_to_update[0].line_total = new_total
            db.add(lines_to_update[0])
    if "contact_name" in data and data["contact_name"]:
        upsert_contact(db, org_id=org_id, name=data["contact_name"], contact_type="supplier")
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


@router.post("/upload-csv", response_model=list[BillResponse], status_code=201)
async def upload_bills_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Accept a CSV of bills and bulk-create them — no LLM needed.

    Supported columns (case-insensitive):
      number / bill_number      → bill number
      supplier / contact_name / vendor / contact → supplier name
      date / issue_date         → issue date (YYYY-MM-DD)
      due_date                  → due date (optional)
      amount / total            → total amount
      currency                  → 3-letter ISO code (default GBP)
      status                    → draft | awaiting_payment (default awaiting_payment)
    """
    import io
    import pandas as pd

    import logging as _logging
    _log = _logging.getLogger(__name__)

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    _log.info("upload-csv bills: received %d bytes, filename=%s", len(contents), file.filename)

    raw = None
    parse_err = None
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            raw = pd.read_csv(io.BytesIO(contents), encoding=enc)
            break
        except Exception as e:
            parse_err = e
            continue
    if raw is None:
        _log.error("upload-csv bills: could not parse CSV — %s", parse_err)
        raise HTTPException(status_code=422, detail=f"Could not parse CSV: {parse_err}")

    raw.columns = [str(c).strip().lower() for c in raw.columns]
    cols = set(raw.columns)

    def _pick(candidates):
        for c in candidates:
            if c in cols:
                return c
        return None

    num_col = _pick(["number", "bill_number", "bill_no", "bill #", "no"])
    supplier_col = _pick(["supplier", "contact_name", "vendor", "contact", "supplier_name", "customer"])
    date_col = _pick(["date", "issue_date", "bill_date"])
    due_col = _pick(["due_date", "due date", "payment_due", "due"])
    amount_col = _pick(["amount", "total", "bill_amount", "bill_total"])
    currency_col = _pick(["currency", "ccy"])
    status_col = _pick(["status"])

    if not supplier_col:
        raise HTTPException(status_code=422, detail=f"CSV missing supplier column. Got: {list(cols)}")
    if not date_col:
        raise HTTPException(status_code=422, detail=f"CSV missing date column. Got: {list(cols)}")
    if not amount_col:
        raise HTTPException(status_code=422, detail=f"CSV missing amount column. Got: {list(cols)}")

    now = _now()
    created: list[BillResponse] = []
    skipped = 0

    for idx, row in raw.iterrows():
        try:
            supplier_name = str(row[supplier_col]).strip()
            if not supplier_name or supplier_name.lower() == "nan":
                skipped += 1
                continue

            raw_date = str(row[date_col]).strip()
            issue_date = _parse_date(raw_date, now[:10])

            due_date = None
            if due_col and str(row.get(due_col, "")).strip() not in ("", "nan"):
                due_date = _parse_date(str(row[due_col]).strip(), None)

            try:
                amount = float(str(row[amount_col]).replace(",", "").replace("£", "").replace("$", "").replace("€", "").strip())
            except (ValueError, TypeError):
                skipped += 1
                continue

            currency = "GBP"
            if currency_col and str(row.get(currency_col, "")).strip() not in ("", "nan"):
                currency = str(row[currency_col]).strip().upper()

            number = None
            if num_col and str(row.get(num_col, "")).strip() not in ("", "nan"):
                number = str(row[num_col]).strip()

            status_val = "awaiting_payment"
            if status_col and str(row.get(status_col, "")).strip().lower() not in ("", "nan"):
                s = str(row[status_col]).strip().lower()
                if s in DocumentStatus._value2member_map_:
                    status_val = s

            contact = upsert_contact(db, org_id=org_id, name=supplier_name, contact_type="supplier")

            # De-dupe by bill number within the org: re-importing the same CSV
            # updates the existing bill in place instead of piling on duplicate
            # rows. Rows without a number always create new records.
            b = None
            if number:
                b = db.exec(
                    select(Bill).where(Bill.org_id == org_id, Bill.number == number)
                ).first()

            if b is not None:
                b.contact_id = contact.id
                b.contact_name = supplier_name
                b.issue_date = issue_date
                b.due_date = due_date
                b.currency = currency
                b.status = DocumentStatus(status_val)
                b.subtotal = amount
                b.tax_total = 0.0
                b.total = amount
                b.updated_at = now
                db.add(b)
                db.commit()
                db.refresh(b)
            else:
                b = Bill(
                    org_id=org_id,
                    number=number,
                    contact_id=contact.id,
                    contact_name=supplier_name,
                    issue_date=issue_date,
                    due_date=due_date,
                    currency=currency,
                    status=DocumentStatus(status_val),
                    subtotal=amount,
                    tax_total=0.0,
                    total=amount,
                    created_at=now,
                    updated_at=now,
                )
                db.add(b)
                db.commit()
                db.refresh(b)

            # Replace line items so the single imported line always matches the
            # current amount (covers both the create and the update path).
            existing_lines = db.exec(
                select(BillLine).where(BillLine.bill_id == b.id, BillLine.org_id == org_id)
            ).all()
            for l in existing_lines:
                db.delete(l)
            line = BillLine(
                org_id=org_id,
                bill_id=b.id,
                description="Imported from CSV",
                quantity=1.0,
                unit_price=amount,
                tax_rate=0.0,
                line_total=amount,
                account_code=None,
            )
            db.add(line)
            db.commit()
            db.refresh(line)
            created.append(_to_resp(b, [line]))
        except Exception as e:  # noqa: BLE001
            _log.error("upload-csv bills: error on row %s: %s", idx, e, exc_info=True)
            skipped += 1
            continue

    _log.info("upload-csv bills: created=%d skipped=%d", len(created), skipped)
    if not created:
        raise HTTPException(status_code=422, detail=f"No valid rows found in CSV. Skipped {skipped} rows.")
    return created


@router.post("/upload", response_model=list[BillResponse], status_code=201)
async def upload_bill(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Accept a PDF/image of one or more supplier bills. The LLM extracts every
    bill it finds in the file, creating one Bill record per document.
    A single-bill PDF returns a list of one; a multi-bill PDF returns many.
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

    results = await asyncio.to_thread(extract_multi_from_file, contents, filename, mime, "purchase")

    if all(r.error for r in results):
        first_err = results[0].error or ""
        is_transient = any(h in first_err.lower() for h in _TRANSIENT_ERROR_HINTS)
        for backoff in ([2.0, 5.0] if is_transient else []):
            await asyncio.sleep(backoff)
            results = await asyncio.to_thread(extract_multi_from_file, contents, filename, mime, "purchase")
            if not all(r.error for r in results):
                break

    ok_results = [r for r in results if r.ok]
    if not ok_results:
        errors = "; ".join(r.error for r in results if r.error)
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract any bills from {filename}: {errors}",
        )

    now = _now()
    created: list[BillResponse] = []
    for i, result in enumerate(ok_results):
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
        created.append(_to_resp(b, [line]))

    return created
