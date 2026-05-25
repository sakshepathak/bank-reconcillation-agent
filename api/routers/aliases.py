from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import VendorAlias
from api.schemas.models import AliasCreate, AliasResponse
from api.deps import get_db

router = APIRouter(prefix="/aliases", tags=["aliases"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/", response_model=list[AliasResponse])
def list_aliases(db: Session = Depends(get_db)):
    rows = db.exec(select(VendorAlias)).all()
    return [AliasResponse(**r.model_dump()) for r in rows]


@router.post("/", response_model=AliasResponse, status_code=201)
def create_alias(body: AliasCreate, db: Session = Depends(get_db)):
    alias = VendorAlias(
        alias=body.alias.lower().strip(),
        canonical_name=body.canonical_name.strip(),
        confidence=body.confidence,
        source="human",
        created_at=_now(),
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return AliasResponse(**alias.model_dump())


@router.delete("/{alias_id}", status_code=204)
def delete_alias(alias_id: int, db: Session = Depends(get_db)):
    row = db.get(VendorAlias, alias_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alias not found")
    db.delete(row)
    db.commit()
