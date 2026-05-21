"""
Multi-level matching engine for Bank Reconciliation.

Matching cascade (applied in order, short-circuits on first match):
  Level 1 — Exact Match:     date == date AND amount == amount (to 2dp)
  Level 2 — Amount Fuzzy:    |amount_diff| <= tolerance AND date within window
  Level 3 — Description Fuzzy: token_set_ratio >= threshold AND amount match
  Level 4 — One-to-Many:    sum of split ledger rows == bank amount (e.g. fees)
  Unmatched: anything that cleared no level → flagged for human review

Design principles:
  - Pure functions only — no side effects. The MCP tool layer handles DB writes.
  - Every match result carries a `reasoning_path` string so the audit log is
    always populated regardless of which level matched.
  - All DataFrames are expected to have normalised column names (see _normalise).
    The calling tool is responsible for normalisation before calling these fns.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz

from config.settings import settings


# ── Data contract ─────────────────────────────────────────────────────────────

REQUIRED_BANK_COLS = {"txn_id", "date", "description", "amount"}
REQUIRED_LEDGER_COLS = {"txn_id", "date", "description", "amount"}


@dataclass
class MatchResult:
    """Result for a single bank transaction after cascade matching."""

    bank_txn_id: str
    ledger_txn_id: Optional[str]       # None = unmatched
    status: str                         # exact | fuzzy | one_to_many | many_to_one | possible | unmatched
    score: float                        # 0.0–1.0 confidence
    reasoning_path: str                 # human-readable chain of decisions
    amount_diff: Optional[float] = None
    date_diff_days: Optional[int] = None
    requires_human_review: bool = False
    matched_ledger_ids: list[str] = field(default_factory=list)  # Level 4: 1 bank → N invoices
    matched_bank_ids: list[str] = field(default_factory=list)    # Level 5: N bank → 1 invoice
    canonical_vendor: Optional[str] = None


@dataclass
class ReconciliationReport:
    """Aggregate result of one full reconciliation run."""

    run_id: str
    total_bank_rows: int
    total_ledger_rows: int
    exact_matches: int = 0
    fuzzy_matches: int = 0
    one_to_many_matches: int = 0
    many_to_one_matches: int = 0
    possible_matches: int = 0
    unmatched_bank: int = 0
    unmatched_ledger: int = 0
    match_results: list[MatchResult] = field(default_factory=list)

    @property
    def match_rate(self) -> float:
        matched = (
            self.exact_matches
            + self.fuzzy_matches
            + self.one_to_many_matches
            + self.many_to_one_matches
            + self.possible_matches
        )
        return matched / self.total_bank_rows if self.total_bank_rows else 0.0

    def summary_text(self) -> str:
        return (
            f"Run {self.run_id}: "
            f"{self.total_bank_rows} bank rows, "
            f"{self.total_ledger_rows} ledger rows. "
            f"Matched: {self.exact_matches} exact, "
            f"{self.fuzzy_matches} fuzzy, "
            f"{self.one_to_many_matches} one-to-many. "
            f"Unmatched bank: {self.unmatched_bank}, "
            f"Unmatched ledger: {self.unmatched_ledger}. "
            f"Match rate: {self.match_rate:.1%}"
        )


from mcp_server.tools.normalizer import DataNormalizer

# ── Normalisation helpers ─────────────────────────────────────────────────────

def normalise_df(df: pd.DataFrame, is_ledger: bool = True) -> pd.DataFrame:
    """
    Senior Data Engineer implementation. 
    Standardises a raw DataFrame into the Canonical Data Layer.
    """
    normalizer = DataNormalizer()
    if is_ledger:
        return normalizer.normalize_ledger(df)
    else:
        return normalizer.normalize_bank_statement(df)


def validate_df(df: pd.DataFrame, required: set[str], label: str) -> None:
    """
    Check for required columns after normalisation.
    """
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"{label} DataFrame is missing required columns: {missing}. "
            f"Available: {list(df.columns)}"
        )
    if df["date"].isna().any():
        raise ValueError(f"{label} has unparseable dates. Check the date column format.")
    if df["amount"].isna().any():
        raise ValueError(f"{label} has non-numeric amount values.")


# ── Level 1: Exact Match ──────────────────────────────────────────────────────

def exact_match(
    bank_row: pd.Series,
    ledger_df: pd.DataFrame,
    used_ledger_ids: set[str],
) -> Optional[MatchResult]:
    """
    Match on date == date AND round(amount, 2) == round(amount, 2).
    The strictest level — if this hits, confidence is 1.0.
    """
    candidates = ledger_df[
        (ledger_df["date"] == bank_row["date"])
        & (ledger_df["amount"] == bank_row["amount"])
        & (~ledger_df["txn_id"].isin(used_ledger_ids))
    ]

    if candidates.empty:
        return None

    # If multiple exact matches, prefer the one whose description is closest
    best = candidates.iloc[0]
    if len(candidates) > 1:
        scores = candidates["description"].apply(
            lambda d: fuzz.token_set_ratio(bank_row["description"], d)
        )
        best = candidates.iloc[scores.idxmax()]

    return MatchResult(
        bank_txn_id=bank_row["txn_id"],
        ledger_txn_id=best["txn_id"],
        status="exact",
        score=1.0,
        reasoning_path=(
            f"Level 1 Exact Match: date={bank_row['date']}, "
            f"amount={bank_row['amount']}. "
            f"Matched ledger txn_id={best['txn_id']}."
        ),
        amount_diff=0.0,
        date_diff_days=0,
    )


# ── Level 2: Amount + Date Fuzzy Match ────────────────────────────────────────

def amount_date_fuzzy_match(
    bank_row: pd.Series,
    ledger_df: pd.DataFrame,
    used_ledger_ids: set[str],
    amount_tolerance: float = None,
    date_window_days: int = None,
) -> Optional[MatchResult]:
    """
    Match within configurable amount tolerance AND date window.
    Handles:
    - Bank fees/charges that post 1-3 days after the ledger entry.
    - Rounding differences on FX transactions.
    """
    tol = amount_tolerance if amount_tolerance is not None else settings.AMOUNT_TOLERANCE
    window = date_window_days if date_window_days is not None else settings.DATE_WINDOW_DAYS

    bank_date: date = bank_row["date"]
    bank_amount: float = bank_row["amount"]

    date_min = bank_date - timedelta(days=window)
    date_max = bank_date + timedelta(days=window)

    candidates = ledger_df[
        (ledger_df["date"] >= date_min)
        & (ledger_df["date"] <= date_max)
        & (abs(ledger_df["amount"] - bank_amount) <= tol)
        & (~ledger_df["txn_id"].isin(used_ledger_ids))
    ]

    if candidates.empty:
        return None

    # Among candidates, rank by description similarity
    candidates = candidates.copy()
    candidates["_desc_score"] = candidates["description"].apply(
        lambda d: fuzz.token_set_ratio(bank_row["description"], d)
    )
    best = candidates.loc[candidates["_desc_score"].idxmax()]
    amount_diff = round(abs(float(best["amount"]) - bank_amount), 4)
    date_diff = (bank_date - best["date"]).days

    # Confidence: penalise large amount diffs and date gaps
    amount_confidence = 1.0 - (amount_diff / max(tol, 0.01))
    date_confidence = 1.0 - (abs(date_diff) / (window + 1))
    desc_confidence = best["_desc_score"] / 100.0
    score = round((amount_confidence + date_confidence + desc_confidence) / 3.0, 4)

    return MatchResult(
        bank_txn_id=bank_row["txn_id"],
        ledger_txn_id=best["txn_id"],
        status="fuzzy",
        score=score,
        reasoning_path=(
            f"Level 2 Fuzzy Match: bank_amount={bank_amount}, "
            f"ledger_amount={best['amount']} (diff={amount_diff}), "
            f"date_diff={date_diff}d, "
            f"desc_similarity={best['_desc_score']}%. "
            f"Composite confidence={score:.2f}."
        ),
        amount_diff=amount_diff,
        date_diff_days=date_diff,
        requires_human_review=(score < 0.70),
    )


# ── Level 3: Description Fuzzy Match ─────────────────────────────────────────

def description_fuzzy_match(
    bank_row: pd.Series,
    ledger_df: pd.DataFrame,
    used_ledger_ids: set[str],
    score_threshold: float = None,
    aliases: Optional[dict[str, str]] = None,
) -> Optional[MatchResult]:
    """
    Match primarily on description similarity using the layered vendor matcher:
      Tier 1  normalize    — strip bank/processor noise, unify vendor identities
      Tier 4  alias lookup — exact O(1) hit from learned VendorAlias DB
      Tier 2  composite    — Jaro-Winkler + token_set + token_sort + partial
      Tier 3  embedding    — fastembed BGE-small, rescues semantic-only matches

    Amount must agree within 10% relative tolerance.
    All results flagged for human review since description alone is weaker evidence.

    `score_threshold` is treated as a 0-1 float; if a 0-100 int is passed
    (legacy), it's divided by 100.
    """
    from engine.vendor_matching import find_matches

    threshold = score_threshold if score_threshold is not None else settings.FUZZY_SCORE_THRESHOLD
    if threshold > 1.0:
        threshold = threshold / 100.0

    available = ledger_df[~ledger_df["txn_id"].isin(used_ledger_ids)]
    if available.empty:
        return None

    invoice_vendors = available["description"].astype(str).tolist()
    candidates = find_matches(
        str(bank_row["description"]),
        invoice_vendors,
        alias_map=aliases,
        threshold=threshold,
        top_k=3,
    )
    if not candidates:
        return None

    bank_amount = float(bank_row["amount"])

    # Iterate candidates in score order; first one passing the amount gate wins.
    for cand in candidates:
        candidate_row = available.iloc[cand.invoice_idx]
        ledger_amount = float(candidate_row["amount"])
        relative_tol = max(abs(bank_amount) * 0.10, 0.10)
        amount_diff = abs(ledger_amount - bank_amount)
        if amount_diff > relative_tol:
            continue

        date_diff = (bank_row["date"] - candidate_row["date"]).days

        # Score cap depends on confidence source. Deterministic methods get
        # the full score; pure fuzzy/embedding gets capped so they're flagged
        # for review rather than ever reaching the auto-approve threshold.
        if cand.method in ("alias-exact", "canonical-exact"):
            score = round(cand.score, 4)        # up to 1.00 — eligible for auto-approve
        else:
            score = round(min(cand.score, 0.85), 4)  # cap fuzzy/embed for review

        return MatchResult(
            bank_txn_id=bank_row["txn_id"],
            ledger_txn_id=candidate_row["txn_id"],
            status="fuzzy",
            score=score,
            reasoning_path=(
                f"Level 3 Description Fuzzy ({cand.method}): "
                f"score={cand.score:.2f} between '{bank_row['description']}' "
                f"and '{candidate_row['description']}'. "
                f"Amount diff={amount_diff:.2f}, date_diff={date_diff}d. "
                f"Flagged for human review."
            ),
            amount_diff=round(amount_diff, 4),
            date_diff_days=date_diff,
            requires_human_review=True,
        )

    return None


# ── Level 4: One-to-Many Match ────────────────────────────────────────────────

def one_to_many_match(
    bank_row: pd.Series,
    ledger_df: pd.DataFrame,
    used_ledger_ids: set[str],
    amount_tolerance: float = None,
    max_split: int = 10,
) -> Optional[MatchResult]:
    """
    One bank transaction = sum of multiple ledger entries.
    Common in: split invoices, partial payments, bank fee consolidations.

    Uses PuLP mixed-integer programming for subset sum search.
    """
    from mcp_server.tools.split_solver import solve_split_payment
    
    tol = amount_tolerance if amount_tolerance is not None else settings.AMOUNT_TOLERANCE
    bank_amount = float(bank_row["amount"])

    # Only consider ledger rows within 7-day window to constrain search space
    bank_date = bank_row["date"]
    window_df = ledger_df[
        (ledger_df["date"] >= bank_date - timedelta(days=7))
        & (ledger_df["date"] <= bank_date + timedelta(days=7))
        & (~ledger_df["txn_id"].isin(used_ledger_ids))
    ]

    if len(window_df) < 2:
        return None

    # Prepare data for solver
    open_invoices = [
        {"id": row["txn_id"], "amount": float(row["amount"])}
        for _, row in window_df.iterrows()
    ]
    
    selected_ids = solve_split_payment(target_deposit=bank_amount, open_invoices=open_invoices, tolerance=tol)

    if not selected_ids:
        return None

    ledger_amounts = window_df[window_df["txn_id"].isin(selected_ids)]["amount"].tolist()
    accumulated = sum(ledger_amounts)
    score = round(1.0 - abs(accumulated - bank_amount) / max(bank_amount, 0.01), 4)

    return MatchResult(
        bank_txn_id=bank_row["txn_id"],
        ledger_txn_id=None,  # multiple — use matched_ledger_ids
        status="one_to_many",
        score=score,
        reasoning_path=(
            f"Level 4 One-to-Many (Subset Sum Solver): bank_amount={bank_amount}, "
            f"exact match found with {len(selected_ids)} ledger rows "
            f"({[round(x, 2) for x in ledger_amounts]}) = {accumulated:.2f} "
            f"(diff={abs(accumulated - bank_amount):.4f}). "
            f"Flagged for human review."
        ),
        amount_diff=round(abs(accumulated - bank_amount), 4),
        requires_human_review=True,
        matched_ledger_ids=selected_ids,
    )


# ── Level 5: Many-to-One Match (installment / bulk payments) ──────────────────

def many_to_one_match_pass(
    bank_df: pd.DataFrame,
    ledger_df: pd.DataFrame,
    report: ReconciliationReport,
    used_ledger_ids: set[str],
    amount_tolerance: float = None,
    date_window_days: int = 14,
    max_candidates: int = 20,
    vendor_threshold: float = 0.45,
) -> int:
    """
    Find groups of unmatched bank lines that together sum to one unmatched invoice
    (installment payments, bulk transfers split into chunks).

    Algorithm:
      1. Gather still-unmatched bank lines + still-unmatched invoices.
      2. For each invoice, BLOCK candidates by date window + vendor similarity
         (using the vendor matcher — same fuzzy logic as Level 3, lower threshold).
      3. Run subset-sum (PuLP) on the candidate block: which bank lines sum to
         the invoice amount within tolerance?
      4. If a valid subset (size ≥ 2) is found, replace the corresponding
         unmatched MatchResults with MANY_TO_ONE results pointing at the invoice.

    Returns: count of bank lines newly matched via this pass.

    Mutates `report` and `used_ledger_ids` in place.
    """
    from engine.vendor_matching import find_matches
    from mcp_server.tools.split_solver import solve_split_payment

    tol = amount_tolerance if amount_tolerance is not None else settings.AMOUNT_TOLERANCE

    # Collect unmatched bank lines and invoices
    unmatched_bank_ids = {
        r.bank_txn_id for r in report.match_results if r.status == "unmatched"
    }
    unmatched_bank = bank_df[bank_df["txn_id"].isin(unmatched_bank_ids)]
    unmatched_inv = ledger_df[~ledger_df["txn_id"].isin(used_ledger_ids)]

    if unmatched_bank.empty or unmatched_inv.empty:
        return 0

    # Bank lines already absorbed by an earlier M2O match in THIS pass
    consumed: set[str] = set()
    newly_matched = 0

    for _, inv in unmatched_inv.iterrows():
        inv_id = str(inv["txn_id"])
        inv_amount = float(inv["amount"])
        inv_date = inv["date"]
        inv_desc = str(inv.get("description", ""))

        # Block 1: date window
        block = unmatched_bank[
            (unmatched_bank["date"] >= inv_date - timedelta(days=date_window_days))
            & (unmatched_bank["date"] <= inv_date + timedelta(days=date_window_days))
            & (~unmatched_bank["txn_id"].isin(consumed))
        ]
        if len(block) < 2:
            continue

        # Block 2: vendor similarity — only keep bank lines whose description
        # resembles the invoice vendor. Loose threshold; the amount-sum constraint
        # will eliminate false positives downstream.
        bank_descs = block["description"].astype(str).tolist()
        scored: list[tuple[int, float]] = []
        for idx, desc in zip(block.index, bank_descs):
            matches = find_matches(
                desc, [inv_desc],
                threshold=vendor_threshold, top_k=1, use_embeddings=True,
            )
            if matches:
                scored.append((idx, matches[0].score))

        if len(scored) < 2:
            continue

        # Sort by vendor score desc, keep top N (cap solver complexity)
        scored.sort(key=lambda x: x[1], reverse=True)
        keep_indices = [x[0] for x in scored[:max_candidates]]
        candidates = block.loc[keep_indices]

        # Subset-sum search
        bank_options = [
            {"id": str(row["txn_id"]), "amount": float(row["amount"])}
            for _, row in candidates.iterrows()
        ]
        selected_ids = solve_split_payment(
            target_deposit=inv_amount,
            open_invoices=bank_options,   # naming is generic; here "open_invoices" = bank lines
            tolerance=tol,
        )
        if len(selected_ids) < 2:
            # A single bank line should've been caught by Level 1/2 already
            continue

        # Apply the match — replace unmatched MatchResults for these bank lines
        total = sum(
            float(bank_df.loc[bank_df["txn_id"] == bid, "amount"].iloc[0])
            for bid in selected_ids
        )
        diff = round(abs(total - inv_amount), 4)

        for r in report.match_results:
            if r.bank_txn_id in selected_ids and r.status == "unmatched":
                r.status = "many_to_one"
                r.ledger_txn_id = inv_id
                r.matched_bank_ids = list(selected_ids)
                r.score = 0.80   # high confidence — exact subset sum
                r.amount_diff = diff
                r.requires_human_review = True
                r.reasoning_path = (
                    f"Level 5 Many-to-One: this bank line is one of {len(selected_ids)} "
                    f"installments summing to invoice {inv_id} "
                    f"(target=${inv_amount:.2f}, total=${total:.2f}, diff=${diff:.2f}). "
                    f"Bank IDs in group: {selected_ids}. Flagged for human review."
                )

        consumed.update(selected_ids)
        used_ledger_ids.add(inv_id)
        report.many_to_one_matches += len(selected_ids)
        report.unmatched_bank -= len(selected_ids)
        newly_matched += len(selected_ids)

    return newly_matched


# ── Level 6a: Relaxed deterministic pass ──────────────────────────────────────

def relaxed_match_pass(
    bank_df: pd.DataFrame,
    ledger_df: pd.DataFrame,
    report: ReconciliationReport,
    used_ledger_ids: set[str],
    vendor_threshold: float = 0.45,
    date_window_days: int = 14,
    amount_relative_tol: float = 0.05,
) -> int:
    """
    Second-chance match for still-unmatched pairs using loosened thresholds.
    Emits MatchStatus.POSSIBLE — always low-confidence, requires human review.
    """
    from engine.vendor_matching import find_matches

    unmatched_bank_ids = {r.bank_txn_id for r in report.match_results if r.status == "unmatched"}
    unmatched_bank = bank_df[bank_df["txn_id"].isin(unmatched_bank_ids)]
    unmatched_inv = ledger_df[~ledger_df["txn_id"].isin(used_ledger_ids)]

    if unmatched_bank.empty or unmatched_inv.empty:
        return 0

    invoice_descs = unmatched_inv["description"].astype(str).tolist()
    invoice_ids = unmatched_inv["txn_id"].astype(str).tolist()

    consumed_inv: set[str] = set()
    applied = 0

    for _, bank_row in unmatched_bank.iterrows():
        candidates = find_matches(
            str(bank_row["description"]),
            invoice_descs,
            threshold=vendor_threshold,
            top_k=5,
            use_embeddings=True,
        )

        for cand in candidates:
            inv_id = invoice_ids[cand.invoice_idx]
            if inv_id in consumed_inv:
                continue

            inv_row = unmatched_inv.iloc[cand.invoice_idx]
            bank_amount = float(bank_row["amount"])
            inv_amount = float(inv_row["amount"])

            relative_tol = max(abs(bank_amount) * amount_relative_tol, 1.0)
            amount_diff = abs(inv_amount - bank_amount)
            if amount_diff > relative_tol:
                continue

            date_diff = abs((bank_row["date"] - inv_row["date"]).days)
            if date_diff > date_window_days:
                continue

            # Blended score with hard cap at 0.65 (speculative)
            date_score = max(0.0, 1.0 - date_diff / date_window_days)
            amt_score = max(0.0, 1.0 - amount_diff / max(relative_tol, 1.0))
            blended = 0.5 * cand.score + 0.3 * date_score + 0.2 * amt_score
            blended = round(min(blended, 0.65), 4)

            for r in report.match_results:
                if r.bank_txn_id == bank_row["txn_id"] and r.status == "unmatched":
                    r.status = "possible"
                    r.ledger_txn_id = inv_id
                    r.score = blended
                    r.amount_diff = round(amount_diff, 4)
                    r.date_diff_days = date_diff
                    r.requires_human_review = True
                    r.reasoning_path = (
                        f"Level 6a Relaxed Match ({cand.method}): "
                        f"vendor={cand.score:.2f}, amount_diff=${amount_diff:.2f}, "
                        f"date_diff={date_diff}d. Speculative — please verify."
                    )
                    break

            consumed_inv.add(inv_id)
            report.possible_matches += 1
            report.unmatched_bank -= 1
            applied += 1
            break  # one match per bank line

    used_ledger_ids.update(consumed_inv)
    return applied


# ── Level 6b: LLM verifier ────────────────────────────────────────────────────

def llm_verifier_pass(
    bank_df: pd.DataFrame,
    ledger_df: pd.DataFrame,
    report: ReconciliationReport,
    used_ledger_ids: set[str],
    confidence_floor: float = 0.7,
    max_set_size: int = 30,
) -> int:
    """
    Last-resort: single batched LLM call to match any pairs the deterministic
    cascade missed. Bounded by max_set_size to keep one call manageable.
    """
    from engine.vendor_matching.llm_verifier import verify_matches

    unmatched_bank_ids = {r.bank_txn_id for r in report.match_results if r.status == "unmatched"}
    unmatched_bank = bank_df[bank_df["txn_id"].isin(unmatched_bank_ids)]
    unmatched_inv = ledger_df[~ledger_df["txn_id"].isin(used_ledger_ids)]

    if unmatched_bank.empty or unmatched_inv.empty:
        return 0
    if len(unmatched_bank) > max_set_size or len(unmatched_inv) > max_set_size:
        return 0  # skip LLM on huge sets — would be slow and lossy

    bank_payload = [{
        "id": str(row["txn_id"]),
        "vendor": str(row["description"]),
        "amount": float(row["amount"]),
        "date": str(row["date"])[:10],
    } for _, row in unmatched_bank.iterrows()]

    inv_payload = [{
        "id": str(row["txn_id"]),
        "vendor": str(row["description"]),
        "amount": float(row["amount"]),
        "date": str(row["date"])[:10],
    } for _, row in unmatched_inv.iterrows()]

    try:
        matches = verify_matches(bank_payload, inv_payload,
                                 confidence_floor=confidence_floor)
    except Exception:  # noqa: BLE001
        return 0

    consumed_inv: set[str] = set()
    applied = 0
    for m in matches:
        inv_id = m["invoice_id"]
        if inv_id in consumed_inv:
            continue
        score = round(min(float(m["confidence"]), 0.65), 4)

        for r in report.match_results:
            if r.bank_txn_id == m["bank_id"] and r.status == "unmatched":
                r.status = "possible"
                r.ledger_txn_id = inv_id
                r.score = score
                r.requires_human_review = True
                r.reasoning_path = (
                    f"Level 6b LLM Verifier (conf={m['confidence']:.2f}): "
                    f"{m['reason'][:200]} — speculative, please verify."
                )
                break
        consumed_inv.add(inv_id)
        applied += 1

    used_ledger_ids.update(consumed_inv)
    report.possible_matches += applied
    report.unmatched_bank -= applied
    return applied


# ── Main cascade orchestrator ─────────────────────────────────────────────────

def run_matching_cascade(
    bank_df: pd.DataFrame,
    ledger_df: pd.DataFrame,
    run_id: str,
    aliases: dict[str, str] = None,
    fuzzy_threshold: int = None,
    amount_tolerance: float = None,
    date_window_days: int = None,
) -> ReconciliationReport:
    """
    Run the full 4-level matching cascade and return a ReconciliationReport.

    Args:
        bank_df:          Normalised bank statement DataFrame.
        ledger_df:        Normalised ledger DataFrame.
        run_id:           Unique identifier for this reconciliation run.
        aliases:          Optional dict mapping raw descriptions to canonical names.
        fuzzy_threshold:  Override description-similarity threshold (0-100).
        amount_tolerance: Override absolute amount tolerance.
        date_window_days: Override date-window size (days).
    """
    validate_df(bank_df, REQUIRED_BANK_COLS, "Bank")
    validate_df(ledger_df, REQUIRED_LEDGER_COLS, "Ledger")

    aliases = aliases or {}
    report = ReconciliationReport(
        run_id=run_id,
        total_bank_rows=len(bank_df),
        total_ledger_rows=len(ledger_df),
    )

    used_ledger_ids: set[str] = set()

    for _, bank_row in bank_df.iterrows():
        # Apply alias normalization to bank description
        bank_desc = bank_row["description"]
        canonical_vendor = aliases.get(bank_desc)
        
        # We work with a temp row for matching logic
        match_row = bank_row.copy()
        if canonical_vendor:
            match_row["description"] = canonical_vendor.lower()

        result = None

        # Level 1
        result = exact_match(match_row, ledger_df, used_ledger_ids)
        if result:
            report.exact_matches += 1
            result.canonical_vendor = canonical_vendor

        # Level 2
        if not result:
            result = amount_date_fuzzy_match(
                match_row, ledger_df, used_ledger_ids,
                amount_tolerance=amount_tolerance,
                date_window_days=date_window_days,
            )
            if result:
                report.fuzzy_matches += 1
                result.canonical_vendor = canonical_vendor

        # Level 3 — uses the layered vendor matcher (normalizer + ensemble + embedding)
        if not result:
            # Pass the raw bank description (not canonical) so the matcher's
            # normalizer can do its own work — we don't want to double-normalize.
            l3_row = bank_row.copy()
            result = description_fuzzy_match(
                l3_row, ledger_df, used_ledger_ids,
                score_threshold=fuzzy_threshold,
                aliases=aliases,
            )
            if result:
                report.fuzzy_matches += 1
                result.canonical_vendor = canonical_vendor

        # Level 4
        if not result:
            result = one_to_many_match(
                bank_row, ledger_df, used_ledger_ids,
                amount_tolerance=amount_tolerance,
            )
            if result:
                report.one_to_many_matches += 1

        # Unmatched
        if not result:
            result = MatchResult(
                bank_txn_id=bank_row["txn_id"],
                ledger_txn_id=None,
                status="unmatched",
                score=0.0,
                reasoning_path=(
                    f"All 4 matching levels failed for bank_txn_id={bank_row['txn_id']} "
                    f"(date={bank_row['date']}, amount={bank_row['amount']}, "
                    f"desc='{bank_row['description']}'). Requires human review."
                ),
                requires_human_review=True,
            )
            report.unmatched_bank += 1

        # Mark used ledger rows to prevent double-matching
        if result.ledger_txn_id:
            used_ledger_ids.add(result.ledger_txn_id)
        elif result.matched_ledger_ids:
            used_ledger_ids.update(result.matched_ledger_ids)

        report.match_results.append(result)

    # Level 5: Many-to-One — installment / bulk payments
    # Runs AFTER the per-bank loop, on remaining unmatched bank+invoice pairs.
    many_to_one_match_pass(
        bank_df, ledger_df, report, used_ledger_ids,
        amount_tolerance=amount_tolerance,
    )

    # Level 6a: Relaxed deterministic match — loose thresholds, POSSIBLE status
    relaxed_match_pass(bank_df, ledger_df, report, used_ledger_ids)

    # Level 6b: LLM verifier — single batched call for any pairs still stuck
    try:
        llm_verifier_pass(bank_df, ledger_df, report, used_ledger_ids)
    except Exception:  # noqa: BLE001
        # LLM failure must never crash the cascade. Deterministic levels stand.
        pass

    # Compute unmatched ledger rows
    all_matched_ledger = {
        r.ledger_txn_id for r in report.match_results if r.ledger_txn_id
    } | {
        lid
        for r in report.match_results
        for lid in r.matched_ledger_ids
    }
    report.unmatched_ledger = len(
        ledger_df[~ledger_df["txn_id"].isin(all_matched_ledger)]
    )

    return report
