"""End-to-end cascade test: run the matching cascade with the new Level 3 wiring."""
import sys
sys.path.insert(0, "/app")

from datetime import date
import pandas as pd

from mcp_server.tools.matching import run_matching_cascade

bank_df = pd.DataFrame([
    {"txn_id": "B1", "date": date(2026, 3, 12), "description": "AMZN MKTPL*Z89K3KS", "amount": 1247.50},
    {"txn_id": "B2", "date": date(2026, 3, 13), "description": "SQ *DAILYBEAN SF", "amount": 12.00},
    {"txn_id": "B3", "date": date(2026, 3, 14), "description": "UBER *TRIP 12MAR", "amount": 35.00},
    {"txn_id": "B4", "date": date(2026, 3, 15), "description": "GOOGLE *CLOUD", "amount": 99.00},
    {"txn_id": "B5", "date": date(2026, 3, 16), "description": "WALMART STORES", "amount": 45.00},
])

ledger_df = pd.DataFrame([
    {"txn_id": "L1", "date": date(2026, 3, 12), "description": "Amazon.com, Inc.", "amount": 1247.50},
    {"txn_id": "L2", "date": date(2026, 3, 13), "description": "The Daily Bean Pvt. Ltd.", "amount": 12.00},
    {"txn_id": "L3", "date": date(2026, 3, 14), "description": "Uber Technologies", "amount": 35.00},
    {"txn_id": "L4", "date": date(2026, 3, 15), "description": "Google Cloud", "amount": 99.00},
])

report = run_matching_cascade(
    bank_df, ledger_df,
    run_id="smoke",
    aliases={},  # no learned aliases yet
    fuzzy_threshold=0.70,
    amount_tolerance=0.05,
    date_window_days=3,
)

print(f"Match rate: {report.match_rate * 100:.0f}%")
print(f"Exact: {report.exact_matches} | Fuzzy: {report.fuzzy_matches} | "
      f"OnetoMany: {report.one_to_many_matches} | Unmatched: {report.unmatched_bank}")
print()
for r in report.match_results:
    arrow = "→" if r.ledger_txn_id else "✗"
    print(f"  {r.bank_txn_id} {arrow} {r.ledger_txn_id or '(unmatched)'}   "
          f"status={r.status} score={r.score:.2f}")
    if r.reasoning_path:
        # First 110 chars of reasoning
        rp = r.reasoning_path.replace("\n", " ")[:110]
        print(f"     {rp}")
