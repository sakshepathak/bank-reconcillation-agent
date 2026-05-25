"""
Persistent left sidebar — user profile (editable), pending review counter, recent runs.

Rendered once from main.py (not per-tab). All DB reads are materialized
into plain dicts inside the session block.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st
from sqlmodel import select

from memory.db import get_session
from memory.models import CompanyProfile, MatchRecord, UserProfile


def _get_user() -> dict:
    with get_session() as session:
        p = session.exec(select(UserProfile)).first()
        if p:
            return {"name": p.name, "role": p.role, "email": p.email or ""}
    return {"name": "Sakshi", "role": "Accountant", "email": ""}


def _save_user(name: str, role: str, email: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as session:
        p = session.exec(select(UserProfile)).first()
        if p:
            p.name = name or p.name
            p.role = role or p.role
            p.email = email or None
            p.updated_at = now
            session.add(p)
        else:
            session.add(UserProfile(name=name or "User", role=role or "Accountant",
                                    email=email or None, updated_at=now))


def _get_company_name() -> str:
    with get_session() as session:
        c = session.exec(select(CompanyProfile)).first()
        if c and c.company_name:
            return c.company_name
    return ""


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
    if "sb_editing_user" not in st.session_state:
        st.session_state["sb_editing_user"] = False

    with st.sidebar:
        user = _get_user()
        company_name = _get_company_name()

        if st.session_state["sb_editing_user"]:
            # ── Edit mode ──────────────────────────────────────────────────
            st.markdown('<div class="sb-section">Edit Profile</div>', unsafe_allow_html=True)
            with st.form("sb_edit_user_form"):
                new_name = st.text_input("Name", value=user["name"])
                new_role = st.text_input("Role", value=user["role"])
                new_email = st.text_input("Email", value=user["email"],
                                          placeholder="you@company.com")
                c1, c2 = st.columns(2)
                with c1:
                    saved = st.form_submit_button("Save", use_container_width=True,
                                                  type="primary")
                with c2:
                    cancelled = st.form_submit_button("Cancel", use_container_width=True)

            if saved:
                _save_user(new_name.strip(), new_role.strip(), new_email.strip())
                st.session_state["sb_editing_user"] = False
                st.rerun()
            elif cancelled:
                st.session_state["sb_editing_user"] = False
                st.rerun()
        else:
            # ── View mode ──────────────────────────────────────────────────
            avatar_letter = (user["name"][:1] or "?").upper()
            company_html = (
                f'<div class="sb-company">{company_name}</div>' if company_name else ""
            )
            st.markdown(f"""
            <div class="sb-user">
              <div class="sb-avatar">{avatar_letter}</div>
              <div class="sb-user-info">
                <div class="sb-user-name">{user["name"]}</div>
                <div class="sb-user-role">{user["role"]}</div>
                {company_html}
              </div>
            </div>
            """, unsafe_allow_html=True)

            if st.button("✏ Edit profile", key="sb_edit_btn", use_container_width=True):
                st.session_state["sb_editing_user"] = True
                st.rerun()

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

        # Footer hint
        st.markdown(
            '<div class="sb-footer">Go to Settings tab to manage company &amp; contacts</div>',
            unsafe_allow_html=True,
        )
