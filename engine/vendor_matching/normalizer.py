"""
Vendor name canonicalization — Tier 1 of the vendor matching pipeline.

Critical distinctions:
  - "Pure processor" prefixes (SQ *, PYPL *, STRIPE *, TST *) are intermediaries
    — the *vendor* is what follows. Strip them.
  - "Vendor processor" prefixes (AMZN *, UBER *, GOOG *, GOOGLE *) — the prefix
    IS the vendor; the asterisk just precedes a product/modifier. Normalize the
    prefix to a canonical vendor name and drop the asterisked modifier.

Pipeline order matters — each step assumes earlier steps have already cleaned
their share of noise.

Pure & deterministic. No I/O. Returns a frozen dataclass.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# ─── Step 0: vendor identity normalization (substitutions) ──────────────────
#
# These convert known abbreviations / brand variations to their canonical
# form BEFORE any stripping happens. Preserves the vendor signal.

_VENDOR_ALIASES = (
    # (pattern, replacement)  — applied repeatedly until stable
    (re.compile(r"\bAMZN(\s+MKTPL)?\s*\*?\s*\w*\b"), "AMAZON"),
    (re.compile(r"\bAMZN\.COM\b"), "AMAZON"),
    (re.compile(r"\bAMAZON\.COM\b"), "AMAZON"),
    (re.compile(r"\bAPL\s*\*?\s*ITUNES\b"), "APPLE"),
    (re.compile(r"\bAPPLE\.COM\s*/?\s*BILL\b"), "APPLE"),
    (re.compile(r"\bGOOG\s*\*?\s*(\w+)?\b"), r"GOOGLE \1"),
    (re.compile(r"\bGOOGLE\s*\*?\s*(\w+)\b"), r"GOOGLE \1"),
    (re.compile(r"\bUBER\s*\*?\s*(TRIP|EATS|RIDE)?\b"), r"UBER \1"),
    (re.compile(r"\bLYFT\s*\*?\s*\w*\b"), "LYFT"),
    (re.compile(r"\bDD\s*\*?\s*\w*\b"), "DOORDASH"),
    (re.compile(r"\bDOORDASH\s*\*?\s*\w*\b"), "DOORDASH"),
    (re.compile(r"\bGRUB(HUB)?\s*\*?\s*\w*\b"), "GRUBHUB"),
    (re.compile(r"\bNYTIMES\s*\*?\s*\w*\b"), "NEW YORK TIMES"),
    (re.compile(r"\bNETFLIX\.COM\b"), "NETFLIX"),
    (re.compile(r"\bSPOTIFY\s*\*?\s*\w*\b"), "SPOTIFY"),
    (re.compile(r"\bMSFT\s*\*?\s*\w*\b"), "MICROSOFT"),
    (re.compile(r"\bMICROSOFT\*BING\b"), "MICROSOFT"),
    (re.compile(r"\bADOBE\s*\*?\s*\w*\b"), "ADOBE"),
)


# ─── Step 1: pure processor prefixes (strip entirely) ───────────────────────
#
# These are payment intermediaries — the vendor is what follows the asterisk.

_PURE_PROCESSOR_PREFIXES = tuple(re.compile(p) for p in (
    r"\bSQ\s*\*\s*",          # Square
    r"\bTST\s*\*\s*",         # Toast restaurant
    r"\bPYPL\s*\*\s*",        # PayPal short
    r"\bPAYPAL\s*\*\s*",      # PayPal long
    r"\bSTRIPE\s*\*\s*",      # Stripe
    r"\bCASH\s*APP\s*\*\s*",  # Cash App
    r"\bVENMO\s*\*\s*",       # Venmo
))


# ─── Step 2: bank-statement noise prefixes ──────────────────────────────────

_BANK_NOISE_PREFIXES = tuple(re.compile(p) for p in (
    r"^POS\s+PURCHASE\s+",
    r"^POS\s+DEB\s+",
    r"^DEBIT\s+CARD\s+PURCHASE\s+",
    r"^DEBIT\s+CARD\s+",
    r"^CHECK\s+CARD\s+",
    r"^PURCHASE\s+AUTHORIZED\s+ON\s+\d{2}/\d{2}\s+",
    r"^ACH\s+(DEBIT|CREDIT|PMT)\s+",
    r"^ELECTRONIC\s+PMT\s+",
    r"^WIRE\s+(TRANSFER\s+)?",
    r"^XFER\s+",
    r"^WITHDRAWAL\s+",
    r"^EFT\s+",
    r"^NEFT\s+",
    r"^IMPS\s+",
    r"^UPI\s+",
    r"^RTGS\s+",
))


# ─── Step 3: trailing transaction IDs (must contain a digit) ────────────────
#
# Lookahead `(?=[A-Z0-9]*\d)` requires at least one digit somewhere in the
# match. This prevents stripping pure-alphabetic vendor names like "DAILYBEAN".

_TRAILING_TXN_IDS = tuple(re.compile(p) for p in (
    r"\*\s*(?=[A-Z0-9]*\d)[A-Z0-9]{4,}\b",         # *A1B2C3 (must have digit)
    r"#\s*[A-Z0-9]{4,}\b",                          # #1234567
    r"\bREF\s*#?\s*\S+\b",                          # REF# ABC123
    r"\s+(?=[A-Z0-9]*\d)[A-Z0-9]{6,}\s*$",         # trailing ID (with digit) at EOL
    r"\b\d{6,}\b",                                  # bare 6+ digit number
))


# ─── Step 4: embedded dates ─────────────────────────────────────────────────

_EMBEDDED_DATES = tuple(re.compile(p) for p in (
    r"\b\d{1,2}[/-]\d{1,2}\b",
    r"\b\d{1,2}[A-Z]{3}\b",
    r"\b[A-Z]{3}\d{1,2}\b",
))


# ─── Step 5: location tails ─────────────────────────────────────────────────

_LOCATION_TAILS = tuple(re.compile(p) for p in (
    r"\s+(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\s*$",
    r"\s+(US|USA|UK|IN|INDIA|CA|CANADA|EU|UAE|AU|NZ|SG)\s*$",
    r"\s+(SAN\s+FRANCISCO|NEW\s+YORK|LOS\s+ANGELES|SF|NYC|LA)\s+[A-Z]{2}\s*$",
))


# ─── Step 6: corporate suffixes (END of string only) ────────────────────────

_CORP_SUFFIXES = tuple(re.compile(p) for p in (
    r"\s+(INC|INC\.|INCORPORATED)\s*$",
    r"\s+(LLC|L\.L\.C\.)\s*$",
    r"\s+(LTD|LTD\.|LIMITED)\s*$",
    r"\s+(PVT\.?\s*LTD\.?|PRIVATE\s+LIMITED)\s*$",
    r"\s+(CORP|CORP\.|CORPORATION)\s*$",
    r"\s+(CO|CO\.|COMPANY)\s*$",
    r"\s+(GMBH|AG|SA|SARL|BV|NV|OY|AB|PLC|LLP)\s*$",
    r"\s+(HOLDINGS|GROUP|SOFTWARE|SYSTEMS|TECHNOLOGIES|TECH)\s*$",
))


# ─── Final cleanup ──────────────────────────────────────────────────────────

_PUNCT_TO_SPACE = re.compile(r"[\*#@\-_/\\|;:,.()\[\]{}\"']+")
_WS_RE = re.compile(r"\s+")


# ─── Public dataclass + entry point ─────────────────────────────────────────

@dataclass(frozen=True)
class Normalized:
    raw: str
    canonical: str
    tokens: tuple[str, ...]


def canonicalize(raw: str) -> Normalized:
    """Turn a noisy vendor description into a canonical form."""
    if not raw:
        return Normalized(raw="", canonical="", tokens=tuple())

    # Unicode normalize + uppercase
    s = unicodedata.normalize("NFKC", str(raw)).upper().strip()

    # Step 0: brand identity normalization (do this first, before any stripping)
    # Repeat to catch chained patterns
    for _ in range(2):
        for pat, repl in _VENDOR_ALIASES:
            s = pat.sub(repl, s)

    # Step 1: pure processor prefixes
    for _ in range(2):
        for r in _PURE_PROCESSOR_PREFIXES:
            s = r.sub(" ", s)

    # Step 2: bank noise prefixes
    for r in _BANK_NOISE_PREFIXES:
        s = r.sub(" ", s)

    # Step 3: trailing txn IDs
    for r in _TRAILING_TXN_IDS:
        s = r.sub(" ", s)

    # Step 4: embedded dates
    for r in _EMBEDDED_DATES:
        s = r.sub(" ", s)

    # Step 5: location tails
    for r in _LOCATION_TAILS:
        s = r.sub(" ", s)

    # Step 6: corporate suffixes — repeat to catch "AMAZON COM INC"
    for _ in range(2):
        for r in _CORP_SUFFIXES:
            s = r.sub(" ", s)

    # Step 7: punctuation cleanup + collapse
    s = _PUNCT_TO_SPACE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()

    tokens = tuple(s.split()) if s else tuple()
    return Normalized(raw=str(raw), canonical=s, tokens=tokens)
