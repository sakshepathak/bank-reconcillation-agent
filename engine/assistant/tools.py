"""
Org-scoped SQL tools for the in-app assistant.

The whole point of these: the assistant answers questions about MONEY and
COUNTS by calling deterministic functions — it never guesses figures. Every
query is filtered by org_id, so one organisation can never see another's data.

Each tool takes (db, org_id, **params) and returns a plain JSON-serialisable
dict/list. No LLM in here — these are the "exact answer" layer.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlmodel import Session, select

from memory.models import (
    Invoice, Bill, Contact, BankAccount, StatementLine,
    DocumentStatus, StatementLineStatus,
)

# Documents in these states are settled/closed — excluded from "outstanding".
_CLOSED = (DocumentStatus.PAID, DocumentStatus.VOIDED)
_MAX_ROWS = 50


def _today() -> str:
    return date.today().isoformat()


def _outstanding(doc) -> float:
    return round((doc.total or 0.0) - (doc.paid_amount or 0.0), 2)


def _doc_row(doc, kind: str) -> dict:
    return {
        "type": kind,
        "number": doc.number or f"#{doc.id}",
        "contact": doc.contact_name,
        "issue_date": doc.issue_date,
        "due_date": doc.due_date,
        "total": round(doc.total or 0.0, 2),
        "outstanding": _outstanding(doc),
        "currency": doc.currency,
        "status": doc.status.value if hasattr(doc.status, "value") else str(doc.status),
    }


def _open_invoices(db: Session, org_id: int) -> list[Invoice]:
    rows = db.exec(
        select(Invoice)
        .where(Invoice.org_id == org_id)
        .where(Invoice.status != DocumentStatus.PAID)
        .where(Invoice.status != DocumentStatus.VOIDED)
    ).all()
    return [d for d in rows if _outstanding(d) > 0.005]


def _open_bills(db: Session, org_id: int) -> list[Bill]:
    rows = db.exec(
        select(Bill)
        .where(Bill.org_id == org_id)
        .where(Bill.status != DocumentStatus.PAID)
        .where(Bill.status != DocumentStatus.VOIDED)
    ).all()
    return [d for d in rows if _outstanding(d) > 0.005]


# ── Tool implementations ──────────────────────────────────────────────────────

def financial_summary(db: Session, org_id: int) -> dict:
    """High-level money position for the organisation."""
    invoices = _open_invoices(db, org_id)
    bills = _open_bills(db, org_id)

    contacts = db.exec(select(Contact).where(Contact.org_id == org_id)).all()
    accounts = db.exec(
        select(BankAccount).where(BankAccount.org_id == org_id, BankAccount.is_active == True)
    ).all()
    pending = db.exec(
        select(StatementLine)
        .where(StatementLine.org_id == org_id)
        .where(StatementLine.status == StatementLineStatus.PENDING)
    ).all()

    receivable = round(sum(_outstanding(i) for i in invoices), 2)
    payable = round(sum(_outstanding(b) for b in bills), 2)

    return {
        "accounts_receivable": receivable,      # money owed TO you
        "accounts_payable": payable,            # money you owe
        "net_position": round(receivable - payable, 2),
        "open_invoices": len(invoices),
        "open_bills": len(bills),
        "customers": sum(1 for c in contacts if c.contact_type == "customer"),
        "suppliers": sum(1 for c in contacts if c.contact_type == "supplier"),
        "bank_accounts": len(accounts),
        "transactions_pending_reconciliation": len(pending),
    }


def list_outstanding_invoices(
    db: Session, org_id: int, contact_name: Optional[str] = None, limit: int = 20,
) -> dict:
    """Unpaid sales invoices (money customers owe you), largest first."""
    rows = _open_invoices(db, org_id)
    if contact_name:
        needle = contact_name.strip().lower()
        rows = [d for d in rows if needle in (d.contact_name or "").lower()]
    rows.sort(key=_outstanding, reverse=True)
    capped = rows[: min(limit, _MAX_ROWS)]
    return {
        "count": len(rows),
        "total_outstanding": round(sum(_outstanding(d) for d in rows), 2),
        "invoices": [_doc_row(d, "invoice") for d in capped],
    }


def list_outstanding_bills(
    db: Session, org_id: int, contact_name: Optional[str] = None, limit: int = 20,
) -> dict:
    """Unpaid purchase bills (money you owe suppliers), largest first."""
    rows = _open_bills(db, org_id)
    if contact_name:
        needle = contact_name.strip().lower()
        rows = [d for d in rows if needle in (d.contact_name or "").lower()]
    rows.sort(key=_outstanding, reverse=True)
    capped = rows[: min(limit, _MAX_ROWS)]
    return {
        "count": len(rows),
        "total_outstanding": round(sum(_outstanding(d) for d in rows), 2),
        "bills": [_doc_row(d, "bill") for d in capped],
    }


def list_overdue(db: Session, org_id: int, kind: str = "both", limit: int = 25) -> dict:
    """Invoices and/or bills whose due_date has passed and are still outstanding."""
    today = _today()
    out: dict = {"as_of": today}

    def _overdue(docs, k):
        od = [d for d in docs if d.due_date and d.due_date < today]
        od.sort(key=lambda d: d.due_date or "")
        return [{**_doc_row(d, k), "days_overdue": (date.fromisoformat(today) - date.fromisoformat(d.due_date)).days}
                for d in od[: min(limit, _MAX_ROWS)]], round(sum(_outstanding(d) for d in od), 2), len(od)

    if kind in ("invoices", "both"):
        rows, total, n = _overdue(_open_invoices(db, org_id), "invoice")
        out["overdue_invoices"] = rows
        out["overdue_invoices_total"] = total
        out["overdue_invoices_count"] = n
    if kind in ("bills", "both"):
        rows, total, n = _overdue(_open_bills(db, org_id), "bill")
        out["overdue_bills"] = rows
        out["overdue_bills_total"] = total
        out["overdue_bills_count"] = n
    return out


def find_contact(db: Session, org_id: int, name: str) -> dict:
    """Look up a customer/supplier by name and summarise what they owe / are owed."""
    needle = (name or "").strip().lower()
    contacts = db.exec(select(Contact).where(Contact.org_id == org_id)).all()
    matches = [
        c for c in contacts
        if needle in (c.full_name or "").lower() or needle in (c.company or "").lower()
    ]
    if not matches:
        return {"found": False, "query": name, "message": "No contact matched that name."}

    results = []
    for c in matches[:5]:
        inv = [d for d in _open_invoices(db, org_id) if d.contact_id == c.id or (c.full_name and d.contact_name == c.full_name)]
        bil = [d for d in _open_bills(db, org_id) if d.contact_id == c.id or (c.full_name and d.contact_name == c.full_name)]
        results.append({
            "name": c.full_name,
            "company": c.company,
            "type": c.contact_type,
            "email": c.email,
            "owes_you": round(sum(_outstanding(d) for d in inv), 2),
            "you_owe": round(sum(_outstanding(d) for d in bil), 2),
            "open_invoices": [_doc_row(d, "invoice") for d in inv[:10]],
            "open_bills": [_doc_row(d, "bill") for d in bil[:10]],
        })
    return {"found": True, "matches": results}


def bank_accounts_summary(db: Session, org_id: int) -> dict:
    """Each bank account's computed balance and how much is left to reconcile."""
    accounts = db.exec(
        select(BankAccount).where(BankAccount.org_id == org_id, BankAccount.is_active == True)
    ).all()
    out = []
    for a in accounts:
        lines = db.exec(
            select(StatementLine.received, StatementLine.spent, StatementLine.status)
            .where(StatementLine.bank_account_id == a.id)
            .where(StatementLine.org_id == org_id)
        ).all()
        statement = round(sum((r or 0.0) - (s or 0.0) for r, s, _ in lines), 2)
        reconciled = round(sum((r or 0.0) - (s or 0.0) for r, s, st in lines
                               if st != StatementLineStatus.PENDING), 2)
        pending = sum(1 for _, _, st in lines if st == StatementLineStatus.PENDING)
        out.append({
            "name": a.name,
            "bank": a.bank_name,
            "currency": a.currency,
            "statement_balance": statement,
            "reconciled_balance": reconciled,
            "difference": round(statement - reconciled, 2),
            "pending_lines": pending,
        })
    return {"accounts": out}


# ── Knowledge base (RAG) + memory — org-scoped Qdrant ─────────────────────────

def search_knowledge(db: Session, org_id: int, query: str) -> dict:
    """Semantic search over THIS org's saved facts/notes (taught via chat)."""
    from knowledge_base.retriever import get_retriever
    try:
        chunks = get_retriever().search(
            query, top_k=5, chunk_type_filter="fact", org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001 — KB optional; never crash the turn
        return {"available": False, "note": "Knowledge base is unavailable right now.", "error": str(exc)}
    if not chunks:
        return {"results": [], "note": "Nothing saved matches that yet — you can teach me with remember_fact."}
    return {"results": [{"text": c.text, "source": c.source, "relevance": round(c.score, 4)} for c in chunks]}


def remember_fact(db: Session, org_id: int, fact: str) -> dict:
    """Save a fact to THIS org's long-term knowledge for future chats."""
    from knowledge_base.retriever import get_retriever
    text = (fact or "").strip()
    if not text:
        return {"saved": False, "error": "Nothing to remember."}
    try:
        get_retriever().add_fact(org_id, text, source="chat")
    except Exception as exc:  # noqa: BLE001
        return {"saved": False, "error": str(exc)}
    return {"saved": True, "fact": text}


# ── Registry + OpenAI/Groq-style tool schemas ─────────────────────────────────

TOOLS = {
    "financial_summary": financial_summary,
    "list_outstanding_invoices": list_outstanding_invoices,
    "list_outstanding_bills": list_outstanding_bills,
    "list_overdue": list_overdue,
    "find_contact": find_contact,
    "bank_accounts_summary": bank_accounts_summary,
    "search_knowledge": search_knowledge,
    "remember_fact": remember_fact,
}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOL_SCHEMAS = [
    _fn("financial_summary",
        "Overall money position: total receivable (owed to the business), total payable "
        "(owed by the business), net position, open invoice/bill counts, customers, "
        "suppliers, bank accounts, and transactions still pending reconciliation. "
        "Use for 'how are we doing', 'total outstanding', 'overview' style questions.",
        {}, []),
    _fn("list_outstanding_invoices",
        "Unpaid sales invoices — money customers owe the business. Optionally filter by a "
        "customer name substring.",
        {"contact_name": {"type": "string", "description": "Optional customer-name filter."},
         "limit": {"type": "integer", "description": "Max rows (default 20)."}}, []),
    _fn("list_outstanding_bills",
        "Unpaid purchase bills — money the business owes suppliers. Optionally filter by a "
        "supplier name substring.",
        {"contact_name": {"type": "string", "description": "Optional supplier-name filter."},
         "limit": {"type": "integer", "description": "Max rows (default 20)."}}, []),
    _fn("list_overdue",
        "Invoices and/or bills past their due date and still outstanding, with days overdue.",
        {"kind": {"type": "string", "enum": ["invoices", "bills", "both"],
                  "description": "Which to return (default both)."},
         "limit": {"type": "integer", "description": "Max rows per type (default 25)."}}, []),
    _fn("find_contact",
        "Look up a specific customer or supplier by name (or company) and see what they owe "
        "you and what you owe them, with their open documents.",
        {"name": {"type": "string", "description": "Name or company to search for."}},
        ["name"]),
    _fn("bank_accounts_summary",
        "Per bank account: computed statement balance, reconciled balance, the difference "
        "left to reconcile, and how many statement lines are still pending.",
        {}, []),
    _fn("search_knowledge",
        "Search this organisation's saved knowledge — facts and notes the team has taught the "
        "assistant (e.g. what the business does, how they categorise certain vendors, internal "
        "policies). Use for non-numeric, knowledge/'about us'/policy questions.",
        {"query": {"type": "string", "description": "What to look up."}},
        ["query"]),
    _fn("remember_fact",
        "Save a fact to this organisation's long-term knowledge so it's recalled in future chats. "
        "Call this whenever the user tells you something to remember (e.g. 'remember we treat "
        "Stripe payouts as revenue', 'our business caters children's parties').",
        {"fact": {"type": "string", "description": "A concise statement of the fact to store."}},
        ["fact"]),
]
