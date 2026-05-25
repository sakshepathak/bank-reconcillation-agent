"""
SQLModel database models for the Bank Reconciliation Agent.

Design decisions:
- VendorAlias: stores canonical vendor name mappings learned from human corrections.
  Indexed on `alias` for fast exact lookups.
- MatchRecord: full audit trail for every reconciliation decision (required spec).
  `reasoning_path` stores the chain-of-thought so every match is explainable.
- The `source` enum distinguishes bank vs. ledger rows without a separate table.
"""
from datetime import date as DateType
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class TransactionSource(str, Enum):
    BANK = "bank"
    LEDGER = "ledger"


class MatchStatus(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    ONE_TO_MANY = "one_to_many"        # 1 bank line = sum of N invoices
    MANY_TO_ONE = "many_to_one"        # N bank lines (installments) = 1 invoice
    POSSIBLE = "possible"              # relaxed match — needs human, low confidence
    UNMATCHED = "unmatched"
    HUMAN_CORRECTED = "human_corrected"


class VendorAlias(SQLModel, table=True):
    """
    Maps inconsistent bank-statement descriptions to canonical vendor names.
    e.g. "AMZN MKTPL *123" -> "Amazon"

    The `alias` column is the raw, messy string from the bank statement.
    Lookups are case-insensitive (normalised before insert/query).
    """

    __tablename__ = "vendor_alias"

    id: Optional[int] = Field(default=None, primary_key=True)
    alias: str = Field(index=True)          # raw dirty string (lowercased)
    canonical_name: str                      # clean vendor name
    confidence: float = Field(default=1.0)   # 1.0 = human confirmed
    source: str = Field(default="human")     # "human" | "agent"
    created_at: str = Field(default="")      # ISO datetime string


class MatchRecord(SQLModel, table=True):
    """
    Immutable audit log of every reconciliation decision made by the agent.
    One row per attempted match (including unmatched rows).
    """

    __tablename__ = "match_record"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)          # groups all rows from one recon run
    bank_txn_id: str                         # stable row ID from bank CSV
    ledger_txn_id: Optional[str] = None      # None if unmatched
    status: MatchStatus
    score: float = Field(default=0.0)        # similarity score 0-1
    reasoning_path: str = Field(default="")  # agent's chain-of-thought
    amount_diff: Optional[float] = None      # absolute amount difference
    date_diff_days: Optional[int] = None     # signed date delta
    requires_human_review: bool = Field(default=False)
    human_approved: Optional[bool] = None    # set after HITL gate
    created_at: str = Field(default="")      # ISO datetime string


class ExtractedInvoice(SQLModel, table=True):
    """
    Structured data extracted from an uploaded invoice/bill (PDF or image)
    by the vision extractor. Acts as the ledger source for reconciliation
    runs — replaces the old ledger-CSV path.

    `file_hash` is the SHA-256 of the original upload; identical re-uploads
    dedupe to the same row.
    """

    __tablename__ = "extracted_invoice"

    id: Optional[int] = Field(default=None, primary_key=True)
    file_hash: str = Field(index=True)
    source_filename: str
    storage_path: str                          # relative to UPLOAD_DIR
    mime_type: str

    # Extracted fields
    vendor: str
    doc_type: str = Field(default="unknown", index=True)   # "sales" | "purchase" | "unknown"
    invoice_id: Optional[str] = None
    date: str                                  # ISO date string
    amount: float
    currency: str = Field(default="USD")

    # Meta
    raw_extraction_json: str = Field(default="")   # full JSON response for audit
    extraction_confidence: float = Field(default=1.0)
    extraction_error: Optional[str] = None     # set if extraction failed
    created_at: str = Field(default="")


class ManualLedgerEntry(SQLModel, table=True):
    """
    Ledger entries created inline by the user from unmatched bank lines
    (Xero-style "Create Entry" flow). Date, amount, and description are
    inherited from the bank line; the user supplies the canonical vendor.
    """

    __tablename__ = "manual_ledger_entry"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    bank_txn_id: str = Field(index=True)
    vendor: str
    amount: float
    date: str                                # ISO date string
    description: str                         # raw bank description preserved
    created_at: str = Field(default="")


class UserProfile(SQLModel, table=True):
    """Single-row user profile. Created on first sidebar render if absent."""

    __tablename__ = "user_profile"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(default="User")
    role: str = Field(default="Accountant")
    email: Optional[str] = None
    updated_at: str = Field(default="")


class CompanyProfile(SQLModel, table=True):
    """Single-row company profile. Managed via the Settings tab."""

    __tablename__ = "company_profile"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_name: str = Field(default="")
    about: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    registration_number: Optional[str] = None
    vat_registered: bool = Field(default=False)
    vat_number: Optional[str] = None
    tax_treatment: str = Field(default="exclusive")  # exclusive | inclusive | exempt
    updated_at: str = Field(default="")


class ServiceOffered(SQLModel, table=True):
    """Services or products the company offers — used for VAT/tax categorisation."""

    __tablename__ = "service_offered"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    service_category: str = Field(default="service")  # service | product
    vat_applicable: bool = Field(default=True)
    created_at: str = Field(default="")


class Contact(SQLModel, table=True):
    """Customers, suppliers, and internal contacts."""

    __tablename__ = "contact"

    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    company: Optional[str] = None
    contact_type: str = Field(default="customer")  # customer | supplier | internal | other
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = Field(default="")
    updated_at: str = Field(default="")


# ─────────────────────────────────────────────────────────────────────────────
# Xero-style accounting entities
# ─────────────────────────────────────────────────────────────────────────────


class DocumentStatus(str, Enum):
    """Lifecycle states for invoices and bills (matches Xero's tab labels)."""
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    VOIDED = "voided"


class StatementLineStatus(str, Enum):
    """Lifecycle of a single line on a bank statement."""
    PENDING = "pending"          # imported, not yet reconciled
    MATCHED = "matched"          # linked to an invoice or bill
    MANUAL = "manual"            # linked to a JournalEntry (Create flow)
    TRANSFER = "transfer"        # cross-account transfer
    DISCUSSED = "discussed"      # has a comment, awaiting resolution


class BankAccount(SQLModel, table=True):
    """
    One row per bank account the company holds. Two balances tracked:

      statement_balance  →  what the bank says (from the latest import)
      ooo_balance        →  what OOO (this app) thinks the balance is,
                            computed from invoices + bills + journal
                            entries that have been reconciled so far.

    The core invariant of the app:

        when every StatementLine is reconciled,
        statement_balance == ooo_balance

    `balance_difference` (computed property, not stored) is what the
    Reconcile screen is trying to drive to zero.
    """

    __tablename__ = "bank_account"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                                    # "Business Bank Account"
    account_number: Optional[str] = None         # "090-8007-006543"
    bank_name: Optional[str] = None              # "Barclays"
    currency: str = Field(default="GBP")         # ISO 4217
    statement_balance: float = Field(default=0.0)   # what the bank shows
    ooo_balance: float = Field(default=0.0)         # what OOO shows (live ledger)
    last_imported_at: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: str = Field(default="")


class Invoice(SQLModel, table=True):
    """
    Sales invoice — money owed TO the company by a customer.
    Flips to PAID when its outstanding amount hits zero from matched
    statement lines.
    """

    __tablename__ = "invoice"

    id: Optional[int] = Field(default=None, primary_key=True)
    number: str = Field(index=True)              # "INV-0028"
    contact_id: Optional[int] = Field(default=None, foreign_key="contact.id", index=True)
    contact_name: str                            # snapshot at issue time
    reference: Optional[str] = None              # customer PO / external ref
    issue_date: str                              # ISO date
    due_date: Optional[str] = None
    subtotal: float = Field(default=0.0)
    tax_total: float = Field(default=0.0)
    total: float = Field(default=0.0)
    paid_amount: float = Field(default=0.0)      # sum of matched payments
    currency: str = Field(default="GBP")
    status: DocumentStatus = Field(default=DocumentStatus.DRAFT, index=True)
    notes: Optional[str] = None
    sent: bool = Field(default=False)            # emailed to customer?
    created_at: str = Field(default="")
    updated_at: str = Field(default="")


class InvoiceLine(SQLModel, table=True):
    """Single line item on a sales invoice."""

    __tablename__ = "invoice_line"

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoice.id", index=True)
    description: str
    quantity: float = Field(default=1.0)
    unit_price: float = Field(default=0.0)
    tax_rate: float = Field(default=0.0)         # 0.20 for 20% VAT
    line_total: float = Field(default=0.0)       # qty * unit_price (pre-tax)
    service_id: Optional[int] = Field(default=None, foreign_key="service_offered.id")


class Bill(SQLModel, table=True):
    """
    Purchase bill — money owed BY the company to a supplier.
    Mirror of Invoice but for accounts payable.
    """

    __tablename__ = "bill"

    id: Optional[int] = Field(default=None, primary_key=True)
    number: Optional[str] = None                 # supplier's bill number
    contact_id: Optional[int] = Field(default=None, foreign_key="contact.id", index=True)
    contact_name: str                            # supplier name snapshot
    reference: Optional[str] = None              # internal ref
    issue_date: str
    due_date: Optional[str] = None
    subtotal: float = Field(default=0.0)
    tax_total: float = Field(default=0.0)
    total: float = Field(default=0.0)
    paid_amount: float = Field(default=0.0)
    currency: str = Field(default="GBP")
    status: DocumentStatus = Field(default=DocumentStatus.DRAFT, index=True)
    notes: Optional[str] = None
    source_file_path: Optional[str] = None       # set if extracted from a PDF
    created_at: str = Field(default="")
    updated_at: str = Field(default="")


class BillLine(SQLModel, table=True):
    """Single line item on a purchase bill."""

    __tablename__ = "bill_line"

    id: Optional[int] = Field(default=None, primary_key=True)
    bill_id: int = Field(foreign_key="bill.id", index=True)
    description: str
    quantity: float = Field(default=1.0)
    unit_price: float = Field(default=0.0)
    tax_rate: float = Field(default=0.0)
    line_total: float = Field(default=0.0)
    account_code: Optional[str] = None           # GL account (e.g. "5000")


class JournalEntry(SQLModel, table=True):
    """
    Manual ledger entry created inline from the Reconcile screen's
    "Create" tab — when a bank line has no matching invoice or bill.
    The signed `amount` follows the convention: positive = money in,
    negative = money out (matches the bank line's direction).
    """

    __tablename__ = "journal_entry"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: str                                    # inherited from bank line
    contact_id: Optional[int] = Field(default=None, foreign_key="contact.id")
    contact_name: Optional[str] = None           # the "Who" field
    account_code: Optional[str] = None           # the "What" field
    description: str                             # the "Why" field
    amount: float                                # signed: + received, - spent
    tax_rate: float = Field(default=0.0)
    currency: str = Field(default="GBP")
    created_at: str = Field(default="")


class StatementLine(SQLModel, table=True):
    """
    One row per line on an imported bank statement. The left side of the
    reconcile split-pane. `status` tracks the reconciliation lifecycle;
    exactly one of `matched_invoice_id`, `matched_bill_id`,
    `matched_journal_id`, or `transfer_to_account_id` is populated once
    reconciled.

    `spent` and `received` are split (Xero convention) so the UI can
    show two columns without sign juggling.
    """

    __tablename__ = "statement_line"

    id: Optional[int] = Field(default=None, primary_key=True)
    bank_account_id: int = Field(foreign_key="bank_account.id", index=True)
    date: str                                    # ISO date
    description: str                             # raw bank text
    reference: Optional[str] = None              # cheque / external ref
    spent: float = Field(default=0.0)            # > 0 if money out
    received: float = Field(default=0.0)         # > 0 if money in
    balance_after: Optional[float] = None        # running balance per stmt
    status: StatementLineStatus = Field(default=StatementLineStatus.PENDING, index=True)

    # Reconciliation links (exactly one populated once status != PENDING)
    matched_invoice_id: Optional[int] = Field(default=None, foreign_key="invoice.id")
    matched_bill_id: Optional[int] = Field(default=None, foreign_key="bill.id")
    matched_journal_id: Optional[int] = Field(default=None, foreign_key="journal_entry.id")
    transfer_to_account_id: Optional[int] = Field(default=None, foreign_key="bank_account.id")

    # Meta
    discussion: Optional[str] = None             # note from "Discuss" tab
    suggested_score: Optional[float] = None      # auto-match confidence 0-1
    imported_at: str = Field(default="")
    reconciled_at: Optional[str] = None
