"""
Tests for the migration runner.

Covers:
  - Applying pending migrations on a freshly-init'd DB (latest schema via
    SQLModel.create_all) — should be a no-op for columns, may still backfill.
  - Applying against a DB simulating "old schema" (org_id columns missing)
    — should add columns and backfill correctly.
  - Idempotency: running twice doesn't duplicate or error.
  - migration_history is populated.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing

import pytest
from sqlmodel import Session, SQLModel, create_engine

import memory.models  # registers all models on metadata
from memory.migrations._001_add_org_id import TARGET_TABLES
from memory.migrations._runner import apply_pending


# ── Helpers ──────────────────────────────────────────────────────────────────

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _create_fresh_db_with_current_schema() -> str:
    """A file-based SQLite DB with the latest schema (via SQLModel.create_all).
    Returns the file path; caller is responsible for deletion."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    return path


def _create_old_schema_db() -> str:
    """A file-based SQLite DB simulating the pre-Step-4 schema:
    - business tables exist but DO NOT have an `org_id` column
    - `organization`/`user`/etc. exist (Step 1 done)
    - 1 org row exists (Step 2 done)
    - a couple of contact/bill/invoice rows pre-exist (need backfilling)
    Returns the file path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    try:
        # Step-1 tables (subset that's relevant)
        conn.executescript(
            """
            CREATE TABLE organization (
                id INTEGER PRIMARY KEY, name TEXT, currency TEXT, created_at TEXT
            );
            INSERT INTO organization (id, name, currency, created_at)
                VALUES (1, 'MyDemoBiz', 'GBP', '2026-05-27T00:00:00+00:00');

            -- Business tables WITHOUT org_id (the pre-migration shape).
            CREATE TABLE contact (
                id INTEGER PRIMARY KEY, full_name TEXT, created_at TEXT, updated_at TEXT
            );
            INSERT INTO contact (id, full_name, created_at, updated_at)
                VALUES (1, 'Acme Ltd', '2026-01-01', '2026-01-01'),
                       (2, 'Beta Inc', '2026-01-02', '2026-01-02');

            CREATE TABLE bill (
                id INTEGER PRIMARY KEY, contact_name TEXT, issue_date TEXT,
                total REAL, created_at TEXT, updated_at TEXT
            );
            INSERT INTO bill (id, contact_name, issue_date, total, created_at, updated_at)
                VALUES (1, 'Acme Ltd', '2026-02-01', 100.0, '2026-02-01', '2026-02-01');

            CREATE TABLE invoice (
                id INTEGER PRIMARY KEY, number TEXT, contact_name TEXT,
                issue_date TEXT, created_at TEXT, updated_at TEXT
            );
            INSERT INTO invoice (id, number, contact_name, issue_date, created_at, updated_at)
                VALUES (1, 'INV-001', 'Customer A', '2026-02-01', '2026-02-01', '2026-02-01');
            """
        )
        # Fill out the remaining target tables empty so the migration touches them.
        for t in TARGET_TABLES:
            if t in ("contact", "bill", "invoice"):
                continue
            # Minimal column for each — just enough that ALTER ADD COLUMN works.
            conn.execute(f"CREATE TABLE {t} (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    return path


# ── Tests ────────────────────────────────────────────────────────────────────

def _by_name(applied: list[dict]) -> dict[str, dict]:
    return {a["name"]: a for a in applied}


def test_runner_no_op_on_fresh_schema_records_history():
    """A freshly-init'd DB already has org_id columns + contact_id on vendor_alias.
    Both migrations should detect the existing schema, skip the ALTERs, and
    still record themselves in history."""
    path = _create_fresh_db_with_current_schema()
    try:
        result = apply_pending(path)
        applied = _by_name(result["applied"])
        assert "001_add_org_id_to_business_tables" in applied
        assert "002_vendor_alias_contact_fk" in applied

        details = applied["001_add_org_id_to_business_tables"]["details"]
        # No columns added (already present), no rows backfilled (empty DB).
        assert details["columns_added"] == []
        assert set(details["columns_already_present"]) >= set(TARGET_TABLES)
        assert details["rows_backfilled"] == {}

        # Migration 002 also no-ops on a fresh schema (contact_id already there).
        details_002 = applied["002_vendor_alias_contact_fk"]["details"]
        assert details_002["column_added"] is False
        assert details_002["total_aliases_processed"] == 0

        with closing(sqlite3.connect(path)) as conn:
            # All target tables have org_id
            for t in TARGET_TABLES:
                assert _column_exists(conn, t, "org_id"), f"missing org_id on {t}"
            # vendor_alias has contact_id
            assert _column_exists(conn, "vendor_alias", "contact_id")
            # migration_history is populated
            rows = {r[0] for r in conn.execute("SELECT name FROM migration_history")}
            assert "001_add_org_id_to_business_tables" in rows
            assert "002_vendor_alias_contact_fk" in rows
    finally:
        os.unlink(path)


def test_runner_idempotent_when_run_twice():
    path = _create_fresh_db_with_current_schema()
    try:
        first = apply_pending(path)
        assert len(first["applied"]) == 2
        second = apply_pending(path)
        assert len(second["applied"]) == 0
        assert len(second["skipped"]) == 2
    finally:
        os.unlink(path)


def test_runner_adds_columns_and_backfills_old_schema():
    """The real scenario: DB pre-dates Step 4 (no org_id columns, real rows)."""
    path = _create_old_schema_db()
    try:
        result = apply_pending(path)
        details = result["applied"][0]["details"]

        # Three target tables had real schema and got org_id added.
        # The other 10 are bare stubs we created — they get org_id added too.
        assert set(details["columns_added"]) == set(TARGET_TABLES)
        assert details["columns_already_present"] == []
        # Only contact (2 rows), bill (1), invoice (1) had pre-existing rows.
        assert details["rows_backfilled"] == {"contact": 2, "bill": 1, "invoice": 1}

        # Verify the actual data is now scoped to org 1.
        with closing(sqlite3.connect(path)) as conn:
            rows = list(conn.execute("SELECT id, org_id FROM contact ORDER BY id"))
            assert rows == [(1, 1), (2, 1)]
            assert list(conn.execute("SELECT id, org_id FROM bill")) == [(1, 1)]
            assert list(conn.execute("SELECT id, org_id FROM invoice")) == [(1, 1)]
    finally:
        os.unlink(path)


def test_runner_creates_indices():
    """Per-org list endpoints need an index on org_id for the hot tables."""
    path = _create_fresh_db_with_current_schema()
    try:
        apply_pending(path)
        with closing(sqlite3.connect(path)) as conn:
            indices = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )]
            assert "idx_contact_org_id" in indices
            assert "idx_invoice_org_id" in indices
            assert "idx_bill_org_id" in indices
    finally:
        os.unlink(path)
