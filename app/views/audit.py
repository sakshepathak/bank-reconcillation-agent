"""
Audit trail view — full history of MatchRecord rows.

One row per (run, bank txn) including final human decision.
Downloadable as CSV.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlmodel import select

from memory.db import get_session
from memory.models import MatchRecord


STATUS_LABEL = {
    "exact": "Matched",
    "fuzzy": "Close Match",
    "one_to_many": "Split Payment",
    "unmatched": "Unmatched",
    "human_corrected": "Corrected",
}


def _load_audit_rows() -> list[dict]:
    """Read all MatchRecord rows and convert to plain dicts inside the session."""
    with get_session() as session:
        records = session.exec(
            select(MatchRecord).order_by(MatchRecord.created_at.desc())
        ).all()
        rows = []
        for r in records:
            raw_st = r.status.value if hasattr(r.status, "value") else str(r.status)
            rows.append({
                "Run": r.run_id,
                "Bank Ref": r.bank_txn_id,
                "Ledger Ref": r.ledger_txn_id or "-",
                "Status": STATUS_LABEL.get(raw_st, raw_st),
                "Confidence": f"{r.score * 100:.0f}%",
                "Reviewed": ("Yes" if r.human_approved else "No") if r.human_approved is not None else "-",
                "Date": r.created_at[:10] if r.created_at else "-",
            })
        return rows


def render() -> None:
    st.markdown('<span class="section-tag">Audit Trail</span>', unsafe_allow_html=True)
    st.caption("Every reconciliation decision made by the agent and user.")

    rows = _load_audit_rows()
    if not rows:
        st.info("No reconciliation runs yet.")
        return

    run_ids = list(dict.fromkeys(r["Run"] for r in rows))
    filt_col, _ = st.columns([2, 5])
    with filt_col:
        chosen_run = st.selectbox("Filter by run", ["All"] + run_ids)

    filtered = [r for r in rows if chosen_run == "All" or r["Run"] == chosen_run]

    df = pd.DataFrame(filtered)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=min(60 + len(filtered) * 38, 480))

    dl_col, _ = st.columns([2, 8])
    dl_col.download_button(
        "Download history CSV",
        data=df.to_csv(index=False),
        file_name="reconciliation_history.csv",
        mime="text/csv",
        use_container_width=True,
    )
