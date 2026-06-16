"""
Explainability layer — produces a step-by-step trace of HOW a single bank line
gets scored against one candidate invoice/bill.

This is the demo/teaching surface: it exposes every intermediate the matcher
computes (normalisation, alias lookup, the four lexical sub-scores, the
embedding cosine, the ensemble decision, the amount/date gates, the final
composite) so a human can watch the pipeline think.

It deliberately reuses the SAME functions the live pipeline uses — `canonicalize`,
`find_matches`, and the exact composite weighting from the `/suggestions`
endpoint — so the numbers it prints are identical to what the app actually
acted on. Nothing here re-implements scoring; it just surfaces it.

Pure function. No DB, no I/O. Callers (CLI, API) handle data loading + rendering.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .normalizer import canonicalize
from .similarity import _WEIGHTS
from .matcher import find_matches, resolve_alias, LEXICAL_LOCK_IN, EMBEDDING_FLOOR, EMBEDDING_BLEND
from ..reconcile_rules import score_date, cap_by_name, auto_match_ready


# Strength bands — kept in lockstep with the frontend's match.ts (HIGH/MID_HIGH/MID_LOW).
_HIGH, _MID_HIGH, _MID_LOW = 0.90, 0.75, 0.65


def _strength(score: float) -> tuple[str, str]:
    if score >= _HIGH:
        return "strong", "Strong match"
    if score >= _MID_HIGH:
        return "likely", "Likely match"
    if score >= _MID_LOW:
        return "possible", "Possible match"
    return "weak", "Weak match"


def _date_diff_days(a, b) -> Optional[int]:
    try:
        da = datetime.fromisoformat(str(a)[:10])
        db = datetime.fromisoformat(str(b)[:10])
        return abs((da - db).days)
    except (ValueError, TypeError):
        return None


def explain_candidate(
    *,
    bank_desc: str,
    bank_amount: float,
    bank_date: str,
    cand_label: str,
    cand_vendor: str,
    cand_amount: float,
    cand_date: str,
    cand_due_date: Optional[str] = None,
    same_currency: bool = True,
    learned_window: Optional[int] = None,
    alias_map: Optional[dict[str, str]] = None,
) -> dict:
    """
    Return a structured, ordered trace of scoring one bank line vs one candidate.

    The shape is JSON-serialisable so the API can return it verbatim and the CLI
    can pretty-print it. `steps` is an ordered list; each has `n`, `title`, and
    step-specific fields. The top-level `final` block carries the headline numbers.
    """
    alias_map = alias_map or {}

    # ── Step 1: normalisation ────────────────────────────────────────────────
    bank_norm = canonicalize(bank_desc)
    cand_norm = canonicalize(cand_vendor)

    # ── Step 2: alias lookup (Tier 4) — exact + substring, same as the matcher ─
    alias_canonical = resolve_alias(bank_desc, bank_norm.canonical, alias_map)
    alias_hit = alias_canonical is not None

    # ── Steps 3–5: run the REAL matcher for this one candidate ────────────────
    # find_matches returns the breakdown, embedding cosine, method and final
    # name-score — exactly what the live pipeline used. threshold=0 so we always
    # get the candidate back even on a weak match (we're explaining, not filtering).
    cands = find_matches(
        bank_desc, [cand_vendor],
        alias_map=alias_map, threshold=0.0, top_k=1, use_embeddings=True,
    )
    cand = cands[0] if cands else None
    name_raw = float(cand.score) if cand else 0.0
    method = cand.method if cand else "no-name"
    bd = cand.breakdown if cand else None
    emb_cos = cand.embedding_cosine if cand else None
    embedding_fired = bd is not None and bd.composite < LEXICAL_LOCK_IN

    # ── Step 6: composite score (mirrors /suggestions exactly) ───────────────
    amt = float(bank_amount)
    out_amt = float(cand_amount)
    amount_diff = abs(amt - out_amt)
    rel = amount_diff / max(abs(amt), 0.01)
    if amount_diff < 0.01:
        amount_component, amount_reason = 0.5, "exact amount"
    elif rel < 0.01:
        amount_component, amount_reason = 0.4, f"≈ amount (Δ{amount_diff:.2f})"
    elif rel < 0.05:
        amount_component, amount_reason = 0.25, f"amount off by {amount_diff:.2f}"
    else:
        amount_component, amount_reason = 0.0, f"amount differs by {amount_diff:.2f}"

    # Asymmetric, terms-aware date rule (shared with /suggestions via reconcile_rules),
    # widened by this vendor's learned payment window when one has been trained.
    date_component, date_reason = score_date(
        bank_date, cand_date, cand_due_date, learned_window=learned_window
    )
    dd = _date_diff_days(bank_date, cand_date)

    name_component = round(name_raw * 0.3, 4)
    # Name similarity caps the label (shared with /suggestions via reconcile_rules):
    # amount + date alone can't push a wrong-vendor coincidence into a high band.
    total = round(cap_by_name(min(amount_component + date_component + name_component, 1.0), name_raw), 4)
    strength, strength_label = _strength(total)

    # Per-candidate readiness for hands-off auto-reconcile. Uniqueness (only one
    # such candidate) and pending-status are enforced by the live endpoint, not here.
    ready = auto_match_ready(
        amount_exact=amount_diff < 0.01,
        name_method=method,
        date_component=date_component,
        same_currency=same_currency,
    )

    # ── Assemble the ordered trace ───────────────────────────────────────────
    steps = [
        {
            "n": 1,
            "title": "Normalise both names",
            "detail": "Strip processor prefixes, bank noise, txn IDs, suffixes; uppercase + collapse.",
            "bank_raw": bank_desc,
            "bank_canonical": bank_norm.canonical,
            "candidate_raw": cand_vendor,
            "candidate_canonical": cand_norm.canonical,
        },
        {
            "n": 2,
            "title": "Alias lookup (learned)",
            "detail": "Exact O(1) hit from the VendorAlias table the user has trained.",
            "hit": alias_hit,
            "resolved_to": alias_canonical,
        },
        {
            "n": 3,
            "title": "Lexical similarity",
            "detail": "Weighted blend of four RapidFuzz / Jaro-Winkler metrics on the canonicals.",
            "metrics": (
                {
                    "jaro_winkler": round(bd.jaro_winkler, 4),
                    "token_set": round(bd.token_set, 4),
                    "token_sort": round(bd.token_sort, 4),
                    "partial": round(bd.partial, 4),
                }
                if bd else None
            ),
            "weights": dict(_WEIGHTS),
            "composite": round(bd.composite, 4) if bd else 0.0,
        },
        {
            "n": 4,
            "title": "Embedding (semantic) fallback",
            "detail": "Only fires when lexical isn't locked in (composite < 0.95). "
                      "BGE-small vector cosine catches meaning that spelling misses.",
            "fired": embedding_fired,
            "cosine": round(emb_cos, 4) if emb_cos is not None else None,
            "floor": EMBEDDING_FLOOR,
            "blend_weight": EMBEDDING_BLEND,
        },
        {
            "n": 5,
            "title": "Ensemble — best signal wins",
            "detail": "Final name score = max(alias, lexical, embedding, blend). Method records which won.",
            "name_score": round(name_raw, 4),
            "method": method,
        },
        {
            "n": 6,
            "title": "Composite match score",
            "detail": "amount (max 0.50) + date (max 0.20) + name×0.30 — the score shown in the app.",
            "amount_component": amount_component,
            "amount_reason": amount_reason,
            "amount_diff": round(amount_diff, 2),
            "date_component": date_component,
            "date_reason": date_reason,
            "date_diff_days": dd,
            "name_component": name_component,
            "name_raw": round(name_raw, 4),
            "total": total,
        },
        {
            "n": 7,
            "title": "Verdict",
            "detail": "Band the composite into a strength label; ≥0.90 is auto-approve quality. "
                      "Hands-off auto-reconcile needs more: exact amount, a KNOWN vendor "
                      "(alias/exact name, not a guess), an in-window date, same currency — "
                      "and that it's the only such candidate (checked when matching).",
            "strength": strength,
            "label": strength_label,
            "auto_approve_quality": total >= _HIGH,
            "auto_match_ready": ready,
            "needs_human_review": total < _HIGH,
        },
    ]

    return {
        "input": {
            "bank_description": bank_desc,
            "bank_amount": amt,
            "bank_date": str(bank_date)[:10],
            "candidate_label": cand_label,
            "candidate_vendor": cand_vendor,
            "candidate_amount": out_amt,
            "candidate_date": str(cand_date)[:10],
        },
        "steps": steps,
        "final": {
            "score": total,
            "score_pct": round(total * 100),
            "method": method,
            "strength": strength,
            "strength_label": strength_label,
        },
    }
