# Bank Reconciliation Agent

An autonomous, AI-powered bank reconciliation system that matches bank statement transactions against company ledger entries, extracts data from invoices using vision AI, and gates every non-obvious decision through a human-in-the-loop approval step — with a full, immutable audit trail behind every decision.

---

## Table of Contents

1. [What This Is](#what-this-is)
2. [Why This Exists](#why-this-exists)
3. [What Makes It Cool](#what-makes-it-cool)
4. [High-Level Architecture](#high-level-architecture)
5. [Tech Stack](#tech-stack)
6. [Project Structure](#project-structure)
7. [Installation — Step by Step](#installation--step-by-step)
8. [Running the App](#running-the-app)
9. [Configuration Reference](#configuration-reference)
10. [The Matching Cascade — Core Algorithm](#the-matching-cascade--core-algorithm)
11. [Vendor Matching Pipeline](#vendor-matching-pipeline)
12. [How Invoice Extraction Works](#how-invoice-extraction-works)
13. [The Knowledge Base and RAG System](#the-knowledge-base-and-rag-system)
14. [What the LLM Does (and Doesn't Do)](#what-the-llm-does-and-doesnt-do)
15. [MCP Server — All 6 Tools](#mcp-server--all-6-tools)
16. [Database — Tables and Purpose](#database--tables-and-purpose)
17. [The UI — Tab by Tab](#the-ui--tab-by-tab)
18. [Self-Learning: The Vendor Alias System](#self-learning-the-vendor-alias-system)
19. [Human-in-the-Loop Gates](#human-in-the-loop-gates)
20. [LLM Provider Strategy and Fallbacks](#llm-provider-strategy-and-fallbacks)
21. [Docker Services](#docker-services)
22. [Running Tests](#running-tests)
23. [Debugging Guide](#debugging-guide)
24. [Scope and Roadmap](#scope-and-roadmap)

---

## What This Is

Bank reconciliation is the process of comparing a company's bank statement against its internal accounting ledger to make sure every transaction is recorded and there are no discrepancies. Traditionally this is done manually in spreadsheets by an accountant, which is tedious, error-prone, and takes hours per month.

This project automates that entire process. Given a bank statement CSV and a set of invoice PDFs or a ledger CSV:

1. Vision AI reads the invoices and extracts structured data (vendor, date, amount, currency)
2. A 6-level matching cascade attempts to pair every bank transaction to a ledger entry
3. Vendor names are resolved even when they're abbreviated or garbled
4. Anything the system isn't confident about is flagged and held for a human to approve
5. Every single decision — match, reject, human correction — is written to an audit log

The result is an accountant-friendly interface where the human only needs to review the genuinely ambiguous cases, not process everything from scratch.

---

## Why This Exists

Manual reconciliation has real problems:

- An accountant processing 200 transactions/month spends 4-8 hours on reconciliation alone
- Human error rate on repetitive matching tasks is non-trivial
- There is no standardised audit trail — decisions live in someone's head or in Excel comments
- Bank descriptions are notoriously messy (`AMZN MKTPL *3X9Z` instead of `Amazon`)
- One bank transaction can cover multiple invoices (payroll, bulk payments), which is hard to spot manually

This agent solves all of these. It is not a replacement for the accountant — it is a tool that handles the mechanical matching work and surfaces only the genuinely hard cases for human judgement.

---

## What Makes It Cool

**The LLM is not the matching engine.** All critical math — exact match, fuzzy amount, subset sum — runs as deterministic Python. The LLM orchestrates the workflow, explains decisions in plain English, and handles the cases the deterministic code cannot. This is intentional: it makes the system auditable, predictable, and cheap to run.

**A 6-level cascade that actually thinks.** Most reconciliation tools do exact match and give up. This system has six progressively looser matching levels, including a subset-sum solver (Mixed-Integer Programming via PuLP) for split payments, a relaxed fuzzy pass, and a last-resort LLM verifier — all chained together so that anything deterministic can handle is never handed to the LLM.

**Hybrid RAG over accounting rules.** The knowledge base (matching rules, SOPs, vendor aliases) is chunked, contextually summarised, and stored in Qdrant with both dense (semantic) and sparse (keyword) embeddings. The agent consults this before every decision. The rules are in plain markdown — an accountant can edit them without touching code.

**The system gets smarter with every run.** When a human corrects a vendor match, that mapping (`AMZN MKTPL *3X9Z → Amazon`) is written to a persistent alias table. Next time the same description appears, it's resolved instantly at O(1) lookup speed — no LLM needed.

**Full audit trail, non-negotiable.** Every reconciliation decision is written to a `MatchRecord` table with the matching level, confidence score, amount difference, date difference, and a plain-English `reasoning_path` string. Human approval or rejection is also logged. This is built as a hard constraint in the agent system prompt — fuzzy matches cannot be finalised without going through `approve_match`.

**Multi-provider LLM fallback.** Gemini, OpenRouter, and Groq are wired into a `FallbackChain`. If Gemini hits a quota, OpenRouter takes over automatically. Multiple Gemini API keys rotate on rate-limit errors. The app stays up even if one provider goes down.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit UI (port 8501)                │
│  Upload bank CSV + invoices → Review matches → Audit trail  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    Agent (engine.py)                        │
│  Groq Llama-3.3-70b or Anthropic Claude                     │
│  Reads system prompt + matching rules, calls MCP tools      │
└──────┬───────────┬──────────┬──────────┬────────────────────┘
       │           │          │          │
  search_kb  get_vendor  reconcile  approve_match  (MCP tools)
       │           │          │          │
┌──────▼──┐  ┌─────▼───┐ ┌───▼──────┐  ┌▼──────────────────┐
│ Qdrant  │  │ SQLite  │ │ Matching │  │   SQLite DB        │
│ (rules/ │  │ Vendor  │ │ Cascade  │  │  MatchRecord table │
│  SOPs)  │  │ Aliases │ │ L1→L6b   │  │  (audit log)       │
└─────────┘  └─────────┘ └──────────┘  └────────────────────┘
                                │
                   ┌────────────▼────────────┐
                   │   Vision AI Extraction  │
                   │  Gemini → OpenRouter    │
                   │  (invoice PDFs/images)  │
                   └─────────────────────────┘
```

**Key design principle:** The agent reasons and orchestrates. The tools do the work. The database stores the results. These three layers never bleed into each other.

---

## Tech Stack

| Layer | Library / Service | Why |
|---|---|---|
| UI | Streamlit | Fast accountant-facing web app, no frontend code needed |
| Agent Orchestration | Groq (Llama-3.3-70b) or Anthropic Claude | Fast text generation for tool-calling loop |
| Vision / Extraction | Google Gemini 2.5 Flash | Native PDF + image understanding, structured JSON output |
| Vision Fallback | OpenRouter (GPT-4o-mini) | Cheap, vision-capable fallback when Gemini is unavailable |
| Vector Database | Qdrant (Docker) | Hybrid dense+sparse search, self-hosted, no cloud lock-in |
| Embeddings | fastembed (BAAI/BGE-small + BM25) | Runs fully local, no API key, cached on disk |
| Relational DB | SQLModel / SQLite → PostgreSQL | Audit log, vendor aliases, extracted invoices |
| Fuzzy Matching | RapidFuzz | Jaro-Winkler, token_set_ratio — fast and accurate |
| Subset Sum Solver | PuLP (MIP) | Exact one-to-many payment matching via integer programming |
| PDF Parsing | PyMuPDF | Pure Python, no system dependencies, fast |
| Data Processing | pandas | CSV normalisation, DataFrame operations |
| Tool Protocol | FastMCP | Exposes tools over Model Context Protocol |
| Validation | Pydantic + pydantic-settings | Structured LLM outputs, type-safe settings |
| Orchestration | Docker Compose | One-command startup for all 5 services |
| Testing | pytest | Matching cascade unit tests |
| Observability | LangSmith (optional) | Trace agent calls (key in `.env`, not yet wired fully) |

---

## Project Structure

```
Bank_reconcillation_model/
│
├── agent/                          # AI agent logic
│   ├── engine.py                   # Main agent loop (tool-calling, Groq or Anthropic)
│   └── prompts.py                  # System prompt — tells agent what to do, in what order
│
├── app/                            # Streamlit web application
│   ├── main.py                     # Entry point: init DB, render sidebar + 3 tabs
│   └── views/
│       ├── reconcile.py            # Upload → Extract → Match → Review flow
│       ├── audit.py                # Full audit trail of all MatchRecord rows
│       ├── aliases.py              # View and add vendor alias mappings
│       └── sidebar.py              # Persistent stats: pending reviews, recent runs
│
├── config/
│   └── settings.py                 # Pydantic settings loaded from .env
│
├── data/
│   ├── uploads/                    # Content-addressed file store (SHA-256 hash filenames)
│   └── fastembed_cache/            # Local embedding model cache (auto-populated)
│
├── engine/                         # Matching and LLM integration
│   ├── bank_statement_parser.py    # CSV/PDF → canonical DataFrame
│   ├── file_store.py               # SHA-256 based deduplication store
│   └── llm/
│       ├── base.py                 # Abstract LLMClient interface
│       ├── factory.py              # Builds Gemini → OpenRouter fallback chain
│       ├── gemini.py               # Google Gemini client (vision + structured output)
│       ├── openrouter.py           # OpenRouter client (fallback)
│       └── fallback.py             # FallbackChain: auto-rotate on error/rate-limit
│   └── vendor_matching/
│       ├── matcher.py              # 4-tier vendor matching orchestrator
│       ├── normalizer.py           # Strip bank noise, expand abbreviations
│       ├── similarity.py           # Jaro-Winkler + token_set + partial ratio ensemble
│       ├── embedder.py             # BGE + BM25 embedding-based similarity
│       └── llm_verifier.py         # Single batched LLM call for last-resort matching
│
├── knowledge/                      # Human-editable rule files (plain markdown)
│   ├── rules/matching_rules.md     # 5 matching rules with conditions + examples
│   ├── sops/reconciliation_sops.md # 6 standard operating procedures for edge cases
│   └── aliases/
│       ├── vendor_aliases.md       # Known vendor name mappings
│       └── vendor_rules.md         # Per-vendor special handling rules
│
├── knowledge_base/                 # RAG pipeline
│   ├── ingest.py                   # Chunk → contextualise → embed → upsert to Qdrant
│   └── retriever.py                # Hybrid search + Reciprocal Rank Fusion
│
├── mcp_server/                     # Model Context Protocol server
│   ├── server.py                   # FastMCP server — registers all 6 tools
│   └── tools/
│       ├── matching.py             # 6-level matching cascade (pure functions)
│       ├── normalizer.py           # Canonical Data Layer — standardises any CSV
│       ├── alias.py                # Vendor alias lookup + upsert
│       ├── search_kb.py            # KB search wrapper
│       ├── invoice_extractor.py    # Vision-based invoice extraction (Gemini)
│       ├── split_solver.py         # PuLP MIP solver for subset sum
│       └── suggestions.py          # UI suggestion text generator
│
├── memory/                         # Database layer
│   ├── db.py                       # SQLModel engine factory + session context manager
│   └── models.py                   # 4 ORM tables: VendorAlias, MatchRecord, etc.
│
├── tests/
│   └── test_matching.py            # Pytest suite: all 4 cascade levels + edge cases
│
├── scratch/                        # Dev/smoke test scripts (not production code)
│
├── sample_data/                    # Sample CSVs for manual testing
│
├── .env.example                    # Template — copy this to .env and fill in keys
├── docker-compose.yml              # 5-service orchestration
└── requirements.txt                # Python dependencies
```

---

## Installation — Step by Step

### Prerequisites

- Python 3.11+
- Docker Desktop (for Qdrant vector database)
- API keys: at minimum one of Groq or Anthropic, and a Gemini key (for invoice extraction)

### Step 1 — Clone and enter the project

```bash
git clone <your-repo-url>
cd Bank_reconcillation_model
```

### Step 2 — Create a virtual environment

```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On macOS / Linux:
source .venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `fastembed` will download the BGE-small and BM25 models on first run (~90 MB). They are cached in `data/fastembed_cache/` and never downloaded again.

### Step 4 — Set up environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
# Choose your agent LLM provider: "groq" or "anthropic"
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your_key_here
ANTHROPIC_API_KEY=sk-ant-your-key-here   # only needed if LLM_PROVIDER=anthropic

# Vision AI for invoice extraction (required)
GEMINI_API_KEY=your_gemini_key_here

# Qdrant vector DB (Docker will start this automatically)
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=bank_recon_kb

# SQLite for development (swap to PostgreSQL URL in production)
DATABASE_URL=sqlite:///./bank_recon.db
```

> **Note:** Get Groq keys free at console.groq.com. Get Gemini keys at aistudio.google.com. Both have generous free tiers.

### Step 5 — Start Qdrant

```bash
docker-compose up qdrant -d
```

Qdrant will be available at `http://localhost:6333`. The dashboard is at `http://localhost:6333/dashboard`.

### Step 6 — Ingest the knowledge base

This reads all markdown files in `knowledge/`, chunks them, generates contextual summaries, embeds them, and upserts to Qdrant. Run this once (and again whenever you edit the knowledge files).

```bash
python -m knowledge_base.ingest
```

You should see output like:

```
Ingesting knowledge/rules/matching_rules.md ...  6 chunks upserted.
Ingesting knowledge/sops/reconciliation_sops.md ... 12 chunks upserted.
Ingesting knowledge/aliases/vendor_aliases.md ...  4 chunks upserted.
Knowledge base ingestion complete. 22 chunks total.
```

### Step 7 — Run the UI

```bash
streamlit run app/main.py
```

Open `http://localhost:8501` in your browser. The app initialises the SQLite database automatically on first launch.

### Step 8 — (Optional) Run the MCP server

If you want to use the agent CLI or connect an external MCP client (Claude Desktop, Cursor):

```bash
python -m mcp_server.server
```

### Step 9 — (Optional) Run everything with Docker

```bash
docker-compose up
```

This starts all 5 services: Qdrant, ingest (runs once and exits), MCP server, Streamlit UI, and the test runner.

---

## Running the App

### Option A — Streamlit UI (recommended for most users)

```bash
streamlit run app/main.py
# Open http://localhost:8501
```

### Option B — Agent CLI (for testing / scripting)

```bash
python agent/engine.py
```

Starts an interactive loop. Type instructions or paste CSV paths. The agent calls tools automatically.

### Option C — Full Docker stack

```bash
# Start everything
docker-compose up

# Start only core services (skip tests)
docker-compose up qdrant ui mcp_server

# View logs for a specific service
docker-compose logs -f ui
docker-compose logs -f mcp_server

# Rebuild after code changes
docker-compose up --build ui
```

---

## Configuration Reference

All settings are loaded from `.env` via Pydantic. Changing any value requires restarting the service.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `groq` | Agent LLM: `groq` or `anthropic` |
| `GROQ_API_KEY` | — | Groq API key (get at console.groq.com) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (needed if using Claude as agent) |
| `GEMINI_API_KEY` | — | Primary vision model (invoice extraction) |
| `AGENT_MODEL` | `llama-3.3-70b-versatile` | Model name for the agent (Groq or Anthropic model ID) |
| `GEMINI_VISION_MODEL` | `gemini-2.5-flash` | Gemini model for vision extraction |
| `OPENROUTER_API_KEY` | — | Fallback vision provider (optional but recommended) |
| `OPENROUTER_FALLBACK_MODEL` | `openai/gpt-4o-mini` | Model used by OpenRouter fallback |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant connection URL |
| `QDRANT_COLLECTION` | `bank_recon_kb` | Qdrant collection name |
| `DENSE_MODEL` | `BAAI/bge-small-en-v1.5` | Dense embedding model (local, auto-downloaded) |
| `SPARSE_MODEL` | `Qdrant/bm25` | Sparse embedding model (local, auto-downloaded) |
| `HYBRID_TOP_K` | `20` | Candidates per sub-search (dense + sparse) before RRF fusion |
| `RERANK_TOP_K` | `5` | Final results returned after Reciprocal Rank Fusion |
| `AMOUNT_TOLERANCE` | `0.05` | Max absolute amount difference for Level 2 fuzzy match |
| `DATE_WINDOW_DAYS` | `3` | Max date gap (days) for Level 2 fuzzy match |
| `FUZZY_SCORE_THRESHOLD` | `80` | Minimum description similarity (0–100) for Level 3 |
| `DATABASE_URL` | `sqlite:///./bank_recon.db` | Database connection string. Swap to `postgresql://...` for production |
| `LANGSMITH_API_KEY` | — | Optional. Enables LangSmith tracing for agent calls |

---

## The Matching Cascade — Core Algorithm

This is the heart of the system. Every bank transaction passes through the levels in order. As soon as a level succeeds, the transaction is marked matched and the loop moves on. Each level is a pure Python function with no side effects.

### Level 1 — Exact Match

**Condition:** `bank.date == ledger.date` AND `round(bank.amount, 2) == round(ledger.amount, 2)`

**Confidence:** 1.0 (maximum)

**Human review:** Not required. Auto-approved.

**Tiebreaker:** If multiple ledger rows satisfy the exact condition (possible with duplicate entries), the one with the highest description similarity to the bank line wins.

**Why this matters:** This is the fast path. Most transactions on a clean ledger will hit Level 1. The cascade only goes deeper for the hard cases.

---

### Level 2 — Fuzzy Amount + Date

**Condition:** `|bank.amount - ledger.amount| <= AMOUNT_TOLERANCE` AND `|bank.date - ledger.date| <= DATE_WINDOW_DAYS`

**Default tolerance:** $0.05 absolute / 3-day window

**Confidence:** Calculated as a composite of amount closeness, date closeness, and description similarity. Typically 0.7–0.9.

**Human review:** Required when composite confidence < 0.70.

**Why this exists:** FX transactions round to different decimal places depending on which rate is used. Bank posting dates routinely lag the ledger booking date by 1–3 business days. Exact match would miss all of these.

---

### Level 3 — Description Fuzzy Match (Vendor Matching)

**Condition:** Vendor similarity score >= `FUZZY_SCORE_THRESHOLD` AND amount within 10% relative tolerance.

The description comparison does not happen on raw strings. It runs through the full vendor matching pipeline (see below), which includes normalisation, alias lookup, lexical ensemble, and embedding similarity.

**Confidence:** Capped at 0.85 for fuzzy/embedding methods; alias-exact and canonical-exact matches can reach 1.0.

**Human review:** Always required (no exceptions — the agent system prompt enforces this hard).

**Why this exists:** Bank descriptions are generated by payment processors, not vendors. `AMZN MKTPL *3X9Z` is Amazon. `SQ *BLUE BOTTLE` is a Blue Bottle Coffee Square POS transaction. No deterministic string compare will catch these. A multi-tier vendor resolver does.

---

### Level 4 — One-to-Many (Subset Sum)

**Condition:** A single bank transaction = SUM of N ledger entries within a 7-day window.

**Algorithm:** PuLP Mixed-Integer Programming solver. Given a target amount and a list of candidate ledger rows, it finds the exact subset (if one exists) whose amounts sum to the target within tolerance. The 7-day window constrains the candidate set to keep the solver fast.

**Confidence:** Approximately 0.7–1.0 depending on sum precision.

**Human review:** Always required.

**Common cases:**
- One consolidated bank card settlement = multiple individual purchases in the ledger
- One payroll bank transfer = multiple individual employee salary entries
- One vendor payment = multiple partially-paid invoices

---

### Level 5 — Many-to-One (Installment Payments)

**Condition:** N unmatched bank transactions together sum to one unmatched ledger entry.

This level runs as a second pass after the per-row loop completes, operating on the residual unmatched set. It blocks candidates first by date window and vendor similarity (to avoid an expensive solver call on unrelated transactions), then runs the subset-sum solver.

**Confidence:** ~0.80 (exact subset sum is strong evidence).

**Human review:** Always required.

**Common case:** A large invoice paid in three instalments. Each bank line appears unmatched after Level 1–4 because none of them individually equals the invoice amount.

---

### Level 6a — Relaxed Deterministic Match

**Condition:** Vendor similarity >= 0.45 (vs. 0.80 in Level 3) AND amount within 5% relative AND date within 14 days.

This is a second-chance pass for transactions that narrowly missed Level 3 thresholds. Results are tagged `possible` (not `fuzzy`) so the UI can display them with a lower confidence indicator.

**Confidence:** Hard capped at 0.65 — deliberately low. These are speculative suggestions, not conclusions.

**Human review:** Always required.

---

### Level 6b — LLM Verifier (Last Resort)

**Condition:** After all deterministic levels, if there are still unmatched rows and the set is small enough (≤ 30 each side), a single batched LLM call is made.

The LLM receives the remaining unmatched bank lines and ledger entries and is asked to identify likely pairs with a confidence score and a reason. It is not allowed to produce an unambiguous match — all results are capped at confidence 0.65 and flagged `possible`.

**Why it's bounded:** On large datasets, an LLM call over hundreds of rows would be slow, expensive, and unreliable. The deterministic levels handle the bulk; the LLM cleans up edge cases the rules couldn't anticipate.

**Human review:** Always required.

**Crash safety:** The entire Level 6b block is wrapped in a `try/except`. If the LLM fails for any reason (quota, network, timeout), the cascade returns the deterministic results. The LLM's failure never causes reconciliation to fail.

---

### Cascade Summary

| Level | Method | Confidence | Auto-approve? |
|---|---|---|---|
| 1 | Exact date + amount | 1.0 | Yes |
| 2 | Fuzzy amount + date window | 0.7–0.9 | Only if score >= 0.70 |
| 3 | Vendor description fuzzy | 0.6–0.85 | Only for alias-exact hits |
| 4 | One-to-many (subset sum) | 0.7–1.0 | No |
| 5 | Many-to-one (installments) | ~0.80 | No |
| 6a | Relaxed fuzzy (speculative) | ≤ 0.65 | No |
| 6b | LLM verifier (last resort) | ≤ 0.65 | No |
| — | Unmatched | 0.0 | No (requires human) |

---

## Vendor Matching Pipeline

Vendor matching runs inside Level 3 of the cascade. It has four tiers, tried in order of increasing cost. As soon as a tier produces a confident result, later tiers are skipped.

### Tier 1 — Normalisation

Strips all the processor-added noise from a bank description before any comparison.

- Remove processor prefixes: `SQ *`, `PYPL *`, `STRIPE *`, `POS PURCHASE`, `ACH DEBIT`, `WIRE`, etc.
- Remove trailing transaction IDs: `*A1B2C3`, `#123456`, numeric suffixes
- Expand common abbreviations: `AMZN → AMAZON`, `APL → APPLE`, `WMT → WALMART`
- Lowercase everything

After normalisation, `AMZN MKTPL *3X9Z` becomes `amazon marketplace`. This dramatically improves all subsequent matching steps.

### Tier 2 — Alias Lookup (Database)

An exact-match lookup in the `VendorAlias` table using the normalised string as the key.

- If found: returns the canonical name immediately at O(1) — no fuzzy logic needed
- The alias table grows with every human-confirmed correction and agent discovery
- Confidence is `1.0` for human-sourced aliases, `0.8` for agent-sourced

### Tier 3 — Composite Lexical Similarity

An ensemble of three string similarity metrics, averaged:

- **Jaro-Winkler:** Good for short strings and typos. Weighs prefix agreement more heavily.
- **token_set_ratio:** Splits strings into token bags. Robust to word order differences and extra words.
- **partial_ratio:** Scores the best matching substring. Handles cases where one string is a substring of the other.

Combined score range: 0.0–1.0.

If score >= 0.95, the lexical result is returned immediately — embedding is skipped (saves compute and latency).

### Tier 4 — Embedding-Based Matching

Only runs when the lexical score is in the "ambiguity zone": [0.60, 0.95]. Below 0.60 it's not worth computing; above 0.95 the lexical result is already confident.

- **Dense embeddings:** BAAI/BGE-small-en-v1.5 (384 dimensions, cosine distance). Captures semantic meaning.
- **Sparse embeddings:** BM25 (keyword frequency, IDF-weighted). Captures exact term importance.
- Both run locally via `fastembed` — no API calls, no latency, no cost.
- Final vendor score: `0.65 × embedding_score + 0.35 × lexical_score`
- Minimum embedding cosine: 0.60 (below this, embeddings add noise not signal)

**Final score:** `max(alias_score, lexical_score, embedding_score)`. Any strong signal from any tier wins.

---

## How Invoice Extraction Works

When a user uploads invoice PDFs or images:

1. **File is hashed (SHA-256).** If the same file was uploaded before, the cached extraction result is returned immediately from the `ExtractedInvoice` table. No redundant LLM call.

2. **File is stored.** Saved to `data/uploads/<hash>.<ext>`. Content-addressed storage means no duplicates on disk.

3. **Gemini Vision reads the document.** The file bytes are sent to Gemini 2.5 Flash with a structured extraction prompt. Gemini has native PDF understanding — it reads multi-page PDFs directly.

4. **Structured output.** The response is validated against a Pydantic schema:
   ```
   vendor, doc_type, invoice_id, date, amount, currency, confidence
   ```

5. **Fallback.** If Gemini fails (quota, timeout, error), the `FallbackChain` retries with OpenRouter (GPT-4o-mini), which also supports vision input.

6. **Result stored.** Written to `ExtractedInvoice` table. The row is now the company's ledger entry for that invoice.

7. **Editable before reconciliation.** The UI presents extracted rows in an editable table. The user can correct any OCR mistake before running the matching cascade.

---

## The Knowledge Base and RAG System

The knowledge base is the system's "accounting brain" — a collection of plain markdown documents that define matching rules, standard operating procedures, and vendor alias conventions. The agent consults it before making decisions.

### Documents

| File | Contents |
|---|---|
| `knowledge/rules/matching_rules.md` | Definitions for all 5 matching levels with conditions, tolerances, and examples |
| `knowledge/sops/reconciliation_sops.md` | 6 SOPs: bank fees, duplicates, FX, reversals, end-of-period timing, payroll |
| `knowledge/aliases/vendor_aliases.md` | Curated list of known vendor name mappings |
| `knowledge/aliases/vendor_rules.md` | Per-vendor special handling (e.g. certain vendors always need wider date windows) |

> **Important:** These files are plain markdown. An accountant can edit them to change matching behaviour — no code changes required. After editing, re-run `python -m knowledge_base.ingest` to update Qdrant.

### Ingestion Pipeline

```
markdown file
    ↓
paragraph-aware chunking
(max 600 chars, 80-char overlap between chunks)
    ↓
contextual enrichment
(Groq LLM generates a 1-2 sentence context summary per chunk)
    ↓
dual embedding
(BGE-small dense + BM25 sparse, both run locally)
    ↓
Qdrant upsert
(deterministic UUID5 point IDs — re-ingesting is idempotent)
```

Contextual enrichment is an Anthropic-published technique. Instead of embedding a raw chunk like "Rule 2: amounts must be within tolerance", it embeds "This chunk describes the fuzzy amount matching rule, which applies to FX rounding and bank posting delays." The context makes the embedding richer and retrieval more accurate.

### Retrieval — Hybrid Search with RRF

When the agent calls `search_kb`, the query is embedded with both dense (semantic) and sparse (keyword) models simultaneously. Both searches return ranked result lists. **Reciprocal Rank Fusion (RRF)** merges the two lists into a single ranking:

```
RRF_score(doc) = 1/(60 + rank_dense) + 1/(60 + rank_sparse)
```

This is better than either search alone. Dense search finds semantically related content even with different wording. Sparse search finds exact keyword matches even when the semantic embedding misses them. RRF combines the advantages of both without requiring a reranker model.

Top 5 results are returned (configurable via `RERANK_TOP_K`).

---

## What the LLM Does (and Doesn't Do)

This is one of the most important design decisions in the project. The LLM is **not** the matching engine.

### What the LLM does

- **Orchestrates the workflow.** Decides which tool to call next based on the system prompt instructions and the current state of the conversation.
- **Explains decisions.** Translates match results and audit records into plain English for the accountant.
- **Reads rules.** Calls `search_kb` before each decision to check if a specific rule or SOP applies.
- **Resolves ambiguity.** For descriptions the deterministic vendor matcher can't confidently resolve, the LLM makes a judgement call (Level 6b).
- **Generates KB chunk context.** During knowledge base ingestion only — Groq generates a short context sentence per chunk to improve embedding quality.

### What the LLM does not do

- **Does not compute amounts.** All amount comparisons are Python floats with explicit tolerances.
- **Does not compute dates.** All date windows are Python `timedelta` arithmetic.
- **Does not do fuzzy string matching.** RapidFuzz handles this deterministically.
- **Does not solve subset sums.** PuLP (an MIP solver) does this.
- **Does not auto-approve fuzzy matches.** The system prompt explicitly prohibits this. All non-exact matches must go through `approve_match`.
- **Does not embed documents.** fastembed runs locally with no LLM involved.

### Why this division matters

1. **Auditability.** Deterministic outputs produce the same result every time given the same input. An LLM would not.
2. **Cost.** Running the matching cascade on 200 transactions costs zero LLM tokens. Only the workflow coordination and last-resort verification hit the LLM.
3. **Speed.** Python math is microseconds. An LLM call is 1–3 seconds.
4. **Trust.** Accountants and auditors need to understand why a match was made. "token_set_ratio = 0.87 between 'AMZN MKTPL' and 'Amazon Marketplace'" is explainable. "The LLM said so" is not.

---

## MCP Server — All 6 Tools

The MCP (Model Context Protocol) server is how the agent accesses all system capabilities. Tools are defined with explicit schemas and descriptive docstrings so the LLM knows exactly when and how to use each one.

The server runs in two modes:
- **Standalone stdio:** `python -m mcp_server.server` — connects to Claude Desktop, Cursor, or any MCP-compatible client
- **Direct import:** Used by the Streamlit UI and agent CLI in the same Python process

---

### Tool 1: `search_kb`

```
Input:  query (string), top_k (int, default 5), chunk_type (optional filter)
Output: Formatted string of top K knowledge base chunks
```

Queries the Qdrant knowledge base with hybrid search. The agent system prompt instructs the agent to call this **first**, before any other tool, to check whether a specific rule or SOP applies to the current situation.

`chunk_type` can filter results to: `rule`, `sop`, `alias`, `historical`, `policy`.

**Example use:** Before matching a transaction labelled "FX TRANSFER EUR", the agent calls `search_kb("foreign exchange tolerance rules")` and gets back the FX SOP which specifies a 2% tolerance and 5-day window.

---

### Tool 2: `get_vendor_name`

```
Input:  raw_description (string — the messy bank statement description)
Output: "Canonical name: <vendor>" or "not in alias store" message
```

Looks up the normalised bank description in the `VendorAlias` table. Returns the canonical vendor name if a mapping exists, or tells the agent to call `store_vendor_alias` once it has identified the vendor.

**Example use:** `get_vendor_name("AMZN MKTPL *3X9Z")` → `"Canonical name: Amazon"`

---

### Tool 3: `store_vendor_alias`

```
Input:  raw_description (string), canonical_name (string), source ("agent" or "human")
Output: Confirmation with action (created/updated), alias, and confidence
```

Writes a new vendor alias to the `VendorAlias` table. Human-confirmed mappings get confidence `1.0`. Agent-discovered mappings get `0.8`. The `source` field is stored in the audit log.

This tool is what makes the system self-learning. Every new alias persists across reconciliation runs, improving future matching speed and accuracy.

**Example use:** After a human confirms `"SQ *BLUE BOTTLE"` = `"Blue Bottle Coffee"`, the UI calls this with `source="human"`.

---

### Tool 4: `reconcile`

```
Input:  bank_csv (CSV string), ledger_csv (CSV string)
Output: JSON with run_id, summary stats, and per-transaction match results
```

This is the core tool. It:
1. Parses both CSV strings into DataFrames
2. Runs the Canonical Data Layer normaliser on both (standardises date formats, amount signs, column names)
3. Loads all vendor aliases from the DB
4. Runs the 6-level matching cascade via `run_matching_cascade()`
5. Persists all `MatchRecord` rows to the database
6. Returns a structured JSON report

**Required columns** (normaliser handles variations in naming):
- Bank CSV: `date`, `description`, `amount` (plus optional `txn_id`)
- Ledger CSV: `date`, `description`, `amount` (plus optional `txn_id`)

**Output includes:** `run_id`, `total_bank`, `total_ledger`, `exact_matches`, `fuzzy_matches`, `one_to_many_matches`, `unmatched_bank`, `unmatched_ledger`, `match_rate`, and a list of per-transaction results.

---

### Tool 5: `get_unmatched`

```
Input:  run_id (string — from the reconcile output)
Output: JSON list of unmatched bank transactions with their reasoning_path
```

Filters the in-memory report for the given run to return only `status == "unmatched"` rows. Used by the agent after `reconcile` to review what needs human attention.

**Example output:**
```json
{
  "run_id": "run_20260521_143022_a3f8c1",
  "unmatched": [
    {
      "bank_txn_id": "B_ID_7",
      "reasoning_path": "All 4 matching levels failed for bank_txn_id=B_ID_7 (date=2026-05-15, amount=-45.00, desc='BANK FEE'). Requires human review."
    }
  ]
}
```

---

### Tool 6: `approve_match`

```
Input:  run_id, bank_txn_id, approved (bool), correction_ledger_id (optional), notes (optional)
Output: Confirmation string
```

The Human-in-the-Loop gate. All fuzzy, one-to-many, possible, and unmatched decisions **must** pass through this tool before being finalised. The agent system prompt makes this non-negotiable:

```
"You MUST ask the human to approve every fuzzy or one-to-many match before finalising."
```

When called:
- Updates the `human_approved` field on the `MatchRecord` in the database
- If `correction_ledger_id` is provided, updates `ledger_txn_id` and sets status to `HUMAN_CORRECTED`
- Appends human review notes to `reasoning_path` in the audit log

This means every single reconciliation decision — machine or human — is traceable in the database.

---

## Database — Tables and Purpose

All tables use SQLModel (SQLAlchemy ORM) and are created automatically on startup. For development, SQLite is used. Swap `DATABASE_URL` to a PostgreSQL connection string for production.

### `VendorAlias`

Maps messy bank descriptions to canonical vendor names.

| Column | Type | Description |
|---|---|---|
| `id` | int PK | Auto-increment |
| `alias` | str (indexed) | Normalised bank description (lowercased) |
| `canonical_name` | str | Clean vendor name (e.g. "Amazon") |
| `confidence` | float | 1.0 = human confirmed, 0.8 = agent discovered |
| `source` | str | "human" or "agent" |
| `created_at` | str | ISO timestamp |

This table is the system's long-term memory for vendor names. It grows with every run.

---

### `MatchRecord`

Immutable audit log of every reconciliation decision ever made.

| Column | Type | Description |
|---|---|---|
| `id` | int PK | Auto-increment |
| `run_id` | str (indexed) | e.g. `run_20260521_143022_a3f8c1` |
| `bank_txn_id` | str | ID of the bank transaction |
| `ledger_txn_id` | str / null | ID of the matched ledger entry (null = unmatched) |
| `status` | enum | exact / fuzzy / one_to_many / many_to_one / possible / unmatched / human_corrected |
| `score` | float | Confidence 0.0–1.0 |
| `reasoning_path` | str | Plain-English chain of decisions that produced this result |
| `amount_diff` | float | Absolute amount difference |
| `date_diff_days` | int | Date gap in days |
| `requires_human_review` | bool | True for all non-exact matches |
| `human_approved` | bool / null | null = pending, True = approved, False = rejected |
| `created_at` | str | ISO timestamp |

This table is append-only by design. Even if a human rejects and corrects a match, the original machine decision stays in the record.

---

### `ExtractedInvoice`

Cached results from vision-AI invoice extraction. Indexed by file hash so the same file is never re-processed.

| Column | Type | Description |
|---|---|---|
| `id` | int PK | Auto-increment |
| `file_hash` | str (indexed) | SHA-256 hash of the uploaded file |
| `source_filename` | str | Original filename from the upload |
| `storage_path` | str | Path in `data/uploads/` |
| `mime_type` | str | `application/pdf` or `image/jpeg` etc. |
| `vendor` | str | Extracted vendor name |
| `doc_type` | str | Invoice / Receipt / Bill |
| `invoice_id` | str | Invoice reference number |
| `date` | str | Invoice date |
| `amount` | float | Total amount |
| `currency` | str | ISO currency code |
| `raw_extraction_json` | str | Full LLM response (for debugging) |
| `extraction_confidence` | float | LLM-reported confidence |
| `extraction_error` | str | Error message if extraction failed |
| `created_at` | str | ISO timestamp |

---

### `ManualLedgerEntry`

User-created ledger entries for bank transactions with no corresponding invoice. Modelled after Xero's "create bill from bank transaction" flow.

| Column | Type | Description |
|---|---|---|
| `id` | int PK | Auto-increment |
| `run_id` | str (indexed) | Which reconciliation run this was created in |
| `bank_txn_id` | str (indexed) | The unmatched bank transaction this covers |
| `vendor` | str | Vendor name entered by user |
| `amount` | float | Amount (from the bank line, pre-filled) |
| `date` | str | Date (from the bank line, pre-filled) |
| `description` | str | User-entered description |
| `created_at` | str | ISO timestamp |

---

## The UI — Tab by Tab

Start the UI with `streamlit run app/main.py` and open `http://localhost:8501`.

### Sidebar (persistent across all tabs)

- User card: name and role
- **Pending reviews counter:** how many `MatchRecord` rows have `requires_human_review=True` and `human_approved=None`
- **Recent runs:** last 5 reconciliation runs with their match rate
- Clicking a run navigates to its results in the Audit tab

### Tab 1 — Reconciliation

This is the main workflow tab.

**Step 1: Upload**
- Left column: upload the bank statement CSV
- Right column: upload invoice/bill PDFs or images (up to 10 files per batch)

**Step 2: Extract**
- Click "Extract Invoices" — sends each file to Gemini Vision in parallel
- Results appear in an editable table: vendor, doc_type, invoice_id, date, amount, currency, confidence
- Edit any cell to correct OCR mistakes
- Delete rows if an extracted invoice is wrong or irrelevant

**Step 3: Reconcile**
- Click "Run Reconciliation"
- The app normalises both the bank CSV and the extracted invoice table, runs the 6-level cascade, and stores all `MatchRecord` rows
- Summary stats appear: total transactions, matched by level, unmatched count, overall match rate

**Step 4: Review**
- Each match is shown as a side-by-side card: bank transaction on the left, matched ledger entry on the right
- A colour-coded status badge shows the match level (green = exact, yellow = fuzzy, orange = possible, red = unmatched)
- A confidence meter shows the score as a percentage (green ≥ 90%, yellow ≥ 75%, red < 75%)
- Fuzzy and one-to-many matches show an Approve / Reject button
- Rejecting a match opens a correction field to link the correct ledger entry

**Step 5: Create missing entries**
- For unmatched bank lines, a form pre-filled with the bank transaction data lets the user create a `ManualLedgerEntry` — the system's equivalent of Xero's "create bill from bank transaction"

### Tab 2 — Audit Trail

A filterable, downloadable table of all `MatchRecord` rows.

- Filter by `run_id` to see a specific reconciliation session
- Columns: Run, Bank Ref, Ledger Ref, Status, Confidence, Human Reviewed, Date
- Download as CSV for external audit or accounting system import

### Tab 3 — Vendor Aliases

- View all entries in the `VendorAlias` table
- Columns: Bank Description, Canonical Vendor, Source (Manual/Auto), Confidence
- Form to add a new alias mapping manually
- Adding an existing alias updates it (idempotent)

---

## Self-Learning: The Vendor Alias System

The `VendorAlias` table is the system's long-term memory for vendor names. It compounds in value over time.

**How aliases are added:**

1. **Human correction in the UI:** When a user rejects a vendor match and provides the correct name, `store_vendor_alias` is called with `source="human"`, confidence `1.0`.
2. **Agent discovery:** When the LLM identifies a vendor from context with high confidence, it calls `store_vendor_alias` with `source="agent"`, confidence `0.8`.
3. **Manual entry:** Via the Vendor Aliases tab in the UI.

**How aliases are used:**

At the start of every `reconcile` call, all aliases are loaded from the database. They are passed to the Level 3 description matching, where they are tried first (Tier 2 of the vendor pipeline — O(1) lookup). An alias hit bypasses all lexical and embedding computation and returns the canonical name immediately.

**Effect on match quality:**

Month 1: The system knows no aliases. Most Level 3 matches go through the full lexical + embedding pipeline.

Month 3: After processing real bank statements, the alias table has hundreds of entries covering all vendors the company regularly deals with. Level 3 matching for known vendors becomes near-instant and near-certain.

This is compounding value — the longer the system runs, the better it gets, with no additional configuration required.

---

## Human-in-the-Loop Gates

Human approval is a hard architectural constraint, not an optional feature. The system prompt says:

```
"You MUST ask the human to approve every fuzzy or one-to-many match before finalising."
"Never approve your own fuzzy match without human confirmation."
```

This is enforced at three levels:

1. **Agent prompt:** The system prompt instructs the agent never to call `approve_match` with `approved=True` on its own fuzzy decisions.
2. **Tool design:** `approve_match` requires an explicit `approved` boolean. The UI renders this as a button the accountant physically clicks.
3. **Database schema:** `human_approved` is `null` until `approve_match` is called. Downstream reporting can query `WHERE human_approved IS NULL AND requires_human_review = TRUE` to find everything pending sign-off.

**What requires human approval:**
- Level 2 fuzzy amount matches (when confidence < 0.70)
- All Level 3 description fuzzy matches
- All Level 4 one-to-many matches
- All Level 5 many-to-one matches
- All Level 6a and 6b possible matches
- All unmatched transactions

**What does not require human approval:**
- Level 1 exact matches (confidence = 1.0, deterministic)
- Level 3 alias-exact matches (confidence = 1.0, the human already confirmed this alias in a prior run)

---

## LLM Provider Strategy and Fallbacks

The system uses three different LLM providers for three different jobs. Each was chosen for a specific reason.

### Vision / Extraction — Gemini (primary) → OpenRouter (fallback)

**Gemini 2.5 Flash** is the primary extraction model because it understands PDFs natively (no pre-processing needed), returns structured JSON output reliably, and is fast and cheap.

**OpenRouter (GPT-4o-mini)** is the fallback. If Gemini returns an error, a rate-limit, or a timeout, the `FallbackChain` retries the same request through OpenRouter automatically. The calling code never sees the failure.

Multiple Gemini API keys can be configured (via `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3` in `.env`). On a quota error, the client rotates to the next key.

### Agent Orchestration — Groq or Anthropic

**Groq (Llama-3.3-70b-versatile)** is the default. It is fast (sub-second for most tool-calling turns), cheap, and handles the agent tool-use loop well. Set `LLM_PROVIDER=groq` in `.env`.

**Anthropic (Claude)** is the alternative for higher-reasoning tasks. Set `LLM_PROVIDER=anthropic` and provide `ANTHROPIC_API_KEY`. Claude tends to produce better plain-English explanations and is more conservative about self-approving matches.

Switch between them by changing `LLM_PROVIDER` in `.env` — no code changes.

### KB Ingestion Context Generation — Groq (llama-3.1-8b-instant)

A smaller, faster Groq model is used during knowledge base ingestion to generate the 1-2 sentence context summary per chunk. This is a batch, offline operation — latency does not matter, only cost. `llama-3.1-8b-instant` is the cheapest option for this task.

---

## Docker Services

`docker-compose.yml` defines 5 services. All share the same `data/` volume so the SQLite database and embedding cache are accessible everywhere.

```yaml
services:
  qdrant       # Vector DB — http://localhost:6333
  ingest       # One-shot: runs python -m knowledge_base.ingest, then exits
  mcp_server   # FastMCP tool server — restart: unless-stopped
  ui           # Streamlit — http://localhost:8501, restart: unless-stopped
  tests        # Runs pytest tests/, then exits
```

### Useful Docker commands

```bash
# Start everything
docker-compose up

# Start only what you need (skip tests)
docker-compose up qdrant ui -d

# Rebuild after code changes
docker-compose up --build ui mcp_server

# View live logs
docker-compose logs -f ui
docker-compose logs -f mcp_server

# Restart a crashing service
docker-compose restart mcp_server

# Stop everything
docker-compose down

# Stop and delete volumes (resets Qdrant data — re-run ingest after this)
docker-compose down -v
```

---

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with detailed output on failures
pytest tests/ -v --tb=long

# Run a specific test
pytest tests/test_matching.py::test_exact_match -v

# Run via Docker
docker-compose run tests
```

The test suite covers:
- Level 1 exact matching (clean match, multiple candidates, tiebreaker)
- Level 2 fuzzy amount matching (within tolerance, outside tolerance, date window)
- Level 3 description fuzzy matching (alias hit, lexical match, no match)
- Level 4 one-to-many matching (valid split, no valid split, duplicate prevention)
- Edge cases: empty DataFrames, missing columns, duplicate bank rows, validation errors

---

## Debugging Guide

### The MCP server keeps crashing

```bash
# Check the crash log
docker-compose logs mcp_server

# The most common cause is a missing or invalid API key in .env
# Check that GROQ_API_KEY or GEMINI_API_KEY is set and valid

# Try running it directly (outside Docker) for clearer error output
python -m mcp_server.server
```

### Invoice extraction fails silently

```bash
# Run the Gemini smoke test
python scratch/gemini_key_check.py

# Check the ExtractedInvoice table for extraction_error values
python -c "
from memory.db import get_session
from memory.models import ExtractedInvoice
from sqlmodel import select
with get_session() as s:
    rows = s.exec(select(ExtractedInvoice).where(ExtractedInvoice.extraction_error != None)).all()
    for r in rows: print(r.source_filename, r.extraction_error)
"
```

### Knowledge base search returns nothing

```bash
# Check Qdrant is running
curl http://localhost:6333/healthz

# Check the collection exists
curl http://localhost:6333/collections

# Check point count
curl http://localhost:6333/collections/bank_recon_kb

# If empty, re-run ingestion
python -m knowledge_base.ingest

# Test retrieval directly
python scratch/cascade_smoke_test.py
```

### Matching cascade produces wrong results

```bash
# Run the normaliser test to check data normalisation
python scratch/normalizer_test.py

# Run the cascade smoke test with sample data
python scratch/cascade_smoke_test.py

# Run the level-specific tests
python scratch/cascade_level3_test.py

# Check vendor matching in isolation
python scratch/vendor_match_test.py
```

### Embeddings downloading slowly or failing

The embedding models (`bge-small-en-v1.5` and `bm25`) download on first use to `data/fastembed_cache/`. They total ~90 MB. If the download is interrupted, delete the cache and retry:

```bash
# Delete partial cache
rm -rf data/fastembed_cache/

# Re-run ingest to force re-download
python -m knowledge_base.ingest
```

### Streamlit UI not showing data

```bash
# Check the database exists
ls -la bank_recon.db

# Check tables were created
python -c "
from memory.db import init_db
init_db()
print('DB initialised successfully')
"

# Check for import errors
python -c "from app.main import *"
```

### Clearing the extraction cache (for re-testing)

```bash
python scratch/clear_extraction_cache.py
```

### LLM smoke tests

```bash
# Test Groq + Gemini connectivity
python scratch/llm_smoke_test.py

# Test the full LLM chain (factory + fallback)
python scratch/llm_chain_check.py

# Test the agent system prompt rendering
python scratch/prompt_smoke_test.py
```

### Check which vendor matching method is winning

```bash
python scratch/vendor_match_test.py
# Shows: normalised input, alias hit / lexical score / embedding score, final method
```

---

## Scope and Roadmap

### In scope (current)

- Single-company bank statement reconciliation
- CSV input for bank statements
- PDF and image invoice extraction
- 6-level deterministic + AI-assisted matching cascade
- Self-learning vendor alias system
- Full audit trail
- Human-in-the-loop approval gates
- Streamlit UI for accountants
- MCP server for agent/CLI use
- Docker-based local deployment
- SQLite for development

### Not in scope (current)

- Multi-company or multi-entity reconciliation
- Direct bank API connections (Plaid, Open Banking)
- ERP / accounting software API integration (Xero, QuickBooks, SAP)
- Multi-currency reconciliation with real-time FX rates
- Scheduled automatic reconciliation

### Roadmap

- **PostgreSQL** — swap `DATABASE_URL` in `.env`. The ORM is already compatible.
- **LangSmith tracing** — `LANGSMITH_API_KEY` is already wired in settings; just needs the tracer hooked into the agent loop.
- **GBrain integration** — compiled intelligence layer for complex recurring patterns (design doc: `gbrains_plan.md`).
- **Multi-account support** — organisation-scoped tables and a login layer.
- **Xero / QuickBooks export** — write reconciled entries back to the accounting system via their APIs.
- **Scheduled runs** — cron-triggered reconciliation against a configured bank feed.

---

## Contributing

1. Edit knowledge base rules in `knowledge/` (plain markdown — no code)
2. Re-ingest: `python -m knowledge_base.ingest`
3. Run tests: `pytest tests/ -v`
4. Add new matching rules by extending `run_matching_cascade()` in `mcp_server/tools/matching.py`
5. Add new MCP tools by adding a decorated function in `mcp_server/server.py`

All matching functions must be pure (no side effects). The MCP tool layer handles DB writes.
