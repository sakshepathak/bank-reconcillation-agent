"""
Vendor matcher orchestrator — runs the layered pipeline and returns ranked candidates.

Pipeline per bank description:
    Tier 1 — normalize bank desc and each invoice vendor
    Tier 4 — exact O(1) alias lookup; if hit, that's our canonical
    Tier 2 — composite lexical similarity (Jaro-W + token + partial)
    Tier 3 — embedding cosine, but ONLY for scores in the ambiguity zone
             [AMBIGUITY_LOW, AMBIGUITY_HIGH]. Outside that zone, lexical
             score is decisive — saves embedding compute on obvious matches
             and obvious non-matches.

Final score per candidate = max(alias_score, composite_score, embedding_score).
This is "ensemble max" — any strong signal wins, weak signals don't drag down.

Returns candidates sorted by score desc, filtered above `threshold`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .normalizer import canonicalize
from .similarity import similarity, ScoreBreakdown
from . import embedder


# Tunable thresholds. These will be re-calibrated on labelled holdout data,
# but the defaults are tuned for typical bank-statement vs invoice matching.

LEXICAL_LOCK_IN = 0.95   # composite ≥ this — we're done, skip embedding
EMBEDDING_FLOOR = 0.60   # embedding < this is treated as "no signal"
EMBEDDING_BLEND = 0.65   # weight on embedding when blending with lexical


@dataclass(frozen=True)
class Candidate:
    """One ranked invoice candidate for a bank description."""
    invoice_idx: int
    invoice_vendor: str
    score: float
    method: str                  # "alias-exact" | "canonical-exact" | "fuzzy" | "fuzzy+embed"
    breakdown: Optional[ScoreBreakdown] = None
    embedding_cosine: Optional[float] = None

    def explain(self) -> str:
        parts = [f"{self.score:.2f} via {self.method}"]
        if self.breakdown is not None:
            parts.append(str(self.breakdown))
        if self.embedding_cosine is not None:
            parts.append(f"emb={self.embedding_cosine:.2f}")
        return " | ".join(parts)


def find_matches(
    bank_desc: str,
    invoice_vendors: list[str],
    *,
    alias_map: Optional[dict[str, str]] = None,
    threshold: float = 0.70,
    use_embeddings: bool = True,
    top_k: int = 5,
) -> list[Candidate]:
    """
    Rank invoice vendors by similarity to a bank description.

    Args:
        bank_desc: raw bank statement description.
        invoice_vendors: list of canonical (already-extracted) invoice vendor strings.
        alias_map: optional dict of {lowercased_raw_desc → canonical_vendor},
                   typically loaded from the VendorAlias table.
        threshold: minimum composite score; candidates below this are dropped.
        use_embeddings: enable Tier 3 embedding compute (default True).
        top_k: at most this many candidates returned.

    Returns: Candidates sorted by score desc.
    """
    if not bank_desc or not invoice_vendors:
        return []

    # Tier 1: normalize everything once
    bank_norm = canonicalize(bank_desc)
    inv_norms = [canonicalize(v) for v in invoice_vendors]

    # Tier 4: alias DB lookup. If hit, that gives us a stronger canonical form.
    alias_canonical = None
    if alias_map:
        lookup = (bank_desc or "").strip().lower()
        alias_canonical = alias_map.get(lookup)
        if alias_canonical is None:
            # Also try the canonical form (lowercased) so re-canonicalizing aliases works
            alias_canonical = alias_map.get(bank_norm.canonical.lower())

    candidates: list[Candidate] = []
    for idx, inv in enumerate(inv_norms):
        # Skip empty invoice vendor entries
        if not inv.canonical:
            continue

        # If alias resolved and matches this invoice exactly, that's a direct hit
        if alias_canonical is not None:
            alias_canon_norm = canonicalize(alias_canonical).canonical
            if alias_canon_norm and alias_canon_norm == inv.canonical:
                candidates.append(Candidate(
                    invoice_idx=idx,
                    invoice_vendor=invoice_vendors[idx],
                    score=1.0,
                    method="alias-exact",
                ))
                continue

        # Tier 2: composite lexical similarity on canonicals
        breakdown = similarity(bank_norm.canonical, inv.canonical)
        composite = breakdown.composite

        # Locked in by strong lexical signal — skip embedding to save compute
        if composite >= LEXICAL_LOCK_IN:
            candidates.append(Candidate(
                invoice_idx=idx,
                invoice_vendor=invoice_vendors[idx],
                score=composite,
                method="canonical-exact" if composite >= 0.99 else "fuzzy",
                breakdown=breakdown,
            ))
            continue

        # Tier 3: embedding — try whenever lexical isn't already locked in.
        # The composite may be low because normalization missed a noisy token;
        # the embedding can still see semantic identity ("DAILYBEAN" ↔ "The Daily Bean").
        emb_cos: Optional[float] = None
        method = "fuzzy"
        final_score = composite
        if use_embeddings:
            emb_cos = embedder.cosine(bank_norm.canonical, inv.canonical)
            if emb_cos is not None and emb_cos >= EMBEDDING_FLOOR:
                # Ensemble max: any strong signal can rescue. We also blend
                # so semi-strong evidence from both metrics combines well.
                blended = EMBEDDING_BLEND * emb_cos + (1 - EMBEDDING_BLEND) * composite
                final_score = max(composite, emb_cos, blended)
                method = "fuzzy+embed"

        candidates.append(Candidate(
            invoice_idx=idx,
            invoice_vendor=invoice_vendors[idx],
            score=final_score,
            method=method,
            breakdown=breakdown,
            embedding_cosine=emb_cos,
        ))

    # Filter + sort + slice
    candidates = [c for c in candidates if c.score >= threshold]
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_k]


def best_match(
    bank_desc: str,
    invoice_vendors: list[str],
    *,
    alias_map: Optional[dict[str, str]] = None,
    threshold: float = 0.70,
    use_embeddings: bool = True,
) -> Optional[Candidate]:
    """Convenience: top candidate or None."""
    matches = find_matches(
        bank_desc, invoice_vendors,
        alias_map=alias_map, threshold=threshold,
        use_embeddings=use_embeddings, top_k=1,
    )
    return matches[0] if matches else None
