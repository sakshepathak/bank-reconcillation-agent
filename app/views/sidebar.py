"""
Persistent left sidebar — user profile, pending review counter, recent runs.

Rendered once from main.py (not per-tab). All DB reads are materialized
into plain dicts inside the session block.
"""
from __future__ import annotations

import streamlit as st
from sqlmodel import select

from memory.db import get_session
from memory.models import MatchRecord


# Placeholder user — replace with real auth context when wired up.
USER_NAME = "Sakshi"
USER_ROLE = "Accountant"


def _load_stats() -> tuple[list[dict], int]:
    """Returns (recent_runs, pending_review_count)."""
    with get_session() as session:
        records = list(session.exec(select(MatchRecord)).all())

    runs: dict[str, dict] = {}
    pending = 0
    for r in records:
        status = r.status.value if hasattr(r.status, "value") else str(r.status)
        if r.requires_human_review and r.human_approved is None:
            pending += 1

        entry = runs.setdefault(r.run_id, {"total": 0, "matched": 0, "latest": ""})
        entry["total"] += 1
        if status in ("exact", "human_corrected"):
            entry["matched"] += 1
        if (r.created_at or "") > entry["latest"]:
            entry["latest"] = r.created_at or ""

    recent = sorted(
        ({"run_id": rid, **stats} for rid, stats in runs.items()),
        key=lambda x: x["latest"],
        reverse=True,
    )[:5]
    return recent, pending


def render() -> None:
    with st.sidebar:
        avatar_letter = (USER_NAME[:1] or "?").upper()

        # User card
        st.markdown(f"""
        <div class="sb-user">
          <div class="sb-avatar">{avatar_letter}</div>
          <div>
            <div class="sb-user-name">{USER_NAME}</div>
            <div class="sb-user-role">{USER_ROLE}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        recent, pending = _load_stats()

        # Pending counter
        st.markdown(f"""
        <div class="sb-pending">
          <div class="sb-pending-num">{pending}</div>
          <div class="sb-pending-lbl">items need review</div>
        </div>
        """, unsafe_allow_html=True)

        # Recent runs
        st.markdown('<div class="sb-section">Recent runs</div>', unsafe_allow_html=True)
        if not recent:
            st.markdown('<div class="sb-empty">No runs yet</div>', unsafe_allow_html=True)
        else:
            for run in recent:
                pct = (run["matched"] / run["total"] * 100) if run["total"] else 0
                short_id = run["run_id"].replace("run_", "")
                date = (run["latest"] or "")[:10]
                st.markdown(f"""
                <div class="sb-run">
                  <div class="sb-run-id">{short_id}</div>
                  <div class="sb-run-meta">
                    <span>{date}</span>
                    <span class="sb-run-pct">{pct:.0f}%</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)
