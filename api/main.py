"""
FastAPI REST backend for the Bank Reconciliation Agent.

Run from project root:
    uvicorn api.main:app --reload --port 8000

Streamlit stays on :8501 during the transition. React dev server runs on :5173
and proxies /api/* to this server.
"""
from __future__ import annotations

import os
import sys

# Ensure project root is on sys.path so memory/, engine/, config/ are importable.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from memory.db import init_db
from api.routers import (
    health, dashboard, runs, matches, contacts, company, aliases, audit, profile,
    bank_accounts, invoices, bills, journal_entries, statement_lines,
    exceptions as exceptions_router,
    auth, orgs, chat, kb, credits,
)

app = FastAPI(
    title="Bank Reconciliation API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Allow React dev server + Streamlit to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # React dev server (Vite)
        "http://localhost:8501",   # Streamlit
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()

    # Pre-warm the vendor-matching embedding model in a background thread.
    # The first reconciliation suggestion call would otherwise pay a ~5–10s
    # one-time model load, which made the Reconcile page look frozen. Doing it
    # here (off the request path, non-blocking for startup) means the model is
    # usually warm by the time the user opens a reconciliation. Best-effort —
    # any failure is swallowed so it can never block the server coming up.
    import threading

    def _warm() -> None:
        try:
            from engine.vendor_matching import embedder
            embedder.warmup()
        except Exception:  # noqa: BLE001 — warmup is purely an optimisation
            pass

    threading.Thread(target=_warm, name="embedder-warmup", daemon=True).start()


# ── Routers ────────────────────────────────────────────────────────────────────
PREFIX = "/api/v1"

app.include_router(health.router)
app.include_router(auth.router,      prefix=PREFIX)
app.include_router(orgs.router,      prefix=PREFIX)
app.include_router(dashboard.router, prefix=PREFIX)
app.include_router(runs.router,      prefix=PREFIX)
app.include_router(matches.router,   prefix=PREFIX)
app.include_router(contacts.router,  prefix=PREFIX)
app.include_router(company.router,   prefix=PREFIX)
app.include_router(aliases.router,   prefix=PREFIX)
app.include_router(audit.router,     prefix=PREFIX)
app.include_router(profile.router,   prefix=PREFIX)

# Xero-style accounting routes
app.include_router(bank_accounts.router,   prefix=PREFIX)
app.include_router(invoices.router,        prefix=PREFIX)
app.include_router(bills.router,           prefix=PREFIX)
app.include_router(journal_entries.router, prefix=PREFIX)
app.include_router(statement_lines.router, prefix=PREFIX)
app.include_router(credits.router,         prefix=PREFIX)
app.include_router(exceptions_router.router, prefix=PREFIX)
app.include_router(chat.router,            prefix=PREFIX)
app.include_router(kb.router,              prefix=PREFIX)
