"""
FastMCP Server — exposes all reconciliation tools over Model Context Protocol.

Tools registered:
  search_kb          — Hybrid RAG search over the knowledge base
  lookup_vendor      — Vendor alias lookup (self-learning KB)
  store_alias        — Persist a new vendor alias (human correction loop)
  reconcile          — Run full 4-level matching cascade on CSV data
  get_unmatched      — Filter a reconciliation report to unmatched rows only
  approve_match      — HITL gate: human approves or rejects a match

This server can run in two modes:
  1. Standalone stdio MCP server (for Claude Desktop, Cursor, etc.):
         python -m mcp_server.server
  2. Direct import (for the Pydantic-AI agent in the same process):
         from mcp_server.server import <tool_functions>
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import json
import uuid
from datetime import datetime, timezone

import pandas as pd
from mcp.server.fastmcp import FastMCP

from mcp_server.tools.alias import list_aliases, lookup_vendor, store_alias
from mcp_server.tools.matching import ReconciliationReport, normalise_df, run_matching_cascade
from mcp_server.tools.search_kb import search_knowledge_base
from memory.db import get_session
from memory.models import MatchRecord, MatchStatus

mcp = FastMCP("BankReconciliationAgent")

# In-memory run store for the current process (report objects keyed by run_id).
# In production, serialise to DB instead.
_run_store: dict[str, ReconciliationReport] = {}


# ── Tool 1: Knowledge Base Search ────────────────────────────────────────────

@mcp.tool()
def search_kb(
    query: str,
    top_k: int = 5,
    chunk_type: str = "",
) -> str:
    """
    Search the reconciliation knowledge base for rules, SOPs, and historical patterns.

    ALWAYS call this first before making any matching decision to check whether
    a specific rule exists for the vendors or transaction types involved.

    Args:
        query:      Natural-language question or keyword phrase.
        top_k:      Number of results (default 5, max 20).
        chunk_type: Optional filter — one of: rule, sop, alias, historical, policy.
    """
    return search_knowledge_base(
        query=query,
        top_k=min(top_k, 20),
        chunk_type_filter=chunk_type or None,
    )


# ── Tool 2: Vendor Alias Lookup ───────────────────────────────────────────────

@mcp.tool()
def get_vendor_name(raw_description: str) -> str:
    """
    Look up the canonical vendor name for a messy bank-statement description.

    Use this whenever you encounter an ambiguous or abbreviated description
    like 'AMZN MKTPL *123' or 'SQ *COFFEE SHOP'.

    Args:
        raw_description: The raw, messy description from the bank statement.

    Returns:
        The canonical vendor name if known, or 'Unknown — not in alias store'.
    """
    result = lookup_vendor(raw_description)
    if result:
        return f"Canonical name: {result}"
    return (
        f"'{raw_description}' is not in the vendor alias store. "
        "If you identify the vendor, call store_vendor_alias to save it."
    )


# ── Tool 3: Store Vendor Alias ────────────────────────────────────────────────

@mcp.tool()
def store_vendor_alias(
    raw_description: str,
    canonical_name: str,
    source: str = "agent",
) -> str:
    """
    Store a new vendor alias mapping in the self-learning knowledge base.

    Call this when:
    - A human corrects a vendor identification.
    - You have confidently identified a vendor from context.

    Args:
        raw_description: The raw bank-statement string (e.g. 'AMZN MKTPL *123').
        canonical_name:  The correct vendor name (e.g. 'Amazon').
        source:          'agent' (auto-discovered) or 'human' (human-confirmed).
    """
    result = store_alias(
        raw_description=raw_description,
        canonical_name=canonical_name,
        source=source,
        confidence=1.0 if source == "human" else 0.8,
    )
    return (
        f"Alias {result['action']}: '{result['alias']}' → '{result['canonical_name']}' "
        f"(source={result['source']}, confidence={result['confidence']})."
    )


# ── Tool 4: Run Reconciliation ────────────────────────────────────────────────

@mcp.tool()
def reconcile(
    bank_csv: str,
    ledger_csv: str,
) -> str:
    """
    Run the full 4-level matching cascade on bank statement and ledger CSVs.

    Matching cascade:
      Level 1 — Exact:        date + amount identical
      Level 2 — Fuzzy Amount: amount within tolerance, date within window
      Level 3 — Fuzzy Desc:   description similarity >= threshold
      Level 4 — One-to-Many:  sum of ledger rows = bank amount

    Args:
        bank_csv:   CSV string of the bank statement.
                    Required columns: date, description, amount.
                    Optional: txn_id (auto-generated if missing).
        ledger_csv: CSV string of the company ledger.
                    Required columns: date, description, amount.
                    Optional: txn_id (auto-generated if missing).

    Returns:
        JSON string with run_id, summary stats, and per-transaction results.
    """
    try:
        bank_df   = normalise_df(pd.read_csv(io.StringIO(bank_csv)),   is_ledger=False)
        ledger_df = normalise_df(pd.read_csv(io.StringIO(ledger_csv)), is_ledger=True)
    except Exception as exc:
        return f"CSV parse error: {exc}. Check column names and formatting."

    # Fetch aliases from DB to pass to matching engine
    with get_session() as session:
        from sqlmodel import select
        from memory.models import VendorAlias
        all_aliases = session.exec(select(VendorAlias)).all()
        alias_dict = {a.alias: a.canonical_name for a in all_aliases}

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    try:
        report = run_matching_cascade(bank_df, ledger_df, run_id, aliases=alias_dict)
    except ValueError as exc:
        return f"Validation error: {exc}"

    # Persist to DB
    _persist_report(report)
    _run_store[run_id] = report

    # Build structured output
    results = []
    for r in report.match_results:
        results.append({
            "bank_txn_id": r.bank_txn_id,
            "ledger_txn_id": r.ledger_txn_id,
            "matched_ledger_ids": r.matched_ledger_ids,
            "status": r.status,
            "score": r.score,
            "amount_diff": r.amount_diff,
            "date_diff_days": r.date_diff_days,
            "requires_human_review": r.requires_human_review,
            "reasoning_path": r.reasoning_path,
        })

    return json.dumps({
        "run_id": run_id,
        "summary": report.summary_text(),
        "stats": {
            "total_bank": report.total_bank_rows,
            "total_ledger": report.total_ledger_rows,
            "exact": report.exact_matches,
            "fuzzy": report.fuzzy_matches,
            "one_to_many": report.one_to_many_matches,
            "unmatched_bank": report.unmatched_bank,
            "unmatched_ledger": report.unmatched_ledger,
            "match_rate": f"{report.match_rate:.1%}",
        },
        "results": results,
    }, indent=2)


# ── Tool 5: Get Unmatched Transactions ───────────────────────────────────────

@mcp.tool()
def get_unmatched(run_id: str) -> str:
    """
    Return only the unmatched bank transactions from a reconciliation run.

    Use after reconcile() to review rows that need human attention.

    Args:
        run_id: The run_id returned by reconcile().
    """
    report = _run_store.get(run_id)
    if not report:
        return f"No report found for run_id={run_id}. Run reconcile() first."

    unmatched = [
        {
            "bank_txn_id": r.bank_txn_id,
            "reasoning_path": r.reasoning_path,
        }
        for r in report.match_results
        if r.status == "unmatched"
    ]

    if not unmatched:
        return f"No unmatched bank transactions in run {run_id}. All rows reconciled."

    return json.dumps({"run_id": run_id, "unmatched": unmatched}, indent=2)


# ── Tool 6: Human Approval Gate (HITL) ───────────────────────────────────────

@mcp.tool()
def approve_match(
    run_id: str,
    bank_txn_id: str,
    approved: bool,
    correction_ledger_id: str = "",
    notes: str = "",
) -> str:
    """
    Human-in-the-Loop gate: approve or reject a match from a reconciliation run.

    IMPORTANT: All final reconciliation decisions MUST pass through this gate
    before being posted to the ledger. This is a non-negotiable audit requirement.

    Args:
        run_id:                The run_id from reconcile().
        bank_txn_id:           The bank transaction ID to approve.
        approved:              True = confirm the match, False = reject it.
        correction_ledger_id:  If rejecting, provide the correct ledger ID.
        notes:                 Optional human notes for the audit log.

    Returns:
        Confirmation string with updated audit record details.
    """
    report = _run_store.get(run_id)
    if not report:
        return f"No report found for run_id={run_id}."

    match = next(
        (r for r in report.match_results if r.bank_txn_id == bank_txn_id), None
    )
    if not match:
        return f"bank_txn_id={bank_txn_id} not found in run {run_id}."

    # Update DB record
    with get_session() as session:
        from sqlmodel import select
        stmt = select(MatchRecord).where(
            MatchRecord.run_id == run_id,
            MatchRecord.bank_txn_id == bank_txn_id,
        )
        record = session.exec(stmt).first()
        if record:
            record.human_approved = approved
            if correction_ledger_id:
                record.ledger_txn_id = correction_ledger_id
                record.status = MatchStatus.HUMAN_CORRECTED
            record.reasoning_path += f" | Human review: approved={approved}. Notes: {notes}"
            session.add(record)

    action = "APPROVED" if approved else "REJECTED"
    correction_note = (
        f" Corrected to ledger_id={correction_ledger_id}." if correction_ledger_id else ""
    )
    return (
        f"Match {action} for bank_txn_id={bank_txn_id} in run {run_id}.{correction_note} "
        f"Audit record updated."
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _persist_report(report: ReconciliationReport) -> None:
    """Write all match results to the DB audit log."""
    records = []
    for r in report.match_results:
        ledger_id = r.ledger_txn_id or (
            ",".join(r.matched_ledger_ids) if r.matched_ledger_ids else None
        )
        records.append(
            MatchRecord(
                run_id=report.run_id,
                bank_txn_id=r.bank_txn_id,
                ledger_txn_id=ledger_id,
                status=MatchStatus(r.status) if r.status in MatchStatus._value2member_map_ else MatchStatus.UNMATCHED,
                score=r.score,
                reasoning_path=r.reasoning_path,
                amount_diff=r.amount_diff,
                date_diff_days=r.date_diff_days,
                requires_human_review=r.requires_human_review,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    with get_session() as session:
        for record in records:
            session.add(record)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    """Run as a standalone stdio MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
