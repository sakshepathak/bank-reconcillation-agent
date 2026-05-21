"""Level 5 smoke test — three bank installments matching one invoice."""
import sys
sys.path.insert(0, "/app")

from datetime import date
import pandas as pd

from mcp_server.tools.matching import run_matching_cascade

# Bank: three $1000 payments to "Adobe" on three Mondays.
# Invoice: one $3000 quarterly Adobe subscription, dated middle of the range.
bank_df = pd.DataFrame([
    {"txn_id": "B1", "date": date(2026, 3,  2), "description": "ADOBE *CREATIVE",   "amount": 1000.00},
    {"txn_id": "B2", "date": date(2026, 3,  9), "description": "ADOBE *CREATIVE",   "amount": 1000.00},
    {"txn_id": "B3", "date": date(2026, 3, 16), "description": "ADOBE *CREATIVE",   "amount": 1000.00},
    # A different vendor, single bank line, should match invoice L2 normally
    {"txn_id": "B4", "date": date(2026, 3, 14), "description": "STRIPE *NETFLIX",   "amount": 12.99},
])

ledger_df = pd.DataFrame([
    {"txn_id": "L1", "date": date(2026, 3, 10), "description": "Adobe Systems Software", "amount": 3000.00},
    {"txn_id": "L2", "date": date(2026, 3, 14), "description": "Netflix",                "amount": 12.99},
])

report = run_matching_cascade(
    bank_df, ledger_df,
    run_id="lvl5-test",
    aliases={},
    fuzzy_threshold=0.70,
    amount_tolerance=0.05,
    date_window_days=3,
)

print(f"Match rate: {report.match_rate * 100:.0f}%")
print(f"Exact: {report.exact_matches}, Fuzzy: {report.fuzzy_matches}, "
      f"OneToMany: {report.one_to_many_matches}, ManyToOne: {report.many_to_one_matches}, "
      f"Unmatched: {report.unmatched_bank}")
print()
for r in report.match_results:
    arrow = "→" if r.ledger_txn_id else "✗"
    extras = ""
    if r.matched_bank_ids:
        extras = f"  (group={r.matched_bank_ids})"
    print(f"  {r.bank_txn_id} {arrow} {r.ledger_txn_id or '(unmatched)'}   "
          f"status={r.status:<13s} score={r.score:.2f}{extras}")
