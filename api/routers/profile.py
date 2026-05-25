from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from memory.models import UserProfile
from api.schemas.models import UserProfileResponse, UserProfileUpdate
from api.deps import get_db

router = APIRouter(prefix="/profile", tags=["profile"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default() -> UserProfileResponse:
    return UserProfileResponse(id=None, name="User", role="Accountant", email=None, updated_at="")


@router.get("/", response_model=UserProfileResponse)
def get_profile(db: Session = Depends(get_db)):
    p = db.exec(select(UserProfile)).first()
    if not p:
        return _default()
    return UserProfileResponse(**p.model_dump())


@router.put("/", response_model=UserProfileResponse)
def upsert_profile(body: UserProfileUpdate, db: Session = Depends(get_db)):
    p = db.exec(select(UserProfile)).first()
    if p:
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(p, k, v)
        p.updated_at = _now()
    else:
        p = UserProfile(**body.model_dump(exclude_unset=True), updated_at=_now())
    db.add(p)
    db.commit()
    db.refresh(p)
    return UserProfileResponse(**p.model_dump())
