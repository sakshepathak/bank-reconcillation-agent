# Bank Reconciliation — Multi-Tenant Accounting System

A multi-tenant bank reconciliation platform. Each organisation gets fully isolated books: invoices, bills, contacts, bank accounts, and statement lines. A deterministic matching cascade pairs bank transactions against open invoices and bills, with a human-review queue for anything the engine isn't sure about.

> 📖 **Documentation:** [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) — module guide (how each part works) · [`docs/FEATURES.md`](docs/FEATURES.md) — full feature list · [`docs/DEMO_CHEATSHEET.md`](docs/DEMO_CHEATSHEET.md) — reconciliation demo runbook.

---

## Table of Contents

1. [What This Is](#what-this-is)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Getting Started](#getting-started)
5. [Running the App](#running-the-app)
6. [Features](#features)
7. [API Overview](#api-overview)
8. [Database and Migrations](#database-and-migrations)
9. [Matching Engine](#matching-engine)
10. [Multi-Tenancy and Auth](#multi-tenancy-and-auth)
11. [Future Scope and Next Steps](#future-scope-and-next-steps)
12. [Running Tests](#running-tests)

---

## What This Is

A full-stack accounting and bank reconciliation tool built for small businesses and accountants. It handles the complete workflow:

1. **Register / log in** — each user belongs to one or more organisations
2. **Add your organisation** — business name, country, currency, VAT details, financial year end
3. **Import bank statements** — CSV or PDF, mapped to a bank account
4. **Create invoices and bills** — manually or by uploading a PDF (LLM extraction)
5. **Run reconciliation** — a 6-level matching cascade pairs statement lines against open documents
6. **Review queue** — anything below the confidence threshold waits for human approval
7. **Contacts and vendor aliases** — normalised contact deduplication with a self-learning alias table that improves matching over time

Every piece of data is scoped to an organisation. There is no way for one tenant to see another tenant's data.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11+ |
| ORM | SQLModel (SQLAlchemy) |
| Database | SQLite (dev) — swap `DATABASE_URL` for PostgreSQL |
| Auth | Session cookies, bcrypt (cost 12), server-side `UserSession` table |
| Frontend | React 18, TypeScript, Vite |
| State / data fetching | TanStack Query v5 |
| Forms | react-hook-form + zod |
| UI components | shadcn/ui, Tailwind CSS, Lucide icons |
| PDF extraction | Google Gemini Vision (with OpenRouter fallback) |
| Fuzzy matching | RapidFuzz (Jaro-Winkler + token/partial ratios) |
| Semantic matching | fastembed (BGE-small-en-v1.5, local) — vendor matching + knowledge base |
| Vector store | Qdrant (knowledge base retrieval) |
| Subset-sum solver | PuLP (Mixed-Integer Programming) |
| Testing | pytest |

---

## Project Structure

```
Bank_reconcillation_model/
│
├── api/                        # FastAPI application
│   ├── main.py                 # App factory, router registration, CORS, migrations
│   ├── auth.py                 # bcrypt helpers, session management
│   ├── deps.py                 # FastAPI dependencies: require_user, get_current_org_id
│   └── routers/
│       ├── auth.py             # /auth/register, /login, /logout, /me, /current-org
│       ├── orgs.py             # /orgs/ — create, list, get/patch current, export, delete (full wipe)
│       ├── bank_accounts.py    # /bank-accounts/
│       ├── invoices.py         # /invoices/ + PDF upload extraction
│       ├── bills.py            # /bills/ + PDF upload extraction
│       ├── contacts.py         # /contacts/ + contact detail with aliases
│       ├── aliases.py          # /aliases/ — vendor alias management
│       ├── statement_lines.py  # /statement-lines/ + CSV/JSON import
│       ├── runs.py             # /runs/ — reconciliation run history
│       ├── matches.py          # /matches/ — approve/reject individual matches
│       ├── exceptions.py       # /exceptions/duplicates, /bulk-approve-queue
│       ├── dashboard.py        # /dashboard/stats
│       ├── audit.py            # /audit/ — immutable match record log
│       └── journal_entries.py  # /journal-entries/
│
├── engine/
│   ├── bank_statement_parser.py  # CSV/PDF → canonical DataFrame
│   ├── contacts.py               # upsert_contact() — normalised dedup within org
│   ├── vendor_matching/          # 4-tier matcher: normalize · similarity · embedder · explain
│   └── llm/                      # Gemini + OpenRouter extraction clients
│
├── knowledge_base/             # Qdrant hybrid retrieval (RAG) — ingest + retriever
├── mcp_server/tools/           # matching.py (batch cascade), split_solver.py (PuLP), …
│
├── memory/
│   ├── models.py                 # All SQLModel ORM models
│   ├── db.py                     # Engine factory, session context manager
│   └── migrations/
│       ├── _runner.py            # Numbered migration runner (idempotent)
│       ├── _001_add_org_id.py    # Added org_id to all 13 business tables
│       └── _002_vendor_alias_contact_fk.py  # VendorAlias → Contact FK
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx               # Router, auth guards, route definitions
│   │   ├── lib/
│   │   │   ├── auth-context.tsx  # AuthProvider, useAuth, org-cache reset
│   │   │   └── api.ts            # Axios instance, ApiError class
│   │   ├── components/
│   │   │   ├── OrgSwitcher.tsx   # Org switcher + "Add new organisation" in sidebar
│   │   │   ├── RequireAuth.tsx   # Redirects to /login if not authenticated
│   │   │   └── RequireOrg.tsx    # Redirects to /onboarding if no org selected
│   │   └── pages/
│   │       ├── Login/            # Login form
│   │       ├── Register/         # Registration form (when ALLOW_REGISTRATION=true)
│   │       ├── Onboarding/       # "Add your business" — country, currency, VAT, FYE
│   │       ├── Dashboard/        # Summary stats
│   │       ├── BankAccounts/     # List + create bank accounts, upload statements
│   │       ├── Sales/            # Invoice list + create + PDF upload
│   │       ├── Purchases/        # Bill list + create + PDF upload
│   │       ├── Contacts/         # Contact list + detail page with aliases
│   │       ├── Aliases/          # Vendor alias management
│   │       ├── Reconciliation/   # Run reconciliation
│   │       ├── ReviewQueue/      # Human approval queue
│   │       ├── AuditTrail/       # Immutable match record log
│   │       └── Settings/         # Profile · Organisation (edit + danger zone) · Services
│   └── vite.config.ts
│
├── tests/
│   ├── conftest.py               # TestClient fixture, fresh DB per test
│   ├── test_auth.py              # Registration, login, session management
│   ├── test_org_scoping.py       # 15 cross-tenant leak tests (every model)
│   ├── test_orgs_router.py       # Org create / switch / patch / list
│   ├── test_stage3_contacts_aliases.py  # Contact dedup, alias FK, rename propagation
│   ├── test_add_org_e2e_flow.py  # End-to-end: seed org A → create org B → verify isolation
│   ├── test_migrations.py        # Migration runner idempotency
│   └── test_matching.py          # Matching cascade unit tests
│
├── scripts/
│   ├── create_first_user.py      # Bootstrap first user when ALLOW_REGISTRATION=false
│   ├── migrate.py                # Run tracked numbered migrations
│   └── explain_match.py          # Terminal step-by-step trace of the matcher
├── docs/                         # WALKTHROUGH (module guide), FEATURES, DEMO_CHEATSHEET
├── sample_data/                  # Sample CSVs for manual testing
├── requirements.txt
└── .env.example
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+

### Step 1 — Clone and create virtual environment

```bash
git clone https://github.com/sakshepathak/bank-reconcillation-agent.git
cd Bank_reconcillation_model

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### Step 2 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Set up environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Database (SQLite for dev, swap to PostgreSQL URL for prod)
DATABASE_URL=sqlite:///./bank_recon.db

# Secret key for session signing
SECRET_KEY=change-me-to-a-long-random-string

# Allow public registration (set false in prod — use scripts/create_first_user.py)
ALLOW_REGISTRATION=true

# Vision AI for PDF invoice/bill extraction (optional — manual entry still works without it)
GEMINI_API_KEY=your_gemini_key_here
OPENROUTER_API_KEY=your_openrouter_key_here   # fallback
```

### Step 4 — Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Running the App

### Backend

```powershell
# Windows (Hyper-V reserves ports 8000/8001 — use 8765)
uvicorn api.main:app --reload --port 8765
```

```bash
# macOS / Linux
uvicorn api.main:app --reload --port 8001
```

The API runs at `http://localhost:8765` (or 8001). Migrations run automatically on startup.

### Frontend

```powershell
# Windows
$env:VITE_API_TARGET = "http://localhost:8765"
cd frontend
npm run dev
```

```bash
# macOS / Linux
VITE_API_TARGET=http://localhost:8001 npm run dev
```

Open `http://localhost:5173` (or `5174` if 5173 is taken).

### First run

1. Register at `/register` (requires `ALLOW_REGISTRATION=true` in `.env`)
2. Fill in your organisation details on the onboarding page
3. You land on the dashboard scoped to your new organisation

> **Production:** Set `ALLOW_REGISTRATION=false` and create the first user via `python scripts/create_first_user.py`.

---

## Features

### Authentication

- Email + password registration and login
- bcrypt password hashing (cost 12)
- Server-side sessions (httpOnly cookie, 30-day sliding renewal)
- `ALLOW_REGISTRATION` env flag controls whether `/register` is accessible

### Multi-Organisation Support

- A single user can belong to multiple organisations (personal books, client books, etc.)
- Session tracks `current_org_id` — all reads and writes are scoped to this org
- **OrgSwitcher** in the sidebar lets you jump between orgs instantly
- **"+ Add new organisation"** walks through the onboarding form and switches to the new org automatically
- If a user has no organisation (or just deleted the one they were in), they land on `/onboarding`, which doubles as an **org picker** — select an existing org or create a new one
- **Delete an organisation** (Settings → Organisation → Danger Zone): permanently wipes every row across all 14 org-scoped tables plus its knowledge-base vectors, then resets the session to "no org selected". A typed-name confirmation is required, and a one-click **JSON backup export** is offered first. Admin-only.

### Settings

- **Profile** — the logged-in user's name, role, email (per user, not per org)
- **Organisation** — one editable form covering both org identity (name, country, currency, VAT/tax) and the rich company profile (about/what the business does, website, phone, address, registration number). Saving writes to `PATCH /orgs/current` and `PUT /company` together so the two records stay in sync. The "About" field is the seed for the planned assistant knowledge base.
- **Services & Products** — per-org catalogue used for VAT categorisation; fully org-scoped

### CSV Import (invoices & bills)

- Upload a CSV of invoices or bills (in addition to PDF/LLM extraction)
- Column names are matched case-insensitively (`number`/`invoice_number`, `customer`/`contact_name`, `date`/`issue_date`, `amount`/`total`, …)
- **ISO dates (`YYYY-MM-DD`) are stored verbatim** — a regex short-circuit in `_parse_date` avoids pandas' `dayfirst` month/day ambiguity entirely; only non-ISO formats fall through to pandas
- **De-duplication by invoice/bill number within the org**: re-importing the same file updates the existing record in place instead of creating duplicates

### Bank Accounts and Statement Import

- Unlimited bank accounts per org
- Import statements as CSV or upload a PDF (Gemini Vision)
- Statement lines feed directly into reconciliation

### Invoices and Bills

- Create invoices (sales) and bills (purchases) manually or via PDF upload
- PDF extraction via Gemini Vision with OpenRouter fallback
- Contacts are auto-created and deduplicated on every create or upload

### Contacts and Vendor Aliases

- Contacts deduplicated within an org by normalised name (strips Ltd/Limited/Inc/Co, punctuation, case)
- Each `VendorAlias` links a raw bank description to a canonical Contact
- The alias table grows with every human correction — improves matching accuracy over time
- Contact detail page shows linked invoices, bills, and all aliases
- Renaming a contact propagates to all its aliases automatically

### Reconciliation Engine

A 6-level matching cascade pairs statement lines against open invoices and bills:

| Level | Method | Auto-approve? |
|---|---|---|
| 1 | Exact date + amount | Yes |
| 2 | Fuzzy amount + date window | Only if confidence ≥ 0.70 |
| 3 | Vendor description fuzzy (alias → lexical → embedding) | Alias-exact only |
| 4 | One-to-many (subset sum via PuLP MIP) | No |
| 5 | Many-to-one (instalment payments) | No |
| 6a | Relaxed fuzzy (speculative) | No |
| 6b | LLM verifier (last resort, small residual sets) | No |

### Reconcile Actions

Each statement line can be resolved four ways (in `api/routers/statement_lines.py`):
- **Match** — link to an invoice or bill; updates the document's paid amount and the bank balance
- **Create** — spawn a journal/ledger entry for lines with no document (e.g. a bank fee)
- **Transfer** — mark as a transfer between two of your own bank accounts (moves both balances)
- **Discuss** — attach a note and leave the line pending
- **Bulk match** — one bank line against multiple invoices/bills, with a live "amount needed" progress bar

### Match Explainability

Every match score can be opened up step by step — useful for trust, audits, and demos:
- **`GET /statement-lines/{id}/explain`** returns the full trace (normalisation → alias → lexical sub-scores → embedding cosine → ensemble → amount/date → verdict)
- **"How was this matched?"** panel in the reconciliation UI renders that trace inline
- **`scripts/explain_match.py`** prints the same trace in the terminal for any real entry (`--line <id>`) or built-in examples
- All three share one function (`engine/vendor_matching/explain.py`), so the numbers always match what the app acted on

### Review Queue

- All non-exact matches wait for human approval
- Approve or reject individual matches
- Bulk-approve queue for high-confidence pending matches above a configurable score

### Audit Trail

- Every reconciliation decision is written to an immutable `MatchRecord` table
- Records include: match level, confidence, amount diff, date diff, reasoning path, human approval status

---

## API Overview

All endpoints are under `/api/v1/`. Every endpoint except `/auth/*` requires a valid session cookie and a `current_org_id` set on the session.

| Endpoint | Description |
|---|---|
| `GET /api/v1/auth/me` | Current user + org memberships |
| `POST /api/v1/auth/login` | Log in |
| `POST /api/v1/auth/register` | Register (requires `ALLOW_REGISTRATION=true`) |
| `POST /api/v1/auth/logout` | Log out |
| `PUT /api/v1/auth/current-org` | Switch active org |
| `GET/POST /api/v1/orgs/` | List / create organisations |
| `GET/PATCH /api/v1/orgs/current` | Get or update current org settings |
| `GET /api/v1/orgs/{id}/export` | Full JSON backup of an org's data (admin-only) |
| `DELETE /api/v1/orgs/{id}` | Permanently delete an org and all its data (admin-only) |
| `GET/PUT /api/v1/company` | Get / upsert the rich company profile for the current org |
| `GET/POST /api/v1/services` | Per-org services & products catalogue |
| `GET/POST /api/v1/bank-accounts/` | Bank accounts |
| `GET/POST /api/v1/invoices/` | Invoices |
| `POST /api/v1/invoices/upload` | Extract invoice from PDF |
| `POST /api/v1/invoices/upload-csv` | Bulk import invoices from CSV (dedupes by number) |
| `GET/POST /api/v1/bills/` | Bills |
| `POST /api/v1/bills/upload` | Extract bill from PDF |
| `POST /api/v1/bills/upload-csv` | Bulk import bills from CSV (dedupes by number) |
| `GET/POST /api/v1/contacts/` | Contacts |
| `GET /api/v1/contacts/{id}/detail` | Contact + linked invoices/bills/aliases |
| `GET/POST /api/v1/aliases/` | Vendor aliases |
| `POST /api/v1/statement-lines/import` | Import statement lines |
| `GET /api/v1/statement-lines/` | List statement lines |
| `GET /api/v1/statement-lines/{id}/suggestions` | Ranked match candidates with confidence scores |
| `GET /api/v1/statement-lines/{id}/explain` | Step-by-step trace of how a candidate is scored |
| `POST /api/v1/statement-lines/{id}/match-invoice` · `match-bill` | Reconcile a line to an invoice / bill |
| `POST /api/v1/statement-lines/{id}/create-entry` · `transfer` · `discuss` | Create entry / mark transfer / add note |
| `GET/POST /api/v1/runs/` | Reconciliation runs |
| `POST /api/v1/matches/{id}/approve` | Approve a match |
| `POST /api/v1/matches/{id}/reject` | Reject a match |
| `GET /api/v1/exceptions/duplicates` | Duplicate detection |
| `GET /api/v1/exceptions/bulk-approve-queue` | High-confidence pending matches |
| `GET /api/v1/dashboard/stats` | Summary counters |
| `GET /api/v1/audit/` | Full match record log |

---

## Database and Migrations

SQLite for development. Set `DATABASE_URL` in `.env` to a PostgreSQL connection string for production — the SQLModel ORM is compatible with both.

There are **two** migration mechanisms, by design:

1. **Lightweight column-adds — run on every startup.** `init_db()` (`memory/db.py`) runs `SQLModel.metadata.create_all` plus a list of `ALTER TABLE … ADD COLUMN` statements, each wrapped in try/except. These are idempotent: on an already-migrated database each statement no-ops. This keeps the schema in sync with the code with zero manual steps.
2. **Tracked numbered migrations — run deliberately.** The numbered runner (`memory/migrations/_runner.py`, invoked via `python scripts/migrate.py`) records applied migrations in a `migration_history` table, skips ones already applied, and wraps each in a transaction. Used for the larger structural changes.

| Numbered migration | What it does |
|---|---|
| `_001_add_org_id.py` | Adds `org_id` to all 13 business tables, backfills to org 1, adds indices |
| `_002_vendor_alias_contact_fk.py` | Adds `contact_id` FK to `vendor_alias`, backfills by matching `canonical_name` to `Contact.full_name` within org |

---

## Matching Engine

The batch cascade lives in `mcp_server/tools/matching.py`; the interactive per-line suggestions the UI uses are in `api/routers/statement_lines.py`; the vendor entity-resolution layer is in `engine/vendor_matching/`. (`api/routers/runs.py` only serves run history.)

**Key design principle:** The LLM is not the matching engine. All amount comparisons, date windows, fuzzy scores, and subset sums are deterministic Python. The LLM only runs as a last-resort pass (Level 6b) on small residual unmatched sets.

**Vendor matching is layered** (`engine/vendor_matching/`):
1. **Normalise** — strip processor prefixes, bank noise, txn IDs, and company suffixes (Ltd/Inc/LLC…); uppercase and collapse whitespace
2. **Alias** — exact O(1) hit from the learned `VendorAlias` table
3. **Lexical** — weighted blend of Jaro-Winkler + token-set/sort + partial ratios (RapidFuzz)
4. **Embedding** — local BGE-small vector cosine, used only when lexical isn't decisive, to catch meaning that spelling misses (e.g. `DAILYBEAN` ↔ `The Daily Bean`)

The final score is an "ensemble max" — any strong signal wins. The same normalisation is used for contact deduplication (`upsert_contact`), so the identity the matcher resolves is the identity stored in the database. The full scoring is inspectable via the [Match Explainability](#features) tooling.

---

## Multi-Tenancy and Auth

Every business-data table has an `org_id` column. Every router endpoint extracts `org_id` from the session via the `get_current_org_id` FastAPI dependency. Every query filters by this `org_id`.

Cross-tenant IDOR is prevented by `_load_X_for_org()` helpers in each router — these return 404 if `row.org_id != session_org_id`, even if the caller knows the row ID.

The frontend mirrors this with a cache-reset strategy: on every org-context change (login, logout, switch, create org), `removeQueries()` drops all cached data except `/auth/me`. Components re-mount into a clean loading state — there is no window where one org's data is visible under another org's view.

---

## Future Scope and Next Steps

### Near-term
- **Org-scope the knowledge base.** The retrieval pipeline (`knowledge_base/`) is currently global. Scope every query by `org_id` before any assistant ships, so one organisation can never retrieve another's data. *(Security-critical prerequisite for the chatbot.)*
- **Schema hardening.** Add a `_003_org_id_not_null` migration to enforce `NOT NULL` on `org_id`, and fold the inline column-adds in `memory/db.py` into the tracked numbered-migration runner so nothing schema-related re-runs on every boot.
- **Consolidate `Organization` and `CompanyProfile`.** They overlap (industry, VAT, tax) and are currently kept in sync by a dual write from Settings; merge into one model to remove the drift risk.

### Mid-term
- **Per-company assistant (chatbot).** An agent over each organisation's data that mixes semantic search (RAG, for descriptions and policies) with exact database queries (for figures), plus a "teach a fact through chat" write-back. Built on the existing local Qdrant + fastembed stack — no new external service.
- **Profile → knowledge base sync.** Feed the Settings "about the company" description and business data into the org-scoped knowledge base automatically, so the assistant has context.

### Longer-term
- **In-house extraction module.** Continue hardening the self-contained document-extraction pipeline (now decoupled from any external service).
- **Production database.** Move from SQLite to PostgreSQL (`DATABASE_URL` already supports it) for concurrent multi-user use.
- **Reconciliation at scale.** A batch "reconcile all" endpoint plus performance tuning for large statements.

---

## Running Tests

```bash
pytest tests/ -v
```

| File | What it tests |
|---|---|
| `test_auth.py` | Registration, login, session management, register-enabled flag |
| `test_org_scoping.py` | 15 cases — every model, every verb, cross-tenant leak detection |
| `test_orgs_router.py` | Org create, auto-switch, isolation, validation, list, get/patch |
| `test_stage3_contacts_aliases.py` | Contact upsert dedup, alias FK migration, detail endpoint, rename propagation |
| `test_add_org_e2e_flow.py` | End-to-end: seed all data in org A → create org B → every list endpoint empty → switch back → data intact |
| `test_migrations.py` | Migration runner idempotency, migrations 001 and 002 |
| `test_matching.py` | Matching cascade levels 1–4, edge cases |
