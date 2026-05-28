"""
Migration runner — discover, apply, and record DB migrations.

Migration files in this package match `_NNN_description.py` and expose:
    NAME: str          # stable id, recorded in migration_history
    DESCRIPTION: str   # one-line summary for logs
    def up(conn) -> dict   # idempotent — apply schema changes, return a summary

The runner:
  1. Ensures the `migration_history` table exists.
  2. Walks all migration files in numeric order.
  3. Skips those already recorded as applied.
  4. Wraps each remaining migration in a single transaction:
       BEGIN; <up()>; INSERT INTO history; COMMIT;
     Failure → ROLLBACK and bail.
"""
from __future__ import annotations

import importlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ensure_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_history (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT,
            details TEXT
        )
        """
    )


def _is_applied(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM migration_history WHERE name = ?", (name,)
    ).fetchone() is not None


def _record(conn: sqlite3.Connection, name: str, description: str, details: str) -> None:
    conn.execute(
        "INSERT INTO migration_history (name, applied_at, description, details) "
        "VALUES (?, ?, ?, ?)",
        (name, datetime.now(timezone.utc).isoformat(), description, details),
    )


def _discover() -> list[Path]:
    """All migration files in numeric order: _001_foo.py, _002_bar.py, ..."""
    here = Path(__file__).parent
    return sorted(p for p in here.glob("_[0-9][0-9][0-9]_*.py"))


def apply_pending(db_path: str) -> dict[str, Any]:
    """
    Apply every migration not yet recorded. Returns a summary dict:
      {
        "applied":  [ {"name": "...", "description": "...", "details": {...} }, ... ],
        "skipped":  [ {"name": "...", "description": "..."}, ... ],
      }
    On failure, raises — the current transaction is rolled back and any
    earlier migrations in the same call have already been committed.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    # Use manual transaction control so each migration is its own commit point.
    conn.isolation_level = None

    try:
        _ensure_history_table(conn)
        conn.commit()

        applied: list[dict] = []
        skipped: list[dict] = []

        for path in _discover():
            module_name = f"memory.migrations.{path.stem}"
            mod = importlib.import_module(module_name)
            name: str = getattr(mod, "NAME", path.stem)
            description: str = getattr(mod, "DESCRIPTION", "")

            if _is_applied(conn, name):
                skipped.append({"name": name, "description": description})
                continue

            conn.execute("BEGIN")
            try:
                details = mod.up(conn)
                _record(conn, name, description, str(details))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            applied.append({"name": name, "description": description, "details": details})

        return {"applied": applied, "skipped": skipped}
    finally:
        conn.close()
