"""
Contact upsert — used by invoice/bill upload paths to auto-create contacts.

`upsert_contact(db, org_id, name, contact_type)` returns an existing Contact
in the org with a normalized name match, or creates a new one. The matching
function is identical to peakeaze's `_normalize_contact_name` so the two
systems agree on what counts as "the same contact" — important for the v2
peakeaze integration where pre-registered company_id mappings need a stable
name dedup function on the bank-recon side.

Normalization rules (lowercase, strip punctuation, collapse whitespace,
remove common suffixes Ltd/Limited/Inc/Co): two display names that map to
the same normalized form are treated as the same contact. First-seen wins
— we link to the older row rather than create a duplicate.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from memory.models import Contact


_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|inc|incorporated|llc|llp|plc|co|company|corp|corporation|gmbh|bv|sa|ag)\.?\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalize(name: str) -> str:
    """Lowercase + strip punctuation + drop common company suffixes + collapse whitespace."""
    if not name:
        return ""
    s = name.lower()
    s = _SUFFIX_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_contact(
    db: Session,
    org_id: int,
    name: str,
    contact_type: str = "supplier",
) -> Contact:
    """
    Find-or-create a Contact in `org_id` whose normalized name matches `name`.

    Returns the existing row if a normalized-name match is found within the org;
    otherwise creates a fresh Contact and returns it.

    `contact_type` is used only when creating — never overwrites an existing
    contact's type. (A vendor that becomes both a customer and a supplier
    stays whatever the user first classified it as; rare in practice.)

    Always commits and refreshes — caller can `contact.id` immediately.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("Contact name cannot be empty")

    target = _normalize(cleaned)

    # Cheap: pull all contacts for the org, compare normalized form in memory.
    # At realistic sizes (≪ 10k per org) this is faster than a fancy index.
    candidates = db.exec(select(Contact).where(Contact.org_id == org_id)).all()
    for c in candidates:
        if _normalize(c.full_name) == target:
            return c

    now = _now_iso()
    contact = Contact(
        org_id=org_id,
        full_name=cleaned,
        contact_type=contact_type,
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact
