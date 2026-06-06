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
import re
import sys

import pandas as pd
from pydantic import BaseModel, Field, field_validator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.llm import LLMError, get_llm


log = logging.getLogger(__name__)


# ─── Schema ──────────────────────────────────────────────────────────────────

class _BankTxn(BaseModel):
    date: str = Field(description="Transaction date in YYYY-MM-DD format")
    # Lenient: the model occasionally names this field differently (narration,
    # details…) or omits it — _coerce maps common aliases, and the default keeps
    # validation from crashing the whole statement over one missing label.
    description: str = Field(default="", description="Transaction description exactly as on the statement")
    amount: float = Field(
        default=0.0,
        description="Signed amount: positive for credit/deposit, negative for debit/withdrawal",
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v):
        # The model may hand back a string ("1,23,456.78", "₹450", "(50)").
        return _to_number(v) if isinstance(v, str) else v


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

def parse_bank_statement(file_bytes: bytes, mime: str, default_dayfirst: bool = True) -> pd.DataFrame:
    """
    Parse a bank statement into the canonical DataFrame.

    Columns returned: date (str ISO), description (str), amount (float signed).
    `default_dayfirst` only breaks ambiguous DD/MM-vs-MM/DD dates where the data
    gives no clue (set it False for US/month-first locales).
    Raises ValueError on unsupported MIME, LLMError if all providers fail.
    """
    if mime in {"text/csv", "application/vnd.ms-excel"}:
        return _parse_csv(file_bytes, default_dayfirst=default_dayfirst)
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
    "txn date", "tran date", "transaction dt", "date of transaction",
    "value date", "completed date", "started date", "date posted",
    # multilingual: German / Spanish / French
    "datum", "buchungstag", "valuta", "fecha", "fecha valor", "date comptable",
    "date operation",
]
_AMOUNT_COLUMNS = ["amount", "value", "transaction amount", "amt",
                   "betrag", "importe", "montant"]
_DEBIT_COLUMNS = ["debit", "debit amount", "money out", "paid out", "withdrawal",
                  "withdrawals", "out", "spent", "payments", "withdrawals/debits",
                  "soll", "cargo", "debito"]
_CREDIT_COLUMNS = ["credit", "credit amount", "money in", "paid in", "deposit",
                   "deposits", "in", "received", "deposits/credits",
                   "haben", "abono", "credito"]
_DESC_COLUMNS = ["description", "memo", "narrative", "details", "transaction details",
                 "narration", "particulars", "beschreibung", "verwendungszweck",
                 "buchungstext", "umsatz", "concepto", "libelle", "libellé"]
_PAYEE_COLUMNS = ["payee", "merchant", "counterparty", "name", "beneficiary"]
_BALANCE_COLUMNS = ["balance", "running balance", "balance after", "closing balance", "saldo"]
# A separate indicator column whose value (DR/CR, Dr/Cr, Debit/Credit) sets the
# SIGN of an otherwise always-positive Amount column.
_TYPE_COLUMNS = ["type", "dr/cr", "cr/dr", "drcr", "debit/credit", "d/c",
                 "transaction type", "txn type", "indicator"]

# Words that make up balance-carry / total / sub-total marker rows (across the
# languages we see). A row is a marker — NOT a real money movement — only when
# EVERY word left in its description (after stripping digits and punctuation) is
# one of these. That drops "OPENING BALANCE B/F", "Saldo Vortrag", "TOTAL
# MOVIMIENTOS", "Balance Carried Forward" while KEEPING real merchants such as
# "Total Wine & More", "Total Gym Membership" or "Balance transfer to Amex".
_BALANCE_TOKENS = {
    "opening", "closing", "balance", "bal", "brought", "carried", "forward",
    "fwd", "bfwd", "cfwd", "bf", "cf", "b", "c", "f", "total", "totals",
    "subtotal", "sub", "grand", "activity", "movement", "movements",
    "movimientos", "summary", "statement", "stmt", "op", "cl",
    # foreign opening/closing balance words (DE / ES / IT / NL / FR / PT)
    "saldo", "vortrag", "neuer", "neu", "alt", "anfang", "aktuell", "inicial",
    "iniziale", "finale", "final", "anterior", "anterieur", "precedent", "nuevo",
    "anfangssaldo", "endsaldo", "beginsaldo", "eindsaldo", "beginbalans",
    "eindbalans", "solde", "initial",
}

# Distinctive multi-word balance/total PHRASES that never occur inside a real
# merchant name — matched anywhere in the description so verbose marker rows
# like "Balance brought forward from previous statement" or "Closing balance as
# at 30 April" are dropped even though they contain ordinary extra words.
_BALANCE_PHRASE_RE = re.compile(
    r"(?i)\b("
    r"brought forward|carried forward|opening balance|closing balance|"
    r"balance forward|statement balance|balance b\s*/?\s*fwd|balance c\s*/?\s*fwd|"
    r"balance b\s*/\s*f|balance c\s*/\s*f|b\s*/\s*fwd|c\s*/\s*fwd|"
    r"total of \d+ transactions?|saldo (?:vortrag|inicial|iniziale|anterior)|"
    r"anfangssaldo|endsaldo|beginsaldo|eindsaldo"
    r")\b"
)


def _is_balance_row(desc) -> bool:
    s = str(desc).strip()
    if not s:
        return False
    if _BALANCE_PHRASE_RE.search(s):
        return True
    words = re.sub(r"[^a-z]+", " ", s.lower()).split()
    return bool(words) and all(w in _BALANCE_TOKENS for w in words)


def _pick_column(cols: list[str], candidates: list[str]) -> str | None:
    """
    Match a wanted column against the CSV's actual columns.

    Handles real-world header variants that a plain exact match misses:
      • currency / unit suffixes — "Withdrawal (USD)", "Amount (GBP)", "Debit (£)"
      • the candidate as the leading word — "Withdrawal Amount", "Credit Amount"

    Returns the ORIGINAL column name (so the caller can index `raw[col]`).
    """
    import re

    def _base(c: str) -> str:
        # drop a trailing parenthetical/currency suffix: "withdrawal (usd)" -> "withdrawal"
        return re.sub(r"\s*\([^)]*\)\s*$", "", c).strip()

    # 1. exact match
    for cand in candidates:
        if cand in cols:
            return cand

    # 2. match after stripping a currency/unit suffix
    base_map: dict[str, str] = {}
    for c in cols:
        base_map.setdefault(_base(c), c)
    for cand in candidates:
        if cand in base_map:
            return base_map[cand]

    # 3. candidate is the leading word of a column (≥4 chars so short tokens
    #    like "in"/"out" can't false-match unrelated headers)
    for cand in candidates:
        if len(cand) >= 4:
            for c in cols:
                k = _base(c)
                if k == cand or k.startswith(cand + " "):
                    return c
    return None


def _to_number(raw_val, eu: bool = False) -> float:
    """
    Parse one money cell to a signed float. Handles, in any combination:
      • currency symbols and spaces (£ $ € ¥ ₹, "USD", NBSP)
      • accounting parentheses for negatives — "(350.00)" → -350.00
      • trailing-minus negatives — "45.27-" → -45.27   (US/Quicken style)
      • US thousands + decimal     — "1,234.56" → 1234.56
      • European thousands + decimal — "1.234,56" → 1234.56  and "89,90" → 89.90
    Blank / non-numeric cells become 0.0.
    """
    if raw_val is None:
        return 0.0
    if isinstance(raw_val, (int, float)):
        try:
            return 0.0 if pd.isna(raw_val) else float(raw_val)
        except (ValueError, TypeError):
            return 0.0

    s = str(raw_val).strip()
    if not s or s.lower() in ("nan", "none", "nat", "-", "--", "n/a"):
        return 0.0

    neg = False

    # Sign carried by a Dr/Cr indicator inside the cell ("2,000.00 Dr" — SBI/
    # Indian passbook style). Dr/Db = debit (negative); Cr/Cd = credit.
    m = re.search(r"\b(dr|db|cr|cd)\b\.?\s*$", s, re.I)
    if m:
        if m.group(1).lower() in ("dr", "db"):
            neg = not neg
        s = s[:m.start()].strip()

    if s.startswith("(") and s.endswith(")"):   # accounting negative
        neg = not neg
        s = s[1:-1].strip()
    if s.endswith("-"):                          # trailing minus
        neg = not neg
        s = s[:-1].strip()
    if s.startswith("-"):
        neg = not neg
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    s = re.sub(r"[^0-9.,]", "", s)
    if not s:
        return 0.0

    if "." in s and "," in s:
        # both present → the RIGHTMOST is the decimal separator
        if s.rfind(",") > s.rfind("."):      # European: 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                 # US: 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        if s.count(",") == 1 and re.search(r",\d{1,2}$", s):
            s = s.replace(",", ".")          # decimal comma: 23,99
        else:
            s = s.replace(",", "")           # thousands: 1,234 / 1,23,456
    elif "." in s:
        if s.count(".") >= 2:                # 1.234.567 → dots are thousands
            s = s.replace(".", "")
        elif eu:                             # European column → dot is thousands
            s = s.replace(".", "")
        # else single dot in a US-style column → decimal, keep as-is

    try:
        val = float(s)
    except ValueError:
        return 0.0
    return -val if neg else val


def _clean_money(series: pd.Series) -> pd.Series:
    """
    Vectorised money parsing. Decides the column's decimal convention ONCE
    (European comma-decimal vs US dot-decimal) so an ambiguous lone-dot value
    like "1.500" is read consistently with the rest of the column.
    """
    if series.dtype.kind in "fi":
        return series.fillna(0).astype(float)
    vals = series.fillna("").astype(str)
    comma_dec = vals.str.contains(r"\d,\d{1,2}(?:\D|$)", regex=True).sum()   # 23,99
    us_dec = vals.str.contains(r"\d\.\d{1,2}(?:\D|$)", regex=True).sum()      # 23.99
    dot_thou = vals.str.contains(r"\d\.\d{3}(?:\D|$)", regex=True).sum()      # 1.000 / 1.234
    multidot = vals.str.contains(r"\d\.\d{3}\.\d", regex=True).sum()          # 1.234.567
    # European when commas are the decimal, OR there are multi-dot thousands,
    # OR every dotted value is dot-3-digits with no plain US "x.yy" decimal
    # anywhere (a whole-number EU thousands column like 1.000 / 2.500).
    eu = (comma_dec > us_dec) or (multidot > 0) or (dot_thou > 0 and us_dec == 0)
    return vals.apply(lambda v: _to_number(v, eu=eu)).astype(float)


def _detect_dayfirst(series: pd.Series, default_dayfirst: bool = True) -> bool:
    """
    Decide DD/MM vs MM/DD for a WHOLE date column by scanning every value (not
    just the first row — a column can start ISO and continue DD/MM). A value
    whose first field is >12 proves day-first; a second field >12 proves
    month-first — actual data always wins. Only when EVERY value is ambiguous
    (both fields ≤12, e.g. a US export where all dates fall on the 1st–12th) do
    we fall back to `default_dayfirst`, which the caller sets from the org's
    country (US → month-first).
    """
    day_votes = month_votes = 0
    for v in series.dropna().astype(str):
        m = re.match(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{2,4}", v.strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            day_votes += 1
        elif b > 12 and a <= 12:
            month_votes += 1
    if day_votes or month_votes:
        return day_votes >= month_votes
    return default_dayfirst


def _to_iso(val, dayfirst: bool = True) -> str | None:
    """
    Convert ONE date string to YYYY-MM-DD. ISO and YYYY/MM/DD are handled
    directly (zero ambiguity); everything else is parsed with the column-wide
    `dayfirst` decision. Returns None for non-dates (e.g. footer labels).
    """
    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)            # ISO (maybe with time)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$", s)  # YYYY/MM/DD
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    try:
        return pd.to_datetime(s, dayfirst=dayfirst).strftime("%Y-%m-%d")
    except Exception:
        return None


def _detect_delimiter(text: str) -> str:
    """
    Pick the delimiter by counting candidates across the data lines. pandas'
    own sniffer (sep=None) mis-detects pipe-delimited files (it once chose 'e'),
    so we decide explicitly among comma / semicolon / tab / pipe.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()][:25]
    if not lines:
        return ","
    best, best_score = ",", -1.0
    for d in (",", ";", "\t", "|"):
        counts = [ln.count(d) for ln in lines]
        present = sum(1 for c in counts if c > 0)
        if present == 0:
            continue
        score = present + sum(counts) / len(lines)  # favour consistent + frequent
        if score > best_score:
            best, best_score = d, score
    return best


def _decode_csv(file_bytes: bytes) -> str:
    """
    Decode CSV bytes to text. An Excel-on-Windows export can glue a UTF-8 BOM
    (EF BB BF) onto a Windows-1252 body, where utf-8 fails and cp1252 then turns
    the 3 BOM bytes into the garbage prefix "ï»¿". So we strip the BOM at the
    BYTE level first, then try utf-8 → cp1252 → latin-1.
    """
    # UTF-16 (Excel "Unicode Text" / some bank exports): a FF FE / FE FF BOM, or
    # — without a BOM — lots of interleaved null bytes. Must be handled before
    # cp1252/latin-1, which would "succeed" by misreading the nulls and wipe text.
    if file_bytes[:2] in (b"\xff\xfe", b"\xfe\xff") or file_bytes[:2000].count(b"\x00") > 64:
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return file_bytes.decode(enc).lstrip("﻿")
            except (UnicodeDecodeError, UnicodeError):
                continue

    if file_bytes[:3] == b"\xef\xbb\xbf":
        file_bytes = file_bytes[3:]
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return file_bytes.decode(enc).lstrip("﻿")
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace").lstrip("﻿")


def _find_header_row(lines: list[str], delim: str) -> int:
    """
    Find the transaction-table header, skipping any metadata preamble.

    The header is the first line that (a) splits into ≥3 fields by the detected
    delimiter and (b) has one cell naming a date column AND another naming a
    money/description column. The ≥3-field rule rejects preamble prose like
    "Statement Date and Balance Summary" (which contains 'date' and 'balance'
    but isn't a real header). Falls back to the first ≥3-field line, then 0.
    """
    date_set = set(_DATE_COLUMNS)
    money_set = (set(_AMOUNT_COLUMNS) | set(_DEBIT_COLUMNS) | set(_CREDIT_COLUMNS)
                 | set(_DESC_COLUMNS) | set(_BALANCE_COLUMNS) | set(_PAYEE_COLUMNS))

    def _cells(line: str) -> list[str]:
        return [re.sub(r"\s*\([^)]*\)\s*$", "", c.strip().lower()).strip()
                for c in line.split(delim)]

    def _matches(cell: str, names: set[str]) -> bool:
        return cell in names or any(cell.startswith(n + " ") for n in names if len(n) >= 4)

    for i, line in enumerate(lines[:80]):
        cells = _cells(line)
        if len(cells) < 3:
            continue
        if any(_matches(c, date_set) for c in cells) and any(_matches(c, money_set) for c in cells):
            return i
    for i, line in enumerate(lines[:80]):
        if len(line.split(delim)) >= 3:
            return i
    return 0


def _parse_csv(file_bytes: bytes, default_dayfirst: bool = True) -> pd.DataFrame:
    """
    Parse a bank statement CSV. Tries a fast deterministic parse first; if the
    file is too messy for that (metadata preambles, odd delimiters, ragged
    rows), falls back to the same LLM text extraction the PDF path uses — so a
    real-world export still works instead of erroring out.
    """
    try:
        return _parse_csv_structured(file_bytes, default_dayfirst=default_dayfirst)
    except Exception as e:  # noqa: BLE001
        log.info("Structured CSV parse failed (%s) — falling back to LLM extraction.", e)
        return _call_llm_text(_decode_csv(file_bytes))


def _parse_csv_structured(file_bytes: bytes, default_dayfirst: bool = True) -> pd.DataFrame:
    """
    Deterministic CSV parse into the canonical DataFrame.

    Robust to capitalised vs lowercase columns, DD-MM-YYYY vs ISO dates,
    signed Amount vs split Debit/Credit columns, currency symbols, commas,
    parenthesised negatives, separate Payee + Description columns, and a
    metadata preamble above the transaction table.
    """
    text = _decode_csv(file_bytes)
    # Normalise line endings — pandas' reader doesn't treat a lone CR (old-Mac /
    # some bank exports) as a row break, which would collapse the whole file.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    delim = _detect_delimiter(text)
    raw = pd.read_csv(
        io.StringIO(text),
        skiprows=_find_header_row(text.splitlines(), delim),
        sep=delim,
        engine="python",
        on_bad_lines="skip",
        dtype=str,                 # parse numbers ourselves (locale-aware)
        keep_default_na=False,
    )

    # Normalise headers: lowercase, trim, and drop a trailing period
    # ("Withdrawal Amt." → "withdrawal amt").
    raw.columns = [re.sub(r"[.\s]+$", "", str(c).strip().lower()) for c in raw.columns]
    cols = list(raw.columns)

    # ── Date (per-row, with a column-wide DD/MM vs MM/DD decision) ───────────
    date_col = _pick_column(cols, _DATE_COLUMNS)
    if not date_col:
        raise ValueError(f"No date column found. Got: {cols}")
    dayfirst = _detect_dayfirst(raw[date_col], default_dayfirst=default_dayfirst)
    iso_dates = raw[date_col].apply(lambda v: _to_iso(v, dayfirst))

    # ── Amount ───────────────────────────────────────────────────────────────
    amount_col = _pick_column(cols, _AMOUNT_COLUMNS)
    if amount_col:
        amounts = _clean_money(raw[amount_col])
        # A separate DR/CR (or Dr/Cr, Debit/Credit) indicator column sets the sign
        # of an otherwise always-positive Amount column.
        type_col = _pick_column(cols, _TYPE_COLUMNS)
        if type_col:
            signs = raw[type_col].apply(_sign_from_type)
            amounts = amounts.abs() * signs
    else:
        debit_col = _pick_column(cols, _DEBIT_COLUMNS)
        credit_col = _pick_column(cols, _CREDIT_COLUMNS)
        if not debit_col and not credit_col:
            raise ValueError(f"No 'Amount' or 'Debit'/'Credit' columns. Got: {cols}")
        # Use magnitudes: a debit is ALWAYS money-out (negative) and a credit
        # ALWAYS money-in (positive), regardless of whether the source column
        # stored the value positive, negative, or in (parentheses).
        debits = _clean_money(raw[debit_col]).abs() if debit_col else pd.Series(0.0, index=raw.index)
        credits = _clean_money(raw[credit_col]).abs() if credit_col else pd.Series(0.0, index=raw.index)
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
    # Drop non-transactions: unparseable dates and balance/total/forward marker
    # rows (they carry a date but aren't money movements). Also drop BLANK rows
    # with no amount and no description — but KEEP a legitimate 0.00 line that
    # has a real description (e.g. "Monthly account fee waived").
    result = result[result["date"].notna()]
    result = result[~result["description"].apply(_is_balance_row)]
    blank_zero = (result["amount"].abs() <= 1e-9) & (result["description"].str.strip() == "")
    result = result[~blank_zero]
    return result.reset_index(drop=True)


def _sign_from_type(t) -> float:
    """Sign for an Amount given a DR/CR-style indicator cell. Debit/withdrawal
    → negative; everything else (credit/deposit) → positive."""
    s = str(t).strip().lower()
    if s in ("d", "dr", "debit", "dbt", "w", "wd", "withdrawal", "out", "-"):
        return -1.0
    if s in ("c", "cr", "credit", "cdt", "dep", "deposit", "in", "+"):
        return 1.0
    if "debit" in s or "withdraw" in s:
        return -1.0
    return 1.0


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

    def _norm_txn(t):
        if not isinstance(t, dict):
            return t
        if not t.get("description"):
            for k in ("narration", "narrative", "details", "particulars", "memo", "desc", "reference"):
                if t.get(k):
                    t["description"] = str(t[k])
                    break
        if t.get("amount") in (None, "") and "amount" not in t:
            for k in ("value", "betrag", "importe", "montant", "amt"):
                if t.get(k) not in (None, ""):
                    t["amount"] = t[k]
                    break
        return t

    def _coerce(obj) -> dict:
        # The model may return a bare array, a single object, or {transactions:[…]},
        # with fields under alternate names. Always normalise to {"transactions":[…]}.
        def wrap(lst):
            return {"transactions": [_norm_txn(t) for t in lst if isinstance(t, dict)]}
        if isinstance(obj, list):
            return wrap(obj)
        if isinstance(obj, dict):
            if isinstance(obj.get("transactions"), list):
                return wrap(obj["transactions"])
            if "date" in obj and ("amount" in obj or "description" in obj):
                return wrap([obj])
            for v in obj.values():
                if isinstance(v, list):
                    return wrap(v)
        return {"transactions": []}

    s = (text or "").strip()

    # 1. Strip markdown code fences if present (```json … ```).
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()

    # 2. Straight parse (handles both a top-level object AND a top-level array).
    try:
        return _coerce(json.loads(s))
    except json.JSONDecodeError:
        pass

    # 3. Narrow to the outermost {...} or [...] and try again.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = s.find(open_ch), s.rfind(close_ch)
        if start >= 0 and end > start:
            try:
                return _coerce(json.loads(s[start:end + 1]))
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
