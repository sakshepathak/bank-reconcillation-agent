"""
One-off data hygiene: link orphaned credits to their contact.

Prepayments booked before the fix were saved with contact_id=None (only a typed
contact_name). The allocation logic now falls back to a normalized-name match, so
those credits already work — this script just tidies the data by stamping the
real contact_id onto each orphan, so the row is consistent with how new credits
are booked.

Conservative by design: it only LINKS a credit to a Contact that already exists
in the same org with a matching normalized name. It never creates a contact and
never overwrites a non-null contact_id. Safe to run repeatedly (idempotent).

Usage (from the repo root, project venv active):
    python scripts/backfill_credit_contacts.py            # dry-run: report only
    python scripts/backfill_credit_contacts.py --apply     # write the changes
"""
import os
import sys
from datetime import datetime, timezone

# Running `python scripts/foo.py` puts scripts/ on sys.path, not the repo root —
# add the root so the `memory`/`engine` packages import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import select

from memory.db import get_session, init_db
from memory.models import CreditNote, Contact
from engine.contacts import _normalize


def main(apply: bool) -> int:
    init_db()
    fixed, skipped = 0, 0
    with get_session() as db:
        orphans = [
            cn for cn in db.exec(select(CreditNote)).all()
            if cn.contact_id is None
            and (cn.contact_name or "").strip() not in ("", "—")
        ]
        if not orphans:
            print("No orphaned credits (all credits already have a contact_id). Nothing to do.")
            return 0

        # Index contacts by (org_id, normalized name) for a cheap lookup.
        by_key: dict[tuple[int, str], Contact] = {}
        for c in db.exec(select(Contact)).all():
            by_key.setdefault((c.org_id, _normalize(c.full_name)), c)

        for cn in orphans:
            match = by_key.get((cn.org_id, _normalize(cn.contact_name)))
            if not match:
                print(f"  SKIP credit#{cn.id} org={cn.org_id} name={cn.contact_name!r} "
                      f"— no existing contact with that name")
                skipped += 1
                continue
            print(f"  {'LINK' if apply else 'WOULD LINK'} credit#{cn.id} "
                  f"({cn.contact_name!r}) -> contact#{match.id}")
            if apply:
                cn.contact_id = match.id
                cn.updated_at = datetime.now(timezone.utc).isoformat()
                db.add(cn)
            fixed += 1

        if not apply:
            # Don't persist on a dry run.
            db.rollback()

    verb = "Linked" if apply else "Would link"
    print(f"\n{verb} {fixed} credit(s); skipped {skipped} (no matching contact).")
    if not apply and fixed:
        print("Re-run with --apply to write these changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
