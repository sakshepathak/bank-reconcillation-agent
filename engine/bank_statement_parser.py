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
#
# Canonical output columns:  date (ISO YYYY-MM-DD), description, amount (signed),
#                            balance_after (nullable).
#
# Handles every common UK / US / AU bank export shape:
#   TIDE       — Date, Amount (signed), Payee, Description, Reference
#   Barclays   — Date, Description, Amount (signed)
#   HSBC       — Date, Description, Debit, Credit (separate columns)
#   Lloyds     — Transaction Date, …, Debit Amount, Credit Amount
#   NatWest    — Date, Type, Description, Value, Balance
#   Wise / Revolut — similar shape to TIDE
#
# Column matching is case-insensitive and whitespace-tolerant.

_DATE_COLUMNS = [
    "date", "transaction date", "posting date", "booked date", "trans date",
    "value date", "completed date", "started date",
]
_AMOUNT_COLUMNS = ["amount", "value", "transaction amount"]
_DEBIT_COLUMNS = ["debit", "debit amount", "money out", "paid out", "withdrawal", "withdrawals", "out", "spent"]
_CREDIT_COLUMNS = ["credit", "credit amount", "money in", "paid in", "deposit", "deposits", "in", "received"]
_DESC_COLUMNS = ["description", "memo", "narrative", "details", "transaction details", "narration"]
_PAYEE_COLUMNS = ["payee", "merchant", "counterparty", "name", "beneficiary"]
_BALANCE_COLUMNS = ["balance", "running balance", "balance after"]


def _pick_column(cols: list[str], candidates: list[str]) -> str | None:
    for cand in candidates:
        if cand in cols:
            return cand
    return None


def _clean_money(series: pd.Series) -> pd.Series:
    """Strip currency symbols, thousand separators, parenthesised negatives."""
    if series.dtype.kind in "fi":
        return series.fillna(0).astype(float)
    s = series.fillna("").astype(str)
    s = s.str.replace(r"\((.*?)\)", r"-\1", regex=True)
    s = s.str.replace(r"[£$€¥₹,\s]", "", regex=True)
    return pd.to_numeric(s, errors="coerce").fillna(0).astype(float)


def _needs_dayfirst(series: pd.Series) -> bool:
    """
    Return False (ISO mode) when dates start with a 4-digit year.
    Return True only for DD/MM/YYYY or DD-MM-YYYY (UK bank export format).
    ISO dates (YYYY-MM-DD) must never use dayfirst — it swaps month and day.
    """
    import re
    sample = series.dropna().astype(str)
    if sample.empty:
        return True
    first = sample.iloc[0].strip()
    # Any date starting with 4-digit year is ISO — never dayfirst
    return not bool(re.match(r'^\d{4}[-/]', first))


def _to_iso(val: str) -> str | None:
    """
    Convert any date string to YYYY-MM-DD.
    ISO inputs stored as-is. All other formats parsed with dayfirst detection.
    """
    import re
    val = str(val).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', val):
        return val  # already ISO — never touches pandas, zero ambiguity
    try:
        df = not bool(re.match(r'^\d{4}', val))
        return pd.to_datetime(val, dayfirst=df).strftime('%Y-%m-%d')
    except Exception:
        return None


def _parse_csv(file_bytes: bytes) -> pd.DataFrame:
    """
    Parse a bank statement CSV into the canonical DataFrame.

    Robust to capitalised vs lowercase columns, DD-MM-YYYY vs ISO dates,
    signed Amount vs split Debit/Credit columns, currency symbols, commas,
    parenthesised negatives, and separate Payee + Description columns.
    """
    # Try the common encodings — UTF-8 first, then fall back
    raw = None
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            raw = pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise ValueError("Could not decode CSV in any common encoding")

    # Normalise column names
    raw.columns = [str(c).strip().lower() for c in raw.columns]
    cols = list(raw.columns)

    # ── Date ─────────────────────────────────────────────────────────────────
    date_col = _pick_column(cols, _DATE_COLUMNS)
    if not date_col:
        raise ValueError(f"No date column found. Got: {cols}")
    dates = pd.to_datetime(raw[date_col], dayfirst=_needs_dayfirst(raw[date_col]), errors="coerce")
    iso_dates = dates.dt.strftime("%Y-%m-%d")

    # ── Amount ───────────────────────────────────────────────────────────────
    amount_col = _pick_column(cols, _AMOUNT_COLUMNS)
    if amount_col:
        amounts = _clean_money(raw[amount_col])
    else:
        debit_col = _pick_column(cols, _DEBIT_COLUMNS)
        credit_col = _pick_column(cols, _CREDIT_COLUMNS)
        if not debit_col and not credit_col:
            raise ValueError(f"No 'Amount' or 'Debit'/'Credit' columns. Got: {cols}")
        debits = _clean_money(raw[debit_col]) if debit_col else pd.Series(0.0, index=raw.index)
        credits = _clean_money(raw[credit_col]) if credit_col else pd.Series(0.0, index=raw.index)
        amounts = credits - debits

    # ── Description (Payee + Description if both present) ────────────────────
    desc_col = _pick_column(cols, _DESC_COLUMNS)
    payee_col = _pick_column(cols, _PAYEE_COLUMNS)
    payee = raw[payee_col].fillna("").astype(str).str.strip() if payee_col else None
    desc = raw[desc_col].fillna("").astype(str).str.strip() if desc_col else None
    if payee is not None and desc is not None:
        descriptions = pd.Series(
            [(p + " — " + d) if p and d else (p or d) for p, d in zip(payee, desc)],
            index=raw.index,
        )
    elif desc is not None:
        descriptions = desc
    elif payee is not None:
        descriptions = payee
    else:
        raise ValueError(f"No description or payee column found. Got: {cols}")

    # ── Balance (optional) ───────────────────────────────────────────────────
    balance_col = _pick_column(cols, _BALANCE_COLUMNS)
    balances = _clean_money(raw[balance_col]) if balance_col else pd.Series([None] * len(raw))

    result = pd.DataFrame({
        "date": iso_dates,
        "description": descriptions,
        "amount": amounts,
        "balance_after": balances,
    })
    result = result.dropna(subset=["date"]).reset_index(drop=True)
    return result


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
    # json_mode (not schema=): Gemini's schema-constrained decoding truncates
    # variable-length lists mid-string, producing invalid JSON. json_mode just
    # enforces valid JSON and we validate manually in _to_dataframe.
    result = llm.complete_text(prompt, json_mode=True, max_tokens=8000)
    return _to_dataframe(result.text)


def _call_llm_pdf(pdf_bytes: bytes) -> pd.DataFrame:
    """Native PDF call — Gemini handles multi-page bank statements in one shot."""
    llm = get_llm()
    result = llm.complete_pdf(_PROMPT, pdf_bytes, json_mode=True, max_tokens=8000)
    return _to_dataframe(result.text)


# ─── Schema validation → DataFrame ───────────────────────────────────────────

def _loads_lenient(text: str) -> dict:
    """
    Parse a JSON object out of an LLM response, tolerating the three ways an LLM
    can wrap or break it: markdown fences, surrounding prose, and a transactions
    array that got truncated mid-way (so the whole object won't parse, but the
    complete transaction rows still can be salvaged).
    """
    import json
    import re

    s = (text or "").strip()

    # 1. Strip markdown code fences if present (```json … ```).
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()

    # 2. Straight parse.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 3. Narrow to the outermost {...} and try again.
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 4. Salvage complete transaction objects from a truncated array.
    objs = []
    for m in re.finditer(r"\{[^{}]*\}", s):
        try:
            o = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if "date" in o and "amount" in o:
            objs.append(o)
    if objs:
        log.warning("Bank statement JSON was malformed/truncated — salvaged %d rows", len(objs))
        return {"transactions": objs}

    raise ValueError(
        f"LLM returned unparseable JSON for the bank statement. "
        f"Response started with: {s[:150]!r}"
    )


def _to_dataframe(raw_json_text: str) -> pd.DataFrame:
    parsed = BankStatementExtraction.model_validate(_loads_lenient(raw_json_text))
    rows = [t.model_dump() for t in parsed.transactions]
    if not rows:
        raise ValueError("No transactions extracted from bank statement.")
    return pd.DataFrame(rows)
