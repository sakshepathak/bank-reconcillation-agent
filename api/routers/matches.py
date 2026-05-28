from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import MatchRecord
from api.schemas.models import BulkActionRequest, MatchResponse
from api.deps import get_db, get_current_org_id

router = APIRouter(prefix="/matches", tags=["matches"])


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
def list_matches(
    run_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = select(MatchRecord).where(MatchRecord.org_id == org_id)
    if run_id:
        q = q.where(MatchRecord.run_id == run_id)
    if status:
        q = q.where(MatchRecord.status == status)
    return [_to_resp(r) for r in db.exec(q).all()]


@router.get("/pending", response_model=list[MatchResponse])
def pending_matches(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    q = (
        select(MatchRecord)
        .where(MatchRecord.org_id == org_id)
        .where(MatchRecord.requires_human_review == True)
        .where(MatchRecord.human_approved == None)
    )
    return [_to_resp(r) for r in db.exec(q).all()]


def _set_approval(match_id: int, approved: bool, db: Session, org_id: int) -> MatchResponse:
    r = db.get(MatchRecord, match_id)
    if not r or r.org_id != org_id:
        raise HTTPException(status_code=404, detail="Match not found")
    r.human_approved = approved
    db.add(r)
    db.commit()
    db.refresh(r)
    return _to_resp(r)


@router.patch("/{match_id}/approve", response_model=MatchResponse)
def approve_match(
    match_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    return _set_approval(match_id, True, db, org_id)


@router.patch("/{match_id}/reject", response_model=MatchResponse)
def reject_match(
    match_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    return _set_approval(match_id, False, db, org_id)


def _bulk_set(ids: list[int], approved: bool, db: Session, org_id: int) -> dict:
    updated = 0
    for mid in ids:
        r = db.get(MatchRecord, mid)
        if r and r.org_id == org_id:
            r.human_approved = approved
            db.add(r)
            updated += 1
    db.commit()
    return {"updated": updated}


@router.post("/bulk-approve")
def bulk_approve(
    body: BulkActionRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    return _bulk_set(body.ids, True, db, org_id)


@router.post("/bulk-reject")
def bulk_reject(
    body: BulkActionRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    return _bulk_set(body.ids, False, db, org_id)
