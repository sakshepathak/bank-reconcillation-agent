"""Invoice CRUD with line items + status transitions."""
import asyncio
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from memory.models import Invoice, InvoiceLine, DocumentStatus, User
from api.schemas.models import (
    InvoiceCreate, InvoiceResponse, InvoiceUpdate, InvoiceLineResponse,
)
from api.deps import get_db, get_current_org_id, require_user
from engine.contacts import upsert_contact
from engine.file_store import save_upload
from mcp_server.tools.invoice_extractor import extract_invoice, extract_multi_from_file

_ALLOWED_MIMES = {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp"}


def _parse_date(raw: str, fallback) -> str | None:
    """
    Parse a date string to YYYY-MM-DD.

    If the input is already YYYY-MM-DD (ISO 8601) it is stored as-is — no
    pandas, no dayfirst ambiguity, impossible to swap month and day.
    Other formats (DD/MM/YYYY, DD-MM-YYYY, etc.) fall back to pandas with
    dayfirst auto-detected from whether the string starts with a 4-digit year.
    """
    import re as _re
    raw = raw.strip()
    if _re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw  # already ISO — store directly, zero parsing
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
    user: User = Depends(require_user),
):
    inv = _load_invoice_for_org(db, invoice_id, org_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        data["status"] = DocumentStatus(data["status"])
    becoming_voided = (
        data.get("status") == DocumentStatus.VOIDED and inv.status != DocumentStatus.VOIDED
    )
    # When total changes, sync subtotal and the single extracted line if present
    if "total" in data:
        new_total = float(data["total"])
        data["subtotal"] = new_total
        data["tax_total"] = 0.0
        lines_to_update = db.exec(
            select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id, InvoiceLine.org_id == org_id)
        ).all()
        if len(lines_to_update) == 1:
            lines_to_update[0].unit_price = new_total
            lines_to_update[0].line_total = new_total
            db.add(lines_to_update[0])
    if "contact_name" in data and data["contact_name"]:
        upsert_contact(db, org_id=org_id, name=data["contact_name"], contact_type="customer")
    for k, v in data.items():
        setattr(inv, k, v)
    if becoming_voided:
        # Voiding an invoice releases any credit that was allocated to it.
        from api.routers.credits import reverse_allocations_for_target
        restored = reverse_allocations_for_target(
            db, org_id=org_id, target_type="invoice", target_id=inv.id, actor=user,
            reason="invoice voided",
        )
        inv.paid_amount = round(max(0.0, inv.paid_amount - restored), 2)
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
    user: User = Depends(require_user),
):
    from api.routers.credits import reverse_allocations_for_target
    inv = _load_invoice_for_org(db, invoice_id, org_id)
    # Any credit applied to this invoice comes back — the money is still ours.
    reverse_allocations_for_target(
        db, org_id=org_id, target_type="invoice", target_id=invoice_id, actor=user,
        reason="invoice deleted",
    )
    lines = db.exec(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id, InvoiceLine.org_id == org_id)
    ).all()
    for l in lines:
        db.delete(l)
    db.delete(inv)
    db.commit()


@router.post("/upload-csv", response_model=list[InvoiceResponse], status_code=201)
async def upload_invoices_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Accept a CSV of invoices and bulk-create them — no LLM needed.

    Supported columns (case-insensitive):
      number / invoice_number   → invoice number
      customer / contact_name / client / contact  → customer name
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

    _log.info("upload-csv invoices: received %d bytes, filename=%s, content_type=%s",
              len(contents), file.filename, file.content_type)

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
        _log.error("upload-csv: could not parse CSV — %s", parse_err)
        raise HTTPException(status_code=422, detail=f"Could not parse CSV: {parse_err}")

    _log.info("upload-csv: parsed %d rows, columns=%s", len(raw), list(raw.columns))

    raw.columns = [str(c).strip().lower() for c in raw.columns]
    cols = set(raw.columns)

    def _pick(candidates):
        for c in candidates:
            if c in cols:
                return c
        return None

    num_col = _pick(["number", "invoice_number", "invoice_no", "invoice #", "no"])
    customer_col = _pick(["customer", "contact_name", "client", "contact", "customer_name"])
    date_col = _pick(["date", "issue_date", "invoice_date"])
    due_col = _pick(["due_date", "due date", "payment_due", "due"])
    amount_col = _pick(["amount", "total", "invoice_amount", "invoice_total"])
    currency_col = _pick(["currency", "ccy"])
    status_col = _pick(["status"])

    if not customer_col:
        raise HTTPException(status_code=422, detail=f"CSV missing customer column. Columns found: {sorted(cols)}")
    if not date_col:
        raise HTTPException(status_code=422, detail=f"CSV missing date column. Columns found: {sorted(cols)}")
    if not amount_col:
        raise HTTPException(status_code=422, detail=f"CSV missing amount column. Columns found: {sorted(cols)}")

    now = _now()
    result: list[InvoiceResponse] = []
    created = updated = skipped = 0

    for idx, row in raw.iterrows():
        try:
            customer_name = str(row[customer_col]).strip()
            if not customer_name or customer_name.lower() == "nan":
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

            contact = upsert_contact(db, org_id=org_id, name=customer_name, contact_type="customer")

            # De-dupe by invoice number within the org: re-importing the same
            # CSV updates the existing invoice in place instead of piling on
            # duplicate rows. Rows without a number always create new records.
            inv = None
            if number:
                inv = db.exec(
                    select(Invoice).where(Invoice.org_id == org_id, Invoice.number == number)
                ).first()

            if inv is not None:
                inv.contact_id = contact.id
                inv.contact_name = customer_name
                inv.issue_date = issue_date
                inv.due_date = due_date
                inv.currency = currency
                inv.status = DocumentStatus(status_val)
                inv.subtotal = amount
                inv.tax_total = 0.0
                inv.total = amount
                inv.updated_at = now
                db.add(inv)
                db.commit()
                db.refresh(inv)
                updated += 1
            else:
                inv = Invoice(
                    org_id=org_id,
                    number=number or f"INV-CSV-{now[:10]}-{created+1:03d}",
                    contact_id=contact.id,
                    contact_name=customer_name,
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
                db.add(inv)
                db.commit()
                db.refresh(inv)
                created += 1

            # Replace line items so the single imported line always matches the
            # current amount (covers both the create and the update path).
            existing_lines = db.exec(
                select(InvoiceLine).where(
                    InvoiceLine.invoice_id == inv.id, InvoiceLine.org_id == org_id
                )
            ).all()
            for l in existing_lines:
                db.delete(l)
            line = InvoiceLine(
                org_id=org_id,
                invoice_id=inv.id,
                description="Imported from CSV",
                quantity=1.0,
                unit_price=amount,
                tax_rate=0.0,
                line_total=amount,
            )
            db.add(line)
            db.commit()
            db.refresh(line)
            result.append(_to_resp(inv, [line]))
        except Exception as e:  # noqa: BLE001
            _log.error("upload-csv: error on row %s: %s", idx, e, exc_info=True)
            skipped += 1
            continue

    _log.info("upload-csv: created=%d updated=%d skipped=%d", created, updated, skipped)
    if not result:
        raise HTTPException(status_code=422, detail=f"No valid rows found in CSV. Skipped {skipped} rows.")
    return result


@router.post("/upload", response_model=list[InvoiceResponse], status_code=201)
async def upload_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Accept a PDF/image of one or more sales invoices. The LLM extracts every
    invoice it finds in the file, creating one Invoice record per document.
    A single-invoice PDF returns a list of one; a multi-invoice PDF returns many.
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

    results = await asyncio.to_thread(extract_multi_from_file, contents, filename, mime, "sales")

    # Retry transient errors on the whole batch (simple: if ALL failed with transient error)
    if all(r.error for r in results):
        first_err = results[0].error or ""
        is_transient = any(h in first_err.lower() for h in _TRANSIENT_ERROR_HINTS)
        for backoff in ([2.0, 5.0] if is_transient else []):
            await asyncio.sleep(backoff)
            results = await asyncio.to_thread(extract_multi_from_file, contents, filename, mime, "sales")
            if not all(r.error for r in results):
                break

    ok_results = [r for r in results if r.ok]
    if not ok_results:
        errors = "; ".join(r.error for r in results if r.error)
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract any invoices from {filename}: {errors}",
        )

    now = _now()
    created: list[InvoiceResponse] = []
    for i, result in enumerate(ok_results):
        customer_name = (result.vendor or "Unknown customer").strip()
        contact = upsert_contact(db, org_id=org_id, name=customer_name, contact_type="customer")
        inv = Invoice(
            org_id=org_id,
            number=result.invoice_id or f"INV-PDF-{file_hash[:8].upper()}-{i+1:02d}",
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
        created.append(_to_resp(inv, [line]))

    return created
