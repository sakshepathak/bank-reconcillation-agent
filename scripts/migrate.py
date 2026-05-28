"""
Apply pending DB migrations.

Usage:
    py -3.13 scripts/migrate.py

Steps it performs:
  1. Resolve the SQLite DB path from settings.DATABASE_URL.
  2. Make a timestamped backup of the DB file.
  3. Call the migration runner to apply every pending migration.
  4. Print a clear summary of what ran / what was skipped.
  5. On failure: print the path of the backup so it can be restored.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone

# Project root onto sys.path so the imports below resolve.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config.settings import settings
from memory.migrations._runner import apply_pending


def _resolve_db_path() -> str:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite:///"):
        raise SystemExit(
            f"This script only supports SQLite. Got DATABASE_URL={url!r}."
        )
    raw = url[len("sqlite:///") :]
    if raw.startswith("./"):
        raw = raw[2:]
    # Allow absolute paths through unchanged; normalise relative ones.
    return raw if os.path.isabs(raw) else os.path.join(_ROOT, raw)


def main() -> int:
    db_path = _resolve_db_path()
    if not os.path.exists(db_path):
        print(f"ERROR: DB file not found at {db_path}")
        print("Hint: start the app once so init_db creates it, then re-run.")
        return 2

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = f"{db_path}.backup-{ts}-pre-migrate"
    shutil.copy2(db_path, backup)
    print(f"Backup created: {backup}")

    try:
        result = apply_pending(db_path)
    except Exception as e:  # noqa: BLE001
        print()
        print(f"MIGRATION FAILED: {e}")
        print(f"Restore from backup with:")
        print(f"    Copy-Item '{backup}' '{db_path}' -Force")
        return 3

    print()
    if result["skipped"]:
        print(f"Already applied ({len(result['skipped'])}):")
        for s in result["skipped"]:
            print(f"  - {s['name']}: {s['description']}")
    if result["applied"]:
        print(f"Newly applied ({len(result['applied'])}):")
        for s in result["applied"]:
            print(f"  - {s['name']}: {s['description']}")
            details = s.get("details") or {}
            if isinstance(details, dict):
                if details.get("columns_added"):
                    print(f"      columns_added: {details['columns_added']}")
                if details.get("columns_already_present"):
                    print(f"      columns_already_present: {details['columns_already_present']}")
                if details.get("rows_backfilled"):
                    print(f"      rows_backfilled: {details['rows_backfilled']}")
                if details.get("skipped_tables_missing"):
                    print(f"      skipped_tables_missing: {details['skipped_tables_missing']}")
    else:
        print("No new migrations applied (DB is already up to date).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
