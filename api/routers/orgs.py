"""
Organisations router — managing the multi-tenant Organization entity.

The auth router covers user/session lifecycle. This router covers:
  • Creating an additional org for an existing logged-in user
  • Listing the orgs the current user belongs to (richer than /auth/me)
  • Reading + editing the current org's details

`POST /` is deliberately separate from `/auth/register`:
  • /auth/register = bootstrap a brand-new user + their first org. Gated by
    the no-users / ALLOW_REGISTRATION rule.
  • POST /orgs     = an already-authenticated user adds another business.
    No gating — once you're logged in you can spin up as many orgs as you
    want; multi-org is a v1 feature.

The freshly-created org becomes the user's `current_org_id` so the next
page they land on is scoped to it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from memory.models import Organization, User, UserOrgMembership, UserSession
from api.deps import get_db, get_current_org_id, get_optional_session, require_user

router = APIRouter(prefix="/orgs", tags=["orgs"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Schemas ──────────────────────────────────────────────────────────────────

class OrgCreate(BaseModel):
    """
    Add-your-business payload. Defaults match the typical UK setup; an
    Indian/US/etc business can override country + currency + FYE.
    """
    name: str = Field(min_length=1, max_length=120)
    country: str = Field(default="GB", min_length=2, max_length=2)        # ISO 3166 alpha-2
    currency: str = Field(default="GBP", min_length=3, max_length=3)      # ISO 4217
    industry: Optional[str] = Field(default=None, max_length=120)
    vat_registered: bool = False
    vat_number: Optional[str] = Field(default=None, max_length=40)
    tax_treatment: str = Field(default="exclusive")
    # UK financial year runs to 5 April. Default to that; user can change.
    financial_year_end_day: int = Field(default=5, ge=1, le=31)
    financial_year_end_month: int = Field(default=4, ge=1, le=12)


class OrgUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    country: Optional[str] = Field(default=None, min_length=2, max_length=2)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    industry: Optional[str] = Field(default=None, max_length=120)
    vat_registered: Optional[bool] = None
    vat_number: Optional[str] = Field(default=None, max_length=40)
    tax_treatment: Optional[str] = None
    financial_year_end_day: Optional[int] = Field(default=None, ge=1, le=31)
    financial_year_end_month: Optional[int] = Field(default=None, ge=1, le=12)


class OrgResponse(BaseModel):
    id: int
    name: str
    country: Optional[str]
    currency: str
    industry: Optional[str]
    vat_registered: bool
    vat_number: Optional[str]
    tax_treatment: str
    financial_year_end_day: int
    financial_year_end_month: int
    created_at: str
    updated_at: str
    role: Optional[str] = None  # the requesting user's role in this org


def _to_resp(org: Organization, role: Optional[str] = None) -> OrgResponse:
    return OrgResponse(
        id=org.id,
        name=org.name,
        country=org.country,
        currency=org.currency,
        industry=org.industry,
        vat_registered=org.vat_registered,
        vat_number=org.vat_number,
        tax_treatment=org.tax_treatment,
        financial_year_end_day=org.financial_year_end_day,
        financial_year_end_month=org.financial_year_end_month,
        created_at=org.created_at,
        updated_at=org.updated_at,
        role=role,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[OrgResponse])
def list_my_orgs(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """All orgs the current user belongs to, with their role per org."""
    memberships = db.exec(
        select(UserOrgMembership)
        .where(UserOrgMembership.user_id == user.id)
        .order_by(UserOrgMembership.org_id)
    ).all()
    out: list[OrgResponse] = []
    for m in memberships:
        org = db.get(Organization, m.org_id)
        if org:
            out.append(_to_resp(org, role=m.role))
    return out


@router.post("/", response_model=OrgResponse, status_code=201)
def create_org(
    body: OrgCreate,
    user: User = Depends(require_user),
    sess: UserSession = Depends(get_optional_session),
    db: Session = Depends(get_db),
):
    """
    Create a new organisation owned by the current user (admin role).
    Switches the session's current_org_id to the new one so the next
    request is scoped to it. Doesn't require ALLOW_REGISTRATION.
    """
    now = _now()
    org = Organization(
        name=body.name.strip(),
        country=body.country.upper(),
        currency=body.currency.upper(),
        industry=(body.industry or "").strip() or None,
        vat_registered=body.vat_registered,
        vat_number=(body.vat_number or "").strip() or None,
        tax_treatment=body.tax_treatment,
        financial_year_end_day=body.financial_year_end_day,
        financial_year_end_month=body.financial_year_end_month,
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    db.flush()  # need org.id

    db.add(UserOrgMembership(
        user_id=user.id,
        org_id=org.id,
        role="admin",
        created_at=now,
    ))

    # Auto-switch the session to the new org. If sess is None (shouldn't
    # happen — require_user passed — but defensive), just create without switch.
    if sess is not None:
        sess.current_org_id = org.id
        db.add(sess)

    db.commit()
    db.refresh(org)
    return _to_resp(org, role="admin")


@router.get("/current", response_model=OrgResponse)
def get_current_org(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(require_user),
):
    """Full details of the org the current session is acting on."""
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    membership = db.exec(
        select(UserOrgMembership).where(
            UserOrgMembership.user_id == user.id,
            UserOrgMembership.org_id == org_id,
        )
    ).first()
    return _to_resp(org, role=membership.role if membership else None)


@router.patch("/current", response_model=OrgResponse)
def update_current_org(
    body: OrgUpdate,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
    user: User = Depends(require_user),
):
    """Edit the current org's profile fields. Membership check is implicit:
    get_current_org_id is set to an org the user is a member of (login wires
    it; switch_org refuses non-member targets)."""
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    data = body.model_dump(exclude_unset=True)
    if "country" in data and data["country"]:
        data["country"] = data["country"].upper()
    if "currency" in data and data["currency"]:
        data["currency"] = data["currency"].upper()
    for k, v in data.items():
        setattr(org, k, v)
    org.updated_at = _now()
    db.add(org)
    db.commit()
    db.refresh(org)

    membership = db.exec(
        select(UserOrgMembership).where(
            UserOrgMembership.user_id == user.id,
            UserOrgMembership.org_id == org_id,
        )
    ).first()
    return _to_resp(org, role=membership.role if membership else None)
