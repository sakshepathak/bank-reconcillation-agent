"""
Composite similarity scoring — Tier 2 of the vendor matching pipeline.

Why composite, not one metric:
  - Jaro-Winkler weights matching prefixes heavily ("STRIPE" vs "Stripe Inc")
  - token_set_ratio handles word reordering ("Amazon Inc" vs "Inc Amazon")
  - token_sort_ratio is sensitive to order, useful for distinguishing similar names
  - partial_ratio catches substring matches ("AMZN" vs "Amazon")

Each metric has a specific failure mode. Combining them with calibrated weights
gives a robust signal that no single metric can match.

Final score = weighted average over the 4 metrics, in [0, 1].
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, distance


# Weights tuned for vendor-name matching specifically.
# Sum to 1.0.
_WEIGHTS = {
    "jaro_winkler": 0.35,    # Prefix-favouring — vendor names usually share start
    "token_set": 0.25,       # Word-reorder tolerant
    "token_sort": 0.15,      # Word-order sensitive (some discriminative power)
    "partial": 0.25,         # Substring-friendly — useful for abbreviations
}
assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9


@dataclass(frozen=True)
class ScoreBreakdown:
    """Per-metric scores + composite. All values in [0, 1]."""
    composite: float
    jaro_winkler: float
    token_set: float
    token_sort: float
    partial: float

    def __str__(self) -> str:
        return (
            f"{self.composite:.2f} "
            f"(jw={self.jaro_winkler:.2f} ts={self.token_set:.2f} "
            f"tort={self.token_sort:.2f} part={self.partial:.2f})"
        )


def similarity(a: str, b: str) -> ScoreBreakdown:
    """
    Composite similarity in [0, 1]. Higher = more similar.

    Inputs should be canonicalized strings (lowercase or uppercase, normalized
    whitespace) for best results — see normalizer.canonicalize().
    """
    if not a or not b:
        return ScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)

    # rapidfuzz scores are 0-100; normalize to 0-1
    jw = distance.JaroWinkler.normalized_similarity(a, b)
    ts = fuzz.token_set_ratio(a, b) / 100.0
    tort = fuzz.token_sort_ratio(a, b) / 100.0
    part = fuzz.partial_ratio(a, b) / 100.0

    composite = (
        _WEIGHTS["jaro_winkler"] * jw
        + _WEIGHTS["token_set"] * ts
        + _WEIGHTS["token_sort"] * tort
        + _WEIGHTS["partial"] * part
    )

    return ScoreBreakdown(
        composite=composite,
        jaro_winkler=jw,
        token_set=ts,
        token_sort=tort,
        partial=part,
    )
