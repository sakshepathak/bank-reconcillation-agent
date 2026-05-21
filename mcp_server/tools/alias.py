"""
Vendor Alias Tool — the Self-Learning KB for vendor name normalisation.

Handles the core "AMZN MKTPL → Amazon" problem in bank reconciliation.

Two operations:
  lookup_vendor: check if a raw description maps to a known canonical name.
  store_alias:   persist a new mapping (human correction or agent discovery).

Lookup strategy (in order):
  1. Exact match (after normalisation) — O(1).
  2. Fuzzy match (token_set_ratio) — catches typos and prefix changes.
  3. Return None if below confidence threshold.

This module is a pure DB wrapper — no LLM calls here.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timezone
from typing import Optional

from rapidfuzz import fuzz
from sqlmodel import select

from memory.db import get_session
from memory.models import VendorAlias

# Minimum score for fuzzy fallback (0–100)
_FUZZY_FLOOR = 85


def _normalise(text: str) -> str:
    """Lower-case + strip for consistent storage and lookup."""
    return text.strip().lower()


def lookup_vendor(raw_description: str) -> Optional[str]:
    """
    Look up the canonical vendor name for a raw bank-statement description.

    Returns the canonical name string if found, else None.
    Tries exact match first, then fuzzy fallback.
    """
    key = _normalise(raw_description)

    with get_session() as session:
        # 1 — exact match
        stmt = select(VendorAlias).where(VendorAlias.alias == key)
        alias = session.exec(stmt).first()
        if alias:
            return alias.canonical_name

        # 2 — fuzzy fallback: load all aliases and score in-memory.
        # For large alias tables (>10k), this should move to a trigram index.
        all_aliases = session.exec(select(VendorAlias)).all()

    if not all_aliases:
        return None

    best_score = 0
    best_name: Optional[str] = None
    for row in all_aliases:
        score = fuzz.token_set_ratio(key, row.alias)
        if score > best_score:
            best_score = score
            best_name = row.canonical_name

    return best_name if best_score >= _FUZZY_FLOOR else None


def store_alias(
    raw_description: str,
    canonical_name: str,
    source: str = "human",
    confidence: float = 1.0,
) -> dict:
    """
    Persist a vendor alias mapping.

    Idempotent: if the same alias already exists, updates the canonical name
    and resets confidence (e.g., a human can correct an earlier agent mapping).

    Args:
        raw_description: The messy bank-statement string.
        canonical_name:  The clean, canonical vendor name.
        source:          "human" or "agent".
        confidence:      0.0–1.0. Human corrections default to 1.0.

    Returns:
        Dict summarising the stored/updated record.
    """
    key = _normalise(raw_description)

    with get_session() as session:
        stmt = select(VendorAlias).where(VendorAlias.alias == key)
        existing = session.exec(stmt).first()

        if existing:
            existing.canonical_name = canonical_name
            existing.confidence = confidence
            existing.source = source
            existing.created_at = datetime.now(timezone.utc).isoformat()
            session.add(existing)
            action = "updated"
        else:
            new_alias = VendorAlias(
                alias=key,
                canonical_name=canonical_name,
                confidence=confidence,
                source=source,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(new_alias)
            action = "created"

    return {
        "action": action,
        "alias": key,
        "canonical_name": canonical_name,
        "source": source,
        "confidence": confidence,
    }


def list_aliases(limit: int = 50) -> list[dict]:
    """Return up to `limit` stored aliases (for debugging / admin views)."""
    with get_session() as session:
        aliases = session.exec(select(VendorAlias).limit(limit)).all()
    return [
        {
            "alias": a.alias,
            "canonical_name": a.canonical_name,
            "source": a.source,
            "confidence": a.confidence,
        }
        for a in aliases
    ]
