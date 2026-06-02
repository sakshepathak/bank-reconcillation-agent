"""
Invoice extraction — pulls structured data from PDFs/images via the LLM layer.

Primary provider is Gemini (native PDF, schema-enforced output). OpenRouter
(Claude) is automatic fallback for image inputs and rendered PDF pages.

Design:
  - One small Pydantic schema (InvoiceExtraction) describes what we need.
  - For PDFs: pass bytes straight to Gemini — no PyMuPDF rendering needed.
  - For images: same call, different mime type.
  - extract_batch parallelises across files with bounded concurrency (gentle
    on rate limits) and preserves input order.

Pure module. No DB writes. No UI. Caller persists results.
"""
from __future__ import annotations

import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import settings
from engine.llm import LLMError, get_llm


def _normalize_date(raw: str) -> str:
    """Convert common date formats to YYYY-MM-DD. Assumes DD/MM/YYYY for ambiguous inputs."""
    import re
    raw = (raw or "").strip()
    if not raw:
        return raw

    # Already YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw

    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }

    # "15 Jan 2025" / "15-Jan-2025" / "15 January 2025"
    m = re.match(r"(\d{1,2})[\s\-/]([A-Za-z]+)[\s\-/](\d{4})", raw)
    if m:
        d, mon, y = m.group(1), m.group(2)[:3].lower(), m.group(3)
        if mon in month_map:
            return f"{y}-{month_map[mon]}-{int(d):02d}"

    # "Jan 15 2025" / "January 15, 2025"
    m = re.match(r"([A-Za-z]+)[\s\-/](\d{1,2})[,\s\-/]+(\d{4})", raw)
    if m:
        mon, d, y = m.group(1)[:3].lower(), m.group(2), m.group(3)
        if mon in month_map:
            return f"{y}-{month_map[mon]}-{int(d):02d}"

    # DD/MM/YYYY or DD-MM-YYYY (treat as day-first)
    m = re.match(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})", raw)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
        # If first part > 12, it must be day
        day, mon = (a, b) if a > 12 else (a, b)
        return f"{y}-{mon:02d}-{day:02d}"

    return raw


log = logging.getLogger(__name__)


# ─── Schemas ─────────────────────────────────────────────────────────────────

class InvoiceExtraction(BaseModel):
    """Structured output schema the LLM is constrained to — one document."""

    vendor: str = Field(
        description="The COUNTERPARTY — the OTHER party on this transaction, "
                    "NOT the business on the letterhead. For sales invoices, "
                    "this is the CUSTOMER (Bill To). For purchase bills, this "
                    "is the SUPPLIER (Vendor / From section)."
    )
    document_type: str = Field(
        default="unknown",
        description="One of: 'sales' (money INCOMING — shop sold to a customer) "
                    "or 'purchase' (money OUTGOING — shop bought from a supplier) "
                    "or 'unknown' if it can't be determined.",
    )
    invoice_id: Optional[str] = Field(default=None, description="Invoice or bill number, null if absent")
    date: str = Field(description="Document date in YYYY-MM-DD format")
    amount: float = Field(description="Total amount as positive number, no symbol or commas")
    currency: str = Field(default="USD", description="3-letter ISO currency code (USD, INR, EUR, GBP)")
    confidence: float = Field(default=0.5, description="Self-assessed confidence 0.0–1.0")


class InvoiceBatchExtraction(BaseModel):
    """Schema for extracting multiple documents from a single file."""
    documents: list[InvoiceExtraction] = Field(
        description="Every invoice or bill found in the file, one object per document."
    )


@dataclass
class ExtractionResult:
    """One file in → one result out. `error` set if extraction failed."""

    source_filename: str
    mime_type: str
    vendor: str = ""                       # the COUNTERPARTY, not the letterhead
    document_type: str = "unknown"         # "sales" | "purchase" | "unknown"
    invoice_id: Optional[str] = None
    date: str = ""
    amount: float = 0.0
    currency: str = "USD"
    confidence: float = 0.0
    raw_json: dict = field(default_factory=dict)
    error: Optional[str] = None
    provider: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and self.amount != 0.0


# ─── Prompt ──────────────────────────────────────────────────────────────────

# Three specialized prompts. The user declares the doc_type at upload time,
# so the model gets a single unambiguous instruction instead of having to
# decide between sales vs purchase by reading layout cues.

_PROMPT_SALES = """Extract data from this SALES INVOICE for bank reconciliation.

The user's business ISSUED this invoice TO a customer. The customer will pay
the business. The business's name and logo are in the LETTERHEAD at the top —
IGNORE the letterhead. Find the CUSTOMER.

Fields:
  • "vendor": the CUSTOMER's name. Look in "BILL TO", "CUSTOMER", "SHIP TO",
    "INVOICED TO" sections. NEVER use the letterhead company name.
  • "document_type": always "sales"
  • "invoice_id": the invoice/document number (e.g. "INV-2026-001")
  • "date": invoice date — convert to YYYY-MM-DD (document dates are in DD/MM/YYYY format)
  • "amount": total amount as positive number, no symbol or commas
  • "currency": 3-letter ISO code (USD, INR, EUR, GBP, AED, ...)
  • "confidence": 0.0–1.0 — your certainty in the CUSTOMER identification

Return JSON only. No markdown, no commentary."""


_PROMPT_PURCHASE = """Extract data from this PURCHASE BILL for bank reconciliation.

A SUPPLIER issued this bill TO the user's business. The business will pay the
supplier. The business may have re-printed this on its own letterhead template —
IGNORE the letterhead. Find the SUPPLIER.

Fields:
  • "vendor": the SUPPLIER's name. Look in "VENDOR", "SUPPLIER", "FROM",
    "BILL FROM" sections. NEVER use the letterhead company name.
  • "document_type": always "purchase"
  • "invoice_id": the bill/invoice number
  • "date": bill date — convert to YYYY-MM-DD (document dates are in DD/MM/YYYY format)
  • "amount": total amount as positive number, no symbol or commas
  • "currency": 3-letter ISO code
  • "confidence": 0.0–1.0 — your certainty in the SUPPLIER identification

Return JSON only. No markdown, no commentary."""


_PROMPT_UNKNOWN = """Extract data from this invoice or bill for bank reconciliation.

The user did not specify whether this is a sales invoice or a purchase bill.
Determine the COUNTERPARTY — the OTHER party in the transaction (not the
business in the letterhead).

  • If "TAX INVOICE (SALE)" / "BILL TO" present → document_type "sales",
    vendor = the customer in BILL TO.
  • If "PURCHASE BILL" / "VENDOR" / "FROM" present → document_type "purchase",
    vendor = the supplier.
  • Otherwise → document_type "unknown", confidence ≤ 0.5.

Return JSON only. No markdown."""


_PROMPT_SALES_MULTI = """Extract ALL sales invoices from this document.

The file may contain one invoice or many — on separate pages or sections.
Extract EVERY invoice you find, one object per invoice.

For each invoice:
  • "vendor": the CUSTOMER's name (BILL TO / INVOICED TO section). NEVER use the letterhead company.
  • "document_type": always "sales"
  • "invoice_id": the invoice number (e.g. INV-001), null if missing
  • "date": invoice date — convert to YYYY-MM-DD (document dates are in DD/MM/YYYY format)
  • "amount": total amount as a positive number, no currency symbol or commas
  • "currency": 3-letter ISO code (GBP, USD, INR, EUR, …)
  • "confidence": 0.0–1.0

Return JSON only — no markdown, no commentary:
{"documents": [ {...}, {...}, ... ]}"""


_PROMPT_PURCHASE_MULTI = """Extract ALL purchase bills from this document.

The file may contain one bill or many — on separate pages or sections.
Extract EVERY bill you find, one object per bill.

For each bill:
  • "vendor": the SUPPLIER's name (VENDOR / FROM / BILL FROM section). NEVER use the letterhead company.
  • "document_type": always "purchase"
  • "invoice_id": the bill number, null if missing
  • "date": bill date — convert to YYYY-MM-DD (document dates are in DD/MM/YYYY format)
  • "amount": total amount as a positive number, no currency symbol or commas
  • "currency": 3-letter ISO code (GBP, USD, INR, EUR, …)
  • "confidence": 0.0–1.0

Return JSON only — no markdown, no commentary:
{"documents": [ {...}, {...}, ... ]}"""


_PROMPT_UNKNOWN_MULTI = """Extract ALL invoices or bills from this document.

The file may contain one or many documents — on separate pages or sections.
Extract EVERY document you find, one object per document.

For each document:
  • "vendor": the COUNTERPARTY (customer if it's a sale, supplier if it's a purchase)
  • "document_type": "sales" if money comes in, "purchase" if money goes out, "unknown" if unclear
  • "invoice_id": document number, null if missing
  • "date": YYYY-MM-DD
  • "amount": total as a positive number
  • "currency": 3-letter ISO code
  • "confidence": 0.0–1.0

Return JSON only:
{"documents": [ {...}, {...}, ... ]}"""


def _select_prompt(doc_type: str) -> str:
    return {
        "sales": _PROMPT_SALES,
        "purchase": _PROMPT_PURCHASE,
    }.get((doc_type or "").lower(), _PROMPT_UNKNOWN)


def _select_multi_prompt(doc_type: str) -> str:
    return {
        "sales": _PROMPT_SALES_MULTI,
        "purchase": _PROMPT_PURCHASE_MULTI,
    }.get((doc_type or "").lower(), _PROMPT_UNKNOWN_MULTI)


# ─── Public functions exposed by this module ─────────────────────────────────

def _pdf_first_page_png(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    """Render page 1 of a PDF to PNG. Used by the invoice viewer dialog."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def extract_invoice(
    file_bytes: bytes, filename: str, mime: str, doc_type: str = "unknown",
) -> ExtractionResult:
    """
    Extract a single invoice. Resilient — captures provider errors into the result.

    `doc_type` tells us which specialized prompt to use:
      - "sales": look for the CUSTOMER (BILL TO section)
      - "purchase": look for the SUPPLIER (VENDOR / FROM section)
      - "unknown": let the model figure it out (less accurate)
    """
    if mime == "application/pdf":
        return _extract_pdf(file_bytes, filename, mime, doc_type)
    if mime in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
        return _extract_image(file_bytes, filename, mime, doc_type)
    return ExtractionResult(
        source_filename=filename, mime_type=mime, document_type=doc_type,
        error=f"unsupported mime: {mime}",
    )


def extract_batch(files: list[tuple]) -> list[ExtractionResult]:
    """
    Run extract_invoice on each (filename, bytes, mime[, doc_type]) in parallel.

    Accepts 3-tuples (legacy, doc_type defaults to "unknown") or 4-tuples
    (preferred — user has declared the doc_type at upload time).

    Preserves input order. Bounded by settings.EXTRACT_PARALLELISM.
    """
    if not files:
        return []

    # Normalize to 4-tuples
    normalized: list[tuple[str, bytes, str, str]] = []
    for f in files:
        if len(f) == 4:
            name, b, mime, doc_type = f
        else:
            name, b, mime = f
            doc_type = "unknown"
        normalized.append((name, b, mime, doc_type))

    workers = max(1, min(len(normalized), settings.EXTRACT_PARALLELISM))
    results: list[Optional[ExtractionResult]] = [None] * len(normalized)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {
            pool.submit(extract_invoice, b, name, mime, doc_type): i
            for i, (name, b, mime, doc_type) in enumerate(normalized)
        }
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:  # noqa: BLE001
                name, _, mime, doc_type = normalized[idx]
                results[idx] = ExtractionResult(
                    source_filename=name, mime_type=mime,
                    document_type=doc_type, error=str(e),
                )

    return [r for r in results if r is not None]


def extract_multi_from_file(
    file_bytes: bytes, filename: str, mime: str, doc_type: str = "unknown",
) -> list[ExtractionResult]:
    """
    Extract ALL invoices/bills from a single file.

    Designed for PDFs that bundle multiple documents (e.g. a month of bills
    printed as one file, or a sales run exported as a single PDF).

    Falls back to a list containing a single extraction if the file looks
    like it only has one document, so callers never need to branch.
    """
    if mime not in {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp"}:
        return [ExtractionResult(
            source_filename=filename, mime_type=mime, document_type=doc_type,
            error=f"unsupported mime for multi-extraction: {mime}",
        )]

    prompt = _select_multi_prompt(doc_type)
    try:
        llm = get_llm()
        # Use json_mode (not schema=) for batch extraction.
        # Gemini's constrained schema decoding truncates JSON mid-string when
        # generating variable-length lists — json_mode just enforces valid JSON
        # without the structural constraint, and we validate manually after.
        if mime == "application/pdf":
            result = llm.complete_pdf(prompt, file_bytes, json_mode=True, max_tokens=8000)
        else:
            result = llm.complete_image(prompt, file_bytes, mime, json_mode=True, max_tokens=8000)
    except LLMError as e:
        return [ExtractionResult(
            source_filename=filename, mime_type=mime, document_type=doc_type, error=str(e),
        )]

    return _parse_batch_response(result, filename, mime, doc_type)


# ─── Internals ───────────────────────────────────────────────────────────────

def _extract_pdf(pdf_bytes: bytes, filename: str, mime: str, doc_type: str) -> ExtractionResult:
    """Gemini handles PDFs natively — no rendering required."""
    prompt = _select_prompt(doc_type)
    try:
        llm = get_llm()
        result = llm.complete_pdf(prompt, pdf_bytes, schema=InvoiceExtraction, max_tokens=900)
    except LLMError as e:
        return ExtractionResult(
            source_filename=filename, mime_type=mime,
            document_type=doc_type, error=str(e),
        )
    return _parse_response(result, filename, mime, expected_doc_type=doc_type)


def _extract_image(image_bytes: bytes, filename: str, mime: str, doc_type: str) -> ExtractionResult:
    """Image path — works for both Gemini and OpenRouter providers."""
    prompt = _select_prompt(doc_type)
    try:
        llm = get_llm()
        result = llm.complete_image(prompt, image_bytes, mime, schema=InvoiceExtraction, max_tokens=900)
    except LLMError as e:
        return ExtractionResult(
            source_filename=filename, mime_type=mime,
            document_type=doc_type, error=str(e),
        )
    return _parse_response(result, filename, mime, expected_doc_type=doc_type)


def _parse_batch_response(llm_result, filename: str, mime: str,
                           expected_doc_type: str = "unknown") -> list[ExtractionResult]:
    """Parse a batch LLM response into a list of ExtractionResults."""
    import json
    try:
        batch = InvoiceBatchExtraction.model_validate_json(llm_result.text)
    except Exception:  # noqa: BLE001
        # Try to fish out a JSON object from any wrapper text
        try:
            text = llm_result.text
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                batch = InvoiceBatchExtraction.model_validate_json(text[start:end + 1])
            else:
                raise ValueError("no JSON object found")
        except Exception as e:
            log.warning("batch extraction bad JSON for %s: %s", filename, e)
            return [ExtractionResult(
                source_filename=filename, mime_type=mime,
                document_type=expected_doc_type,
                error=f"batch schema mismatch: {e}",
                raw_json={"raw_text": llm_result.text[:500]},
                provider=getattr(llm_result, "provider", ""),
            )]

    if not batch.documents:
        return [ExtractionResult(
            source_filename=filename, mime_type=mime,
            document_type=expected_doc_type,
            error="LLM returned no documents in batch",
        )]

    results = []
    for inv in batch.documents:
        final_doc_type = (
            expected_doc_type
            if expected_doc_type and expected_doc_type != "unknown"
            else (inv.document_type or "unknown").strip().lower()
        )
        results.append(ExtractionResult(
            source_filename=filename,
            mime_type=mime,
            vendor=inv.vendor.strip(),
            document_type=final_doc_type,
            invoice_id=(inv.invoice_id.strip() if inv.invoice_id else None),
            date=_normalize_date(inv.date),
            amount=float(inv.amount or 0.0),
            currency=(inv.currency or "USD").strip().upper(),
            confidence=float(inv.confidence or 0.5),
            raw_json=inv.model_dump(),
            provider=getattr(llm_result, "provider", ""),
        ))
    return results


def _parse_response(llm_result, filename: str, mime: str,
                     expected_doc_type: str = "unknown") -> ExtractionResult:
    """Validate the LLM response against the schema and coerce to ExtractionResult."""
    try:
        invoice = InvoiceExtraction.model_validate_json(llm_result.text)
    except Exception as e:  # noqa: BLE001
        # Fallback: try the legacy JSON-recovery in LLMResult
        try:
            raw = llm_result.json()
            invoice = InvoiceExtraction.model_validate(raw)
        except Exception as e2:  # noqa: BLE001
            log.warning("extraction returned invalid schema for %s: %s", filename, e2)
            return ExtractionResult(
                source_filename=filename, mime_type=mime,
                error=f"schema mismatch: {e2}",
                raw_json={"raw_text": llm_result.text[:500]},
                provider=llm_result.provider,
            )

    # User-declared doc_type wins — model's classification is informational only.
    final_doc_type = (
        expected_doc_type
        if expected_doc_type and expected_doc_type != "unknown"
        else (invoice.document_type or "unknown").strip().lower()
    )

    return ExtractionResult(
        source_filename=filename,
        mime_type=mime,
        vendor=invoice.vendor.strip(),
        document_type=final_doc_type,
        invoice_id=(invoice.invoice_id.strip() if invoice.invoice_id else None),
        date=_normalize_date(invoice.date),
        amount=float(invoice.amount or 0.0),
        currency=(invoice.currency or "USD").strip().upper(),
        confidence=float(invoice.confidence or 0.5),
        raw_json=invoice.model_dump(),
        provider=llm_result.provider,
    )
