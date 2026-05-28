import csv
import io
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from memory.models import MatchRecord
from api.schemas.models import MatchResponse
from api.deps import get_db, get_current_org_id

router = APIRouter(prefix="/audit", tags=["audit"])

_FIELDS = [
    "id", "run_id", "bank_txn_id", "ledger_txn_id", "status",
    "score", "amount_diff", "date_diff_days",
    "requires_human_review", "human_approved", "created_at",
]


def _to_resp(r: MatchRecord) -> MatchResponse:
    return MatchResponse(
        id=r.id,
        run_id=r.run_id,
        bank_txn_id=r.bank_txn_id,
        ledger_txn_id=r.ledger_txn_id,
        status=r.status.value if hasattr(r.status, "value") else str(r.status),
        score=r.score,
        reasoning_path=r.reasoning_path,
        amount_diff=r.amount_diff,
        date_diff_days=r.date_diff_days,
        requires_human_review=r.requires_human_review,
        human_approved=r.human_approved,
        created_at=r.created_at,
    )


@router.get("/", response_model=list[MatchResponse])
def get_audit(
    run_id: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(MatchRecord).where(MatchRecord.org_id == org_id)
    if run_id:
        q = q.where(MatchRecord.run_id == run_id)
    q = q.offset(skip).limit(limit)
    return [_to_resp(r) for r in db.exec(q).all()]


@router.get("/export")
def export_audit(
    run_id: str | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(MatchRecord).where(MatchRecord.org_id == org_id)
    if run_id:
        q = q.where(MatchRecord.run_id == run_id)
    records = db.exec(q).all()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_FIELDS)
    writer.writeheader()
    for r in records:
        writer.writerow({
            "id": r.id, "run_id": r.run_id, "bank_txn_id": r.bank_txn_id,
            "ledger_txn_id": r.ledger_txn_id,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "score": r.score, "amount_diff": r.amount_diff,
            "date_diff_days": r.date_diff_days,
            "requires_human_review": r.requires_human_review,
            "human_approved": r.human_approved, "created_at": r.created_at,
        })
    buf.seek(0)
    filename = f"audit_{run_id or 'all'}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
