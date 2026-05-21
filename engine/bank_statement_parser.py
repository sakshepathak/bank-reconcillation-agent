"""
Bank statement parser — CSV passthrough + PDF extraction.

PDF strategy:
  1. Try fast text extraction via PyMuPDF (free, works for ~80% of bank PDFs
     that aren't scanned images).
  2. If text is meaningful, send to Gemini for structured parsing.
  3. If text extraction yields very little, send the PDF itself to Gemini —
     it handles scanned/image PDFs natively.

Output is the canonical DataFrame: columns date (ISO), description (string),
amount (signed: + credit / - debit). Identical to what the CSV path produces,
so the matching engine treats both paths the same.
"""
from __future__ import annotations

import io
import logging
import os
import sys

import pandas as pd
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.llm import LLMError, get_llm


log = logging.getLogger(__name__)


# ─── Schema ──────────────────────────────────────────────────────────────────

class _BankTxn(BaseModel):
    date: str = Field(description="Transaction date in YYYY-MM-DD format")
    description: str = Field(description="Transaction description exactly as on the statement")
    amount: float = Field(
        description="Signed amount: positive for credit/deposit, negative for debit/withdrawal"
    )


class BankStatementExtraction(BaseModel):
    transactions: list[_BankTxn]


# ─── Prompt ──────────────────────────────────────────────────────────────────

_PROMPT = """Extract every transaction row from this bank statement.

Rules:
- Use the transaction date (not the value or posting date). Convert to YYYY-MM-DD.
- "amount" is a single signed number: positive for credit/deposit, negative for
  debit/withdrawal. If the statement has separate Debit and Credit columns,
  collapse them into one signed number.
- Strip currency symbols and thousand separators from amount.
- IGNORE running balance columns, opening/closing balance lines, headers,
  footers, page numbers, account info, and totals/subtotals.
- IGNORE any line that doesn't represent an actual money movement.

Return only the JSON object — no commentary, no markdown fences."""


# ─── Public API ──────────────────────────────────────────────────────────────

def parse_bank_statement(file_bytes: bytes, mime: str) -> pd.DataFrame:
    """
    Parse a bank statement into the canonical DataFrame.

    Columns returned: date (str ISO), description (str), amount (float signed).
    Raises ValueError on unsupported MIME, LLMError if all providers fail.
    """
    if mime in {"text/csv", "application/vnd.ms-excel"}:
        return _parse_csv(file_bytes)
    if mime == "application/pdf":
        return _parse_pdf(file_bytes)
    raise ValueError(f"Unsupported bank statement format: {mime}")


# ─── CSV ────────────────────────────────────────────────────────────────────

def _parse_csv(file_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(file_bytes))


# ─── PDF: text-first, vision-fallback ───────────────────────────────────────

def _parse_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    text = _extract_text(pdf_bytes)
    if text and len(text) > 200:
        log.info("PDF text extraction succeeded (%d chars) — using text-mode LLM call", len(text))
        return _call_llm_text(text)

    log.info("PDF text extraction insufficient — falling back to native PDF vision")
    return _call_llm_pdf(pdf_bytes)


def _extract_text(pdf_bytes: bytes) -> str:
    """Pull all text from a PDF via PyMuPDF. Empty string if PDF is image-only."""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return "\n".join(page.get_text("text") for page in doc).strip()
        finally:
            doc.close()
    except Exception as e:  # noqa: BLE001
        log.warning("PDF text extraction failed: %s", e)
        return ""


def _call_llm_text(text: str) -> pd.DataFrame:
    """LLM parses already-extracted text — fast, cheap, no vision needed."""
    llm = get_llm()
    # Truncate to be safe on context limits (Gemini 2.5 handles 1M, but bills can be huge)
    prompt = _PROMPT + "\n\nBank statement text:\n" + text[:60_000]
    result = llm.complete_text(prompt, schema=BankStatementExtraction, max_tokens=8000)
    return _to_dataframe(result.text)


def _call_llm_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    """Native PDF call — Gemini handles multi-page bank statements in one shot."""
    llm = get_llm()
    result = llm.complete_pdf(_PROMPT, pdf_bytes, schema=BankStatementExtraction, max_tokens=8000)
    return _to_dataframe(result.text)


# ─── Schema validation → DataFrame ───────────────────────────────────────────

def _to_dataframe(raw_json_text: str) -> pd.DataFrame:
    try:
        parsed = BankStatementExtraction.model_validate_json(raw_json_text)
    except Exception:  # noqa: BLE001
        # Last-ditch: try to recover JSON object from any wrapping text
        import json
        try:
            obj = json.loads(raw_json_text)
        except json.JSONDecodeError:
            start, end = raw_json_text.find("{"), raw_json_text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("LLM returned no parseable JSON for bank statement")
            obj = json.loads(raw_json_text[start:end + 1])
        parsed = BankStatementExtraction.model_validate(obj)

    rows = [t.model_dump() for t in parsed.transactions]
    if not rows:
        raise ValueError("No transactions extracted from bank statement.")
    return pd.DataFrame(rows)
