"""
The in-app assistant agent — a tool-using loop over Groq function-calling.

Design notes:
- Runs ENTIRELY org-scoped: it's handed an org_id and a DB session and every
  tool it can call is filtered to that org. There is no way for it to reach
  another organisation's data.
- "Numbers come from tools, words come from the model." The system prompt forces
  a tool call for anything quantitative, so the assistant never invents a figure.
- Provider is Groq (llama-3.3-70b) because that's what's configured here; the
  loop is a thin wrapper, so swapping to another function-calling provider later
  is a small change.
"""
from __future__ import annotations

import json
import re
from datetime import date

from sqlmodel import Session

from config.settings import settings
from memory.models import Organization
from engine.assistant import tools as T

_MAX_STEPS = 6


def _parse_failed_tool_calls(exc) -> list[tuple[str, str]] | None:
    """
    Recover tool calls from a Groq `tool_use_failed` 400.

    llama sometimes serialises a call as text — `<function=name{...json...}</function>`
    — which Groq rejects but echoes back in `failed_generation`. We pull out the
    intended (name, arguments-json) pairs so the loop can run them anyway.
    """
    body = getattr(exc, "body", None)
    if body is None:
        try:
            body = exc.response.json()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            body = {}
    failed = ""
    if isinstance(body, dict):
        failed = (body.get("error") or {}).get("failed_generation") or ""
    if not failed:
        failed = str(exc)

    calls = re.findall(
        r"<function=([A-Za-z_][A-Za-z0-9_]*)\s*>?\s*(\{.*?\})\s*</function>", failed, re.DOTALL,
    )
    if not calls:  # tolerate a missing closing tag
        calls = re.findall(
            r"<function=([A-Za-z_][A-Za-z0-9_]*)\s*>?\s*(\{.*\})", failed, re.DOTALL,
        )
    return calls or None


def _next_step(client, messages: list):
    """
    Run one model turn. Returns ("text", reply) for a final answer, or
    ("tools", (assistant_message, calls)) where calls is a list of
    (call_id, name, args_dict). Recovers Groq's malformed tool calls so a
    `tool_use_failed` becomes a normal tool execution instead of an error.
    """
    from groq import BadRequestError

    try:
        resp = client.chat.completions.create(
            model=settings.AGENT_MODEL,
            messages=messages,
            tools=T.TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=1200,
        )
    except BadRequestError as exc:
        if "tool_use_failed" not in str(exc):
            raise
        parsed = _parse_failed_tool_calls(exc)
        if not parsed:
            raise
        tool_calls, calls = [], []
        for i, (name, args_str) in enumerate(parsed):
            cid = f"call_recovered_{i}"
            tool_calls.append({
                "id": cid, "type": "function",
                "function": {"name": name, "arguments": args_str},
            })
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {}
            calls.append((cid, name, args))
        return ("tools", ({"role": "assistant", "content": "", "tool_calls": tool_calls}, calls))

    msg = resp.choices[0].message
    if not msg.tool_calls:
        return ("text", msg.content or "")
    calls = []
    for tc in msg.tool_calls:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append((tc.id, tc.function.name, args))
    return ("tools", (msg, calls))

_SYSTEM_TEMPLATE = """You are the bookkeeping assistant inside a bank-reconciliation app, helping the team at "{org_name}".

Context you can rely on:
- Today's date is {today}.
- The organisation's base currency is {currency}.
- The organisation's industry is {industry}.
- You can ONLY see this organisation's data.

How to answer:
- For ANY question about amounts, balances, who owes what, overdue items, counts, or specific contacts, you MUST call a tool. NEVER invent, estimate, or recall figures from memory.
- Base every number strictly on what the tools return. Report figures from tool results EXACTLY as returned — never substitute 0, round a value away, or change it. (A contact's "owes_you" field is what they owe you.)
- Format money with the {currency} amount (e.g. "{currency} 1,200.00"), unless a row carries its own currency.
- For questions about what the business does, its policies, reconciliation rules or procedures, or anything the team has noted, call search_knowledge first. If it returns any result, use that text as the answer and state it confidently — only say you don't know if it returns nothing.
- When the user tells you something to remember ("remember that…", "note that…", "we do X", "we treat Y as Z"), call remember_fact with a concise statement, then confirm you've saved it.
- When the user says two VENDOR/SUPPLIER/CUSTOMER NAMES are the same entity ("X and Y are the same supplier", "treat X as Y", "X is just Y", "X on the bank statement is Y"), you MUST call add_vendor_alias with the two names — NOT remember_fact. That tool writes a real alias the reconciliation engine uses to match the bank line to that vendor's invoice/bill. After it returns, confirm that future reconciliations will now match them.
- Be concise and friendly. Prefer a short sentence or a tight list over long paragraphs.
- If a tool or search_knowledge returns nothing for a SPECIFIC fact about this org (a figure, a contact), say so plainly and suggest a next step — never guess this org's own data.
- For GENERAL questions — accounting/bookkeeping concepts, or how to use this app — you may answer from your own general knowledge when the knowledge base has nothing; just make clear it's general guidance.
- If the question is clearly unrelated to this business, bookkeeping, or this app, briefly say it's outside what you help with and offer something useful instead. If the user makes clear they still want an answer, give a short, helpful one.
"""


def run_assistant(
    message: str,
    history: list[dict] | None,
    db: Session,
    org_id: int,
) -> dict:
    """
    Run one assistant turn. Returns {"reply": str, "tools_used": list[str]}.
    `history` is a list of prior {"role": "user"|"assistant", "content": str}.
    """
    if not settings.GROQ_API_KEY:
        return {
            "reply": "The assistant isn't configured yet — no GROQ_API_KEY is set on the server.",
            "tools_used": [],
        }

    from groq import Groq

    client = Groq(api_key=settings.GROQ_API_KEY)
    org = db.get(Organization, org_id)
    system = _SYSTEM_TEMPLATE.format(
        org_name=org.name if org else "your business",
        today=date.today().isoformat(),
        currency=org.currency if org else "GBP",
        industry=(org.industry if org and org.industry else "not specified"),
    )

    messages: list = [{"role": "system", "content": system}]
    for turn in (history or []):
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    tools_used: list[str] = []

    for _ in range(_MAX_STEPS):
        try:
            kind, payload = _next_step(client, messages)
        except Exception:  # noqa: BLE001 — never let a provider hiccup 500 the chat
            return {
                "reply": "Sorry — I hit a snag answering that. Please try rephrasing your question.",
                "tools_used": tools_used,
            }

        if kind == "text":
            return {"reply": payload, "tools_used": tools_used}

        assistant_msg, calls = payload
        messages.append(assistant_msg)
        for cid, name, args in calls:
            fn = T.TOOLS.get(name)
            if fn is None:
                result = {"error": f"unknown tool '{name}'"}
            else:
                try:
                    result = fn(db, org_id, **args)
                except Exception as exc:  # noqa: BLE001 — surface to model, never crash the turn
                    result = {"error": str(exc)}
            tools_used.append(name)
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "name": name,
                "content": json.dumps(result, default=str),
            })

    return {
        "reply": "I looked into that but couldn't wrap it up — try asking a bit more specifically.",
        "tools_used": tools_used,
    }
