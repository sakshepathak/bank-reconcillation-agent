"""
Exceptions router — endpoints for the Exceptions page (formerly Review Queue).

Surfaces the *cross-cutting* reconciliation jobs that the line-by-line
Reconcile screen handles poorly:

  • Bulk auto-approve   — top match per pending line across all accounts
  • Duplicate detection — invoice/bill pairs that look like the same doc
  • Splits / unusual    — deferred

Heavy lifting comes from existing modules — the vendor matcher for name
similarity, `score_one`-style amount + date scoring inlined to keep the
endpoint self-contained.
"""
from __future__ import annotations

from datetime import datetime
from itertools import combinations

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from memory.models import (
    BankAccount, Bill, DocumentStatus, Invoice,
    StatementLine, StatementLineStatus, VendorAlias,
)
from api.deps import get_db, get_current_org_id
from engine.vendor_matching.matcher import find_matches as match_vendors

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


# ─── Bulk approve queue ──────────────────────────────────────────────────────

def _date_diff(a: str, b: str) -> int | None:
    try:
        return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).days
    except (ValueError, TypeError):
        return None


def _score_pair(
    desc: str, line_date: str, line_amount: float,
    doc_date: str, doc_amount: float, doc_contact: str,
    name_score_raw: float, method: str,
) -> tuple[float, str]:
    """Identical composite as /statement-lines/{id}/suggestions — see there."""
    reasons: list[str] = []
    diff = abs(line_amount - doc_amount)
    if diff < 0.01:
        amount_score = 0.5; reasons.append("exact amount")
    elif diff / max(line_amount, 0.01) < 0.01:
        amount_score = 0.4; reasons.append(f"≈ amount (Δ{diff:.2f})")
    elif diff / max(line_amount, 0.01) < 0.05:
        amount_score = 0.25; reasons.append(f"amount off by {diff:.2f}")
    else:
        amount_score = 0.0; reasons.append(f"amount differs by {diff:.2f}")

    d = _date_diff(line_date, doc_date)
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

    name_score = name_score_raw * 0.3
    if name_score_raw >= 0.95:
        reasons.append(f"name {method}")
    elif name_score_raw >= 0.70:
        reasons.append(f"name fuzzy ({int(name_score_raw * 100)}%)")

    return min(amount_score + date_score + name_score, 1.0), ", ".join(reasons)


@router.get("/bulk-approve-queue")
def bulk_approve_queue(
    min_score: float = 0.65,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> list[dict]:
    """
    Return all pending statement lines across all accounts paired with
    their top match candidate (an invoice for inflows, a bill for
    outflows). Only lines with a top score >= min_score are returned.
    """
    pending = db.exec(
        select(StatementLine).where(
            StatementLine.org_id == org_id,
            StatementLine.status == StatementLineStatus.PENDING,
        )
    ).all()
    if not pending:
        return []

    # Preload candidates once
    invoices = db.exec(
        select(Invoice).where(
            Invoice.org_id == org_id,
            Invoice.status != DocumentStatus.PAID,
            Invoice.status != DocumentStatus.VOIDED,
        )
    ).all()
    invoices = [i for i in invoices if (i.total - i.paid_amount) > 0]

    bills = db.exec(
        select(Bill).where(
            Bill.org_id == org_id,
            Bill.status != DocumentStatus.PAID,
            Bill.status != DocumentStatus.VOIDED,
        )
    ).all()
    bills = [b for b in bills if (b.total - b.paid_amount) > 0]

    accounts = {a.id: a for a in db.exec(select(BankAccount).where(BankAccount.org_id == org_id)).all()}

    alias_rows = db.exec(select(VendorAlias).where(VendorAlias.org_id == org_id)).all()
    alias_map = {a.alias.lower(): a.canonical_name for a in alias_rows}

    out: list[dict] = []
    for line in pending:
        is_inflow = line.received > 0
        amount = line.received if is_inflow else line.spent
        candidates = invoices if is_inflow else bills
        if not candidates:
            continue

        names = [
            (c.contact_name)
            for c in candidates
        ]
        name_matches = match_vendors(
            line.description or "",
            names,
            alias_map=alias_map,
            threshold=0.0,
            use_embeddings=True,
            top_k=len(names),
        )
        name_score_by_idx = {nm.invoice_idx: (nm.score, nm.method) for nm in name_matches}

        best = None
        best_score = -1.0
        best_reason = ""
        for idx, c in enumerate(candidates):
            outstanding = round(c.total - c.paid_amount, 2)
            ns, method = name_score_by_idx.get(idx, (0.0, "no-name"))
            sc, reason = _score_pair(
                line.description or "", line.date, amount,
                c.issue_date, outstanding, c.contact_name, ns, method,
            )
            if sc > best_score:
                best_score = sc
                best_reason = reason
                best = (c, method, outstanding)

        if best is None or best_score < min_score:
            continue

        candidate, method, outstanding = best
        kind = "invoice" if is_inflow else "bill"
        acc = accounts.get(line.bank_account_id)
        out.append({
            "line": {
                "id": line.id,
                "bank_account_id": line.bank_account_id,
                "bank_account_name": acc.name if acc else f"#{line.bank_account_id}",
                "date": line.date,
                "description": line.description,
                "spent": line.spent,
                "received": line.received,
                "currency": acc.currency if acc else "GBP",
            },
            "candidate": {
                "type": kind,
                "id": candidate.id,
                "label": getattr(candidate, "number", None) or f"{kind}#{candidate.id}",
                "contact_name": candidate.contact_name,
                "date": candidate.issue_date,
                "amount": outstanding,
            },
            "score": round(best_score, 3),
            "method": method,
            "reason": best_reason,
        })

    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# ─── Duplicate detection ─────────────────────────────────────────────────────

def _find_dupes_in(
    docs: list,
    kind: str,
    alias_map: dict[str, str],
    name_sim_threshold: float = 0.80,
    days_window: int = 30,
) -> list[dict]:
    """
    Compare every pair in `docs` and return suspected duplicates.

    Match criteria:
      • same amount (within 0.01 absolute)
      • dates within `days_window`
      • vendor names match via the cascade matcher (>= name_sim_threshold)
    """
    out: list[dict] = []
    for a, b in combinations(docs, 2):
        if abs(a.total - b.total) > 0.01:
            continue
        d = _date_diff(a.issue_date, b.issue_date)
        if d is None or abs(d) > days_window:
            continue

        # Name similarity via the cascade matcher
        sims = match_vendors(
            a.contact_name or "",
            [b.contact_name or ""],
            alias_map=alias_map,
            threshold=0.0,
            use_embeddings=True,
            top_k=1,
        )
        if not sims or sims[0].score < name_sim_threshold:
            continue

        out.append({
            "kind": kind,
            "left": {
                "id": a.id,
                "label": getattr(a, "number", None) or f"{kind}#{a.id}",
                "contact_name": a.contact_name,
                "date": a.issue_date,
                "amount": a.total,
                "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            },
            "right": {
                "id": b.id,
                "label": getattr(b, "number", None) or f"{kind}#{b.id}",
                "contact_name": b.contact_name,
                "date": b.issue_date,
                "amount": b.total,
                "status": b.status.value if hasattr(b.status, "value") else str(b.status),
            },
            "name_similarity": round(sims[0].score, 3),
            "days_apart": abs(d),
        })
    return out


@router.get("/duplicates")
def duplicates(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
) -> list[dict]:
    """
    Return suspected duplicate pairs across invoices and bills. A pair is
    flagged when amount matches exactly, dates are within 30 days, and
    vendor names are ≥80% similar (via the cascade matcher).
    """
    alias_rows = db.exec(select(VendorAlias).where(VendorAlias.org_id == org_id)).all()
    alias_map = {a.alias.lower(): a.canonical_name for a in alias_rows}

    invoices = db.exec(
        select(Invoice).where(Invoice.org_id == org_id, Invoice.status != DocumentStatus.VOIDED)
    ).all()
    bills = db.exec(
        select(Bill).where(Bill.org_id == org_id, Bill.status != DocumentStatus.VOIDED)
    ).all()

    inv_dupes = _find_dupes_in(invoices, "invoice", alias_map)
    bill_dupes = _find_dupes_in(bills, "bill", alias_map)

    return inv_dupes + bill_dupes
