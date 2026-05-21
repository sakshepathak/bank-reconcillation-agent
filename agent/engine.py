"""
Bank Reconciliation Agent Engine.

Uses the Anthropic Python SDK (claude-3-5-sonnet) with MCP tool integration.

The agent imports tools directly from the MCP server module when running
in the same process. For production deployment (Claude Desktop / remote MCP),
swap to MCPServerStdio / MCPServerHTTP transport.

Usage:
    from agent.engine import run_recon_agent
    import asyncio
    asyncio.run(run_recon_agent("Reconcile the attached CSVs."))
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from typing import AsyncIterator

import anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from agent.prompts import RECON_SYSTEM_PROMPT
from config.settings import settings
from mcp_server.server import (
    approve_match,
    get_unmatched,
    get_vendor_name,
    reconcile,
    search_kb,
    store_vendor_alias,
)

console = Console()

# ── Tool registry (maps tool name → callable) ─────────────────────────────────
# This registry pattern makes adding new tools a one-liner.
_TOOL_REGISTRY: dict[str, callable] = {
    "search_kb": search_kb,
    "get_vendor_name": get_vendor_name,
    "store_vendor_alias": store_vendor_alias,
    "reconcile": reconcile,
    "get_unmatched": get_unmatched,
    "approve_match": approve_match,
}

# ── Anthropic tool schemas ────────────────────────────────────────────────────
_TOOLS: list[dict] = [
    {
        "name": "search_kb",
        "description": (
            "Search the reconciliation knowledge base for rules, SOPs, and historical patterns. "
            "ALWAYS call this first before making any matching decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question or keyword."},
                "top_k": {"type": "integer", "description": "Number of results (default 5)."},
                "chunk_type": {
                    "type": "string",
                    "description": "Optional filter: rule, sop, alias, historical, policy.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_vendor_name",
        "description": "Look up the canonical vendor name for a messy bank-statement description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_description": {
                    "type": "string",
                    "description": "The raw, messy description from the bank statement.",
                }
            },
            "required": ["raw_description"],
        },
    },
    {
        "name": "store_vendor_alias",
        "description": "Store a new vendor alias mapping in the self-learning knowledge base.",
        "input_schema": {
            "type": "object",
            "properties": {
                "raw_description": {"type": "string"},
                "canonical_name": {"type": "string"},
                "source": {
                    "type": "string",
                    "enum": ["agent", "human"],
                    "description": "Who identified the mapping.",
                },
            },
            "required": ["raw_description", "canonical_name"],
        },
    },
    {
        "name": "reconcile",
        "description": (
            "Run the full 4-level matching cascade on bank and ledger CSV strings. "
            "Returns run_id, summary stats, and per-transaction results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bank_csv": {"type": "string", "description": "CSV string of the bank statement."},
                "ledger_csv": {"type": "string", "description": "CSV string of the company ledger."},
            },
            "required": ["bank_csv", "ledger_csv"],
        },
    },
    {
        "name": "get_unmatched",
        "description": "Return only the unmatched bank transactions from a reconciliation run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The run_id returned by reconcile()."}
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "approve_match",
        "description": (
            "HITL gate: human approves or rejects a match. "
            "MUST be called for every fuzzy and one-to-many match before finalising."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "bank_txn_id": {"type": "string"},
                "approved": {"type": "boolean"},
                "correction_ledger_id": {
                    "type": "string",
                    "description": "If rejecting, the correct ledger ID.",
                },
                "notes": {"type": "string", "description": "Optional human notes for audit log."},
            },
            "required": ["run_id", "bank_txn_id", "approved"],
        },
    },
]


# ── Agent loop ────────────────────────────────────────────────────────────────

async def run_recon_agent(
    user_message: str,
    conversation_history: list[dict] | None = None,
    max_iterations: int = 20,
) -> str:
    """
    Run the reconciliation agent for one user turn.
    Supports Anthropic (Claude) and Groq (Llama 3 function calling).
    """
    provider = settings.LLM_PROVIDER.lower()
    messages = list(conversation_history or [])
    
    # Provider-specific setup
    if provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        messages.append({"role": "user", "content": user_message})
    elif provider == "groq":
        if not settings.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set.")
        from groq import Groq
        client = Groq(api_key=settings.GROQ_API_KEY)
        # Groq (OpenAI-style) uses 'role: user' content as strings
        messages.append({"role": "user", "content": user_message})
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    for iteration in range(max_iterations):
        console.print(f"[dim]── Agent iteration {iteration + 1} ({provider}) ──[/]")

        if provider == "anthropic":
            response = client.messages.create(
                model=settings.AGENT_MODEL,
                max_tokens=8096,
                system=RECON_SYSTEM_PROMPT,
                tools=_TOOLS,
                messages=messages,
            )
            
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    console.print(Panel(Markdown(block.text), title="Agent", border_style="blue"))

            if response.stop_reason == "end_turn":
                return " ".join(b.text for b in response.content if hasattr(b, "text") and b.text)

            if response.stop_reason != "tool_use":
                return " ".join(b.text for b in response.content if hasattr(b, "text") and b.text)

            tool_results = []
            for block in response.content:
                if block.type != "tool_use": continue
                
                tool_name, tool_input = block.name, block.input
                console.print(f"[bold cyan]⚙ Tool call:[/] {tool_name}")
                
                try:
                    result_content = _TOOL_REGISTRY[tool_name](**tool_input)
                except Exception as exc:
                    result_content = f"Error: {exc}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result_content),
                })
            
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        elif provider == "groq":
            # Groq implementation (OpenAI-compatible)
            # We must map our system prompt to a system message for OpenAI-style
            full_msgs = [{"role": "system", "content": RECON_SYSTEM_PROMPT}] + messages
            
            # Map _TOOLS to OpenAI tool format
            groq_tools = []
            for t in _TOOLS:
                groq_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"]
                    }
                })

            response = client.chat.completions.create(
                model=settings.AGENT_MODEL,
                messages=full_msgs,
                tools=groq_tools,
                tool_choice="auto",
                max_tokens=4096,
            )

            response_message = response.choices[0].message
            content = response_message.content
            if content:
                console.print(Panel(Markdown(content), title="Agent", border_style="blue"))

            if not response_message.tool_calls:
                return content or "No response from agent."

            # Process tool calls
            messages.append(response_message)
            
            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                console.print(f"[bold cyan]⚙ Tool call:[/] {tool_name}")
                
                try:
                    result = _TOOL_REGISTRY[tool_name](**tool_args)
                except Exception as e:
                    result = f"Error: {e}"
                
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": tool_name,
                    "content": str(result),
                })

    return "Max iterations reached."


# ── CLI entry point ───────────────────────────────────────────────────────────

async def _interactive_loop() -> None:
    """Simple interactive REPL for local testing."""
    console.print(Panel(
        "[bold green]Bank Reconciliation Agent[/]\n"
        "Type your instruction or paste CSV paths. Type 'exit' to quit.",
        title="Welcome",
        border_style="green",
    ))
    history: list[dict] = []
    while True:
        try:
            user_input = input("\n> ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        response = await run_recon_agent(user_input, history)
        # Maintain multi-turn context
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    asyncio.run(_interactive_loop())
