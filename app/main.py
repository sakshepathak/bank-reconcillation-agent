"""
Streamlit entry point — thin shell, all logic lives in views/.

Run with:  streamlit run app/main.py
"""
from __future__ import annotations

import os
import sys

# Make sibling packages importable (memory, mcp_server, config, ...)
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for path in (_ROOT, _HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import streamlit as st

from memory.db import init_db
from views import reconcile, audit, aliases, sidebar, settings


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Reconciliation Engine",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Bootstrap ─────────────────────────────────────────────────────────────────
init_db()


# ── Styles ────────────────────────────────────────────────────────────────────
def _load_css() -> None:
    css_path = os.path.join(_HERE, "styles.css")
    if not os.path.exists(css_path):
        return
    with open(css_path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


_load_css()


# ── Persistent sidebar ────────────────────────────────────────────────────────
sidebar.render()


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-header">
  <h1>Reconciliation Workspace</h1>
  <p>Match bank statements against the ledger, review pairs, and resolve the rest.</p>
</div>
""", unsafe_allow_html=True)


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_recon, tab_audit, tab_aliases, tab_settings = st.tabs([
    "Reconciliation",
    "Audit Trail",
    "Vendor Aliases",
    "Settings",
])

with tab_recon:
    reconcile.render()

with tab_audit:
    audit.render()

with tab_aliases:
    aliases.render()

with tab_settings:
    settings.render()
