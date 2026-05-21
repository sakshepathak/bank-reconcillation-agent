"""
Reset extraction state so previously-cached (wrong-vendor) invoices don't persist.

Clears:
  - ExtractedInvoice  (all rows — re-upload will re-extract via new prompt)
  - ManualLedgerEntry (linked to old runs — safer to clear with cache)
  - MatchRecord       (linked to old extraction IDs)

Leaves alone:
  - VendorAlias (learned aliases — keep them so the system carries forward
    its knowledge across the reset)
"""
import sys
sys.path.insert(0, "/app")

from sqlmodel import delete
from memory.db import get_session
from memory.models import ExtractedInvoice, ManualLedgerEntry, MatchRecord

with get_session() as session:
    ext_count = len(list(session.exec(__import__("sqlmodel").select(ExtractedInvoice)).all()))
    manual_count = len(list(session.exec(__import__("sqlmodel").select(ManualLedgerEntry)).all()))
    match_count = len(list(session.exec(__import__("sqlmodel").select(MatchRecord)).all()))

    session.exec(delete(ExtractedInvoice))
    session.exec(delete(ManualLedgerEntry))
    session.exec(delete(MatchRecord))

print(f"Cleared: {ext_count} ExtractedInvoice, {manual_count} ManualLedgerEntry, {match_count} MatchRecord")
print("VendorAlias rows preserved.")
