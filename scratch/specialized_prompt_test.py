"""Verify the specialized sales/purchase prompts work on the user's sample data."""
import sys
sys.path.insert(0, "/app")

from engine.llm import get_llm
from mcp_server.tools.invoice_extractor import (
    InvoiceExtraction, _PROMPT_SALES, _PROMPT_PURCHASE,
)

SALES_DOC = """CRABBY PATTY
Premium Burger Shop & Catering Services
Commercial Street, Ground Floor, Bengaluru, KA
GSTIN: 29CRABP1234M1Z5

TAX INVOICE (SALE)
Invoice No: CP-2026-002
Date: May 05, 2026

BILL TO
Zomato Delivery
Order #5541A
Payment: Online Aggregator Payout

Items:
- Double Crabby Patty x2 - Rs 438
- Large Seaweed Fries x1 - Rs 119
Subtotal Rs 557, CGST Rs 13.93, SGST Rs 13.93
Total Rs 584.86
"""

PURCHASE_DOC = """CRABBY PATTY
Premium Burger Shop & Catering Services
Commercial Street, Ground Floor, Bengaluru, KA

PURCHASE BILL
Invoice No: SUPP-BUN-8891
Date: May 01, 2026

VENDOR
Ocean Blue Bakery & Flour Mills
Industrial Area, Phase 2
Payment: Net Banking (NEFT)

Items:
- Premium Sesame Burger Buns x500 - Rs 3,000
GST (5%) Rs 150
Total Rs 3,150
"""

llm = get_llm()

print("=== SALES PROMPT on the sales invoice ===")
r = llm.complete_text(
    _PROMPT_SALES + "\n\nDocument text:\n" + SALES_DOC,
    schema=InvoiceExtraction, max_tokens=900,
)
parsed = InvoiceExtraction.model_validate_json(r.text)
print(f"  vendor:     {parsed.vendor}    (expected: Zomato Delivery)")
print(f"  doc_type:   {parsed.document_type}")
print(f"  date:       {parsed.date}")
print(f"  amount:     {parsed.amount} {parsed.currency}")
print(f"  confidence: {parsed.confidence}")

print()
print("=== PURCHASE PROMPT on the purchase bill ===")
r = llm.complete_text(
    _PROMPT_PURCHASE + "\n\nDocument text:\n" + PURCHASE_DOC,
    schema=InvoiceExtraction, max_tokens=900,
)
parsed = InvoiceExtraction.model_validate_json(r.text)
print(f"  vendor:     {parsed.vendor}    (expected: Ocean Blue Bakery & Flour Mills)")
print(f"  doc_type:   {parsed.document_type}")
print(f"  date:       {parsed.date}")
print(f"  amount:     {parsed.amount} {parsed.currency}")
print(f"  confidence: {parsed.confidence}")
