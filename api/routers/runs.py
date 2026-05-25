from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from memory.models import MatchRecord
from api.schemas.models import MatchResponse, RunSummary
from api.deps import get_db

router = APIRouter(prefix="/runs", tags=["runs"])

_MATCHED = {"exact", "fuzzy", "one_to_many", "many_to_one", "human_corrected"}


def _build_runs(records: list[MatchRecord]) -> list[RunSummary]:
    runs: dict[str, dict] = {}
    for r in records:
        status = r.status.value if hasattr(r.status, "value") else str(r.status)
        e = runs.setdefault(r.run_id, {
            "run_id": r.run_id, "created_at": r.created_at or "",
            "total": 0, "matched": 0, "pending": 0, "unmatched": 0,
        })
        e["total"] += 1
        if status in _MATCHED:
            e["matched"] += 1
        elif status == "unmatched":
            e["unmatched"] += 1
        if r.requires_human_review and r.human_approved is None:
            e["pending"] += 1
        if (r.created_at or "") > e["created_at"]:
            e["created_at"] = r.created_at or ""

    result = []
    for e in sorted(runs.values(), key=lambda x: x["created_at"], reverse=True):
        rate = round(e["matched"] / e["total"] * 100, 1) if e["total"] else 0.0
        result.append(RunSummary(**e, match_rate=rate))
    return result


def _match_to_response(r: MatchRecord) -> MatchResponse:
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


@router.get("/", response_model=list[RunSummary])
def list_runs(db: Session = Depends(get_db)):
    return _build_runs(db.exec(select(MatchRecord)).all())


@router.get("/{run_id}", response_model=RunSummary)
def get_run(run_id: str, db: Session = Depends(get_db)):
    records = db.exec(select(MatchRecord).where(MatchRecord.run_id == run_id)).all()
    if not records:
        raise HTTPException(status_code=404, detail="Run not found")
    return _build_runs(records)[0]


@router.get("/{run_id}/matches", response_model=list[MatchResponse])
def run_matches(run_id: str, db: Session = Depends(get_db)):
    records = db.exec(select(MatchRecord).where(MatchRecord.run_id == run_id)).all()
    if not records:
        raise HTTPException(status_code=404, detail="Run not found")
    return [_match_to_response(r) for r in records]


@router.post("/upload", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def upload_run():
    """Reconciliation upload — implemented in Phase 2."""
    raise HTTPException(
        status_code=501,
        detail="Use the Streamlit UI at :8501 for reconciliation runs during Phase 1.",
    )
