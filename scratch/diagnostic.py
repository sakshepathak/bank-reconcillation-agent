"""
Final diagnostic - tests all fixed functionality.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print('=== Testing all imports ===')

try:
    from config.settings import settings
    print('settings OK')
except Exception as e:
    print(f'settings FAIL: {e}')

# CRITICAL: import models BEFORE db (and before init_db)
try:
    from memory.models import MatchRecord, MatchStatus, VendorAlias
    print('models OK')
except Exception as e:
    print(f'models FAIL: {e}')

try:
    from memory.db import get_session, init_db
    init_db()  # safe now - models are registered in SQLModel.metadata
    print('DB init OK (tables created)')
except Exception as e:
    print(f'DB init FAIL: {e}')

try:
    from mcp_server.tools.matching import normalise_df, run_matching_cascade, MatchResult, ReconciliationReport
    print('matching OK')
except Exception as e:
    print(f'matching FAIL: {e}')

try:
    from mcp_server.tools.suggestions import generate_unmatched_suggestion, generate_fuzzy_suggestion
    print('suggestions OK')
except Exception as e:
    print(f'suggestions FAIL: {e}')

try:
    from mcp_server.tools.search_kb import search_knowledge_base
    print('search_kb OK')
except Exception as e:
    print(f'search_kb FAIL: {e}')

try:
    from mcp_server.tools.split_solver import solve_split_payment
    print('split_solver OK')
except Exception as e:
    print(f'split_solver FAIL: {e}')

print()
print('=== Testing MatchStatus enum ===')
try:
    statuses = [MatchStatus.EXACT, MatchStatus.FUZZY, MatchStatus.ONE_TO_MANY, MatchStatus.UNMATCHED, MatchStatus.HUMAN_CORRECTED]
    print(f'  All statuses: {[s.value for s in statuses]}')
    print('MatchStatus enum OK')
except Exception as e:
    print(f'MatchStatus FAIL: {e}')

print()
print('=== Testing end-to-end reconciliation ===')
import pandas as pd
from sqlmodel import select
from datetime import datetime

bank_df = pd.read_csv('sample_data/bank_statement.csv')
ledger_df = pd.read_csv('sample_data/company_ledger.csv')

try:
    bank_norm = normalise_df(bank_df.copy(), is_ledger=False)
    ledger_norm = normalise_df(ledger_df.copy(), is_ledger=True)
    print('Normalisation OK')

    report = run_matching_cascade(bank_norm, ledger_norm, 'test_run_diag',
                                   aliases={}, fuzzy_threshold=70,
                                   amount_tolerance=0.05, date_window_days=3)
    print(f'  Cascade OK: exact={report.exact_matches}, fuzzy={report.fuzzy_matches}, split={report.one_to_many_matches}, unmatched={report.unmatched_bank}')
    print(f'  Match rate: {report.match_rate:.1%}')
except Exception as e:
    import traceback
    print(f'  E2E FAIL: {e}')
    traceback.print_exc()

print()
print('=== Testing DB session (with init_db fix) ===')
try:
    with get_session() as session:
        aliases = session.exec(select(VendorAlias)).all()
    print(f'  DB read OK. Aliases: {len(aliases)}')
except Exception as e:
    print(f'  DB read FAIL: {e}')

print()
print('=== Testing MatchRecord write ===')
try:
    _status_map = {
        "exact": MatchStatus.EXACT, "fuzzy": MatchStatus.FUZZY,
        "one_to_many": MatchStatus.ONE_TO_MANY, "unmatched": MatchStatus.UNMATCHED,
    }
    with get_session() as session:
        for r in report.match_results:
            rec = MatchRecord(
                run_id='test_run_diag',
                bank_txn_id=r.bank_txn_id,
                ledger_txn_id=r.ledger_txn_id,
                status=_status_map.get(r.status, MatchStatus.UNMATCHED),
                score=r.score,
                reasoning_path=r.reasoning_path,
                amount_diff=r.amount_diff,
                date_diff_days=r.date_diff_days,
                requires_human_review=r.requires_human_review,
                created_at=datetime.utcnow().isoformat(),
            )
            session.add(rec)
    print('  MatchRecord write OK')

    with get_session() as session:
        records = session.exec(select(MatchRecord).where(MatchRecord.run_id == 'test_run_diag')).all()
    print(f'  MatchRecord read OK. Records: {len(records)}')
except Exception as e:
    import traceback
    print(f'  MatchRecord FAIL: {e}')
    traceback.print_exc()

print()
print('=== Testing suggestion engine ===')
try:
    result = generate_unmatched_suggestion(description="WIRE FEE", amount=15.00, date="2024-01-28")
    print(f'  Unmatched suggestion OK: {result[:80]}...')
except Exception as e:
    print(f'  Suggestion FAIL: {e}')

print()
print('=== ALL DONE ===')
