"""
Statement line management — the heart of the Reconcile screen.

Reconcile actions:
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
import json
from collections import defaultdict
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
    MatchBulkInvoicesRequest, MatchBulkBillsRequest,
    BulkMatchSuggestionsResponse, BulkMatchOpenDoc,
)
from api.deps import get_db, get_current_org_id
from engine.bank_statement_parser import parse_bank_statement
from engine.vendor_matching.matcher import find_matches as match_vendors
from engine.vendor_matching.explain import explain_candidate

_STATEMENT_MIMES = {
    "text/csv", "application/vnd.ms-excel",
    "application/pdf",
}

router = APIRouter(prefix="/statement-lines", tags=["statement-lines"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_resp(s: StatementLine) -> StatementLineResponse:
    def _parse_json_field(raw) -> list[dict] | None:
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else None
        except (json.JSONDecodeError, TypeError):
            return None

    return StatementLineResponse(
        id=s.id, bank_account_id=s.bank_account_id, date=s.date,
        description=s.description, reference=s.reference,
        spent=s.spent, received=s.received, balance_after=s.balance_after,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        matched_invoice_id=s.matched_invoice_id,
        matched_bill_id=s.matched_bill_id,
        matched_journal_id=s.matched_journal_id,
        transfer_to_account_id=s.transfer_to_account_id,
        matched_invoice_ids=_parse_json_field(getattr(s, "matched_invoice_ids", None)),
        matched_bill_ids=_parse_json_field(getattr(s, "matched_bill_ids", None)),
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


@router.get("/{line_id}/explain")
def explain_suggestion(
    line_id: int,
    doc_type: str | None = None,
    doc_id: int | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> dict:
    """
    Step-by-step trace of HOW this bank line scores against one candidate
    invoice/bill — the "How was this matched?" panel. Returns every intermediate
    the matcher computes (normalisation, alias, lexical sub-scores, embedding
    cosine, ensemble, amount/date gates, composite). The numbers are identical
    to what `/suggestions` produced because both call the same engine.

    If `doc_type`+`doc_id` are omitted, explains the top-ranked suggestion.
    """
    s = _load_line_for_org(db, line_id, org_id)
    is_inflow = s.received > 0
    bank_amount = s.received if is_inflow else s.spent

    # Resolve which candidate to explain.
    if doc_type not in ("invoice", "bill") or doc_id is None:
        top = get_suggestions(line_id, db, org_id)
        if not top:
            raise HTTPException(status_code=404, detail="No candidates to explain for this line")
        doc_type, doc_id = top[0]["type"], top[0]["id"]

    if doc_type == "invoice":
        doc = db.get(Invoice, doc_id)
        if not doc or doc.org_id != org_id:
            raise HTTPException(status_code=404, detail="Invoice not found")
        cand_label = doc.number or f"INV #{doc.id}"
    else:
        doc = db.get(Bill, doc_id)
        if not doc or doc.org_id != org_id:
            raise HTTPException(status_code=404, detail="Bill not found")
        cand_label = doc.number or f"Bill #{doc.id}"

    outstanding = round(doc.total - doc.paid_amount, 2)

    alias_rows = db.exec(select(VendorAlias).where(VendorAlias.org_id == org_id)).all()
    alias_map = {a.alias.lower(): a.canonical_name for a in alias_rows}

    trace = explain_candidate(
        bank_desc=s.description or "",
        bank_amount=bank_amount,
        bank_date=s.date,
        cand_label=cand_label,
        cand_vendor=doc.contact_name or "",
        cand_amount=outstanding,
        cand_date=doc.issue_date,
        alias_map=alias_map,
    )
    trace["candidate"] = {"type": doc_type, "id": doc_id}
    return trace


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


# ── Bulk-match helpers ───────────────────────────────────────────────────────

def _find_bulk_combinations(
    items: list[tuple[int, float]],   # (id, outstanding_amount)
    target: float,
    tolerance: float = 0.01,
    max_results: int = 5,
) -> list[list[tuple[int, float]]]:
    """
    DFS subset-sum: find all subsets of `items` whose outstanding amounts sum
    within `tolerance` of `target`.  Returns up to `max_results` groups,
    preferring smaller subsets (fewer invoices first).
    """
    results: list[list[tuple[int, float]]] = []

    def dfs(start: int, running: float, path: list[tuple[int, float]]) -> None:
        if len(results) >= max_results:
            return
        if abs(running - target) <= tolerance:
            results.append(list(path))
            return
        if running > target + tolerance:
            return
        for i in range(start, len(items)):
            item_id, amt = items[i]
            path.append((item_id, amt))
            dfs(i + 1, running + amt, path)
            path.pop()

    dfs(0, 0.0, [])
    return results


# ── Bulk-match endpoints ──────────────────────────────────────────────────────

@router.get("/{line_id}/bulk-suggestions", response_model=BulkMatchSuggestionsResponse)
def get_bulk_suggestions(
    line_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Identify the likely vendor from the bank description using the vendor
    matcher, then return all their open invoices/bills plus any exact-sum
    subsets.  The UI uses this to render the interactive Bulk Match panel.
    """
    s = _load_line_for_org(db, line_id, org_id)

    is_inflow = s.received > 0
    target = s.received if is_inflow else s.spent
    doc_type = "invoice" if is_inflow else "bill"

    empty = BulkMatchSuggestionsResponse(
        vendor=None, vendor_score=0.0, doc_type=doc_type,
        open_docs=[], suggested_groups=[],
    )

    if s.status != StatementLineStatus.PENDING:
        return empty

    # ── Fetch all open docs for this org ────────────────────────────────────
    if is_inflow:
        all_docs = db.exec(
            select(Invoice).where(
                Invoice.org_id == org_id,
                Invoice.status != DocumentStatus.PAID,
                Invoice.status != DocumentStatus.VOIDED,
            )
        ).all()
    else:
        all_docs = db.exec(
            select(Bill).where(
                Bill.org_id == org_id,
                Bill.status != DocumentStatus.PAID,
                Bill.status != DocumentStatus.VOIDED,
            )
        ).all()

    open_docs = [d for d in all_docs if (d.total - d.paid_amount) > 0.005]
    if len(open_docs) < 2:
        return empty

    # ── Identify top vendor from bank description ────────────────────────────
    alias_rows = db.exec(select(VendorAlias).where(VendorAlias.org_id == org_id)).all()
    alias_map = {a.alias.lower(): a.canonical_name for a in alias_rows}

    unique_vendors = list({d.contact_name for d in open_docs})
    name_matches = match_vendors(
        s.description or "",
        unique_vendors,
        alias_map=alias_map,
        threshold=0.0,
        use_embeddings=True,
        top_k=1,
    )

    top_vendor: str | None = None
    top_score: float = 0.0
    if name_matches:
        nm = name_matches[0]
        top_score = nm.score
        if top_score >= 0.25:           # loose threshold — user can see the list
            top_vendor = unique_vendors[nm.invoice_idx]

    # ── Filter to top vendor's docs ──────────────────────────────────────────
    if top_vendor:
        vendor_docs = [d for d in open_docs if d.contact_name == top_vendor]
    else:
        # No clear vendor — still expose all open docs (user can pick manually)
        vendor_docs = open_docs

    if len(vendor_docs) < 2:
        return empty

    # ── Build open_docs list ─────────────────────────────────────────────────
    open_docs_out: list[BulkMatchOpenDoc] = []
    for d in vendor_docs:
        outstanding = round(d.total - d.paid_amount, 2)
        label = getattr(d, "number", None) or f"{doc_type.capitalize()} #{d.id}"
        if not label:
            label = f"{doc_type.capitalize()} #{d.id}"
        open_docs_out.append(BulkMatchOpenDoc(
            id=d.id,
            label=str(label),
            amount=outstanding,
            date=d.issue_date,
            contact_name=d.contact_name,
        ))

    # Sort by date ascending so the panel shows oldest first
    open_docs_out.sort(key=lambda x: x.date)

    # ── Find exact-sum subsets ───────────────────────────────────────────────
    id_amt_pairs = [(doc.id, doc.amount) for doc in open_docs_out]
    combos = _find_bulk_combinations(id_amt_pairs, target, tolerance=0.01, max_results=3)
    suggested_groups = [
        [iid for iid, _ in combo]
        for combo in combos if len(combo) >= 2
    ]

    return BulkMatchSuggestionsResponse(
        vendor=top_vendor,
        vendor_score=round(top_score, 3),
        doc_type=doc_type,
        open_docs=open_docs_out,
        suggested_groups=suggested_groups,
    )


@router.post("/{line_id}/match-bulk-invoices", response_model=StatementLineResponse)
def match_bulk_invoices(
    line_id: int,
    body: MatchBulkInvoicesRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Match a PENDING statement line (money-in) to multiple invoices whose
    outstanding amounts sum to the bank credit.  Allocates payment
    proportionally and stores the allocation as JSON.
    """
    s = _load_line_for_org(db, line_id, org_id)
    _require_pending(s)

    if not body.invoice_ids:
        raise HTTPException(status_code=422, detail="invoice_ids must not be empty")

    target = s.received
    allocations: list[dict] = []
    total_allocated = 0.0

    for inv_id in body.invoice_ids:
        inv = db.get(Invoice, inv_id)
        if not inv or inv.org_id != org_id:
            raise HTTPException(status_code=404, detail=f"Invoice {inv_id} not found")
        outstanding = round(inv.total - inv.paid_amount, 2)
        if outstanding <= 0:
            raise HTTPException(status_code=409, detail=f"Invoice {inv_id} is already fully paid")
        allocations.append({"id": inv_id, "amount": outstanding})
        total_allocated = round(total_allocated + outstanding, 2)

    if abs(total_allocated - target) > 0.01:
        raise HTTPException(
            status_code=422,
            detail=f"Invoice totals ({total_allocated}) do not match bank credit ({target})",
        )

    now = _now()
    for alloc in allocations:
        inv = db.get(Invoice, alloc["id"])
        inv.paid_amount = round(inv.paid_amount + alloc["amount"], 2)
        if inv.paid_amount >= inv.total - 0.005:
            inv.status = DocumentStatus.PAID
        inv.updated_at = now
        db.add(inv)

    s.matched_invoice_ids = json.dumps(allocations)
    s.status = StatementLineStatus.MATCHED
    s.reconciled_at = now
    _apply_balance(db, s.bank_account_id, target, org_id)

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/match-bulk-bills", response_model=StatementLineResponse)
def match_bulk_bills(
    line_id: int,
    body: MatchBulkBillsRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Match a PENDING statement line (money-out) to multiple bills whose
    outstanding amounts sum to the bank debit.
    """
    s = _load_line_for_org(db, line_id, org_id)
    _require_pending(s)

    if not body.bill_ids:
        raise HTTPException(status_code=422, detail="bill_ids must not be empty")

    target = s.spent
    allocations: list[dict] = []
    total_allocated = 0.0

    for bill_id in body.bill_ids:
        bill = db.get(Bill, bill_id)
        if not bill or bill.org_id != org_id:
            raise HTTPException(status_code=404, detail=f"Bill {bill_id} not found")
        outstanding = round(bill.total - bill.paid_amount, 2)
        if outstanding <= 0:
            raise HTTPException(status_code=409, detail=f"Bill {bill_id} is already fully paid")
        allocations.append({"id": bill_id, "amount": outstanding})
        total_allocated = round(total_allocated + outstanding, 2)

    if abs(total_allocated - target) > 0.01:
        raise HTTPException(
            status_code=422,
            detail=f"Bill totals ({total_allocated}) do not match bank debit ({target})",
        )

    now = _now()
    for alloc in allocations:
        bill = db.get(Bill, alloc["id"])
        bill.paid_amount = round(bill.paid_amount + alloc["amount"], 2)
        if bill.paid_amount >= bill.total - 0.005:
            bill.status = DocumentStatus.PAID
        bill.updated_at = now
        db.add(bill)

    s.matched_bill_ids = json.dumps(allocations)
    s.status = StatementLineStatus.MATCHED
    s.reconciled_at = now
    _apply_balance(db, s.bank_account_id, -target, org_id)

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


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
    bulk_inv_raw = getattr(s, "matched_invoice_ids", None)
    bulk_bill_raw = getattr(s, "matched_bill_ids", None)

    if bulk_inv_raw:
        # Bulk invoice match — reverse each allocation stored in JSON
        try:
            allocations = json.loads(bulk_inv_raw)
        except (json.JSONDecodeError, TypeError):
            allocations = []
        for alloc in allocations:
            inv = db.get(Invoice, alloc["id"])
            if inv and inv.org_id == org_id:
                inv.paid_amount = round(inv.paid_amount - alloc["amount"], 2)
                if inv.paid_amount < inv.total - 0.005 and inv.status == DocumentStatus.PAID:
                    inv.status = DocumentStatus.AWAITING_PAYMENT
                inv.updated_at = _now()
                db.add(inv)
        _apply_balance(db, s.bank_account_id, -amount, org_id)

    elif bulk_bill_raw:
        # Bulk bill match — reverse each allocation
        try:
            allocations = json.loads(bulk_bill_raw)
        except (json.JSONDecodeError, TypeError):
            allocations = []
        for alloc in allocations:
            bill = db.get(Bill, alloc["id"])
            if bill and bill.org_id == org_id:
                bill.paid_amount = round(bill.paid_amount - alloc["amount"], 2)
                if bill.paid_amount < bill.total - 0.005 and bill.status == DocumentStatus.PAID:
                    bill.status = DocumentStatus.AWAITING_PAYMENT
                bill.updated_at = _now()
                db.add(bill)
        _apply_balance(db, s.bank_account_id, -amount, org_id)

    elif s.matched_invoice_id:
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
    if hasattr(s, "matched_invoice_ids"):
        s.matched_invoice_ids = None
    if hasattr(s, "matched_bill_ids"):
        s.matched_bill_ids = None
    s.status = StatementLineStatus.PENDING
    s.reconciled_at = None

    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)
