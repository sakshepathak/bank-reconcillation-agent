"""Pydantic request/response schemas for the REST API."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


# ── Runs ──────────────────────────────────────────────────────────────────────

class RunSummary(BaseModel):
    run_id: str
    created_at: str
    total: int
    matched: int
    pending: int
    unmatched: int
    match_rate: float


# ── Matches ───────────────────────────────────────────────────────────────────

class MatchResponse(BaseModel):
    id: int
    run_id: str
    bank_txn_id: str
    ledger_txn_id: Optional[str]
    status: str
    score: float
    reasoning_path: str
    amount_diff: Optional[float]
    date_diff_days: Optional[int]
    requires_human_review: bool
    human_approved: Optional[bool]
    created_at: str


class BulkActionRequest(BaseModel):
    ids: list[int]


# ── Contacts ──────────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    full_name: str
    company: Optional[str] = None
    contact_type: str = "customer"
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class ContactUpdate(BaseModel):
    full_name: Optional[str] = None
    company: Optional[str] = None
    contact_type: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class ContactResponse(BaseModel):
    id: int
    full_name: str
    company: Optional[str]
    contact_type: str
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str


# ── Company & Services ────────────────────────────────────────────────────────

class CompanyResponse(BaseModel):
    id: Optional[int]
    company_name: str
    about: Optional[str]
    industry: Optional[str]
    website: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    registration_number: Optional[str]
    vat_registered: bool
    vat_number: Optional[str]
    tax_treatment: str
    updated_at: str


class CompanyUpdate(BaseModel):
    company_name: Optional[str] = None
    about: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    registration_number: Optional[str] = None
    vat_registered: Optional[bool] = None
    vat_number: Optional[str] = None
    tax_treatment: Optional[str] = None


class ServiceResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    service_category: str
    vat_applicable: bool
    created_at: str


class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    service_category: str = "service"
    vat_applicable: bool = True


# ── Vendor Aliases ────────────────────────────────────────────────────────────

class AliasResponse(BaseModel):
    id: int
    alias: str
    canonical_name: str
    confidence: float
    source: str
    created_at: str


class AliasCreate(BaseModel):
    alias: str
    canonical_name: str
    confidence: float = 1.0


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_runs: int
    total_transactions: int
    overall_match_rate: float
    pending_review: int
    total_contacts: int
    last_run_date: Optional[str]
