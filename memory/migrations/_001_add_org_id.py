"""
Migration 001 — add nullable `org_id INTEGER` to every business-data table
and backfill all existing rows to org_id=1 (the first organization created
by `scripts/create_first_user.py`).

This migration is idempotent — it checks for existing columns and only
adds what's missing. Safe to re-run.

NOT NULL is NOT enforced here. That comes in a much later migration (Step 10
of the implementation plan), after Step 5 has wired org_id scoping on every
endpoint so we know we never insert NULL by accident.
"""
from __future__ import annotations

import sqlite3
from typing import Any

NAME = "001_add_org_id_to_business_tables"
DESCRIPTION = "Add nullable org_id to business tables; backfill existing rows to org 1"

# Order matters cosmetically (logs read cleaner) but isn't semantically
# significant — each ALTER is independent.
TARGET_TABLES: tuple[str, ...] = (
    "contact",
    "vendor_alias",
    "bank_account",
    "statement_line",
    "invoice",
    "invoice_line",
    "bill",
    "bill_line",
    "journal_entry",
    "service_offered",
    "match_record",
    "extracted_invoice",
    "manual_ledger_entry",
)

# A subset that we want indexed by org_id for the hot paths in the matching
# engine and the per-org list endpoints. Others can be indexed later if perf
# data shows it's worth it.
INDEX_TABLES: tuple[str, ...] = (
    "contact",
    "invoice",
    "bill",
    "bank_account",
    "statement_line",
    "vendor_alias",
    "match_record",
    "extracted_invoice",
)

DEFAULT_ORG_ID = 1


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def up(conn: sqlite3.Connection) -> dict[str, Any]:
    """Idempotent — re-running this against an already-migrated DB is a no-op."""
    columns_added: list[str] = []
    columns_already_present: list[str] = []
    rows_backfilled: dict[str, int] = {}
    skipped_tables: list[str] = []

    # 1) Add column (only if missing) and backfill nulls.
    for table in TARGET_TABLES:
        if not _table_exists(conn, table):
            # Tolerate missing tables — happens on partial / customised installs.
            skipped_tables.append(table)
            continue
        if _column_exists(conn, table, "org_id"):
            columns_already_present.append(table)
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN org_id INTEGER")
            columns_added.append(table)
        # Backfill — runs whether the column was just added or already existed.
        # rowcount = number of rows that actually had NULL org_id before this.
        cur = conn.execute(
            f"UPDATE {table} SET org_id = ? WHERE org_id IS NULL",
            (DEFAULT_ORG_ID,),
        )
        if cur.rowcount > 0:
            rows_backfilled[table] = cur.rowcount

    # 2) Indices (IF NOT EXISTS makes them safe to re-run).
    for table in INDEX_TABLES:
        if _table_exists(conn, table):
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_org_id ON {table}(org_id)"
            )

    return {
        "columns_added": columns_added,
        "columns_already_present": columns_already_present,
        "rows_backfilled": rows_backfilled,
        "skipped_tables_missing": skipped_tables,
    }
