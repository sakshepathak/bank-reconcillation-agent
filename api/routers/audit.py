"""
Audit Trail API — the immutable, org-scoped log of every reconciliation decision
made in the live app (the Reconcile screen). Backed by the AuditLog table, which
is written by the reconcile actions in statement_lines.py.

Endpoints:
  GET /audit/         filtered + paginated event list
  GET /audit/summary  totals by action + accounts + date range (drives the UI)
  GET /audit/export   CSV of the (filtered) events
"""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import Session, select

from memory.models import AuditLog, BankAccount
from api.deps import get_db, get_current_org_id

router = APIRouter(prefix="/audit", tags=["audit"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    id: int
    created_at: str
    actor_name: str
    action: str
    statement_line_id: Optional[int]
    bank_account_id: Optional[int]
    line_date: Optional[str]
    line_description: str
    amount: float
    currency: str
    target_type: Optional[str]
    target_id: Optional[int]
    target_label: str
    method: Optional[str]
    score: Optional[float]
    detail: str


class AuditAccount(BaseModel):
    id: int
    name: str


class AuditSummary(BaseModel):
    total: int
    by_action: dict[str, int]
    accounts: list[AuditAccount]
    first_at: Optional[str]
    last_at: Optional[str]


_EXPORT_FIELDS = [
    "created_at", "actor_name", "action", "line_date", "line_description",
    "amount", "currency", "target_type", "target_label", "method", "score", "detail",
]


def _to_event(r: AuditLog) -> AuditEvent:
    return AuditEvent(
        id=r.id, created_at=r.created_at, actor_name=r.actor_name, action=r.action,
        statement_line_id=r.statement_line_id, bank_account_id=r.bank_account_id,
        line_date=r.line_date, line_description=r.line_description, amount=r.amount,
        currency=r.currency, target_type=r.target_type, target_id=r.target_id,
        target_label=r.target_label, method=r.method, score=r.score, detail=r.detail,
    )


def _filtered_query(
    org_id: int,
    action: Optional[str],
    bank_account_id: Optional[int],
    q: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
):
    """Build the org-scoped, filtered AuditLog query shared by list + export."""
    stmt = select(AuditLog).where(AuditLog.org_id == org_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if bank_account_id is not None:
        stmt = stmt.where(AuditLog.bank_account_id == bank_account_id)
    if date_from:
        stmt = stmt.where(func.substr(AuditLog.created_at, 1, 10) >= date_from)
    if date_to:
        stmt = stmt.where(func.substr(AuditLog.created_at, 1, 10) <= date_to)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            AuditLog.line_description.ilike(like),
            AuditLog.target_label.ilike(like),
            AuditLog.actor_name.ilike(like),
            AuditLog.detail.ilike(like),
        ))
    return stmt


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[AuditEvent])
def list_audit(
    action: Optional[str] = None,
    bank_account_id: Optional[int] = None,
    q: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    stmt = (
        _filtered_query(org_id, action, bank_account_id, q, date_from, date_to)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return [_to_event(r) for r in db.exec(stmt).all()]


@router.get("/summary", response_model=AuditSummary)
def audit_summary(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    rows = db.exec(
        select(AuditLog.action, AuditLog.created_at).where(AuditLog.org_id == org_id)
    ).all()

    by_action: dict[str, int] = {}
    first_at: Optional[str] = None
    last_at: Optional[str] = None
    for action, created in rows:
        by_action[action] = by_action.get(action, 0) + 1
        if created:
            if first_at is None or created < first_at:
                first_at = created
            if last_at is None or created > last_at:
                last_at = created

    accts = db.exec(
        select(BankAccount).where(BankAccount.org_id == org_id)
    ).all()

    return AuditSummary(
        total=len(rows),
        by_action=by_action,
        accounts=[AuditAccount(id=a.id, name=a.name) for a in accts],
        first_at=first_at,
        last_at=last_at,
    )


@router.get("/export")
def export_audit(
    action: Optional[str] = None,
    bank_account_id: Optional[int] = None,
    q: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    stmt = _filtered_query(org_id, action, bank_account_id, q, date_from, date_to).order_by(
        AuditLog.created_at.desc(), AuditLog.id.desc()
    )
    rows = db.exec(stmt).all()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_EXPORT_FIELDS)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: getattr(r, k) for k in _EXPORT_FIELDS})
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_trail.csv"},
    )
