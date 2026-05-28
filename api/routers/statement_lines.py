"""
Statement line management — the heart of the Reconcile screen.

Reconcile actions (Xero-style):
  Match    → link statement line to an Invoice or Bill, update paid_amount
  Create   → spawn a JournalEntry, link it
  Transfer → mark as cross-account transfer
  Discuss  → attach a note, leave pending
  Unreconcile → undo any of the above

Every reconcile action updates the corresponding BankAccount.ooo_balance so
the invariant `statement_balance == ooo_balance` (once all lines are
reconciled) is maintained.
"""
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from memory.models import (
    BankAccount, StatementLine, StatementLineStatus,
    Invoice, Bill, JournalEntry, DocumentStatus, VendorAlias,
)
from api.schemas.models import (
    StatementLineResponse, StatementImportRequest,
    MatchInvoiceRequest, MatchBillRequest, CreateEntryRequest,
    TransferRequest, DiscussRequest,
)
from api.deps import get_db, get_current_org_id
from engine.bank_statement_parser import parse_bank_statement
from engine.vendor_matching.matcher import find_matches as match_vendors

_STATEMENT_MIMES = {
    "text/csv", "application/vnd.ms-excel",
    "application/pdf",
}

router = APIRouter(prefix="/statement-lines", tags=["statement-lines"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_resp(s: StatementLine) -> StatementLineResponse:
    return StatementLineResponse(
        id=s.id, bank_account_id=s.bank_account_id, date=s.date,
        description=s.description, reference=s.reference,
        spent=s.spent, received=s.received, balance_after=s.balance_after,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        matched_invoice_id=s.matched_invoice_id,
        matched_bill_id=s.matched_bill_id,
        matched_journal_id=s.matched_journal_id,
        transfer_to_account_id=s.transfer_to_account_id,
        discussion=s.discussion, suggested_score=s.suggested_score,
        imported_at=s.imported_at, reconciled_at=s.reconciled_at,
    )


def _net_amount(s: StatementLine) -> float:
    """Signed: +ve if money in, -ve if money out."""
    return s.received - s.spent


def _apply_balance(db: Session, account_id: int, delta: float, org_id: int) -> None:
    """Adjust the OOO balance of a bank account by the given signed delta."""
    acc = db.get(BankAccount, account_id)
    if acc and acc.org_id == org_id:
        acc.ooo_balance = round(acc.ooo_balance + delta, 2)
        db.add(acc)


def _require_pending(line: StatementLine) -> None:
    if line.status != StatementLineStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Line is already {line.status.value}. Unreconcile first.",
        )


def _load_line_for_org(db: Session, line_id: int, org_id: int) -> StatementLine:
    s = db.get(StatementLine, line_id)
    if not s or s.org_id != org_id:
        raise HTTPException(status_code=404, detail="Statement line not found")
    return s


def _load_account_for_org(db: Session, account_id: int, org_id: int) -> BankAccount:
    acc = db.get(BankAccount, account_id)
    if not acc or acc.org_id != org_id:
        raise HTTPException(status_code=404, detail="Bank account not found")
    return acc


# ── List / read ──────────────────────────────────────────────────────────────

@router.get("/", response_model=list[StatementLineResponse])
def list_lines(
    bank_account_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(StatementLine).where(StatementLine.org_id == org_id)
    if bank_account_id is not None:
        q = q.where(StatementLine.bank_account_id == bank_account_id)
    if status:
        q = q.where(StatementLine.status == status)
    q = q.order_by(StatementLine.date.desc())
    return [_to_resp(s) for s in db.exec(q).all()]


@router.get("/{line_id}", response_model=StatementLineResponse)
def get_line(
    line_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    s = _load_line_for_org(db, line_id, org_id)
    return _to_resp(s)


# ── Bulk import ──────────────────────────────────────────────────────────────

@router.post("/import", response_model=list[StatementLineResponse], status_code=201)
def import_lines(
    body: StatementImportRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    acc = _load_account_for_org(db, body.bank_account_id, org_id)

    now = _now()
    created = []
    for ln in body.lines:
        s = StatementLine(
            org_id=org_id,
            bank_account_id=body.bank_account_id,
            date=ln.date, description=ln.description, reference=ln.reference,
            spent=ln.spent, received=ln.received, balance_after=ln.balance_after,
            status=StatementLineStatus.PENDING,
            imported_at=now,
        )
        db.add(s)
        created.append(s)

    # Update the bank's recorded statement_balance to the latest line's running balance
    if body.lines and body.lines[-1].balance_after is not None:
        acc.statement_balance = body.lines[-1].balance_after
    acc.last_imported_at = now
    db.add(acc)

    db.commit()
    for s in created:
        db.refresh(s)
    return [_to_resp(s) for s in created]


@router.get("/{line_id}/suggestions")
def get_suggestions(
    line_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> list[dict]:
    """
    Return ranked match candidates for a statement line.

    Money in (received > 0)  → matches open invoices (customer paying us)
    Money out (spent > 0)    → matches open bills (us paying suppliers)

    Composite score = amount(0.5) + date(0.2) + name(0.3) where the name
    component comes from the full 4-tier vendor matcher (alias lookup,
    canonical normalization, lexical similarity, embedding fallback).
    """
    s = _load_line_for_org(db, line_id, org_id)

    amount = s.received if s.received > 0 else s.spent
    is_inflow = s.received > 0

    # ── Gather candidates ────────────────────────────────────────────────────
    if is_inflow:
        docs = db.exec(
            select(Invoice).where(
                Invoice.org_id == org_id,
                Invoice.status != DocumentStatus.PAID,
                Invoice.status != DocumentStatus.VOIDED,
            )
        ).all()
        # (id, label, contact, date, outstanding, currency)
        cands = [
            (d.id, d.number, d.contact_name, d.issue_date,
             round(d.total - d.paid_amount, 2), d.currency)
            for d in docs if (d.total - d.paid_amount) > 0
        ]
        cand_type = "invoice"
    else:
        docs = db.exec(
            select(Bill).where(
                Bill.org_id == org_id,
                Bill.status != DocumentStatus.PAID,
                Bill.status != DocumentStatus.VOIDED,
            )
        ).all()
        cands = [
            (d.id, d.number or f"Bill #{d.id}", d.contact_name, d.issue_date,
             round(d.total - d.paid_amount, 2), d.currency)
            for d in docs if (d.total - d.paid_amount) > 0
        ]
        cand_type = "bill"

    if not cands:
        return []

    # ── Name match via the real vendor matcher (alias + canonical + fuzzy + embed) ──
    alias_rows = db.exec(select(VendorAlias).where(VendorAlias.org_id == org_id)).all()
    alias_map = {a.alias.lower(): a.canonical_name for a in alias_rows}

    contact_names = [c[2] for c in cands]
    name_matches = match_vendors(
        s.description or "",
        contact_names,
        alias_map=alias_map,
        threshold=0.0,           # don't filter — we want a score for every candidate
        use_embeddings=True,
        top_k=len(contact_names),
    )
    # idx → (name_score, method)
    name_score_by_idx: dict[int, tuple[float, str]] = {
        nm.invoice_idx: (nm.score, nm.method) for nm in name_matches
    }

    # ── Date diff helper ────────────────────────────────────────────────────
    def date_diff(a: str, b: str) -> int | None:
        try:
            return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).days
        except (ValueError, TypeError):
            return None

    # ── Score every candidate ───────────────────────────────────────────────
    out: list[dict] = []
    for idx, (cid, label, contact, doc_date, outstanding, currency) in enumerate(cands):
        reasons: list[str] = []

        # Amount component (0–0.5)
        diff = abs(amount - outstanding)
        if diff < 0.01:
            amount_score = 0.5
            reasons.append("exact amount")
        elif diff / max(amount, 0.01) < 0.01:
            amount_score = 0.4
            reasons.append(f"≈ amount (Δ{diff:.2f})")
        elif diff / max(amount, 0.01) < 0.05:
            amount_score = 0.25
            reasons.append(f"amount off by {diff:.2f}")
        else:
            amount_score = 0.0
            reasons.append(f"amount differs by {diff:.2f}")

        # Date component (0–0.2)
        d = date_diff(s.date, doc_date)
        if d is None:
            date_score = 0.0
        else:
            ad = abs(d)
            if ad == 0:
                date_score = 0.2; reasons.append("same day")
            elif ad <= 3:
                date_score = 0.17; reasons.append(f"{ad}d apart")
            elif ad <= 14:
                date_score = 0.10; reasons.append(f"{ad}d apart")
            elif ad <= 30:
                date_score = 0.05; reasons.append(f"{ad}d apart")
            else:
                date_score = 0.0; reasons.append(f"{ad}d apart")

        # Name component (0–0.3) via the proper matcher
        name_score_raw, method = name_score_by_idx.get(idx, (0.0, "no-name"))
        name_score = name_score_raw * 0.3
        if name_score_raw >= 0.95:
            reasons.append(f"name {method}")
        elif name_score_raw >= 0.70:
            reasons.append(f"name fuzzy ({int(name_score_raw * 100)}%)")
        # else: silent, don't clutter

        composite = min(amount_score + date_score + name_score, 1.0)

        out.append({
            "type": cand_type,
            "id": cid,
            "label": label,
            "contact_name": contact,
            "date": doc_date,
            "amount": outstanding,
            "currency": currency,
            "score": round(composite, 3),
            "reason": ", ".join(reasons) or "low confidence",
            "method": method,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:5]


@router.post("/upload", response_model=list[StatementLineResponse], status_code=201)
async def upload_statement(
    bank_account_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Accept a CSV or PDF bank statement, parse it via the engine's
    statement parser (CSV passthrough or LLM-extracted for PDFs), and
    insert StatementLine rows for the named bank account.
    """
    acc = _load_account_for_org(db, bank_account_id, org_id)

    contents = await file.read()
    mime = (file.content_type or "").lower()
    if mime not in _STATEMENT_MIMES:
        # Be lenient on csv mime variations
        if (file.filename or "").lower().endswith(".csv"):
            mime = "text/csv"
        elif (file.filename or "").lower().endswith(".pdf"):
            mime = "application/pdf"
        else:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type: {mime or 'unknown'}. Use CSV or PDF.",
            )

    try:
        df = await asyncio.to_thread(parse_bank_statement, contents, mime)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=422, detail=f"Could not parse statement: {e}",
        )

    now = _now()
    created: list[StatementLine] = []
    last_balance_after: float | None = None

    for _, row in df.iterrows():
        amount = float(row.get("amount", 0.0))
        balance_after = row.get("balance_after")
        if balance_after is not None and not (isinstance(balance_after, float) and balance_after != balance_after):  # NaN check
            try:
                last_balance_after = float(balance_after)
            except (TypeError, ValueError):
                last_balance_after = None

        s = StatementLine(
            org_id=org_id,
            bank_account_id=bank_account_id,
            date=str(row.get("date", "")),
            description=str(row.get("description", "")),
            reference=None,
            spent=abs(amount) if amount < 0 else 0.0,
            received=amount if amount > 0 else 0.0,
            balance_after=last_balance_after,
            status=StatementLineStatus.PENDING,
            imported_at=now,
        )
        db.add(s)
        created.append(s)

    if last_balance_after is not None:
        acc.statement_balance = last_balance_after
    acc.last_imported_at = now
    db.add(acc)

    db.commit()
    for s in created:
        db.refresh(s)
    return [_to_resp(s) for s in created]


# ── Reconcile actions ────────────────────────────────────────────────────────

@router.post("/{line_id}/match-invoice", response_model=StatementLineResponse)
def match_invoice(
    line_id: int,
    body: MatchInvoiceRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    s = _load_line_for_org(db, line_id, org_id)
    _require_pending(s)

    inv = db.get(Invoice, body.invoice_id)
    if not inv or inv.org_id != org_id:
        raise HTTPException(status_code=404, detail="Invoice not found")

    amount = _net_amount(s)  # invoice payment = received from customer (positive)
    s.matched_invoice_id = inv.id
    s.status = StatementLineStatus.MATCHED
    s.reconciled_at = _now()

    inv.paid_amount = round(inv.paid_amount + amount, 2)
    if inv.paid_amount >= inv.total - 0.005:
        inv.status = DocumentStatus.PAID
    inv.updated_at = _now()

    _apply_balance(db, s.bank_account_id, amount, org_id)

    db.add(s); db.add(inv)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/match-bill", response_model=StatementLineResponse)
def match_bill(
    line_id: int,
    body: MatchBillRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    s = _load_line_for_org(db, line_id, org_id)
    _require_pending(s)

    bill = db.get(Bill, body.bill_id)
    if not bill or bill.org_id != org_id:
        raise HTTPException(status_code=404, detail="Bill not found")

    amount = _net_amount(s)  # bill payment = spent on supplier (negative line)
    abs_amount = abs(amount)
    s.matched_bill_id = bill.id
    s.status = StatementLineStatus.MATCHED
    s.reconciled_at = _now()

    bill.paid_amount = round(bill.paid_amount + abs_amount, 2)
    if bill.paid_amount >= bill.total - 0.005:
        bill.status = DocumentStatus.PAID
    bill.updated_at = _now()

    _apply_balance(db, s.bank_account_id, amount, org_id)

    db.add(s); db.add(bill)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/create-entry", response_model=StatementLineResponse)
def create_entry(
    line_id: int,
    body: CreateEntryRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    s = _load_line_for_org(db, line_id, org_id)
    _require_pending(s)

    amount = _net_amount(s)
    j = JournalEntry(
        org_id=org_id,
        date=s.date, contact_id=body.contact_id, contact_name=body.contact_name,
        account_code=body.account_code, description=body.description,
        amount=amount, tax_rate=body.tax_rate, created_at=_now(),
    )
    db.add(j); db.commit(); db.refresh(j)

    s.matched_journal_id = j.id
    s.status = StatementLineStatus.MANUAL
    s.reconciled_at = _now()

    _apply_balance(db, s.bank_account_id, amount, org_id)

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/transfer", response_model=StatementLineResponse)
def transfer(
    line_id: int,
    body: TransferRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    s = _load_line_for_org(db, line_id, org_id)
    _require_pending(s)

    to_acc = _load_account_for_org(db, body.to_account_id, org_id)

    amount = _net_amount(s)
    s.transfer_to_account_id = body.to_account_id
    s.status = StatementLineStatus.TRANSFER
    s.reconciled_at = _now()

    # Both sides move — source by amount, destination by -amount
    _apply_balance(db, s.bank_account_id, amount, org_id)
    _apply_balance(db, body.to_account_id, -amount, org_id)

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/discuss", response_model=StatementLineResponse)
def discuss(
    line_id: int,
    body: DiscussRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    s = _load_line_for_org(db, line_id, org_id)
    s.discussion = body.note
    # Discussing doesn't reconcile — keep PENDING unless already resolved
    if s.status == StatementLineStatus.PENDING:
        s.status = StatementLineStatus.DISCUSSED
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/unreconcile", response_model=StatementLineResponse)
def unreconcile(
    line_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Undo any reconcile action, restoring the line to PENDING."""
    s = _load_line_for_org(db, line_id, org_id)
    if s.status == StatementLineStatus.PENDING:
        return _to_resp(s)

    amount = _net_amount(s)

    # Reverse any side effects of the original action
    if s.matched_invoice_id:
        inv = db.get(Invoice, s.matched_invoice_id)
        if inv and inv.org_id == org_id:
            inv.paid_amount = round(inv.paid_amount - amount, 2)
            if inv.paid_amount < inv.total - 0.005 and inv.status == DocumentStatus.PAID:
                inv.status = DocumentStatus.AWAITING_PAYMENT
            inv.updated_at = _now()
            db.add(inv)
        _apply_balance(db, s.bank_account_id, -amount, org_id)

    elif s.matched_bill_id:
        bill = db.get(Bill, s.matched_bill_id)
        if bill and bill.org_id == org_id:
            bill.paid_amount = round(bill.paid_amount - abs(amount), 2)
            if bill.paid_amount < bill.total - 0.005 and bill.status == DocumentStatus.PAID:
                bill.status = DocumentStatus.AWAITING_PAYMENT
            bill.updated_at = _now()
            db.add(bill)
        _apply_balance(db, s.bank_account_id, -amount, org_id)

    elif s.matched_journal_id:
        j = db.get(JournalEntry, s.matched_journal_id)
        if j and j.org_id == org_id:
            db.delete(j)
        _apply_balance(db, s.bank_account_id, -amount, org_id)

    elif s.transfer_to_account_id:
        _apply_balance(db, s.bank_account_id, -amount, org_id)
        _apply_balance(db, s.transfer_to_account_id, amount, org_id)

    s.matched_invoice_id = None
    s.matched_bill_id = None
    s.matched_journal_id = None
    s.transfer_to_account_id = None
    s.status = StatementLineStatus.PENDING
    s.reconciled_at = None

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)
