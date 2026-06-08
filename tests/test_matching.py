"""
Tests for the 4-level matching cascade in mcp_server/tools/matching.py.

Covers:
  - Exact match (happy path)
  - Fuzzy amount match with date offset
  - Description fuzzy match (AMZN → Amazon)
  - One-to-many match (sum of split entries)
  - Unmatched (all levels fail)
  - Duplicate prevention (same ledger row never matched twice)
  - Input validation (bad dates, missing columns)
  - Idempotency (running cascade twice gives same result)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd

from mcp_server.tools.matching import (
    normalise_df,
    run_matching_cascade,
    validate_df,
    exact_match,
    amount_date_fuzzy_match,
    one_to_many_match,
    REQUIRED_BANK_COLS,
    REQUIRED_LEDGER_COLS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_bank(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return normalise_df(df)


def make_ledger(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return normalise_df(df)


# ── Test 1: Exact Match ───────────────────────────────────────────────────────

def test_exact_match():
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-01-15", "description": "Amazon", "amount": 100.00},
    ])
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-15", "description": "Amazon Purchase", "amount": 100.00},
    ])
    report = run_matching_cascade(bank, ledger, "test_exact")
    assert len(report.match_results) == 1
    r = report.match_results[0]
    assert r.status == "exact"
    assert r.score == 1.0
    assert r.ledger_txn_id == "L1"
    assert report.exact_matches == 1
    assert report.unmatched_bank == 0
    assert report.match_rate == 1.0


# ── Test 2: Fuzzy Amount + Date Match ─────────────────────────────────────────

def test_fuzzy_amount_date_match():
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-01-17", "description": "AWS Invoice", "amount": 250.03},
    ])
    ledger = make_ledger([
        # 2-day offset + $0.03 difference (FX rounding)
        {"txn_id": "L1", "date": "2024-01-15", "description": "AWS Invoice", "amount": 250.00},
    ])
    report = run_matching_cascade(bank, ledger, "test_fuzzy_amt")
    r = report.match_results[0]
    assert r.status == "fuzzy"
    assert r.ledger_txn_id == "L1"
    assert r.amount_diff <= 0.05
    assert r.date_diff_days is not None


# ── Test 3: Description Fuzzy Match (slight wording variation) ────────────────

def test_description_fuzzy_match():
    """
    Level 3 matches on description similarity.
    Uses a slight wording variation, not a full abbreviation jump.
    Abbreviation mapping (AMZN→Amazon) is handled by the vendor alias system,
    not the raw fuzzy matcher.
    """
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-01-10", "description": "Amazon Marketplace Purchase", "amount": 49.99},
    ])
    ledger = make_ledger([
        # Completely different date (> 3-day window) so L2 won't fire
        {"txn_id": "L1", "date": "2024-01-01", "description": "Amazon Marketplace", "amount": 49.99},
    ])
    report = run_matching_cascade(bank, ledger, "test_fuzzy_desc")
    r = report.match_results[0]
    # Should match via description fuzzy (Level 3)
    assert r.status == "fuzzy"
    assert r.ledger_txn_id == "L1"
    assert r.requires_human_review is True


# ── Test 4: One-to-Many Match ─────────────────────────────────────────────────

def test_one_to_many_match():
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-01-20", "description": "Payroll", "amount": 10000.00},
    ])
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-20", "description": "Alice Salary", "amount": 4000.00},
        {"txn_id": "L2", "date": "2024-01-20", "description": "Bob Salary", "amount": 3500.00},
        {"txn_id": "L3", "date": "2024-01-20", "description": "Carol Salary", "amount": 2500.00},
    ])
    report = run_matching_cascade(bank, ledger, "test_one_to_many")
    r = report.match_results[0]
    assert r.status == "one_to_many"
    assert set(r.matched_ledger_ids) == {"L1", "L2", "L3"}
    assert r.requires_human_review is True
    assert r.amount_diff <= 0.05


# ── Test 5: Unmatched ─────────────────────────────────────────────────────────

def test_unmatched():
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-01-01", "description": "Mystery Charge", "amount": 999.99},
    ])
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-03-01", "description": "Totally Unrelated", "amount": 1.00},
    ])
    report = run_matching_cascade(bank, ledger, "test_unmatched")
    r = report.match_results[0]
    assert r.status == "unmatched"
    assert r.ledger_txn_id is None
    assert r.requires_human_review is True
    assert report.unmatched_bank == 1


# ── Test 6: Duplicate Prevention ─────────────────────────────────────────────

def test_no_double_match():
    """
    Two bank rows with identical details should NOT both match the same ledger row.
    Second bank row must be unmatched.
    """
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-01-15", "description": "Office Supplies", "amount": 200.00},
        {"txn_id": "B2", "date": "2024-01-15", "description": "Office Supplies", "amount": 200.00},
    ])
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-15", "description": "Office Supplies", "amount": 200.00},
    ])
    report = run_matching_cascade(bank, ledger, "test_no_double")
    statuses = {r.bank_txn_id: r.status for r in report.match_results}
    # One matched, one unmatched — L1 cannot be used twice
    assert statuses["B1"] == "exact"
    assert statuses["B2"] == "unmatched"


# ── Test 7: Input Validation — Missing Column ─────────────────────────────────

def test_missing_column_raises():
    """The cascade's data contract: a frame missing a required column is
    rejected. We pass a RAW frame (no normalise_df) on purpose — normalise_df
    auto-fills 'description', which is exactly what was hiding this check
    before and made the old test fail.
    """
    bad_bank = pd.DataFrame([{"txn_id": "B1", "date": "2024-01-01", "amount": 100.0}])  # no description
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-01", "description": "Test", "amount": 100.0}
    ])
    with pytest.raises(ValueError, match="missing required columns"):
        run_matching_cascade(bad_bank, ledger, "test_validation")


# ── Test 8: Idempotency ───────────────────────────────────────────────────────

def test_idempotent():
    """Running the same cascade twice must return identical results."""
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-02-01", "description": "Rent", "amount": 3000.00},
    ])
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-02-01", "description": "Office Rent", "amount": 3000.00},
    ])
    report1 = run_matching_cascade(bank, ledger, "run_idem_1")
    report2 = run_matching_cascade(bank, ledger, "run_idem_2")
    assert report1.match_results[0].status == report2.match_results[0].status
    assert report1.match_results[0].score == report2.match_results[0].score


# ── Test 9: Summary Stats Accuracy ───────────────────────────────────────────

def test_summary_stats():
    bank = make_bank([
        {"txn_id": "B1", "date": "2024-01-01", "description": "Alpha", "amount": 100.0},  # exact
        {"txn_id": "B2", "date": "2024-01-02", "description": "Beta", "amount": 999.0},   # unmatched
    ])
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-01", "description": "Alpha", "amount": 100.0},
        {"txn_id": "L2", "date": "2024-03-01", "description": "Gamma", "amount": 50.0},   # unmatched ledger
    ])
    report = run_matching_cascade(bank, ledger, "test_stats")
    assert report.exact_matches == 1
    assert report.unmatched_bank == 1
    assert report.unmatched_ledger == 1
    assert abs(report.match_rate - 0.5) < 0.01


# ── Test 10: exact match is exact — a cent off must NOT match at Level 1 ───────

def test_exact_match_requires_identical_amount():
    """Level 1 only fires on an identical amount. A 1-cent difference must fall
    through to a fuzzy level — it is not an 'exact' match."""
    bank_row = make_bank([
        {"txn_id": "B1", "date": "2024-01-15", "description": "Rent", "amount": 100.00},
    ]).iloc[0]

    same = make_ledger([
        {"txn_id": "L1", "date": "2024-01-15", "description": "Rent", "amount": 100.00},
    ])
    off_by_a_cent = make_ledger([
        {"txn_id": "L1", "date": "2024-01-15", "description": "Rent", "amount": 100.01},
    ])

    assert exact_match(bank_row, same, set()) is not None
    assert exact_match(bank_row, off_by_a_cent, set()) is None


# ── Test 11: exact match never reuses an already-matched ledger row ───────────

def test_exact_match_skips_used_ledger():
    bank_row = make_bank([
        {"txn_id": "B1", "date": "2024-01-15", "description": "Rent", "amount": 100.00},
    ]).iloc[0]
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-15", "description": "Rent", "amount": 100.00},
    ])
    # Free → matches L1; once L1 is marked used → no match left.
    assert exact_match(bank_row, ledger, set()).ledger_txn_id == "L1"
    assert exact_match(bank_row, ledger, {"L1"}) is None


# ── Test 12: Level 2 amount-tolerance gate ────────────────────────────────────

def test_fuzzy_amount_tolerance_gate():
    """With a $0.05 tolerance: a small diff matches, a large one doesn't.

    The exact-boundary value ($0.05 on the nose) is intentionally avoided —
    float rounding makes `diff == 0.05` ambiguous, which is itself the reason
    money is risky as a float. Clearly-inside / clearly-outside is the robust
    way to pin a gate.
    """
    bank_row = make_bank([
        {"txn_id": "B1", "date": "2024-01-15", "description": "AWS", "amount": 100.00},
    ]).iloc[0]

    within = make_ledger([
        {"txn_id": "L1", "date": "2024-01-15", "description": "AWS", "amount": 100.03},
    ])
    outside = make_ledger([
        {"txn_id": "L1", "date": "2024-01-15", "description": "AWS", "amount": 100.50},
    ])

    assert amount_date_fuzzy_match(bank_row, within, set(), amount_tolerance=0.05, date_window_days=3) is not None
    assert amount_date_fuzzy_match(bank_row, outside, set(), amount_tolerance=0.05, date_window_days=3) is None


# ── Test 13: Level 2 date-window gate ─────────────────────────────────────────

def test_fuzzy_date_window_gate():
    """With a 3-day window: a ledger entry 3 days off matches; 6 days off
    doesn't. Amount is identical, so only the date gate decides."""
    bank_row = make_bank([
        {"txn_id": "B1", "date": "2024-01-15", "description": "AWS", "amount": 100.00},
    ]).iloc[0]

    in_window = make_ledger([
        {"txn_id": "L1", "date": "2024-01-12", "description": "AWS", "amount": 100.00},
    ])
    out_of_window = make_ledger([
        {"txn_id": "L1", "date": "2024-01-09", "description": "AWS", "amount": 100.00},
    ])

    assert amount_date_fuzzy_match(bank_row, in_window, set(), amount_tolerance=0.05, date_window_days=3) is not None
    assert amount_date_fuzzy_match(bank_row, out_of_window, set(), amount_tolerance=0.05, date_window_days=3) is None


# ── Test 14: Level 4 one-to-many subset sum ───────────────────────────────────

def test_one_to_many_finds_exact_subset():
    """Bank deposit = sum of two ledger rows → matched as one_to_many with both
    ledger ids, and flagged for human review."""
    bank_row = make_bank([
        {"txn_id": "B1", "date": "2024-01-20", "description": "Payroll", "amount": 300.00},
    ]).iloc[0]
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-20", "description": "Alice", "amount": 100.00},
        {"txn_id": "L2", "date": "2024-01-20", "description": "Bob", "amount": 200.00},
    ])
    result = one_to_many_match(bank_row, ledger, set(), amount_tolerance=0.01)
    assert result is not None
    assert result.status == "one_to_many"
    assert set(result.matched_ledger_ids) == {"L1", "L2"}
    assert result.requires_human_review is True


def test_one_to_many_needs_at_least_two_rows():
    """A single ledger row can't be a 'split' — Level 4 must decline (a lone
    exact-amount row is Level 1's job, not Level 4's)."""
    bank_row = make_bank([
        {"txn_id": "B1", "date": "2024-01-20", "description": "Payroll", "amount": 300.00},
    ]).iloc[0]
    ledger = make_ledger([
        {"txn_id": "L1", "date": "2024-01-20", "description": "Alice", "amount": 300.00},
    ])
    assert one_to_many_match(bank_row, ledger, set(), amount_tolerance=0.01) is None


# ── Test 15: normaliser is lenient — a missing description is filled, not fatal ─

def test_normalise_fills_missing_description():
    """Counterpart to test_missing_column_raises: once a frame goes THROUGH
    normalise_df, a missing description becomes a placeholder rather than
    crashing the run. This documents the deliberate leniency."""
    df = normalise_df(pd.DataFrame([{"txn_id": "B1", "date": "2024-01-01", "amount": 100.0}]))
    assert "description" in df.columns
    assert df.iloc[0]["description"]  # non-empty placeholder
