from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from memory.models import Contact, MatchRecord
from api.schemas.models import DashboardStats
from api.deps import get_db, get_current_org_id

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_MATCHED = {"exact", "fuzzy", "one_to_many", "many_to_one", "human_corrected"}


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    records = db.exec(select(MatchRecord).where(MatchRecord.org_id == org_id)).all()
    contacts_count = len(db.exec(select(Contact).where(Contact.org_id == org_id)).all())

    run_ids: set[str] = set()
    total = matched = pending = 0
    last_date: str = ""

    for r in records:
        run_ids.add(r.run_id)
        total += 1
        status = r.status.value if hasattr(r.status, "value") else str(r.status)
        if status in _MATCHED:
            matched += 1
        if r.requires_human_review and r.human_approved is None:
            pending += 1
        if r.created_at and r.created_at > last_date:
            last_date = r.created_at

    rate = round(matched / total * 100, 1) if total else 0.0

    return DashboardStats(
        total_runs=len(run_ids),
        total_transactions=total,
        overall_match_rate=rate,
        pending_review=pending,
        total_contacts=contacts_count,
        last_run_date=last_date or None,
    )
