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
