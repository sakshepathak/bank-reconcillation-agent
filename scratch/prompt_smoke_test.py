"""
Simulate the extractor's behavior on the two user-provided PDFs by feeding
the same prompt to Gemini text mode with the document content as text.
Not identical to vision (no layout), but proves the prompt logic works.
"""
import sys
sys.path.insert(0, "/app")

from engine.llm import get_llm
from mcp_server.tools.invoice_extractor import InvoiceExtraction, _PROMPT

SALES = """[Document content as text — sales invoice]

CRABBY PATTY
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
- Double Crabby Patty x2 — Rs 438.00
- Large Seaweed Fries x1 — Rs 119.00
Subtotal Rs 557.00, CGST Rs 13.93, SGST Rs 13.93
Total Rs 584.86
"""

PURCHASE = """[Document content as text — purchase bill]

CRABBY PATTY
Premium Burger Shop & Catering Services
Commercial Street, Ground Floor, Bengaluru, KA
GSTIN: 29CRABP1234M1Z5

PURCHASE BILL
Invoice No: SUPP-BUN-8891
Date: May 01, 2026

VENDOR
Ocean Blue Bakery & Flour Mills
Industrial Area, Phase 2
Payment: Net Banking (NEFT)

Items:
- Premium Sesame Burger Buns x500 — Rs 3,000.00
GST (5%) Rs 150.00
Total Rs 3,150.00
"""

llm = get_llm()

for label, doc in [("SALES", SALES), ("PURCHASE", PURCHASE)]:
    full_prompt = _PROMPT + "\n\nDocument content:\n" + doc
    r = llm.complete_text(full_prompt, schema=InvoiceExtraction, max_tokens=500)
    try:
        parsed = InvoiceExtraction.model_validate_json(r.text)
        print(f"=== {label} ===")
        print(f"  provider:    {r.provider}")
        print(f"  doc_type:    {parsed.document_type}")
        print(f"  vendor:      {parsed.vendor}")
        print(f"  invoice_id:  {parsed.invoice_id}")
        print(f"  date:        {parsed.date}")
        print(f"  amount:      {parsed.amount} {parsed.currency}")
        print(f"  confidence:  {parsed.confidence}")
        print()
    except Exception as e:
        print(f"FAILED to parse: {e}")
        print(f"raw text: {r.text[:300]}")
        print()
