The Master Requirement & Scope Document

1. Project Vision & Scope
Build a production-grade Bank Reconciliation Agent capable of autonomously matching bank statements against company ledgers. This is the first module in a larger Multi-Agent Accounting Ecosystem. The system must handle messy, real-world financial data with 100% auditability and high accuracy.

2. Core Technical Stack (Best-in-Class)
Orchestration: Claude Agent SDK (Python/TypeScript).

Protocol: Model Context Protocol (MCP) for all tool communications.

Reasoning: Claude 3.5 Sonnet (for logic/matching) and Claude 3 Opus (for complex edge-case resolution).

Memory/Knowledge Base: PostgreSQL with pgvector (to store vendor aliases and learned patterns).

Observability: LangSmith (for full trace visibility and debugging).

Sandbox: E2B (for secure, isolated data processing).

3. Functional Requirements
Multi-Step Matching Engine: Implement logic that moves from "Exact Match" to "Fuzzy Match" (date windows, amount tolerance, and string similarity).

Vendor Alias Knowledge Base: A persistent store to map inconsistent descriptions (e.g., AMZN MKTPL → Amazon).

Self-Learning Loop: The agent must identify when a human corrects a match, store that "learning" in the Knowledge Base, and apply it to all future runs (Gbrain integration ready).

End-to-End Reliability: The agent must handle edge cases: duplicates, bank fees missing from ledgers, one-to-many matches, and date-shifted transactions.

Human-in-the-Loop (HITL): Every financial "post" or final report must require human validation via a structured approval gate.

4. Non-Functional Requirements (The "Best Developer" Standards)
Scalability: Architecture must support adding new agents (e.g., AP/AR Agents) without refactoring the core runtime.

Idempotency: Re-running the same file must never create duplicate entries.

Auditability: Every match must include a reasoning_path logged in the metadata.

Code Quality: Strictly modular code, type-hinted, and documented using industry best practices.

📝 The World-Class Implementation Prompt

Role: You are a Senior Principal AI Engineer specializing in Agentic Workflows and Financial Systems.

Task: Build a Bank Reconciliation Agent following the provided bank_reconciliation_agent_spec.md.

Core Instruction: Do not simply implement a logic script. You are building a Multi-Agent Architecture using the Claude Agent SDK and MCP. Every tool you build must be exposed via an MCP server to ensure it is reusable by future agents (like AR or AP agents).

Specific Engineering Directives:

End-to-End Excellence: The system must work from file upload to final reconciled report. Handle messy data (typos, date shifts, fees) as first-class citizens, not afterthoughts.

Self-Learning Knowledge Base: Setup a PostgreSQL/vector-based memory. When a user identifies that "Vendor X" is actually "Vendor Y," the agent must store this alias and never ask again.

Architecture over Speed: Ensure strict separation between the Agent (Reasoning), MCP Server (Tools), and Database (Memory).

Expert Consultation: You are the expert. If you believe a specific library, architectural pattern, or data structure is better than what is suggested in the brief, stop and consult me. Explain the "Why" behind your recommendation.

Reliability: Implement comprehensive error handling and structured logging. If a tool fails, the agent should catch the error, explain it, and attempt a retry or ask for help.

First Milestone: Begin with setting up the Advanced RAG Knowledge Base (Qdrant, Hybrid Search) as the foundation. Then set up the SDK and a single MCP-based matching tool. Show me the folder structure before proceeding to M2.

Architecture Overview
💡 Should you start from scratch or build on your RAG bot?
Verdict: Build the "Agent Engine" from scratch, but implement an Advanced RAG system (similar to the Peakvisory project) as the core Knowledge Base before adding complex reasoning (GBrains).

Why? A Knowledge Base is the most important thing. The agent needs data to reason over.

The Hybrid Approach: Use the Advanced RAG logic (Hybrid Search + Contextual Retrieval) for "looking up company policy", "rules", and "past reconciliations", while building the Bank Reconciliation Agent as a new, specialized worker using the Claude Agent SDK.


The Result: Your Meta-Agent (the router) will eventually be able to say: "I'll use the Recon Agent to match these files, and if I find a weird tax fee, I'll call the RAG Bot to look up our corporate tax policy on how to handle it."

📋 Resources to ask your Manager
Infrastructure: "I need a PostgreSQL instance with pgvector to act as the long-term knowledge base for vendor aliases.".

Development Tools: "I need access to LangSmith for production-grade observability so we can audit the agent's financial decisions.".

API Limits: "We need a Tier 2 or higher Anthropic API account to ensure the agent has enough throughput for large CSV processing."