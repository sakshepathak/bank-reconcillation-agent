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

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, update as sa_update
from sqlmodel import Session, select

from memory.models import (
    Organization, User, UserOrgMembership, UserSession,
    # Org-scoped business tables wiped on org deletion:
    StatementLine, MatchRecord, InvoiceLine, BillLine, VendorAlias,
    Invoice, Bill, JournalEntry, ServiceOffered, BankAccount, Contact,
    ManualLedgerEntry, ExtractedInvoice, CompanyProfile,
)
from api.deps import get_db, get_current_org_id, get_optional_session, require_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/orgs", tags=["orgs"])

# Ordered children-first so the wipe respects FK references (StatementLine →
# Invoice/Bill/Journal/BankAccount; *Line → parent; Alias/Invoice/Bill/Journal →
# Contact). Every table carries org_id (backfilled by migration 001), so each
# is a flat `DELETE ... WHERE org_id = ?` — no joins needed.
_ORG_SCOPED_MODELS = [
    StatementLine,      # references invoice/bill/journal/bank_account
    MatchRecord,
    InvoiceLine,        # references invoice, service_offered
    BillLine,           # references bill
    VendorAlias,        # references contact
    Invoice,            # references contact
    Bill,               # references contact
    JournalEntry,       # references contact
    ServiceOffered,
    BankAccount,
    Contact,
    ManualLedgerEntry,
    ExtractedInvoice,
    CompanyProfile,
]


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


# ── Export + delete ──────────────────────────────────────────────────────────

def _require_admin_membership(db: Session, user: User, org_id: int) -> Organization:
    """Load the org and assert the user is an admin member of it. 404 if the org
    doesn't exist, 403 if the user isn't an admin of it."""
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    membership = db.exec(
        select(UserOrgMembership).where(
            UserOrgMembership.user_id == user.id,
            UserOrgMembership.org_id == org_id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="You are not a member of that organisation")
    if membership.role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can perform this action")
    return org


def _delete_org_kb_vectors(org_id: int) -> None:
    """
    Best-effort removal of this org's knowledge-base vectors from Qdrant.

    The KB isn't org-scoped yet (chunks carry no org_id payload today), so this
    is forward-compatible and a no-op for now. It must never block the SQL wipe:
    if Qdrant is unreachable or the collection is missing, we log and move on.
    """
    try:
        from qdrant_client import QdrantClient, models as qmodels
        from config.settings import settings as _settings

        client = QdrantClient(url=_settings.QDRANT_URL)
        if not client.collection_exists(_settings.QDRANT_COLLECTION):
            return
        client.delete(
            collection_name=_settings.QDRANT_COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="org_id", match=qmodels.MatchValue(value=org_id),
                    )]
                )
            ),
        )
    except Exception as e:  # noqa: BLE001 — KB cleanup is best-effort
        log.warning("KB vector cleanup skipped for org %s: %s", org_id, e)


@router.get("/{org_id}/export")
def export_org(
    org_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """
    Full JSON dump of everything stored for an organisation — the safety net the
    user downloads before a permanent delete. Admin-only.
    """
    org = _require_admin_membership(db, user, org_id)

    payload: dict = {
        "exported_at": _now(),
        "organisation": _to_resp(org).model_dump(),
        "data": {},
    }
    for model in _ORG_SCOPED_MODELS:
        rows = db.exec(select(model).where(model.org_id == org_id)).all()
        payload["data"][model.__tablename__] = [r.model_dump() for r in rows]

    return payload


@router.delete("/{org_id}", status_code=200)
def delete_org(
    org_id: int,
    user: User = Depends(require_user),
    sess: UserSession = Depends(get_optional_session),
    db: Session = Depends(get_db),
):
    """
    Permanently delete an organisation and EVERYTHING in it — a clean slate.

    Wipes all org-scoped business rows (children-first), the org's KB vectors,
    every user's membership of it, then the org itself. Any session pointing at
    the deleted org (including the caller's) is reset to "no org selected" so the
    app drops to the org picker. Admin-only. Irreversible — callers should offer
    the /export download first.
    """
    _require_admin_membership(db, user, org_id)

    deleted_counts: dict[str, int] = {}
    for model in _ORG_SCOPED_MODELS:
        res = db.execute(sa_delete(model).where(model.org_id == org_id))
        deleted_counts[model.__tablename__] = res.rowcount or 0

    # Best-effort KB cleanup (no-op until the KB is org-scoped).
    _delete_org_kb_vectors(org_id)

    # Drop every user's membership of this org.
    db.execute(sa_delete(UserOrgMembership).where(UserOrgMembership.org_id == org_id))

    # Reset any session (including the caller's) currently acting on this org so
    # nothing references a now-deleted org and the user lands on the picker.
    db.execute(
        sa_update(UserSession)
        .where(UserSession.current_org_id == org_id)
        .values(current_org_id=None)
    )

    # Finally the org row itself.
    db.execute(sa_delete(Organization).where(Organization.id == org_id))
    db.commit()

    log.info("Deleted org %s (by user %s). Rows removed: %s", org_id, user.id, deleted_counts)

    remaining = db.exec(
        select(UserOrgMembership).where(UserOrgMembership.user_id == user.id)
    ).all()
    return {
        "deleted_org_id": org_id,
        "rows_deleted": deleted_counts,
        "remaining_org_count": len(remaining),
        "current_org_id": None,
    }
