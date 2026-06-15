"""
LLM verifier — last-resort matching for unmatched bank lines.

After the deterministic composite scorer (amount + date + name, see
`engine/reconcile_rules.py` and `knowledge/rules/matching_rules.md`) has ranked
candidates and the confident ones have been handled, this optional module takes
whatever is still unmatched and asks the LLM to make a judgment call. ONE batched
call per reconciliation run, not per-pair — so cost is bounded regardless of
dataset size.

Design notes:
  - Structured output via Pydantic schema — Gemini enforces, OpenRouter sends
    JSON-schema. Either way the result is parseable, not free-text.
  - Prompt is conservative: explicitly tells the model "false positives are
    worse than misses, return null when in doubt."
  - All matches emit MatchStatus.POSSIBLE — they always need human approval.
"""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from engine.llm import LLMError, get_llm


log = logging.getLogger(__name__)


# ─── Pydantic schema enforced on the response ───────────────────────────────

class LLMMatch(BaseModel):
    bank_id: str = Field(description="The B=... id from the bank lines list")
    invoice_id: Optional[str] = Field(
        default=None,
        description="The L=... id from the invoices list, or null if no good match",
    )
    confidence: float = Field(
        default=0.0,
        description="0.0 = no match, 0.7+ = strong, 1.0 = certain",
    )
    reason: str = Field(
        default="",
        description="Brief one-sentence justification (≤ 20 words)",
    )


class LLMMatchResponse(BaseModel):
    matches: list[LLMMatch]


# ─── Prompt template ────────────────────────────────────────────────────────

_PROMPT = """You are a forensic accountant matching unresolved bank transactions to invoices.

Find genuine matches based on vendor identity, amount proximity, and date proximity.

CRITICAL RULES:
- BE CONSERVATIVE. Return null for invoice_id when in doubt.
- False positives are worse than misses.
- For each bank line, return AT MOST one invoice match.
- Each invoice can be claimed by AT MOST one bank line — don't double-assign.
- Use confidence 0.0 if no plausible match, 0.7+ only if you're confident.

Bank lines (unmatched):
{bank_block}

Available invoices (unmatched):
{invoice_block}

Return JSON only. Format:
{{
  "matches": [
    {{"bank_id": "B1", "invoice_id": "L5", "confidence": 0.85, "reason": "Both reference Adobe Creative Cloud"}},
    {{"bank_id": "B2", "invoice_id": null, "confidence": 0.0, "reason": "No clear match"}}
  ]
}}"""


# ─── Public API ─────────────────────────────────────────────────────────────

def verify_matches(
    unmatched_bank: list[dict],
    unmatched_invoices: list[dict],
    *,
    confidence_floor: float = 0.7,
) -> list[dict]:
    """
    Send a batched LLM call asking for matches across the remaining unmatched set.

    Args:
        unmatched_bank:     [{id, vendor, amount, date}, ...]
        unmatched_invoices: [{id, vendor, amount, date}, ...]
        confidence_floor:   below this, discard.

    Returns:
        Filtered list of {bank_id, invoice_id, confidence, reason} dicts.
        Empty list if no matches above threshold, or if LLM call fails.
    """
    if not unmatched_bank or not unmatched_invoices:
        return []

    bank_lines = [
        f"- B={b['id']} | {b['vendor'][:60]} | ${b['amount']:.2f} | {b['date']}"
        for b in unmatched_bank
    ]
    invoice_lines = [
        f"- L={i['id']} | {i['vendor'][:60]} | ${i['amount']:.2f} | {i['date']}"
        for i in unmatched_invoices
    ]

    prompt = _PROMPT.format(
        bank_block="\n".join(bank_lines),
        invoice_block="\n".join(invoice_lines),
    )

    try:
        llm = get_llm()
        result = llm.complete_text(
            prompt,
            schema=LLMMatchResponse,
            max_tokens=1500,
        )
    except LLMError as e:
        log.warning("LLM verifier failed: %s", e)
        return []

    try:
        parsed = LLMMatchResponse.model_validate_json(result.text)
    except Exception as e:  # noqa: BLE001
        log.warning("LLM verifier returned unparseable schema: %s", e)
        return []

    # Filter, dedup invoices (LLM should already obey this — defensive)
    seen_invoices: set[str] = set()
    out: list[dict] = []
    for m in parsed.matches:
        if not m.invoice_id:
            continue
        if m.confidence < confidence_floor:
            continue
        if m.invoice_id in seen_invoices:
            continue
        seen_invoices.add(m.invoice_id)
        out.append(m.model_dump())

    return out
