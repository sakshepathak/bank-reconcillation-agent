"""
Vendor alias management view.

Two sections:
  1. Table of current aliases (read-only, sourced from DB)
  2. Form to add a new manual mapping
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from sqlmodel import select

from memory.db import get_session
from memory.models import VendorAlias


def _all_aliases() -> list[dict]:
    """Read aliases and materialize to plain dicts inside the session."""
    with get_session() as session:
        return [
            {
                "Bank description": a.alias,
                "Canonical vendor": a.canonical_name,
                "Source": "Manual" if a.source == "human" else "Auto",
                "Confidence": f"{a.confidence:.2f}",
            }
            for a in session.exec(select(VendorAlias)).all()
        ]


def _save_alias(raw: str, canonical: str) -> None:
    with get_session() as session:
        session.add(VendorAlias(
            alias=raw.strip().lower(),
            canonical_name=canonical.strip(),
            source="human",
            confidence=1.0,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))


def render() -> None:
    st.markdown('<span class="section-tag">Active vendor mappings</span>', unsafe_allow_html=True)
    st.caption("Maps messy bank descriptions to canonical vendor names used by the matcher.")

    rows = _all_aliases()
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No aliases registered yet. Add one below.")

    st.markdown('<span class="section-tag">Add new mapping</span>', unsafe_allow_html=True)
    with st.form("add_alias_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        raw = c1.text_input("Bank description", placeholder="AMZN MKTPL *1A2B")
        canonical = c2.text_input("Canonical vendor", placeholder="Amazon")
        if st.form_submit_button("Save Mapping", type="primary"):
            if raw and canonical:
                _save_alias(raw, canonical)
                st.success(f"Saved: '{raw}' → '{canonical}'")
                st.rerun()
            else:
                st.warning("Both fields are required.")
