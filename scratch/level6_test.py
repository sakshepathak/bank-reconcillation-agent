"""Level 6 smoke test: relaxed deterministic + LLM verifier on stuck pairs."""
import sys
sys.path.insert(0, "/app")

from datetime import date
import pandas as pd

from mcp_server.tools.matching import run_matching_cascade

# Crafted to make Levels 1-5 miss but Level 6 catch.
bank_df = pd.DataFrame([
    # Big date gap + small amount diff — Level 2 misses (date window), Level 3 might catch
    {"txn_id": "B1", "date": date(2026, 3, 30), "description": "AMZN MKTPL*K9X3D7", "amount": 1247.50},
    # Semantically same vendor, very different string — needs LLM
    {"txn_id": "B2", "date": date(2026, 3, 15), "description": "WEEKLY GROCERIES DLY",  "amount": 87.50},
    # Truly no match in invoice list
    {"txn_id": "B3", "date": date(2026, 3, 16), "description": "RANDOM XYZ CORP",   "amount": 250.00},
])

ledger_df = pd.DataFrame([
    {"txn_id": "L1", "date": date(2026, 3,  5), "description": "Amazon.com, Inc.",       "amount": 1247.50},
    {"txn_id": "L2", "date": date(2026, 3, 14), "description": "Whole Foods Market",     "amount": 87.50},
])

report = run_matching_cascade(
    bank_df, ledger_df,
    run_id="lvl6-test",
    aliases={},
    fuzzy_threshold=0.70,
    amount_tolerance=0.05,
    date_window_days=3,
)

print(f"Match rate: {report.match_rate * 100:.0f}%")
print(f"Exact: {report.exact_matches}, Fuzzy: {report.fuzzy_matches}, "
      f"OneToMany: {report.one_to_many_matches}, ManyToOne: {report.many_to_one_matches}, "
      f"Possible: {report.possible_matches}, Unmatched: {report.unmatched_bank}")
print()
for r in report.match_results:
    arrow = "→" if r.ledger_txn_id else "✗"
    print(f"  {r.bank_txn_id} {arrow} {r.ledger_txn_id or '(unmatched)'}   "
          f"status={r.status:<13s} score={r.score:.2f}")
    if r.reasoning_path:
        print(f"     {r.reasoning_path[:140]}")
