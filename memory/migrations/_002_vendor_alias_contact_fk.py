"""
Migration 002 — add nullable `contact_id INTEGER` to `vendor_alias` and
backfill it by matching each alias's `canonical_name` against the
Contact table within the same `org_id`.

Idempotent. Safe to re-run.

Backfill semantics:
  • For each vendor_alias row, normalize its canonical_name and look for
    a Contact in the SAME org whose normalized full_name matches.
  • On match: set vendor_alias.contact_id = that contact's id.
  • On no match: leave contact_id NULL — the user can wire it up later
    from the Contact detail page, or a future upload that creates the
    contact will not retroactively backfill (deferred to a later cleanup).

The normalization used here is the same logic as `engine.contacts._normalize`
— if those drift apart, aliases and uploads will disagree on dedup, so
they SHOULD stay in sync. They're duplicated here intentionally rather
than imported: migration scripts should not import application code that
might be refactored away later (the migration must keep working forever).
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

NAME = "002_vendor_alias_contact_fk"
DESCRIPTION = "Add nullable contact_id to vendor_alias; backfill via normalized canonical_name match within org"


# Mirror of engine.contacts._normalize. Kept duplicated for migration stability.
_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|inc|incorporated|llc|llp|plc|co|company|corp|corporation|gmbh|bv|sa|ag)\.?\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalize(name: str) -> str:
    if not name:
        return ""
    s = name.lower()
    s = _SUFFIX_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def up(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "vendor_alias"):
        return {"skipped": "vendor_alias table missing"}

    column_added = False
    if not _column_exists(conn, "vendor_alias", "contact_id"):
        conn.execute("ALTER TABLE vendor_alias ADD COLUMN contact_id INTEGER")
        column_added = True

    # Index — speeds up "find aliases for contact X" on the Contact detail page.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vendor_alias_contact_id ON vendor_alias(contact_id)"
    )

    # ── Backfill ─────────────────────────────────────────────────────────────
    # Build a per-org map: normalized_name → contact_id (first wins).
    contacts_by_org: dict[int, dict[str, int]] = {}
    if _table_exists(conn, "contact"):
        cur = conn.execute("SELECT id, org_id, full_name FROM contact")
        for row in cur.fetchall():
            contact_id, org_id, full_name = row
            if org_id is None:
                continue
            key = _normalize(full_name or "")
            if not key:
                continue
            org_map = contacts_by_org.setdefault(org_id, {})
            # First-seen wins — preserves the same rule the runtime upsert uses.
            org_map.setdefault(key, contact_id)

    # Walk every alias with NULL contact_id, try to resolve.
    updated = 0
    no_match = 0
    null_org = 0
    # If the schema doesn't carry canonical_name (only happens on bare stub
    # tables in migration tests — production always has it), skip the backfill.
    if not _column_exists(conn, "vendor_alias", "canonical_name"):
        return {
            "column_added": column_added,
            "aliases_linked": 0,
            "aliases_no_contact_match": 0,
            "aliases_skipped_null_org": 0,
            "total_aliases_processed": 0,
            "note": "vendor_alias.canonical_name missing — backfill skipped",
        }
    cur = conn.execute(
        "SELECT id, org_id, canonical_name FROM vendor_alias WHERE contact_id IS NULL"
    )
    rows = cur.fetchall()
    for alias_id, alias_org_id, canonical_name in rows:
        if alias_org_id is None:
            null_org += 1
            continue
        key = _normalize(canonical_name or "")
        target = contacts_by_org.get(alias_org_id, {}).get(key)
        if target is None:
            no_match += 1
            continue
        conn.execute(
            "UPDATE vendor_alias SET contact_id = ? WHERE id = ?",
            (target, alias_id),
        )
        updated += 1

    return {
        "column_added": column_added,
        "aliases_linked": updated,
        "aliases_no_contact_match": no_match,
        "aliases_skipped_null_org": null_org,
        "total_aliases_processed": len(rows),
    }
