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


class ContactDocSummary(BaseModel):
    """Slimmed Invoice/Bill row shown on the Contact detail page."""
    id: int
    number: Optional[str]
    issue_date: str
    total: float
    outstanding: float
    currency: str
    status: str


# ContactDetailResponse is defined further down — after AliasResponse — so the
# `aliases: list[AliasResponse]` field resolves cleanly without forward refs.


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
    contact_id: Optional[int] = None
    confidence: float
    source: str
    created_at: str


class AliasCreate(BaseModel):
    """
    Create an alias linked to a Contact. `canonical_name` is set from the
    target Contact's `full_name` automatically — clients only need to send
    the raw alias string + the contact_id it maps to.

    `canonical_name` is accepted (and used) when contact_id is omitted, for
    backwards-compat with callers that don't know the contact yet (the old
    free-string flow on the standalone Aliases page).
    """
    alias: str
    contact_id: Optional[int] = None
    canonical_name: Optional[str] = None
    confidence: float = 1.0


class ContactDetailResponse(BaseModel):
    """Bundle returned by GET /contacts/{id}/detail."""
    contact: ContactResponse
    invoices: list[ContactDocSummary]
    bills: list[ContactDocSummary]
    aliases: list[AliasResponse]


class ContactPaymentTimingResponse(BaseModel):
    """Learned payment-timing summary for the Contact 'Payment behaviour' card.

    Central/spread/trend fields are null until enough payments have been observed
    (the engine needs a few before it trusts a pattern)."""
    contact_id: int
    observations: int                      # all-time payments learned for this vendor
    sample_size: int                       # recent payments the stats are computed over
    typical_days: Optional[int] = None     # median lag — "typically pays in ~N days"
    window_days: Optional[int] = None      # the window the matcher credits to (p80)
    min_days: Optional[int] = None
    max_days: Optional[int] = None
    consistency: Optional[str] = None      # "consistent" | "variable"
    trend: Optional[str] = None            # "steady" | "slower" | "faster"
    recent_lags: list[int] = []
    updated_at: Optional[str] = None


# ── Bank Accounts ────────────────────────────────────────────────────────────

class BankAccountCreate(BaseModel):
    name: str
    account_number: Optional[str] = None
    bank_name: Optional[str] = None
    currency: str = "GBP"
    statement_balance: float = 0.0
    ooo_balance: float = 0.0


class BankAccountUpdate(BaseModel):
    name: Optional[str] = None
    account_number: Optional[str] = None
    bank_name: Optional[str] = None
    currency: Optional[str] = None
    statement_balance: Optional[float] = None
    is_active: Optional[bool] = None


class BankAccountResponse(BaseModel):
    id: int
    name: str
    account_number: Optional[str]
    bank_name: Optional[str]
    currency: str
    statement_balance: float
    ooo_balance: float
    balance_difference: float           # statement_balance - ooo_balance
    pending_count: int                  # statement lines awaiting reconcile
    last_imported_at: Optional[str]
    is_active: bool
    created_at: str


# ── Invoices (Sales / AR) ────────────────────────────────────────────────────

class InvoiceLineCreate(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    tax_rate: float = 0.0
    service_id: Optional[int] = None


class InvoiceLineResponse(BaseModel):
    id: int
    invoice_id: int
    description: str
    quantity: float
    unit_price: float
    tax_rate: float
    line_total: float
    service_id: Optional[int]


class InvoiceCreate(BaseModel):
    number: str
    contact_id: Optional[int] = None
    contact_name: str
    reference: Optional[str] = None
    issue_date: str
    due_date: Optional[str] = None
    currency: str = "GBP"
    notes: Optional[str] = None
    status: str = "draft"
    lines: list[InvoiceLineCreate] = []


class InvoiceUpdate(BaseModel):
    number: Optional[str] = None
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None
    reference: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    sent: Optional[bool] = None
    currency: Optional[str] = None
    total: Optional[float] = None


class InvoiceResponse(BaseModel):
    id: int
    number: str
    contact_id: Optional[int]
    contact_name: str
    reference: Optional[str]
    issue_date: str
    due_date: Optional[str]
    subtotal: float
    tax_total: float
    total: float
    paid_amount: float
    outstanding: float                  # total - paid_amount
    currency: str
    status: str
    notes: Optional[str]
    sent: bool
    lines: list[InvoiceLineResponse] = []
    created_at: str
    updated_at: str


# ── Bills (Purchases / AP) ───────────────────────────────────────────────────

class BillLineCreate(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    tax_rate: float = 0.0
    account_code: Optional[str] = None


class BillLineResponse(BaseModel):
    id: int
    bill_id: int
    description: str
    quantity: float
    unit_price: float
    tax_rate: float
    line_total: float
    account_code: Optional[str]


class BillCreate(BaseModel):
    number: Optional[str] = None
    contact_id: Optional[int] = None
    contact_name: str
    reference: Optional[str] = None
    issue_date: str
    due_date: Optional[str] = None
    currency: str = "GBP"
    notes: Optional[str] = None
    status: str = "draft"
    lines: list[BillLineCreate] = []


class BillUpdate(BaseModel):
    number: Optional[str] = None
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None
    reference: Optional[str] = None
    issue_date: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    currency: Optional[str] = None
    total: Optional[float] = None


class BillResponse(BaseModel):
    id: int
    number: Optional[str]
    contact_id: Optional[int]
    contact_name: str
    reference: Optional[str]
    issue_date: str
    due_date: Optional[str]
    subtotal: float
    tax_total: float
    total: float
    paid_amount: float
    outstanding: float                  # total - paid_amount
    currency: str
    status: str
    notes: Optional[str]
    lines: list[BillLineResponse] = []
    created_at: str
    updated_at: str


# ── Journal Entries (manual entries from Reconcile "Create" tab) ─────────────

class JournalEntryCreate(BaseModel):
    date: str
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None
    account_code: Optional[str] = None
    description: str
    amount: float                       # signed: + received, - spent
    tax_rate: float = 0.0
    currency: str = "GBP"


class JournalEntryResponse(BaseModel):
    id: int
    date: str
    contact_id: Optional[int]
    contact_name: Optional[str]
    account_code: Optional[str]
    description: str
    amount: float
    tax_rate: float
    currency: str
    created_at: str


# ── Bulk Match ───────────────────────────────────────────────────────────────

class BulkMatchOpenDoc(BaseModel):
    id: int
    label: str
    amount: float
    date: str
    contact_name: str


class BulkMatchSuggestionsResponse(BaseModel):
    """Returned by GET /{line_id}/bulk-suggestions."""
    vendor: Optional[str] = None           # top vendor identified from bank description
    vendor_score: float = 0.0              # matcher confidence 0–1
    doc_type: str                          # "invoice" | "bill"
    open_docs: list[BulkMatchOpenDoc]      # all open docs for that vendor
    suggested_groups: list[list[int]]      # [[id1,id2,id3], ...] exact-sum subsets


# ── Statement Lines ──────────────────────────────────────────────────────────

class StatementLineResponse(BaseModel):
    id: int
    bank_account_id: int
    date: str
    description: str
    reference: Optional[str]
    spent: float
    received: float
    balance_after: Optional[float]
    status: str
    matched_invoice_id: Optional[int]
    matched_bill_id: Optional[int]
    matched_journal_id: Optional[int]
    transfer_to_account_id: Optional[int]
    matched_invoice_ids: Optional[list[dict]] = None  # bulk: [{"id":1,"amount":520.0},...]
    matched_bill_ids: Optional[list[dict]] = None
    discussion: Optional[str]
    suggested_score: Optional[float]
    imported_at: str
    reconciled_at: Optional[str]


class StatementLineImport(BaseModel):
    """One statement line in a manual upload batch."""
    date: str
    description: str
    reference: Optional[str] = None
    spent: float = 0.0
    received: float = 0.0
    balance_after: Optional[float] = None


class StatementImportRequest(BaseModel):
    bank_account_id: int
    lines: list[StatementLineImport]


# ── Reconcile actions (the heart of the Reconcile screen) ────────────────────

class MatchInvoiceRequest(BaseModel):
    invoice_id: int
    # When true, save this bank description → invoice vendor as a learned
    # VendorAlias so future reconciliations match it automatically.
    learn_alias: bool = False


class MatchBillRequest(BaseModel):
    bill_id: int
    learn_alias: bool = False


class MatchBulkInvoicesRequest(BaseModel):
    invoice_ids: list[int]


class MatchBulkBillsRequest(BaseModel):
    bill_ids: list[int]


class CreateEntryRequest(BaseModel):
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None
    account_code: Optional[str] = None
    description: str
    tax_rate: float = 0.0


class TransferRequest(BaseModel):
    to_account_id: int


class DiscussRequest(BaseModel):
    note: str


# ── User Profile ─────────────────────────────────────────────────────────────

class UserProfileResponse(BaseModel):
    id: Optional[int]
    name: str
    role: str
    email: Optional[str]
    updated_at: str


class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_runs: int
    total_transactions: int
    overall_match_rate: float
    pending_review: int
    total_contacts: int
    last_run_date: Optional[str]
