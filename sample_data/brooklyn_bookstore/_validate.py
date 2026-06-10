"""Throwaway validation: run the real cascade over the demo data and print results."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import pandas as pd
from mcp_server.tools.matching import run_matching_cascade, normalise_df

HERE = os.path.dirname(os.path.abspath(__file__))
bank = pd.read_csv(os.path.join(HERE, "bank_statement.csv"))
ledger = pd.read_csv(os.path.join(HERE, "company_ledger.csv"))

bank_n = normalise_df(bank, is_ledger=False)
ledger_n = normalise_df(ledger, is_ledger=True)

rep = run_matching_cascade(bank_n, ledger_n, run_id="brooklyn-demo")
print(rep.summary_text())
print("-" * 80)
for r in sorted(rep.match_results, key=lambda x: x.bank_txn_id):
    tgt = r.ledger_txn_id or (r.matched_ledger_ids or r.matched_bank_ids or "")
    print(f"{r.bank_txn_id:5} {r.status:12} score={r.score:<5} -> {tgt}")
