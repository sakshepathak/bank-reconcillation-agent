"""
Reconciliation view — upload bank CSV + invoices, extract, edit, reconcile.

Flow:
  1. Upload bank CSV (left) + up to 10 invoice PDF/JPEG files (right)
  2. Click "Extract Invoices" → vision model fills a structured table
  3. Review and edit extracted rows (fix any OCR mistakes)
  4. Click "Run Reconciliation" → matching cascade runs against the bank CSV
  5. Side-by-side review of matched pairs with link to view source invoice
  6. Create manual entries for unmatched bank lines (Xero-style)
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from sqlmodel import select

from memory.db import get_session
from memory.models import (
    ExtractedInvoice,
    ManualLedgerEntry,
    MatchRecord,
    MatchStatus,
    VendorAlias,
)
from mcp_server.tools.matching import run_matching_cascade, normalise_df
from mcp_server.tools.invoice_extractor import extract_batch, ExtractionResult
from mcp_server.tools.suggestions import (
    generate_unmatched_suggestion,
    generate_fuzzy_suggestion,
)
from engine.file_store import save_upload, absolute_path, load_file
from engine.bank_statement_parser import parse_bank_statement
from config.settings import settings


STATUS_LABEL = {
    "exact": "Matched",
    "fuzzy": "Close Match",
    "one_to_many": "Split Payment",
    "many_to_one": "Installments",
    "possible": "Possible",
    "unmatched": "Unmatched",
    "human_corrected": "Corrected",
}


def _friendly_error(err: str | Exception) -> str:
    """
    Translate raw API / library errors into plain-English messages safe to
    show in the UI. The raw error is still logged to docker logs for support.
    """
    import logging
    msg = str(err or "").lower()
    logging.getLogger(__name__).warning("internal error surfaced to user: %s", err)

    if any(t in msg for t in ("429", "rate", "quota", "resource_exhausted")):
        return "The AI service is busy right now. Please wait a minute and try again."
    if any(t in msg for t in ("permission_denied", "leaked", "unauthorized", "401", "403")):
        return "Authentication issue with the AI service. Check that API keys are valid."
    if any(t in msg for t in ("timeout", "timed out")):
        return "The request took too long. Please try again."
    if any(t in msg for t in ("schema", "validation", "invalid json", "model_validate")):
        return "The AI returned an unexpected response for this file. Try re-extracting."
    if any(t in msg for t in ("connection", "network", "ssl", "dns", "name or service")):
        return "Network issue connecting to the AI service. Check your internet."
    if any(t in msg for t in ("pdf has no pages", "could not read")):
        return "Could not read this file. It may be corrupted or password-protected."
    if "unsupported mime" in msg:
        return "This file format is not supported. Use PDF, PNG, or JPEG."
    if "no llm provider" in msg:
        return "No AI provider configured. Set GEMINI_API_KEY or OPENROUTER_API_KEY."
    if any(t in msg for t in ("no transactions extracted", "no parseable json")):
        return "We could not pull any transactions from this file."
    # Generic safety net — never expose raw stack traces
    return "Something went wrong. Please try again, or re-extract this file."

STATUS_BADGE = {
    "exact": ("EXACT", "badge-exact"),
    "fuzzy": ("FUZZY", "badge-fuzzy"),
    "one_to_many": ("SPLIT", "badge-split"),
    "many_to_one": ("INSTALLMENTS", "badge-split"),
    "possible": ("POSSIBLE", "badge-fuzzy"),
    "unmatched": ("UNMATCHED", "badge-unmatched"),
    "human_corrected": ("CORRECTED", "badge-exact"),
}


_MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".csv": "text/csv",
}


# ═════════════════════════════════════════════════════════════════════════════
#  Generic helpers (rendering)
# ═════════════════════════════════════════════════════════════════════════════

def _row(df: pd.DataFrame, txn_id: str) -> dict | None:
    if df is None or df.empty or not txn_id:
        return None
    matched = df[df["txn_id"] == txn_id]
    if matched.empty:
        return None
    r = matched.iloc[0]
    return {
        "id": str(r.get("txn_id", "-")),
        "name": str(r.get("description", "-")),
        "amount": float(r.get("amount", 0.0) or 0.0),
        "date": str(r.get("date", "-"))[:10],
    }


def _meter_color(score: float) -> str:
    if score >= 0.9:
        return "var(--success)"
    if score >= 0.75:
        return "var(--warning)"
    return "var(--danger)"


def _confidence_bar_html(score: float) -> str:
    pct = round(score * 100)
    return (
        f'<div class="meter">'
        f'  <div class="meter-bar"><div class="meter-fill" '
        f'       style="width:{pct}%;background:{_meter_color(score)}"></div></div>'
        f'  <span><strong>{pct}%</strong></span>'
        f'</div>'
    )


def _card_html(label: str, kind: str, data: dict | None, empty_msg: str = "") -> str:
    if data is None:
        return (
            f'<div class="compare-card empty">'
            f'  <div class="label">{label}</div>'
            f'  <div class="empty-msg">{empty_msg}</div>'
            f'</div>'
        )
    return (
        f'<div class="compare-card {kind}">'
        f'  <div class="label">{label}</div>'
        f'  <div class="field"><span class="key">ID</span><span class="val">{data["id"]}</span></div>'
        f'  <div class="field"><span class="key">Name</span><span class="val">{data["name"]}</span></div>'
        f'  <div class="field"><span class="key">Date</span><span class="val">{data["date"]}</span></div>'
        f'  <div class="field"><span class="key">Amount</span><span class="val">${data["amount"]:,.2f}</span></div>'
        f'</div>'
    )


def _compare_row(bank: dict | None, ledger: dict | None, empty_msg: str = "") -> None:
    html = (
        f'<div class="compare-row">'
        f'{_card_html("Bank Statement", "bank", bank)}'
        f'{_card_html("Invoice", "ledger", ledger, empty_msg)}'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  DB helpers
# ═════════════════════════════════════════════════════════════════════════════

def _persist_extraction(
    result: ExtractionResult, file_hash: str, storage_path: str, doc_type: str,
) -> int:
    """Save one ExtractionResult to DB. Returns the row id.

    Dedupes on (file_hash, doc_type) — same PDF uploaded under different
    categories gets two distinct rows (different vendor / context).
    """
    import json
    with get_session() as session:
        existing = session.exec(
            select(ExtractedInvoice).where(
                ExtractedInvoice.file_hash == file_hash,
                ExtractedInvoice.doc_type == doc_type,
            )
        ).first()
        if existing:
            return existing.id or 0

        inv = ExtractedInvoice(
            file_hash=file_hash,
            source_filename=result.source_filename,
            storage_path=storage_path,
            mime_type=result.mime_type,
            vendor=result.vendor,
            doc_type=doc_type,
            invoice_id=result.invoice_id,
            date=result.date,
            amount=result.amount,
            currency=result.currency,
            raw_extraction_json=json.dumps(result.raw_json),
            extraction_confidence=result.confidence,
            extraction_error=result.error,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(inv)
        session.flush()
        return inv.id or 0


def _update_match_record(run_id: str, bank_txn_id: str, **fields) -> None:
    with get_session() as session:
        rec = session.exec(
            select(MatchRecord).where(
                MatchRecord.bank_txn_id == bank_txn_id,
                MatchRecord.run_id == run_id,
            )
        ).first()
        if rec:
            for k, v in fields.items():
                setattr(rec, k, v)
            session.add(rec)


def _create_manual_entry(
    run_id: str, bank_txn_id: str, vendor: str, amount: float, date: str, description: str
) -> int:
    with get_session() as session:
        entry = ManualLedgerEntry(
            run_id=run_id,
            bank_txn_id=bank_txn_id,
            vendor=vendor,
            amount=amount,
            date=date,
            description=description,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(entry)
        session.flush()
        return entry.id or 0


def _upsert_alias(raw: str, canonical: str) -> None:
    raw_norm = raw.strip().lower()
    with get_session() as session:
        existing = session.exec(
            select(VendorAlias).where(VendorAlias.alias == raw_norm)
        ).first()
        if existing:
            existing.canonical_name = canonical.strip()
            existing.source = "human"
            existing.confidence = 1.0
            session.add(existing)
        else:
            session.add(VendorAlias(
                alias=raw_norm,
                canonical_name=canonical.strip(),
                source="human",
                confidence=1.0,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))


AUTO_APPROVE_THRESHOLD = 0.95


def _auto_approve_high_confidence(report, b_norm: pd.DataFrame, l_norm: pd.DataFrame) -> None:
    """
    Sweep through the report once per run. Any fuzzy match with a score
    above AUTO_APPROVE_THRESHOLD gets pre-approved silently — the user
    doesn't need to approve stuff the system is already certain about.

    Idempotent: we use a per-run sentinel key so this only fires the first
    time a particular report is rendered, even though render() is called
    many times across Streamlit reruns.
    """
    sentinel = f"_auto_approved::{report.run_id}"
    if st.session_state.get(sentinel):
        return

    approved = 0
    for r in report.match_results:
        status_val = r.status.value if hasattr(r.status, "value") else r.status
        if status_val != "fuzzy":
            continue
        if r.score < AUTO_APPROVE_THRESHOLD:
            continue
        decision_key = f"decision_{r.bank_txn_id}"
        if decision_key in st.session_state:
            continue   # user already decided
        st.session_state[decision_key] = "approved"
        _update_match_record(
            report.run_id, r.bank_txn_id,
            human_approved=True,
            status=MatchStatus.HUMAN_CORRECTED,
        )
        if r.ledger_txn_id:
            _auto_learn_alias_from_match(r, b_norm, l_norm)
        approved += 1

    st.session_state[sentinel] = True
    if approved > 0:
        st.toast(
            f"Auto-approved {approved} high-confidence match"
            f"{'es' if approved != 1 else ''} (>= {int(AUTO_APPROVE_THRESHOLD * 100)}%)"
        )


def _auto_learn_alias_from_match(r, b_norm: pd.DataFrame, l_norm: pd.DataFrame) -> None:
    """
    When the user approves a fuzzy match, store the bank description as a
    learned alias pointing at the invoice vendor. The next run with the
    same bank description gets a free O(1) alias hit at Level 2.
    """
    bank = _row(b_norm, r.bank_txn_id)
    ledger = _row(l_norm, r.ledger_txn_id) if r.ledger_txn_id else None
    if not bank or not ledger:
        return
    raw = str(bank["name"] or "").strip()
    canonical = str(ledger["name"] or "").strip()
    if not raw or not canonical:
        return
    if raw.lower() == canonical.lower():
        return
    _upsert_alias(raw, canonical)


def _invoice_storage_lookup() -> dict[str, dict]:
    """Build {txn_id -> {storage_path, mime, filename}} for the viewer dialog."""
    invoices = st.session_state.get("invoice_df")
    if invoices is None or invoices.empty:
        return {}
    return {
        row["txn_id"]: {
            "storage_path": row["_storage_path"],
            "mime": row["_mime"],
            "filename": row["_filename"],
        }
        for _, row in invoices.iterrows()
        if row.get("_storage_path")
    }


# ═════════════════════════════════════════════════════════════════════════════
#  Upload & extraction
# ═════════════════════════════════════════════════════════════════════════════

def _mime_for(filename: str, fallback: str | None = None) -> str:
    import os
    _, ext = os.path.splitext(filename or "")
    return _MIME_BY_EXT.get(ext.lower(), fallback or "application/octet-stream")


def _load_bank_statement(uploaded_file) -> pd.DataFrame:
    """Parse the uploaded bank statement (CSV or PDF) using session-state cache."""
    file_bytes = uploaded_file.getvalue()
    mime = uploaded_file.type or _mime_for(uploaded_file.name)

    # Cache so we don't re-parse on every Streamlit rerun
    import hashlib
    key = "bank_parsed_" + hashlib.sha256(file_bytes).hexdigest()[:16]
    if key in st.session_state:
        return st.session_state[key]

    if mime == "application/pdf":
        with st.spinner("Reading PDF bank statement..."):
            df = parse_bank_statement(file_bytes, "application/pdf")
    else:
        df = parse_bank_statement(file_bytes, "text/csv")

    st.session_state[key] = df
    return df


def _render_upload() -> tuple[pd.DataFrame | None, list]:
    """
    Bank statement (full width) above two categorized invoice uploaders.

    Returns:
        (bank_df, typed_uploads)
        typed_uploads is list of (UploadedFile, doc_type) where doc_type
        is "sales" or "purchase" — declared by the user via which uploader
        they used.
    """
    # ─── Bank statement (top, full width) ─────────────────────────────────
    st.markdown('<span class="section-tag">Bank Statement (CSV or PDF)</span>',
                unsafe_allow_html=True)
    bank_df = None
    bank_up = st.file_uploader(
        "bank statement",
        type=["csv", "pdf"],
        key="bank_up",
        label_visibility="collapsed",
    )
    if bank_up is not None:
        try:
            bank_df = _load_bank_statement(bank_up)
            st.dataframe(bank_df, use_container_width=True, hide_index=True, height=160)
            st.caption(f"{len(bank_df)} transactions read.")
        except Exception as ex:
            st.error(_friendly_error(ex))
            bank_df = None

    # ─── Invoices, split by category ──────────────────────────────────────
    per_cat = settings.MAX_INVOICES_PER_CATEGORY
    st.markdown(
        f'<span class="section-tag">Invoices & Bills · up to {per_cat} files per category</span>',
        unsafe_allow_html=True,
    )

    sales_col, purchase_col = st.columns(2, gap="medium")
    typed_uploads: list[tuple] = []

    with sales_col:
        st.markdown(
            "<div class='upload-cat upload-cat-sales'>"
            "<div class='upload-cat-title'>Sales Invoices</div>"
            "<div class='upload-cat-sub'>Money <strong>incoming</strong> "
            "— invoices you issued to customers</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        sales_files = st.file_uploader(
            "sales",
            type=["pdf", "png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="sales_up",
            label_visibility="collapsed",
        )
        sales_files = sales_files or []
        if len(sales_files) > per_cat:
            st.warning(f"Only the first {per_cat} sales invoices will be processed.")
            sales_files = sales_files[:per_cat]
        for f in sales_files:
            typed_uploads.append((f, "sales"))
        if sales_files:
            st.caption(f"{len(sales_files)} sales invoice"
                       f"{'s' if len(sales_files) != 1 else ''}")

    with purchase_col:
        st.markdown(
            "<div class='upload-cat upload-cat-purchase'>"
            "<div class='upload-cat-title'>Purchase Bills</div>"
            "<div class='upload-cat-sub'>Money <strong>outgoing</strong> "
            "— bills you received from suppliers</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        purchase_files = st.file_uploader(
            "purchase",
            type=["pdf", "png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="purchase_up",
            label_visibility="collapsed",
        )
        purchase_files = purchase_files or []
        if len(purchase_files) > per_cat:
            st.warning(f"Only the first {per_cat} purchase bills will be processed.")
            purchase_files = purchase_files[:per_cat]
        for f in purchase_files:
            typed_uploads.append((f, "purchase"))
        if purchase_files:
            st.caption(f"{len(purchase_files)} purchase bill"
                       f"{'s' if len(purchase_files) != 1 else ''}")

    return bank_df, typed_uploads


def _detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag logical duplicates within the extraction batch.

    Uses the vendor canonicalizer so "Amazon" / "Amazon Inc" / "AMZN.COM" all
    collapse to a single canonical form before comparison — catches more
    duplicates than naive string lowercasing.

    Two heuristics, in priority order:
      1. Same canonical vendor + invoice number (strongest signal)
      2. Same canonical vendor + date + amount (catches re-scans without inv#)
    """
    from engine.vendor_matching import canonicalize

    df = df.copy()
    df["_dup_warning"] = ""
    if len(df) < 2:
        return df

    canon_vendor = df["vendor"].fillna("").astype(str).apply(
        lambda v: canonicalize(v).canonical
    )
    invno = df["invoice_id"].fillna("").astype(str).str.strip().str.lower()
    date = df["date"].fillna("").astype(str)
    amount = df["amount"].fillna(0.0).astype(float).round(2)

    # Rule 1: same canonical vendor + invoice # (only when invoice # present)
    has_inv = invno != ""
    inv_key = (canon_vendor + "||" + invno).where(has_inv, "")
    inv_counts = inv_key.value_counts()
    dup_inv_keys = {k for k, c in inv_counts.items() if c > 1 and k}
    df.loc[inv_key.isin(dup_inv_keys), "_dup_warning"] = "Duplicate invoice #"

    # Rule 2: same canonical vendor + date + amount (don't overwrite a rule-1 hit)
    full_key = canon_vendor + "||" + date + "||" + amount.astype(str)
    full_counts = full_key.value_counts()
    dup_full_keys = {k for k, c in full_counts.items() if c > 1}
    mask = full_key.isin(dup_full_keys) & (df["_dup_warning"] == "")
    df.loc[mask, "_dup_warning"] = "Same vendor / date / amount"

    return df


def _run_extraction(typed_uploads: list[tuple]) -> None:
    """
    Persist uploads, dedupe, call extractor only on new files, build editable DataFrame.

    `typed_uploads` is a list of (UploadedFile, doc_type) tuples where doc_type
    is "sales" or "purchase" — declared by the user at upload time. The doc_type
    is passed to the extractor for a specialized prompt AND becomes part of the
    cache key so the same PDF uploaded under different types extracts separately.
    """
    if not typed_uploads:
        st.warning("Upload at least one invoice first.")
        return

    # ── Step 1: Save + hash all uploads, dedupe identical (file_hash + doc_type)
    seen: set[tuple[str, str]] = set()  # (file_hash, doc_type)
    files_meta: list[dict] = []
    duplicate_files_dropped = 0
    for up, doc_type in typed_uploads:
        raw = up.getvalue()
        mime = up.type or _mime_for(up.name)
        file_hash, storage_path = save_upload(raw, up.name, mime)
        key = (file_hash, doc_type)
        if key in seen:
            duplicate_files_dropped += 1
            continue
        seen.add(key)
        files_meta.append({
            "filename": up.name,
            "raw": raw,
            "mime": mime,
            "file_hash": file_hash,
            "storage_path": storage_path,
            "doc_type": doc_type,
        })

    if duplicate_files_dropped:
        st.toast(
            f"Skipped {duplicate_files_dropped} identical file"
            f"{'s' if duplicate_files_dropped != 1 else ''}"
        )

    # ── Step 2: Look up DB cache — match by (file_hash, doc_type) tuple
    hashes = list({m["file_hash"] for m in files_meta})
    cached_by_key: dict[tuple[str, str], "ExtractedInvoice"] = {}
    if hashes:
        with get_session() as session:
            existing = list(session.exec(
                select(ExtractedInvoice).where(ExtractedInvoice.file_hash.in_(hashes))
            ).all())
            for r in existing:
                cached_by_key[(r.file_hash, r.doc_type)] = r

    # ── Step 3: Extract only the uncached files
    uncached = [
        m for m in files_meta
        if (m["file_hash"], m["doc_type"]) not in cached_by_key
    ]
    extracted_by_key: dict[tuple[str, str], tuple[ExtractionResult, int]] = {}
    if uncached:
        progress = st.progress(0.0, text=f"Extracting {len(uncached)} invoice(s)...")
        results = extract_batch([
            (m["filename"], m["raw"], m["mime"], m["doc_type"]) for m in uncached
        ])
        progress.progress(1.0)
        for meta, result in zip(uncached, results):
            inv_id = _persist_extraction(
                result, meta["file_hash"], meta["storage_path"], meta["doc_type"],
            )
            extracted_by_key[(meta["file_hash"], meta["doc_type"])] = (result, inv_id)

    if cached_by_key:
        st.toast(
            f"Reused {len(cached_by_key)} previously-extracted invoice"
            f"{'s' if len(cached_by_key) != 1 else ''}"
        )

    # ── Step 4: Build the unified DataFrame (cached + fresh, original upload order)
    rows = []
    for meta in files_meta:
        key = (meta["file_hash"], meta["doc_type"])
        if key in cached_by_key:
            existing = cached_by_key[key]
            rows.append({
                "txn_id": f"inv:{existing.id}",
                "filename": meta["filename"],
                "vendor": existing.vendor,
                "doc_type": existing.doc_type or meta["doc_type"],
                "invoice_id": existing.invoice_id or "",
                "date": existing.date,
                "amount": existing.amount,
                "currency": existing.currency,
                "confidence": round(existing.extraction_confidence * 100),
                "cached": True,
                "error": existing.extraction_error or "",
                "_file_hash": existing.file_hash,
                "_storage_path": existing.storage_path,
                "_mime": existing.mime_type,
                "_filename": meta["filename"],
            })
        else:
            result, inv_id = extracted_by_key[key]
            rows.append({
                "txn_id": f"inv:{inv_id}",
                "filename": meta["filename"],
                "vendor": result.vendor or "?",
                "doc_type": result.document_type or meta["doc_type"],
                "invoice_id": result.invoice_id or "",
                "date": result.date or "",
                "amount": result.amount,
                "currency": result.currency or "USD",
                "confidence": round(result.confidence * 100),
                "cached": False,
                "error": result.error or "",
                "_file_hash": meta["file_hash"],
                "_storage_path": meta["storage_path"],
                "_mime": meta["mime"],
                "_filename": meta["filename"],
            })

    df = pd.DataFrame(rows)
    df = _detect_duplicates(df)

    st.session_state["invoice_df"] = df
    # Drop any prior reconciliation report — needs to be re-run after re-extract
    st.session_state.pop("report", None)


def _retry_extraction(idx, file_hash: str, doc_type: str, filename: str,
                       storage_path: str, mime: str) -> None:
    """Re-run extraction for a single failed file. Bypasses session-state cache;
    re-reads file bytes from disk; updates the DB row in place and refreshes
    the in-session DataFrame."""
    import json
    from mcp_server.tools.invoice_extractor import extract_invoice

    try:
        file_bytes = load_file(storage_path)
    except Exception as e:  # noqa: BLE001
        st.toast(_friendly_error(e))
        return

    result = extract_invoice(file_bytes, filename, mime, doc_type)

    # Update or create DB row
    with get_session() as session:
        existing = session.exec(
            select(ExtractedInvoice).where(
                ExtractedInvoice.file_hash == file_hash,
                ExtractedInvoice.doc_type == doc_type,
            )
        ).first()
        if existing:
            existing.vendor = result.vendor
            existing.invoice_id = result.invoice_id
            existing.date = result.date
            existing.amount = result.amount
            existing.currency = result.currency
            existing.raw_extraction_json = json.dumps(result.raw_json)
            existing.extraction_confidence = result.confidence
            existing.extraction_error = result.error
            session.add(existing)

    # Refresh the in-session DataFrame
    df = st.session_state.get("invoice_df")
    if df is not None and idx in df.index:
        df.at[idx, "vendor"] = result.vendor or "?"
        df.at[idx, "doc_type"] = doc_type
        df.at[idx, "invoice_id"] = result.invoice_id or ""
        df.at[idx, "date"] = result.date or ""
        df.at[idx, "amount"] = result.amount
        df.at[idx, "currency"] = result.currency or "INR"
        df.at[idx, "confidence"] = round(result.confidence * 100)
        df.at[idx, "error"] = result.error or ""
        st.session_state["invoice_df"] = _detect_duplicates(df)

    # Invalidate any prior report
    st.session_state.pop("report", None)

    if result.error:
        st.toast(f"Still failing: {_friendly_error(result.error)}")
    else:
        st.toast(f"Re-extracted {filename}")


def _render_failed_panel(failed_df: pd.DataFrame) -> None:
    """
    Friendly panel listing rows where extraction failed, with a per-row
    Re-extract button. Sits above the editable invoice table.
    """
    n = len(failed_df)
    st.markdown('<span class="section-tag">Extraction issues</span>',
                unsafe_allow_html=True)
    st.caption(
        f"{n} file{'s' if n != 1 else ''} could not be read. "
        "Click Re-extract to try again — most failures are transient."
    )
    for idx, row in failed_df.iterrows():
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 5, 1.5], gap="small")
            c1.markdown(
                f"<div class='dup-vendor'><strong>{row['filename']}</strong>"
                f"<br><span class='dup-file'>{row.get('doc_type', 'unknown')}</span></div>",
                unsafe_allow_html=True,
            )
            c2.markdown(
                f"<div class='failed-reason'>{_friendly_error(row['error'])}</div>",
                unsafe_allow_html=True,
            )
            if c3.button("Re-extract", key=f"retry_{idx}",
                         help="Try extracting this file again",
                         use_container_width=True):
                _retry_extraction(
                    idx,
                    file_hash=str(row.get("_file_hash") or ""),
                    doc_type=str(row.get("doc_type") or "unknown"),
                    filename=str(row["filename"]),
                    storage_path=str(row["_storage_path"]),
                    mime=str(row["_mime"]),
                )
                st.rerun()


def _render_duplicate_panel() -> None:
    """
    Compact panel listing duplicate rows with explicit per-row delete buttons.
    Renders only when duplicates exist. Sits between the extraction table
    and the Run Reconciliation button — the user can clean up before matching.
    """
    df = st.session_state.get("invoice_df")
    if df is None or df.empty or "_dup_warning" not in df.columns:
        return

    dups = df[df["_dup_warning"] != ""]
    if dups.empty:
        return

    st.markdown('<span class="section-tag">Possible duplicates</span>',
                unsafe_allow_html=True)
    st.caption(
        f"{len(dups)} row{'s' if len(dups) != 1 else ''} flagged. "
        "Delete any true duplicate; the others stay in the run."
    )

    for idx, row in dups.iterrows():
        with st.container(border=True):
            # Tight one-line: vendor / amount / date / reason / delete
            c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 3, 1], gap="small")
            c1.markdown(
                f"<div class='dup-vendor'><strong>{row['vendor'] or '?'}</strong>"
                f"<br><span class='dup-file'>{row['filename']}</span></div>",
                unsafe_allow_html=True,
            )
            c2.markdown(f"<div class='dup-amt'>${float(row['amount']):,.2f}</div>",
                        unsafe_allow_html=True)
            c3.markdown(f"<div class='dup-date'>{row['date']}</div>",
                        unsafe_allow_html=True)
            c4.markdown(
                f"<div class='dup-reason'>{row['_dup_warning']}</div>",
                unsafe_allow_html=True,
            )
            if c5.button("Delete", key=f"del_dup_{idx}",
                         help="Remove this row from the run"):
                new_df = df.drop(idx).reset_index(drop=True)
                new_df = _detect_duplicates(new_df)
                st.session_state["invoice_df"] = new_df
                # Invalidate any prior reconciliation since the input changed
                st.session_state.pop("report", None)
                st.toast(f"Deleted {row['filename']}")
                st.rerun()


def _render_extraction_table() -> pd.DataFrame | None:
    """Editable table of extracted invoices. Returns the (possibly edited) df."""
    df = st.session_state.get("invoice_df")
    if df is None or df.empty:
        return None

    # Surface any extraction errors prominently with per-row Re-extract.
    if "error" in df.columns:
        errors = df[df["error"] != ""]
        if not errors.empty:
            _render_failed_panel(errors)

    # Warn about logical duplicates so user can delete extras
    if "_dup_warning" in df.columns:
        dups = df[df["_dup_warning"] != ""]
        if not dups.empty:
            n = len(dups)
            st.warning(
                f"{n} possible duplicate{'s' if n != 1 else ''} detected. "
                "Review the Note column — delete a row from the table to exclude it from reconciliation."
            )

    st.markdown('<span class="section-tag">Extracted Invoices</span>', unsafe_allow_html=True)
    cached_count = int(df["cached"].sum()) if "cached" in df.columns else 0
    if cached_count:
        st.caption(f"{cached_count} row(s) reused from previously-extracted files.")

    display_cols = [
        "filename", "doc_type", "vendor", "invoice_id", "date",
        "amount", "currency", "confidence", "_dup_warning",
    ]
    hidden_cols = ["txn_id", "_file_hash", "_storage_path", "_mime", "_filename", "cached", "error"]
    # Make sure all expected columns exist (defensive — old session-state shapes)
    for col in display_cols + hidden_cols:
        if col not in df.columns:
            df[col] = "" if col != "cached" else False

    edited = st.data_editor(
        df[display_cols + hidden_cols],
        column_config={
            "filename": st.column_config.TextColumn("File", disabled=True, width="medium"),
            "doc_type": st.column_config.SelectboxColumn(
                "Type", options=["sales", "purchase", "unknown"], width="small",
                help="Sales = money INCOMING (issued to customer). Purchase = money OUTGOING (received from supplier).",
            ),
            "vendor": st.column_config.TextColumn(
                "Counterparty (customer / supplier)", width="medium",
                help="The OTHER party on the transaction — NOT the company on your letterhead.",
            ),
            "invoice_id": st.column_config.TextColumn("Invoice #", width="small"),
            "date": st.column_config.TextColumn("Date (YYYY-MM-DD)", width="small"),
            "amount": st.column_config.NumberColumn("Amount", format="%.2f", width="small"),
            "currency": st.column_config.TextColumn("Cur.", width="small"),
            "confidence": st.column_config.ProgressColumn(
                "Conf", min_value=0, max_value=100, format="%d%%", width="small"
            ),
            "_dup_warning": st.column_config.TextColumn(
                "Note", disabled=True, width="small",
                help="Possible duplicate — same counterparty + invoice # or same counterparty/date/amount.",
            ),
            "txn_id": None,
            "_file_hash": None,
            "_storage_path": None,
            "_mime": None,
            "_filename": None,
            "cached": None,
            "error": None,
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="invoice_editor",
    )

    st.session_state["invoice_df"] = edited
    return edited


# ═════════════════════════════════════════════════════════════════════════════
#  Reconciliation run
# ═════════════════════════════════════════════════════════════════════════════

def _invoices_to_ledger_df(invoices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert the editable invoice table into the canonical ledger DataFrame
    expected by the matching cascade: columns txn_id, date, description, amount.

    Sign convention (matches the bank statement):
      • doc_type == "sales"    → amount POSITIVE (money incoming, credit)
      • doc_type == "purchase" → amount NEGATIVE (money outgoing, debit)
      • doc_type == "unknown"  → amount POSITIVE (best-guess)
    """
    valid = invoices_df[
        (invoices_df["error"] == "") if "error" in invoices_df.columns else True
    ].copy() if "error" in invoices_df.columns else invoices_df.copy()

    if valid.empty:
        return pd.DataFrame(columns=["txn_id", "date", "description", "amount"])

    rows = []
    for _, r in valid.iterrows():
        vendor = str(r.get("vendor") or "").strip() or "Unknown"
        inv_no = str(r.get("invoice_id") or "").strip()
        desc = f"{vendor} #{inv_no}" if inv_no else vendor

        raw_amount = float(r.get("amount") or 0.0)
        doc_type = str(r.get("doc_type") or "unknown").lower()
        if doc_type == "purchase":
            signed_amount = -abs(raw_amount)
        else:
            signed_amount = abs(raw_amount)

        rows.append({
            "txn_id": str(r["txn_id"]),
            "date": str(r.get("date") or "").strip(),
            "description": desc,
            "amount": signed_amount,
        })
    return pd.DataFrame(rows)


def _run_reconciliation(
    bank_df: pd.DataFrame,
    invoices_df: pd.DataFrame,
    fuzzy_threshold: float,
    amt_tolerance: float,
    date_window: int,
) -> None:
    ledger_raw = _invoices_to_ledger_df(invoices_df)
    if ledger_raw.empty:
        st.error("No valid invoices to reconcile against.")
        st.stop()

    b_norm = normalise_df(bank_df.copy(), is_ledger=False)
    # The ledger df is already in canonical shape; pass through normaliser for safety
    l_norm = normalise_df(ledger_raw, is_ledger=True)

    if b_norm["date"].isna().all():
        st.error("Bank statement dates missing or invalid.")
        st.stop()
    if l_norm["date"].isna().all():
        st.error("Invoice dates missing or invalid. Fix the date column above and re-run.")
        st.stop()

    with get_session() as session:
        alias_rows = session.exec(select(VendorAlias)).all()
        alias_map = {a.alias: a.canonical_name for a in alias_rows}

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    report = run_matching_cascade(
        b_norm, l_norm, run_id,
        aliases=alias_map,
        fuzzy_threshold=fuzzy_threshold,
        amount_tolerance=amt_tolerance,
        date_window_days=date_window,
    )

    status_to_enum = {
        "exact": MatchStatus.EXACT,
        "fuzzy": MatchStatus.FUZZY,
        "one_to_many": MatchStatus.ONE_TO_MANY,
        "unmatched": MatchStatus.UNMATCHED,
    }
    with get_session() as session:
        for item in report.match_results:
            session.add(MatchRecord(
                run_id=run_id,
                bank_txn_id=item.bank_txn_id,
                ledger_txn_id=item.ledger_txn_id,
                status=status_to_enum.get(item.status, MatchStatus.UNMATCHED),
                score=item.score,
                reasoning_path=item.reasoning_path,
                amount_diff=item.amount_diff,
                date_diff_days=item.date_diff_days,
                requires_human_review=item.requires_human_review,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

    st.session_state["report"] = report
    st.session_state["bank_normalized"] = b_norm
    st.session_state["ledger_normalized"] = l_norm


# ═════════════════════════════════════════════════════════════════════════════
#  Results review
# ═════════════════════════════════════════════════════════════════════════════

def _render_summary(report) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Processed", report.total_bank_rows)
    c2.metric("Matched", report.exact_matches, delta=f"{report.match_rate:.0f}% match rate")
    c3.metric("Needs Review", report.fuzzy_matches + report.one_to_many_matches)
    c4.metric("Unmatched", report.unmatched_bank)

    try:
        ts = datetime.strptime(report.run_id.replace("run_", ""), "%Y%m%d_%H%M%S")
        st.caption(f"Last run: {ts.strftime('%H:%M:%S UTC, %Y-%m-%d')}")
    except Exception:
        st.caption(f"Run ID: {report.run_id}")


@st.dialog("Invoice")
def _show_invoice_dialog(storage_path: str, mime: str, filename: str) -> None:
    st.caption(filename)
    abs_path = absolute_path(storage_path)
    if mime == "application/pdf":
        # Render page 1 to PNG for inline preview
        try:
            from mcp_server.tools.invoice_extractor import _pdf_first_page_png
            with open(abs_path, "rb") as f:
                pdf_bytes = f.read()
            st.image(_pdf_first_page_png(pdf_bytes), use_container_width=True)
            st.download_button("Download original PDF", data=pdf_bytes,
                               file_name=filename, mime="application/pdf")
        except Exception as e:
            st.error(_friendly_error(e))
    else:
        st.image(abs_path, use_container_width=True)


def _render_many_to_one(group_rows: list, b_norm: pd.DataFrame, l_norm: pd.DataFrame,
                         run_id: str, invoice_lookup: dict[str, dict]) -> None:
    """
    Render a single MANY_TO_ONE group: one invoice on the right, stacked bank
    lines on the left, group-level approve/reject buttons.

    Args:
        group_rows: all MatchResult rows sharing the same ledger_txn_id and
                    status="many_to_one". The first one is the representative.
    """
    if not group_rows:
        return
    rep = group_rows[0]
    badge_text, badge_class = STATUS_BADGE["many_to_one"]
    bank_ids = rep.matched_bank_ids or [rep.bank_txn_id]
    ledger = _row(l_norm, rep.ledger_txn_id) if rep.ledger_txn_id else None
    bank_rows = [_row(b_norm, bid) for bid in bank_ids]
    bank_rows = [b for b in bank_rows if b is not None]

    # Group decision: store under a stable key derived from the bank-id set
    group_key = "decision_m2o_" + "_".join(sorted(bank_ids))
    decision = st.session_state.get(group_key)

    with st.container(border=True):
        head_l, head_r = st.columns([5, 1])
        with head_l:
            total = sum(b["amount"] for b in bank_rows)
            inv_amt = ledger["amount"] if ledger else 0.0
            diff = abs(total - inv_amt)
            badge_html = (
                f'<span class="badge {badge_class}">{badge_text}</span>'
                f' <span class="bank-ref">{len(bank_rows)} bank lines = '
                f'${total:,.2f} vs invoice ${inv_amt:,.2f}'
                + (f' (diff ${diff:.2f})' if diff > 0.005 else '')
                + '</span>'
            )
            st.markdown(badge_html, unsafe_allow_html=True)

        with head_r:
            if decision == "approved":
                st.markdown("<div class='inline-status status-ok'>Approved</div>",
                            unsafe_allow_html=True)
            elif decision == "rejected":
                st.markdown("<div class='inline-status status-bad'>Rejected</div>",
                            unsafe_allow_html=True)
            else:
                b1, b2 = st.columns([1, 1], gap="small")
                if b1.button("Reject", key=f"m2o_rej_{group_key}",
                             help="Reject this group", use_container_width=True):
                    st.session_state[group_key] = "rejected"
                    for gr in group_rows:
                        _update_match_record(
                            run_id, gr.bank_txn_id,
                            human_approved=False, status=MatchStatus.UNMATCHED,
                        )
                    st.rerun()
                if b2.button("Approve", key=f"m2o_app_{group_key}", type="primary",
                             help="Approve all installments", use_container_width=True):
                    st.session_state[group_key] = "approved"
                    for gr in group_rows:
                        _update_match_record(
                            run_id, gr.bank_txn_id,
                            human_approved=True,
                            status=MatchStatus.HUMAN_CORRECTED,
                        )
                    st.rerun()

        # Side-by-side: stacked bank lines on the left, single invoice on the right
        cl, cr = st.columns(2, gap="small")
        with cl:
            inner_html = ['<div class="compare-card bank">']
            inner_html.append(f'<div class="label">Bank Statement · {len(bank_rows)} lines</div>')
            for b in bank_rows:
                inner_html.append(
                    f'<div class="m2o-line">'
                    f'<span class="m2o-amt">${b["amount"]:,.2f}</span>'
                    f'<span class="m2o-date">{b["date"]}</span>'
                    f'<span class="m2o-desc">{b["name"]}</span>'
                    f'</div>'
                )
            inner_html.append('</div>')
            st.markdown("".join(inner_html), unsafe_allow_html=True)

        with cr:
            st.markdown(_card_html("Invoice (total)", "ledger", ledger), unsafe_allow_html=True)

            # View invoice link (if file stored)
            inv_info = invoice_lookup.get(rep.ledger_txn_id or "")
            if inv_info:
                if st.button("View invoice", key=f"view_m2o_{group_key}",
                             help=inv_info["filename"]):
                    _show_invoice_dialog(inv_info["storage_path"],
                                         inv_info["mime"], inv_info["filename"])

        with st.expander("Why this group?"):
            st.write(rep.reasoning_path or "No reasoning recorded.")


def _render_pair(r, b_norm: pd.DataFrame, l_norm: pd.DataFrame, run_id: str,
                 invoice_lookup: dict[str, dict]) -> None:
    raw_status = r.status.value if hasattr(r.status, "value") else str(r.status)
    badge_text, badge_class = STATUS_BADGE.get(raw_status, ("?", "badge-fuzzy"))
    decision_key = f"decision_{r.bank_txn_id}"
    decision = st.session_state.get(decision_key)

    with st.container(border=True):
        # Header: badge + confidence + action buttons
        head_l, head_r = st.columns([5, 1])
        with head_l:
            badge_html = (
                f'<span class="badge {badge_class}">{badge_text}</span>'
                f' <span class="bank-ref">{r.bank_txn_id}</span>'
            )
            if raw_status != "unmatched":
                badge_html += f' &nbsp; {_confidence_bar_html(r.score)}'
            st.markdown(badge_html, unsafe_allow_html=True)

        with head_r:
            if raw_status == "exact":
                st.markdown("<div class='inline-status status-ok'>Auto-matched</div>",
                            unsafe_allow_html=True)
            elif decision == "approved":
                st.markdown("<div class='inline-status status-ok'>Approved</div>",
                            unsafe_allow_html=True)
            elif decision == "rejected":
                st.markdown("<div class='inline-status status-bad'>Rejected</div>",
                            unsafe_allow_html=True)
            elif decision == "entry_created":
                st.markdown("<div class='inline-status status-new'>Bill created</div>",
                            unsafe_allow_html=True)
            elif raw_status in ("fuzzy", "one_to_many", "possible"):
                b1, b2 = st.columns([1, 1], gap="small")
                if b1.button("Reject", key=f"rej_{r.bank_txn_id}",
                             help="Reject this match", use_container_width=True):
                    st.session_state[decision_key] = "rejected"
                    _update_match_record(run_id, r.bank_txn_id, human_approved=False,
                                         status=MatchStatus.UNMATCHED)
                    st.rerun()
                if b2.button("Approve", key=f"app_{r.bank_txn_id}", type="primary",
                             help="Approve this match", use_container_width=True):
                    st.session_state[decision_key] = "approved"
                    _update_match_record(run_id, r.bank_txn_id, human_approved=True,
                                         status=MatchStatus.HUMAN_CORRECTED)
                    # Auto-learn alias when user approves a fuzzy or possible match.
                    # Next run, the exact bank description hits the alias DB at O(1).
                    if raw_status in ("fuzzy", "possible") and r.ledger_txn_id:
                        _auto_learn_alias_from_match(r, b_norm, l_norm)
                    st.rerun()

        # Comparison cards
        bank_data = _row(b_norm, r.bank_txn_id)

        if raw_status == "one_to_many":
            inv_ids = ", ".join(r.matched_ledger_ids or []) or "-"
            total = 0.0
            if r.matched_ledger_ids:
                rows = l_norm[l_norm["txn_id"].isin(r.matched_ledger_ids)]
                total = float(rows["amount"].sum()) if not rows.empty else 0.0
            ledger_data = {
                "id": inv_ids,
                "name": f"{len(r.matched_ledger_ids or [])} invoices (split)",
                "date": "-",
                "amount": total,
            }
            _compare_row(bank_data, ledger_data)
        elif raw_status == "unmatched":
            _compare_row(bank_data, None, empty_msg="No invoice match found.")
            _render_create_entry(r, bank_data, run_id, decision_key)
        else:
            ledger_data = _row(l_norm, r.ledger_txn_id) if r.ledger_txn_id else None
            _compare_row(bank_data, ledger_data)

            # View invoice link
            inv_info = invoice_lookup.get(r.ledger_txn_id or "")
            if inv_info:
                if st.button("View invoice", key=f"view_{r.bank_txn_id}",
                             help=inv_info["filename"]):
                    _show_invoice_dialog(inv_info["storage_path"],
                                         inv_info["mime"], inv_info["filename"])

        # Mismatch summary
        if raw_status != "exact":
            with st.expander("Why this match?"):
                st.write(r.reasoning_path or "No reasoning recorded.")
                if raw_status == "fuzzy" and bank_data and r.ledger_txn_id:
                    ledger_data = _row(l_norm, r.ledger_txn_id)
                    if ledger_data:
                        summary = generate_fuzzy_suggestion(
                            bank_desc=bank_data["name"], bank_amount=bank_data["amount"],
                            bank_date=bank_data["date"],
                            ledger_desc=ledger_data["name"], ledger_amount=ledger_data["amount"],
                            ledger_date=ledger_data["date"],
                            score=r.score, amount_diff=r.amount_diff or 0.0,
                            date_diff_days=r.date_diff_days or 0,
                        )
                        st.caption(summary)


def _render_create_entry(r, bank_data: dict | None, run_id: str, decision_key: str) -> None:
    """Inline 'add a new bill' form for an unmatched bank line."""
    if bank_data is None:
        return

    show_key = f"show_create_{r.bank_txn_id}"
    if not st.session_state.get(show_key):
        c1, _ = st.columns([2, 8])
        if c1.button("+ Add Bill", key=f"crt_{r.bank_txn_id}", type="primary",
                     use_container_width=True,
                     help=f"Create a new bill for this bank line "
                          f"(${bank_data['amount']:,.2f} on {bank_data['date']})"):
            st.session_state[show_key] = True
            st.rerun()
        return

    with st.form(key=f"form_{r.bank_txn_id}", clear_on_submit=False, border=True):
        st.markdown(
            f"<div class='mini-form-hint'>New bill · "
            f"<strong>${bank_data['amount']:,.2f}</strong> · {bank_data['date']}</div>",
            unsafe_allow_html=True,
        )
        vendor = st.text_input(
            "Vendor",
            placeholder="e.g. Amazon, Stripe",
            key=f"vendor_{r.bank_txn_id}",
            label_visibility="collapsed",
        )
        sc1, sc2 = st.columns([1, 1], gap="small")
        save_clicked = sc1.form_submit_button("Save", type="primary",
                                              use_container_width=True)
        cancel_clicked = sc2.form_submit_button("Cancel",
                                                use_container_width=True)
        if cancel_clicked:
            st.session_state[show_key] = False
            st.rerun()
        if save_clicked:
            if not vendor.strip():
                st.warning("Vendor name is required.")
            else:
                entry_id = _create_manual_entry(
                    run_id=run_id, bank_txn_id=r.bank_txn_id,
                    vendor=vendor.strip(),
                    amount=bank_data["amount"], date=bank_data["date"],
                    description=bank_data["name"],
                )
                _upsert_alias(bank_data["name"], vendor.strip())
                _update_match_record(
                    run_id, r.bank_txn_id,
                    ledger_txn_id=f"manual:{entry_id}",
                    status=MatchStatus.HUMAN_CORRECTED,
                    human_approved=True,
                )
                st.session_state[decision_key] = "entry_created"
                st.session_state[show_key] = False
                st.toast(f"Bill created for {vendor.strip()}")
                st.rerun()


def _render_bulk_actions(report, run_id: str) -> None:
    """Quick-action buttons: approve all high-confidence, reject all low-confidence."""
    pending = [
        r for r in report.match_results
        if (r.status.value if hasattr(r.status, "value") else r.status) == "fuzzy"
        and st.session_state.get(f"decision_{r.bank_txn_id}") is None
    ]
    if not pending:
        return

    high = [r for r in pending if r.score >= 0.9]
    low = [r for r in pending if r.score <= 0.6]
    if not high and not low:
        return

    c1, c2, _ = st.columns([2, 2, 6])
    if high and c1.button(
        f"Approve all >= 90% ({len(high)})",
        key="bulk_approve", use_container_width=True,
    ):
        for r in high:
            st.session_state[f"decision_{r.bank_txn_id}"] = "approved"
            _update_match_record(
                run_id, r.bank_txn_id,
                human_approved=True,
                status=MatchStatus.HUMAN_CORRECTED,
            )
        st.rerun()

    if low and c2.button(
        f"Reject all <= 60% ({len(low)})",
        key="bulk_reject", use_container_width=True,
    ):
        for r in low:
            st.session_state[f"decision_{r.bank_txn_id}"] = "rejected"
            _update_match_record(
                run_id, r.bank_txn_id,
                human_approved=False,
                status=MatchStatus.UNMATCHED,
            )
        st.rerun()


def _filter_results(results, chosen: str):
    if chosen == "All":
        return results
    mapping = {
        "Matched": ["exact", "human_corrected"],
        "Close Match": ["fuzzy"],
        "Split Payment": ["one_to_many"],
        "Installments": ["many_to_one"],
        "Possible": ["possible"],
        "Unmatched": ["unmatched"],
        "Needs Review": ["fuzzy", "one_to_many", "many_to_one", "possible", "unmatched"],
    }
    keep = mapping.get(chosen, [])
    return [r for r in results if (r.status.value if hasattr(r.status, "value") else r.status) in keep]


def _render_export(report, b_norm: pd.DataFrame, l_norm: pd.DataFrame) -> None:
    st.markdown('<span class="section-tag">Export</span>', unsafe_allow_html=True)
    summary_rows = []
    for r in report.match_results:
        raw_status = r.status.value if hasattr(r.status, "value") else str(r.status)
        summary_rows.append({
            "bank_txn_id": r.bank_txn_id,
            "invoice_txn_id": r.ledger_txn_id or "-",
            "status": STATUS_LABEL.get(raw_status, raw_status),
            "confidence": f"{r.score * 100:.0f}%",
            "amount_diff": r.amount_diff or 0.0,
            "date_diff_days": r.date_diff_days or 0,
        })
    summary_df = pd.DataFrame(summary_rows)
    c1, c2 = st.columns(2)
    c1.download_button("Reconciliation report", data=summary_df.to_csv(index=False),
                       file_name=f"reconciliation_{report.run_id}.csv",
                       mime="text/csv", use_container_width=True)
    if not b_norm.empty:
        c2.download_button("Normalised bank file", data=b_norm.to_csv(index=False),
                           file_name="bank_normalised.csv",
                           mime="text/csv", use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ═════════════════════════════════════════════════════════════════════════════

def render() -> None:
    # Toast feedback after a fresh reconciliation run
    if st.session_state.pop("_just_ran", False):
        st.toast("Reconciliation complete")

    # Matching settings — tucked into a collapsed expander
    with st.expander("Matching settings", expanded=False):
        c1, c2, c3 = st.columns(3)
        fuzzy_threshold = c1.slider("Fuzzy threshold", 0.5, 1.0, 0.8, 0.05)
        amt_tolerance = c2.number_input("Amount tolerance", min_value=0.0, value=0.01, step=0.01)
        date_window = c3.number_input("Date window (days)", min_value=1, max_value=30, value=7)

    # 1. Upload
    bank_df, uploaded = _render_upload()
    bank_ok = bank_df is not None
    have_uploads = bool(uploaded)

    # 2. Extract button — relabels to "Re-extract" once invoices have been processed
    has_extraction = st.session_state.get("invoice_df") is not None
    extract_label = "Re-extract Invoices" if has_extraction else "Extract Invoices"
    extract_col, _ = st.columns([2, 8])
    if extract_col.button(
        extract_label, type="primary",
        disabled=not have_uploads, use_container_width=True,
    ):
        with st.spinner("Extracting invoices with vision model..."):
            _run_extraction(uploaded)
        st.toast("Extraction complete")
        st.rerun()

    # 3. Review/edit table (if extraction has happened)
    edited_df = _render_extraction_table()

    # 3a. Surface duplicates with explicit delete buttons (if any)
    _render_duplicate_panel()

    # 4. Run Reconciliation button — relabels to "Re-run" once a run exists
    has_prior_run = "report" in st.session_state
    run_label = "Re-run Reconciliation" if has_prior_run else "Run Reconciliation"
    can_run = bank_ok and edited_df is not None and not edited_df.empty
    run_col, _ = st.columns([2, 8])
    if run_col.button(
        run_label, type="primary",
        disabled=not can_run, use_container_width=True,
        key="run_recon",
    ):
        # Clear everything tied to the previous run so the user gets a fresh view.
        # Drop `report` too — otherwise the old summary lingers during the spinner.
        for k in list(st.session_state.keys()):
            if k.startswith(("decision_", "show_create_", "vendor_",
                             "fuzzy_sug_", "miss_sug_")):
                del st.session_state[k]
        st.session_state.pop("report", None)
        st.session_state.pop("bank_normalized", None)
        st.session_state.pop("ledger_normalized", None)

        with st.spinner("Running matching cascade..."):
            try:
                _run_reconciliation(bank_df, edited_df, fuzzy_threshold,
                                    amt_tolerance, date_window)
                st.session_state["_just_ran"] = True
                st.rerun()
            except Exception as ex:
                st.error(_friendly_error(ex))
                st.stop()

    # 5. Results
    if "report" not in st.session_state:
        return

    report = st.session_state["report"]
    b_norm = st.session_state["bank_normalized"]
    l_norm = st.session_state["ledger_normalized"]
    invoice_lookup = _invoice_storage_lookup()

    # Auto-approve high-confidence matches (≥ 0.95). Runs once per fresh run.
    _auto_approve_high_confidence(report, b_norm, l_norm)

    st.markdown('<span class="section-tag">Summary</span>', unsafe_allow_html=True)
    _render_summary(report)

    st.markdown('<span class="section-tag">Review Queue</span>', unsafe_allow_html=True)
    _render_bulk_actions(report, report.run_id)

    # Filter labels show counts so user can see at a glance what's where
    counts = {"exact": 0, "human_corrected": 0, "fuzzy": 0, "one_to_many": 0,
              "many_to_one": 0, "possible": 0, "unmatched": 0}
    for r in report.match_results:
        s = r.status.value if hasattr(r.status, "value") else r.status
        counts[s] = counts.get(s, 0) + 1
    review_count = (counts["fuzzy"] + counts["one_to_many"]
                    + counts["many_to_one"] + counts["possible"]
                    + counts["unmatched"])
    matched_count = counts["exact"] + counts["human_corrected"]

    filter_options = [
        f"All ({len(report.match_results)})",
        f"Matched ({matched_count})",
        f"Close Match ({counts['fuzzy']})",
        f"Split Payment ({counts['one_to_many']})",
        f"Installments ({counts['many_to_one']})",
    ]
    if counts["possible"]:
        filter_options.append(f"Possible ({counts['possible']})")
    filter_options.append(f"Unmatched ({counts['unmatched']})")
    filter_options.append(f"Needs Review ({review_count})")
    chosen_label = st.selectbox("Filter", filter_options, label_visibility="collapsed")
    chosen = chosen_label.split(" (")[0]

    visible = _filter_results(report.match_results, chosen)
    if not visible:
        st.info("No items match the current filter.")
    else:
        # Group MANY_TO_ONE results by ledger_txn_id so installments render as
        # one card instead of N separate cards.
        m2o_groups: dict[str, list] = {}
        for r in visible:
            status_val = r.status.value if hasattr(r.status, "value") else r.status
            if status_val == "many_to_one" and r.ledger_txn_id:
                m2o_groups.setdefault(r.ledger_txn_id, []).append(r)

        rendered_m2o: set[str] = set()
        for r in visible:
            status_val = r.status.value if hasattr(r.status, "value") else r.status
            if status_val == "many_to_one" and r.ledger_txn_id:
                if r.ledger_txn_id in rendered_m2o:
                    continue
                rendered_m2o.add(r.ledger_txn_id)
                _render_many_to_one(
                    m2o_groups[r.ledger_txn_id],
                    b_norm, l_norm, report.run_id, invoice_lookup,
                )
            else:
                _render_pair(r, b_norm, l_norm, report.run_id, invoice_lookup)

    _render_export(report, b_norm, l_norm)
