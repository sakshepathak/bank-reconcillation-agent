from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from memory.models import Contact, VendorAlias
from api.schemas.models import AliasCreate, AliasResponse
from api.deps import get_db, get_current_org_id

router = APIRouter(prefix="/aliases", tags=["aliases"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_resp(a: VendorAlias) -> AliasResponse:
    # model_dump() works too, but explicit beats implicit when the schema
    # has more fields than the model surfaces by default.
    return AliasResponse(
        id=a.id,
        alias=a.alias,
        canonical_name=a.canonical_name,
        contact_id=a.contact_id,
        confidence=a.confidence,
        source=a.source,
        created_at=a.created_at,
    )


@router.get("/", response_model=list[AliasResponse])
def list_aliases(
    contact_id: int | None = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """List aliases in the current org. Pass ?contact_id=N to filter to one contact."""
    q = select(VendorAlias).where(VendorAlias.org_id == org_id)
    if contact_id is not None:
        q = q.where(VendorAlias.contact_id == contact_id)
    rows = db.exec(q).all()
    return [_to_resp(r) for r in rows]


@router.post("/", response_model=AliasResponse, status_code=201)
def create_alias(
    body: AliasCreate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """
    Two acceptable input shapes:
      • {alias, contact_id}                  → canonical_name pulled from Contact.full_name
      • {alias, canonical_name}              → legacy free-string flow (no contact link)

    If both are supplied, contact_id wins and canonical_name is overwritten
    from the Contact — keeps the cache in sync with the source of truth.
    """
    canonical: str | None = None
    contact_id: int | None = None

    if body.contact_id is not None:
        contact = db.get(Contact, body.contact_id)
        if not contact or contact.org_id != org_id:
            raise HTTPException(status_code=404, detail="Contact not found")
        contact_id = contact.id
        canonical = contact.full_name
    elif body.canonical_name and body.canonical_name.strip():
        canonical = body.canonical_name.strip()
    else:
        raise HTTPException(
            status_code=400,
            detail="Either contact_id or canonical_name must be provided",
        )

    alias = VendorAlias(
        org_id=org_id,
        alias=body.alias.lower().strip(),
        canonical_name=canonical,
        contact_id=contact_id,
        confidence=body.confidence,
        source="human",
        created_at=_now(),
    )
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return _to_resp(alias)


@router.delete("/{alias_id}", status_code=204)
def delete_alias(
    alias_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    row = db.get(VendorAlias, alias_id)
    if not row or row.org_id != org_id:
        raise HTTPException(status_code=404, detail="Alias not found")
    db.delete(row)
    db.commit()
