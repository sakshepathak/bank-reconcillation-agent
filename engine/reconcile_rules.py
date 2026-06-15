"""
Composite-scoring rules for reconciliation, kept in ONE place so the live API
(`get_suggestions`) and the explainability trace (`explain_candidate`) always
agree on the numbers.

Today this module owns the DATE rule. The rule is deliberately *asymmetric*,
because in real bookkeeping a payment lands ON or AFTER the document is issued —
often days later, under the supplier's payment terms (net-7/15/30…). So:

  • Paying on/after the issue date, within terms (+ a grace period), is the NORMAL
    case and must NOT be penalised — it earns full date credit. Punishing a normal
    payment delay was suppressing correct matches and hurting auto-reconcile.
  • Paying BEFORE the document exists is a strong "this isn't the one" signal and
    earns no date credit. With date worth 0.20 of a 1.0 composite, that alone caps
    the score at 0.80 — below auto-approve quality — so such pairs are never
    auto-reconciled and always surface for a human.
  • Paying far beyond terms tapers off (late, then implausibly far apart).

When a due date is present we treat the window as issue→due (+grace); otherwise we
assume net-30, since invoices don't always carry explicit terms.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

# Date is worth at most this much of the 1.0 composite (amount 0.50 + date 0.20 + name 0.30).
DATE_MAX = 0.20

# Tunables — change here and BOTH the API and the explain trace move together.
_DEFAULT_TERMS_DAYS = 30   # assumed payment terms when no due date is given
_GRACE_DAYS = 14           # slightly-late but still clearly the payment
_LATE_TAPER_DAYS = 60      # "late" band beyond terms+grace
_BEFORE_TOLERANCE = 2      # tiny allowance for clock skew / same-batch timing


def _parse(value) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        return None


def score_date(payment_date, issue_date, due_date=None) -> tuple[float, str]:
    """
    Score a payment date against the document it might settle.

    Returns (component in 0..DATE_MAX, short human reason). `delta` is the number
    of days the payment falls AFTER the issue date — negative means the payment
    predates the document.
    """
    pay = _parse(payment_date)
    iss = _parse(issue_date)
    if pay is None or iss is None:
        return 0.0, "date unknown"

    delta = (pay - iss).days

    # ── Paid before the document exists — suspicious ─────────────────────────
    if delta < 0:
        n = -delta
        if n <= _BEFORE_TOLERANCE:
            return 0.05, f"paid {n}d before issue"
        return 0.0, f"paid {n}d before issue — unusual"

    # ── Paid on/after issue — the normal case ────────────────────────────────
    due = _parse(due_date)
    terms = (due - iss).days if (due is not None and (due - iss).days >= 0) else _DEFAULT_TERMS_DAYS
    within = terms + _GRACE_DAYS

    if delta <= within:
        if delta == 0:
            return DATE_MAX, "same day"
        return DATE_MAX, f"{delta}d after — within terms"
    if delta <= within + _LATE_TAPER_DAYS:
        return 0.10, f"{delta}d after — late"
    if delta <= 365:
        return 0.05, f"{delta}d after"
    return 0.0, f"{delta}d apart — far"


# ════════════════════════════════════════════════════════════════════════════
# Name similarity gates the confidence LABEL
# ════════════════════════════════════════════════════════════════════════════
# A matching amount and date are not enough to call a match confident — the
# vendor NAME has to agree too. Otherwise an exact-amount, on-time coincidence
# with a *different* vendor reads as "Likely", which oversells it. So the name
# score sets the HIGHEST band a match may reach; amount + date then place it
# within or below that ceiling:
#
#   • names clearly match  → may reach Strong
#   • names partly match   → at most Likely
#   • names barely match   → at most a low match (Possible/Weak)
#
# A genuinely-correct match with a dissimilar name is NOT lost — it still shows,
# ranked low, under "show more suggestions". The cap only stops the labels from
# overselling coincidences; it never raises a score.

# Confidence-band thresholds — kept in lockstep with the frontend (match.ts) and
# the explain trace (explain.py).
BAND_STRONG = 0.90
BAND_LIKELY = 0.75
BAND_POSSIBLE = 0.65

# How similar the vendor names must be (name score 0..1 from the matcher) to be
# allowed into each band.
NAME_FOR_STRONG = 0.80   # at/above → names clearly match
NAME_FOR_LIKELY = 0.50   # at/above → some similarity; below → low match only

# Ceilings sit just under the next band so a capped score lands in the band below.
_LIKELY_CEILING = round(BAND_STRONG - 0.01, 2)     # 0.89 — top of Likely
_POSSIBLE_CEILING = round(BAND_LIKELY - 0.01, 2)   # 0.74 — top of Possible


def cap_by_name(composite: float, name_raw: float) -> float:
    """
    Clamp the composite so the confidence label can't outrun the name agreement.

    `name_raw` is the 0..1 vendor-name score (1.0 = exact name / learned alias).
    Only ever LOWERS a score, never raises it.
    """
    if name_raw >= NAME_FOR_STRONG:
        return composite
    if name_raw >= NAME_FOR_LIKELY:
        return min(composite, _LIKELY_CEILING)
    return min(composite, _POSSIBLE_CEILING)


# ════════════════════════════════════════════════════════════════════════════
# Ambiguity — two candidates that look equally good
# ════════════════════════════════════════════════════════════════════════════
# Two open documents with the same amount + same vendor score almost identically.
# We must not silently treat one as confident: flag the tie so the UI can warn,
# and (below) so neither candidate qualifies for hands-off auto-reconcile.
AMBIGUITY_EPS = 0.02   # top scores within this of each other are "tied"


def is_ambiguous(top_score: float, runner_up_score: float) -> bool:
    """True when the two best candidates are tied near the top (both ≥ Likely)."""
    return (
        runner_up_score >= BAND_LIKELY
        and abs(top_score - runner_up_score) <= AMBIGUITY_EPS
    )


# ════════════════════════════════════════════════════════════════════════════
# Auto-reconcile gate (strict, multi-signal)
# ════════════════════════════════════════════════════════════════════════════
# A 1:1 match may be applied WITHOUT a human only when every signal is certain.
# This predicate is the per-candidate part; the caller additionally enforces
# UNIQUENESS (this is the only candidate that passes), that the line is still
# pending, and that it is a single document (not a split) — see
# statement_lines.get_suggestions.
_CERTAIN_NAME_METHODS = frozenset({"alias-exact", "canonical-exact"})


def auto_match_ready(
    *,
    amount_exact: bool,
    name_method: str,
    date_component: float,
    same_currency: bool,
) -> bool:
    """
    Whether THIS candidate's signals are certain enough to reconcile hands-off:

      • amount exact        (the 0.50 tier — not "≈", not "within 5%")
      • vendor KNOWN        (a learned alias or an exact name — never a fuzzy guess)
      • date within window  (full date credit from `score_date`)
      • same currency

    Uniqueness, pending-status and single-document are the caller's job.
    """
    return (
        bool(amount_exact)
        and name_method in _CERTAIN_NAME_METHODS
        and date_component >= DATE_MAX
        and bool(same_currency)
    )
