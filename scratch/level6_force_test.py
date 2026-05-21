"""Force Level 6 by making semantically-related but lexically-different vendors."""
import sys
sys.path.insert(0, "/app")

from datetime import date
import pandas as pd

from mcp_server.tools.matching import run_matching_cascade

# Bank: cryptic descriptions, slightly off amounts.
# Each one only matches an invoice semantically (via LLM understanding).
bank_df = pd.DataFrame([
    {"txn_id": "B1", "date": date(2026, 3, 12), "description": "WEEKLY GROCERY RUN", "amount": 87.50},
    {"txn_id": "B2", "date": date(2026, 3, 14), "description": "MONTHLY FUEL CHARGE", "amount": 60.00},
    {"txn_id": "B3", "date": date(2026, 3, 16), "description": "DENTIST APPOINTMENT", "amount": 200.00},
])

ledger_df = pd.DataFrame([
    {"txn_id": "L1", "date": date(2026, 3, 13), "description": "Whole Foods Market", "amount": 87.55},
    {"txn_id": "L2", "date": date(2026, 3, 14), "description": "Shell Gas Station", "amount": 60.00},
    # L3 has different amount AND different vendor — should stay unmatched
    {"txn_id": "L3", "date": date(2026, 3, 20), "description": "Costco Wholesale", "amount": 412.30},
])

report = run_matching_cascade(
    bank_df, ledger_df,
    run_id="lvl6-force",
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
        print(f"     {r.reasoning_path[:200]}")
