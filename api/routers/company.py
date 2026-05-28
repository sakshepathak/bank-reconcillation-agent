from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from memory.models import CompanyProfile, ServiceOffered
from api.schemas.models import (
    CompanyResponse, CompanyUpdate,
    ServiceCreate, ServiceResponse,
)
from api.deps import get_db, get_current_org_id, require_user
from memory.models import User

router = APIRouter(tags=["company"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_company() -> CompanyResponse:
    return CompanyResponse(
        id=None, company_name="", about=None, industry=None, website=None,
        phone=None, address=None, registration_number=None,
        vat_registered=False, vat_number=None, tax_treatment="exclusive",
        updated_at="",
    )


@router.get("/company", response_model=CompanyResponse)
def get_company(
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    # Legacy single-row table — being migrated to Organization in a later step.
    # Authentication required here is enough; per-org split happens with the migration.
    c = db.exec(select(CompanyProfile)).first()
    if not c:
        return _empty_company()
    return CompanyResponse(**c.model_dump())


@router.put("/company", response_model=CompanyResponse)
def upsert_company(
    body: CompanyUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_user),
):
    c = db.exec(select(CompanyProfile)).first()
    if c:
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(c, k, v)
        c.updated_at = _now()
    else:
        c = CompanyProfile(**body.model_dump(exclude_unset=True), updated_at=_now())
    db.add(c)
    db.commit()
    db.refresh(c)
    return CompanyResponse(**c.model_dump())


# ── Services ──────────────────────────────────────────────────────────────────

@router.get("/services", response_model=list[ServiceResponse])
def list_services(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    rows = db.exec(select(ServiceOffered).where(ServiceOffered.org_id == org_id)).all()
    return [ServiceResponse(**r.model_dump()) for r in rows]


@router.post("/services", response_model=ServiceResponse, status_code=201)
def create_service(
    body: ServiceCreate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    svc = ServiceOffered(**body.model_dump(), org_id=org_id, created_at=_now())
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return ServiceResponse(**svc.model_dump())


@router.delete("/services/{service_id}", status_code=204)
def delete_service(
    service_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    from fastapi import HTTPException
    svc = db.get(ServiceOffered, service_id)
    if not svc or svc.org_id != org_id:
        raise HTTPException(status_code=404, detail="Service not found")
    db.delete(svc)
    db.commit()
