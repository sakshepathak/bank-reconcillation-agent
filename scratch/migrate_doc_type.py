"""
Drop + recreate extracted_invoice table to pick up the new doc_type column.

Safe because we already cleared all ExtractedInvoice rows in the previous step.
VendorAlias, MatchRecord, and ManualLedgerEntry are untouched.
"""
import sys
sys.path.insert(0, "/app")

from memory.db import engine
from memory.models import ExtractedInvoice

print("Dropping extracted_invoice table...")
ExtractedInvoice.__table__.drop(engine, checkfirst=True)
print("Recreating with new schema (doc_type column added)...")
ExtractedInvoice.__table__.create(engine, checkfirst=True)

# Sanity-check column list
from sqlalchemy import inspect
columns = [c["name"] for c in inspect(engine).get_columns("extracted_invoice")]
print("Columns now:", columns)
