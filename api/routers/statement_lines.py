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
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from memory.models import (
    BankAccount, StatementLine, StatementLineStatus,
    Invoice, Bill, JournalEntry, DocumentStatus, VendorAlias, Organization,
    AuditLog, AuditAction, User,
)

# Countries that write dates month-first (MM/DD/YYYY). Used only to break
# ambiguous dates the statement data itself can't resolve.
_MONTH_FIRST_COUNTRIES = {"US"}
from api.schemas.models import (
    StatementLineResponse, StatementImportRequest,
    MatchInvoiceRequest, MatchBillRequest, CreateEntryRequest,
    TransferRequest, DiscussRequest,
    MatchBulkInvoicesRequest, MatchBulkBillsRequest,
    BulkMatchSuggestionsResponse, BulkMatchOpenDoc,
)
from api.deps import get_db, get_current_org_id, require_user
from engine.bank_statement_parser import parse_bank_statement
from engine.vendor_matching.matcher import find_matches as match_vendors
from engine.vendor_matching.normalizer import canonicalize
from engine.vendor_matching.explain import explain_candidate
from engine.reconcile_rules import (
    score_date, cap_by_name, auto_match_ready, is_ambiguous, BAND_LIKELY, AMBIGUITY_EPS,
)
from engine.llm.factory import get_llm
from engine.llm.base import LLMError

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


def _log_audit(
    db: Session,
    *,
    org_id: int,
    actor: User,
    action: AuditAction,
    line: StatementLine,
    target_type: str | None = None,
    target_id: int | None = None,
    target_label: str = "",
    method: str | None = None,
    score: float | None = None,
    detail: str = "",
) -> None:
    """
    Append one immutable audit row for a reconcile action. Snapshots the line +
    target so the record stays readable even if the line is later removed. Added
    to the SAME transaction as the action, so action and audit commit atomically.
    """
    acc = db.get(BankAccount, line.bank_account_id)
    db.add(AuditLog(
        org_id=org_id,
        created_at=_now(),
        actor_id=getattr(actor, "id", None),
        actor_name=(getattr(actor, "name", "") or getattr(actor, "email", "") or "—"),
        action=action.value,
        statement_line_id=line.id,
        bank_account_id=line.bank_account_id,
        line_date=line.date,
        line_description=line.description or "",
        amount=_net_amount(line),
        currency=(acc.currency if acc else "GBP"),
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        method=method,
        score=score,
        detail=detail,
    ))


def _maybe_learn_alias(
    db: Session,
    org_id: int,
    line: StatementLine,
    canonical_name: str | None,
    contact_id: int | None = None,
) -> bool:
    """
    Self-learning: when the user approves a match, optionally remember this bank
    description → vendor so the engine matches it automatically next time.

    Stores the CLEANED (canonicalized) form of the description as the alias key,
    so it survives varying transaction-id/reference noise on future statements.
    No-op when the description or vendor is blank, or when an equivalent alias
    already exists (we never duplicate). Added to the caller's transaction so it
    commits atomically with the reconcile action. Returns True if one was created.
    """
    desc = (line.description or "").strip()
    vendor = (canonical_name or "").strip()
    if not desc or not vendor:
        return False
    key = (canonicalize(desc).canonical or desc).strip().lower()
    if not key:
        return False
    existing = db.exec(
        select(VendorAlias).where(VendorAlias.org_id == org_id, VendorAlias.alias == key)
    ).first()
    if existing is not None:
        return False  # already learned — don't pile on duplicates
    db.add(VendorAlias(
        org_id=org_id,
        alias=key,
        canonical_name=vendor,
        contact_id=contact_id,
        confidence=1.0,
        source="human",
        created_at=_now(),
    ))
    return True


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


# ── Pipeline run (batch explainability) ──────────────────────────────────────
# NOTE: these static-path routes MUST be declared BEFORE "/{line_id}" below.
# FastAPI matches routes in declaration order, so if "/{line_id}" came first a
# GET to /statement-lines/pipeline(-lines) would be captured by it and 422 while
# trying to parse "pipeline" as an integer.

def _build_pipeline_entry(s: StatementLine, db: Session, org_id: int) -> dict:
    """Score one statement line and assemble its top candidate + full trace."""
    is_inflow = s.received > 0
    amount = s.received if is_inflow else s.spent

    suggestions = get_suggestions(s.id, db, org_id)
    top = suggestions[0] if suggestions else None
    trace = None
    if top is not None:
        trace = explain_suggestion(s.id, top["type"], top["id"], db, org_id)

    return {
        "line": {
            "id": s.id,
            "date": str(s.date)[:10],
            "description": s.description,
            "reference": s.reference,
            "spent": s.spent,
            "received": s.received,
            "amount": amount,
            "direction": "in" if is_inflow else "out",
            "status": s.status.value if hasattr(s.status, "value") else str(s.status),
        },
        "candidate_count": len(suggestions),
        "top_candidate": top,
        "trace": trace,
    }


@router.get("/pipeline")
def pipeline_run(
    bank_account_id: int | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> dict:
    """
    Run the full matching cascade over EVERY statement line at once and return
    each line's top candidate plus the complete step-by-step trace.

    This is the "Pipeline Run" demo surface: upload a whole statement + invoices,
    then watch the engine score each entry and see every intermediate it computed.
    The numbers are identical to the live Reconcile screen because this reuses the
    same `get_suggestions()` + `explain_candidate()` the rest of the app uses.
    """
    q = select(StatementLine).where(StatementLine.org_id == org_id)
    if bank_account_id is not None:
        q = q.where(StatementLine.bank_account_id == bank_account_id)
    q = q.order_by(StatementLine.date.asc())
    lines = db.exec(q).all()

    entries = [_build_pipeline_entry(s, db, org_id) for s in lines]

    bands = {"strong": 0, "likely": 0, "possible": 0, "weak": 0, "none": 0}
    methods: dict[str, int] = {}
    for e in entries:
        if e["trace"] is not None:
            band = e["trace"]["final"]["strength"]
            method = e["trace"]["final"]["method"]
            bands[band] = bands.get(band, 0) + 1
            methods[method] = methods.get(method, 0) + 1
        else:
            bands["none"] += 1

    total = len(entries)
    auto = bands["strong"]
    return {
        "summary": {
            "bank_account_id": bank_account_id,
            "total": total,
            "auto_matched": auto,
            "needs_review": bands["likely"] + bands["possible"] + bands["weak"],
            "unmatched": bands["none"],
            "match_rate": round(auto / total * 100, 1) if total else 0.0,
            "bands": bands,
            "methods": methods,
        },
        "entries": entries,
    }


@router.get("/pipeline-lines")
def pipeline_lines(
    bank_account_id: int | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> list[dict]:
    """
    Just the line ids/descriptions to process — the frontend fetches this first,
    then streams one `/{line_id}/pipeline-entry` call per line so the UI can show
    the engine working through the statement live, line by line.
    """
    q = select(StatementLine).where(StatementLine.org_id == org_id)
    if bank_account_id is not None:
        q = q.where(StatementLine.bank_account_id == bank_account_id)
    q = q.order_by(StatementLine.date.asc())
    return [
        {
            "id": s.id,
            "date": str(s.date)[:10],
            "description": s.description,
            "amount": s.received if s.received > 0 else s.spent,
            "direction": "in" if s.received > 0 else "out",
        }
        for s in db.exec(q).all()
    ]


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
    total_movement = 0.0
    for ln in body.lines:
        total_movement += (ln.received or 0.0) - (ln.spent or 0.0)
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

    # Reconciliation target = net of the imported credits/debits (see upload).
    acc.statement_balance = round(acc.statement_balance + total_movement, 2)
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
        # (id, label, contact, date, outstanding, currency, due_date)
        cands = [
            (d.id, d.number, d.contact_name, d.issue_date,
             round(d.total - d.paid_amount, 2), d.currency, d.due_date)
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
             round(d.total - d.paid_amount, 2), d.currency, d.due_date)
            for d in docs if (d.total - d.paid_amount) > 0
        ]
        cand_type = "bill"

    if not cands:
        return []

    # Currency the line is denominated in (StatementLine inherits its bank account's).
    acc = db.get(BankAccount, s.bank_account_id)
    line_currency = acc.currency if acc else "GBP"

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

    # ── Score every candidate ───────────────────────────────────────────────
    out: list[dict] = []
    for idx, (cid, label, contact, doc_date, outstanding, currency, due_date) in enumerate(cands):
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

        # Date component (0–0.2) — asymmetric: don't punish a normal payment delay
        # after the invoice; treat a payment dated BEFORE it as a red flag.
        date_score, date_reason = score_date(s.date, doc_date, due_date)
        reasons.append(date_reason)

        # Name component (0–0.3) via the proper matcher
        name_score_raw, method = name_score_by_idx.get(idx, (0.0, "no-name"))
        name_score = name_score_raw * 0.3
        if name_score_raw >= 0.95:
            reasons.append(f"name {method}")
        elif name_score_raw >= 0.70:
            reasons.append(f"name fuzzy ({int(name_score_raw * 100)}%)")
        # else: silent, don't clutter

        # Name similarity caps the confidence LABEL: amount + date alone can't make
        # a wrong-vendor coincidence look "Likely"/"Strong" (see reconcile_rules).
        composite = cap_by_name(min(amount_score + date_score + name_score, 1.0), name_score_raw)

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
            # Per-candidate readiness for hands-off auto-reconcile (uniqueness
            # enforced below). Stored under a private key, finalised after sort.
            "_ready": auto_match_ready(
                amount_exact=diff < 0.01,
                name_method=method,
                date_component=date_score,
                same_currency=(currency == line_currency),
            ),
        })

    out.sort(key=lambda x: x["score"], reverse=True)

    # ── Ambiguity: flag a near-tie among the best candidates ─────────────────
    # Two same-amount, same-vendor docs score alike — warn, and bar both from
    # hands-off auto-reconcile so we never silently pick the wrong one.
    ambiguous = len(out) >= 2 and is_ambiguous(out[0]["score"], out[1]["score"])
    tied = (
        {id(c) for c in out if c["score"] >= BAND_LIKELY
         and abs(c["score"] - out[0]["score"]) <= AMBIGUITY_EPS}
        if ambiguous else set()
    )

    # ── Auto-eligibility: certain AND the only such candidate AND line pending ─
    ready_count = sum(1 for c in out if c["_ready"])
    line_pending = s.status == StatementLineStatus.PENDING
    for c in out:
        ready = c.pop("_ready")
        c["ambiguous"] = id(c) in tied
        c["auto_eligible"] = bool(
            ready and ready_count == 1 and line_pending and not c["ambiguous"]
        )

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

    acc = db.get(BankAccount, s.bank_account_id)
    line_currency = acc.currency if acc else "GBP"

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
        cand_due_date=doc.due_date,
        same_currency=(doc.currency == line_currency),
        alias_map=alias_map,
    )
    trace["candidate"] = {"type": doc_type, "id": doc_id}
    return trace


@router.get("/{line_id}/pipeline-entry")
def pipeline_entry(
    line_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> dict:
    """One line's top candidate + full trace — the unit the live Pipeline Run streams."""
    s = _load_line_for_org(db, line_id, org_id)
    return _build_pipeline_entry(s, db, org_id)


def _narrative_prompt(trace: dict) -> str:
    """Turn a scoring trace into a compact, plain-English explanation prompt."""
    inp = trace.get("input", {})
    steps = {s.get("n"): s for s in trace.get("steps", [])}
    final = trace.get("final", {})
    s1, s2, s3, s4, s5, s6 = (steps.get(n, {}) for n in (1, 2, 3, 4, 5, 6))

    lines = [
        f"Bank line: \"{inp.get('bank_description')}\" for {inp.get('bank_amount')} on {inp.get('bank_date')}.",
        f"Candidate: {inp.get('candidate_vendor')} ({inp.get('candidate_label')}) "
        f"for {inp.get('candidate_amount')} on {inp.get('candidate_date')}.",
        f"Step 1 normalise: '{s1.get('bank_canonical')}' vs '{s1.get('candidate_canonical')}'.",
        f"Step 2 learned-alias lookup: {'HIT → ' + str(s2.get('resolved_to')) if s2.get('hit') else 'no match'}.",
        f"Step 3 spelling similarity composite: {s3.get('composite')}.",
        (
            f"Step 4 AI meaning/embedding: cosine {s4.get('cosine')} (floor {s4.get('floor')})."
            if s4.get("fired") else "Step 4 AI meaning check: skipped (spelling already strong)."
        ),
        f"Step 5 best-signal name score: {s5.get('name_score')} via method '{s5.get('method')}'.",
        f"Step 6 composite = amount {s6.get('amount_component')} ({s6.get('amount_reason')}) "
        f"+ date {s6.get('date_component')} ({s6.get('date_reason')}) "
        f"+ name {s6.get('name_component')} = {s6.get('total')}.",
        f"Verdict: {final.get('score_pct')}% — {final.get('strength_label')}.",
    ]
    context = "\n".join(lines)
    return (
        "You explain an automated bank-reconciliation engine to a non-technical finance manager.\n"
        "Below is the real trace of how ONE bank line was scored against ONE invoice/bill, "
        "as it cascaded through six stages.\n\n"
        f"{context}\n\n"
        "Write 2–3 short, plain-English sentences narrating how the decision cascaded "
        "(normalise the names → check learned aliases → spelling similarity → AI meaning check → "
        "combine amount, date and name into one score → verdict) and why it landed where it did. "
        "Reference the key numbers naturally. No jargon, no bullet points, no preamble."
    )


@router.post("/narrate")
def narrate_trace(
    trace: dict = Body(...),
    org_id: int = Depends(get_current_org_id),
) -> dict:
    """
    Turn a scoring trace into a plain-English explanation via the LLM.

    The matching itself stays fully deterministic; the model is used only to
    narrate the numbers for a human — exactly the "use a model where the data
    can't speak for itself" line the rest of the codebase follows.
    """
    try:
        res = get_llm().complete_text(_narrative_prompt(trace), max_tokens=260)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {e}")
    return {"narrative": res.text.strip(), "provider": res.provider, "model": res.model}


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

    # Use the org's country only to break ambiguous DD/MM-vs-MM/DD dates that
    # the statement data gives no other clue about.
    org = db.get(Organization, org_id)
    default_dayfirst = (org.country or "GB").upper() not in _MONTH_FIRST_COUNTRIES if org else True

    try:
        df = await asyncio.to_thread(parse_bank_statement, contents, mime, default_dayfirst)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=422, detail=f"Could not parse statement: {e}",
        )

    now = _now()
    created: list[StatementLine] = []
    last_balance_after: float | None = None
    total_movement = 0.0   # sum of signed amounts across the imported lines

    for _, row in df.iterrows():
        amount = float(row.get("amount", 0.0))
        total_movement += amount
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

    # Reconciliation target is the NET of the imported credits/debits — NOT the
    # bank's running/closing balance. Accumulate so it covers every imported
    # line. The OOO balance (moved by the reconcile actions as each line is
    # matched) climbs to meet it, so the difference is exactly the amount still
    # unreconciled → 0 once the statement is fully reconciled. The per-line
    # running balance is still stored for display, just not used here.
    acc.statement_balance = round(acc.statement_balance + total_movement, 2)
    acc.last_imported_at = now
    db.add(acc)

    db.commit()
    for s in created:
        db.refresh(s)
    return [_to_resp(s) for s in created]


# ── Bulk-match helpers ───────────────────────────────────────────────────────

def _vendor_key(doc) -> str:
    """Stable identity for 'same vendor' checks — contact_id when present, else
    the normalised contact name. Used to enforce single-vendor split payments."""
    cid = getattr(doc, "contact_id", None)
    if cid:
        return f"id:{cid}"
    return f"name:{(getattr(doc, 'contact_name', '') or '').strip().lower()}"


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

    # ── Filter to the ONE statement-matched vendor ───────────────────────────
    # A split payment is, by definition, one vendor settling several of their own
    # documents in a single transfer. We never mix vendors just because amounts
    # happen to sum, so if we can't tie the statement to a vendor we offer no
    # bulk suggestions at all (the single-match flow still applies).
    if not top_vendor:
        return empty
    vendor_docs = [d for d in open_docs if d.contact_name == top_vendor]
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
    user: User = Depends(require_user),
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
    vendors: set[str] = set()

    for inv_id in body.invoice_ids:
        inv = db.get(Invoice, inv_id)
        if not inv or inv.org_id != org_id:
            raise HTTPException(status_code=404, detail=f"Invoice {inv_id} not found")
        outstanding = round(inv.total - inv.paid_amount, 2)
        if outstanding <= 0:
            raise HTTPException(status_code=409, detail=f"Invoice {inv_id} is already fully paid")
        vendors.add(_vendor_key(inv))
        allocations.append({"id": inv_id, "amount": outstanding})
        total_allocated = round(total_allocated + outstanding, 2)

    # A split payment must settle ONE vendor's invoices — never a mix whose
    # amounts merely add up to the bank credit.
    if len(vendors) > 1:
        raise HTTPException(
            status_code=422,
            detail="All invoices in a split must be from the same vendor.",
        )

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

    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.MATCH_BULK_INVOICES, line=s,
        target_type="bulk", target_label=f"{len(allocations)} invoices",
        detail=f"Split across invoice IDs {', '.join(str(a['id']) for a in allocations)}",
    )

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
    user: User = Depends(require_user),
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
    vendors: set[str] = set()

    for bill_id in body.bill_ids:
        bill = db.get(Bill, bill_id)
        if not bill or bill.org_id != org_id:
            raise HTTPException(status_code=404, detail=f"Bill {bill_id} not found")
        outstanding = round(bill.total - bill.paid_amount, 2)
        if outstanding <= 0:
            raise HTTPException(status_code=409, detail=f"Bill {bill_id} is already fully paid")
        vendors.add(_vendor_key(bill))
        allocations.append({"id": bill_id, "amount": outstanding})
        total_allocated = round(total_allocated + outstanding, 2)

    # A split payment must settle ONE vendor's bills — never a mix whose amounts
    # merely add up to the bank debit.
    if len(vendors) > 1:
        raise HTTPException(
            status_code=422,
            detail="All bills in a split must be from the same vendor.",
        )

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

    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.MATCH_BULK_BILLS, line=s,
        target_type="bulk", target_label=f"{len(allocations)} bills",
        detail=f"Split across bill IDs {', '.join(str(a['id']) for a in allocations)}",
    )

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
    user: User = Depends(require_user),
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

    if body.learn_alias:
        _maybe_learn_alias(db, org_id, s, inv.contact_name, inv.contact_id)

    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.MATCH_INVOICE, line=s,
        target_type="invoice", target_id=inv.id,
        target_label=f"{inv.number} · {inv.contact_name}",
        score=s.suggested_score,
        detail=f"Matched to invoice {inv.number} ({inv.contact_name})",
    )

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
    user: User = Depends(require_user),
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

    if body.learn_alias:
        _maybe_learn_alias(db, org_id, s, bill.contact_name, bill.contact_id)

    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.MATCH_BILL, line=s,
        target_type="bill", target_id=bill.id,
        target_label=f"{bill.number or f'Bill #{bill.id}'} · {bill.contact_name}",
        score=s.suggested_score,
        detail=f"Matched to bill {bill.number or bill.id} ({bill.contact_name})",
    )

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
    user: User = Depends(require_user),
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

    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.CREATE_ENTRY, line=s,
        target_type="journal", target_id=j.id,
        target_label=(body.contact_name or body.description or "Journal entry"),
        detail=f"Created journal entry: {body.description or '—'}",
    )

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
    user: User = Depends(require_user),
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

    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.TRANSFER, line=s,
        target_type="account", target_id=to_acc.id,
        target_label=f"Transfer → {to_acc.name}",
        detail=f"Marked as a transfer to {to_acc.name}",
    )

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
    user: User = Depends(require_user),
):
    s = _load_line_for_org(db, line_id, org_id)
    s.discussion = body.note
    # Discussing doesn't reconcile — keep PENDING unless already resolved
    if s.status == StatementLineStatus.PENDING:
        s.status = StatementLineStatus.DISCUSSED
    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.DISCUSS, line=s,
        target_type="none", target_label="Note added",
        detail=body.note or "",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _to_resp(s)


@router.post("/{line_id}/unreconcile", response_model=StatementLineResponse)
def unreconcile(
    line_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(require_user),
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

    _log_audit(
        db, org_id=org_id, actor=user, action=AuditAction.UNRECONCILE, line=s,
        target_type="none", target_label="Unreconciled",
        detail="Undid " + (
            f"invoice match (#{s.matched_invoice_id})" if s.matched_invoice_id
            else f"bill match (#{s.matched_bill_id})" if s.matched_bill_id
            else f"journal entry (#{s.matched_journal_id})" if s.matched_journal_id
            else f"transfer to account #{s.transfer_to_account_id}" if s.transfer_to_account_id
            else "a bulk match" if (getattr(s, "matched_invoice_ids", None) or getattr(s, "matched_bill_ids", None))
            else "a reconciliation"
        ),
    )

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
