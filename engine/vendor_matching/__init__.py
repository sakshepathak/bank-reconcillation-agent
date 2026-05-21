"""
Vendor matching — entity-resolution layer for bank descriptions ↔ invoice vendors.

Public API:
    from engine.vendor_matching import find_matches, canonicalize, similarity

    candidates = find_matches(
        bank_desc="AMZN MKTPL *Z89K3KS",
        invoice_vendors=["Amazon.com, Inc.", "Stripe Inc"],
        alias_map=alias_lookup,
        threshold=0.7,
    )

Internally layered:
    Tier 1 — normalizer:   regex strip + Unicode NFKC + corp suffix
    Tier 2 — similarity:   composite of Jaro-Winkler / token-set / partial
    Tier 3 — embedder:     fastembed BGE-small cosine, gated by ambiguity zone
    Tier 4 — alias DB:     exact O(1) lookup, populated by user approvals

Everything is pure-function and deterministic. The embedder caches by name.
"""
from .normalizer import canonicalize, Normalized
from .similarity import similarity, ScoreBreakdown
from .matcher import find_matches, Candidate

__all__ = [
    "canonicalize", "Normalized",
    "similarity", "ScoreBreakdown",
    "find_matches", "Candidate",
]
