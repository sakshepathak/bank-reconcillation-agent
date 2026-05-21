"""
Mismatch summary for fuzzy and unmatched rows.

Plain, deterministic — no LLM. Just states which fields differ so the
accountant can decide quickly. The full reasoning path from the matching
engine is still available behind the "Why this match?" expander.
"""
from __future__ import annotations

from rapidfuzz import fuzz


def generate_fuzzy_suggestion(
    bank_desc: str,
    bank_amount: float,
    bank_date: str,
    ledger_desc: str,
    ledger_amount: float,
    ledger_date: str,
    score: float,
    amount_diff: float,
    date_diff_days: int,
) -> str:
    """Lists the fields that don't match between a fuzzy bank/ledger pair."""
    issues: list[str] = []

    if abs(amount_diff) > 0.005:
        issues.append(f"Amount differs by ${abs(amount_diff):.2f}")

    days = abs(int(date_diff_days or 0))
    if days > 0:
        issues.append(f"Date differs by {days} day{'s' if days != 1 else ''}")

    desc_sim = fuzz.token_set_ratio(str(bank_desc).lower(), str(ledger_desc).lower())
    if desc_sim < 80:
        issues.append(f"Vendor names differ ({desc_sim}% similar)")

    if not issues:
        return "All fields close — likely the same transaction."
    return " · ".join(issues)


def generate_unmatched_suggestion(description: str, amount: float, date: str) -> str:
    """Brief message for a bank line with no ledger match."""
    return f"No ledger entry found near {date} for ${amount:.2f}."
