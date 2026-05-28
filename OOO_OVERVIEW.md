# OOO — Bank Reconciliation App

A Xero-style bank reconciliation tool that closes the gap between what your
bank says you have and what your ledger thinks you have. Built as a small
accounting application with sales (AR), purchases (AP), bank statement
ingestion, and a split-pane reconcile screen.

---

## 1. The core problem

Every business with a bank account has two numbers:

| Source | What it shows |
|---|---|
| **Statement balance** | What the bank tells you the account holds *right now*. |
| **OOO balance** | What OOO (this app) has tracked across reconciled invoices, bills, transfers, and manual entries. |

When you import a fresh bank statement, the two numbers disagree — because
some statement lines haven't been matched against an invoice/bill/journal
entry yet. **Reconciliation closes that gap.**

### The invariant

> When every `StatementLine` on an account is reconciled,
> `statement_balance == ooo_balance`.

The whole app exists to drive that delta to zero, one statement line at a
time. The Reconcile screen is where this happens.

---

## 2. Architecture at a glance

```
┌──────────────────────────────────────────────────────────────────┐
│                        REACT + TYPESCRIPT                        │
│                     (Vite dev server on :5173)                   │
│                                                                  │
│   Sidebar → 10 pages, each calls FastAPI via /api/v1/*           │
│   TanStack Query for server state, Zustand for UI state          │
└────────────────────────────────┬─────────────────────────────────┘
                                 │ HTTP
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                       FASTAPI BACKEND                            │
│                       (uvicorn on :8000)                         │
│                                                                  │
│   /api/v1/* — 45+ routes split across 14 routers                 │
│   /api/docs — interactive OpenAPI                                │
└──────┬─────────────────────┬──────────────────┬──────────────────┘
       │                     │                  │
       ▼                     ▼                  ▼
┌────────────┐    ┌────────────────────┐    ┌────────────────────┐
│  SQLModel  │    │   LLM Pipeline     │    │   Vector KB        │
│  (SQLite)  │    │   (Gemini +        │    │   (Qdrant +        │
│            │    │    OpenRouter)     │    │    fastembed)      │
│ ~20 tables │    │   - Invoice PDFs   │    │   - Aliases        │
│            │    │   - Statement PDFs │    │   - Matching rules │
└────────────┘    └────────────────────┘    └────────────────────┘
```

A **legacy Streamlit UI** still runs on :8501 as a fallback. It will be cut
once every screen is ported to React.

---

## 3. Data model

### Xero-style accounting entities (Phase 4a)

| Table | Purpose | Key fields |
|---|---|---|
| `bank_account` | One row per bank account the company holds. Tracks both balances. | `statement_balance`, `ooo_balance`, `currency`, `pending_count` (computed) |
| `statement_line` | Raw bank line, queryable. Left side of the reconcile split-pane. | `spent`, `received`, `status`, `matched_invoice_id`, `matched_bill_id`, `matched_journal_id`, `transfer_to_account_id` |
| `invoice` | Sales — money owed TO you by customers. | `number`, `contact_name`, `total`, `paid_amount`, `status` |
| `invoice_line` | Line items on a sales invoice. | `description`, `quantity`, `unit_price`, `tax_rate` |
| `bill` | Purchases — money owed BY you to suppliers. Mirror of invoice. | Same as invoice + `source_file_path` for the PDF |
| `bill_line` | Line items on a bill. | + `account_code` (GL account) |
| `journal_entry` | Manual ledger entry from the Reconcile "Create" tab. | Signed `amount`, contact, description |

### Supporting entities (pre-existing)

| Table | Purpose |
|---|---|
| `contact` | Customers / suppliers / internal contacts. |
| `company_profile` | Single-row company info (name, VAT, tax treatment). |
| `user_profile` | Single-row user info (name, role, email). |
| `service_offered` | Service / product catalogue with VAT applicability. |
| `vendor_alias` | "AMZN MKTPL *123" → "Amazon" mappings to improve auto-matching. |
| `match_record` | Audit log of every reconciliation decision (legacy engine). |
| `extracted_invoice` | LLM-extracted PDF data (legacy, being replaced by direct Invoice/Bill creation). |
| `manual_ledger_entry` | Older inline-created entries (legacy). |

### Status enums

- `DocumentStatus`: `draft / awaiting_approval / awaiting_payment / paid / voided` (mirrors Xero's tabs)
- `StatementLineStatus`: `pending / matched / manual / transfer / discussed`

---

## 4. The 10 pages and what they do

| # | Page | Path | Purpose |
|---|---|---|---|
| 1 | Dashboard | `/dashboard` | (current: legacy KPIs from match-record engine; rebuild planned) |
| 2 | Sales | `/sales` | Invoice list with status tabs, create/import PDFs, view-only details panel |
| 3 | Purchases | `/purchases` | Bill list with status tabs, create/import PDFs, view-only details panel |
| 4 | Bank Accounts | `/bank-accounts` | Cards showing Statement vs OOO balance, balance diff, import statements (CSV/PDF) |
| 5 | **Reconcile** | `/reconciliation` | **The headline.** Split-pane: statement line LEFT, Match/Create/Transfer/Discuss tabs RIGHT |
| 6 | Review Queue | `/review` | Matches the legacy engine flagged for human review (approve/reject, bulk + keyboard shortcuts) |
| 7 | Contacts | `/contacts` | Full CRUD with slide-in panel, type filter (customer/supplier/internal/other) |
| 8 | Audit Trail | `/audit` | Paginated history of every match decision, CSV export |
| 9 | Vendor Aliases | `/aliases` | Manage canonical-name mappings for fuzzy matching |
| 10 | Settings | `/settings` | 3 tabs: Profile, Company (VAT, tax treatment), Services & Products catalogue |

---

## 5. Key user workflows

### Workflow A — Setting up the app for the first time

1. **Settings → Profile** → enter your name, role, email
2. **Settings → Company** → company name, registration number, VAT settings
3. **Settings → Services & Products** → add your service/product catalogue
4. **Contacts → Add Contact** → add a few customers and suppliers
5. **Bank Accounts → New Account** → create your business bank account

### Workflow B — Recording a sale (invoice)

There are two paths:

**Manual:**
1. Sales → "+ New Invoice" → slide-in panel opens with auto-numbered `INV-XXXX`
2. Fill in customer, dates, line items (description / qty / unit price / VAT %)
3. Live subtotal + VAT + total at the bottom
4. "Save as Draft" or "Approve" (jumps to awaiting_payment)

**From a PDF:**
1. Sales → "Import PDF" → file picker (multi-select, supports PDF/PNG/JPG/WEBP)
2. LLM extracts customer (BILL TO), invoice number, date, total
3. Each file becomes a Draft Invoice with a single line item containing the total
4. User reviews the draft, breaks the single line into multiple if needed, then approves

### Workflow C — Recording a purchase (bill)

Same as Workflow B but on the Purchases tab. The LLM uses a **different prompt**
that looks for the SUPPLIER (FROM / VENDOR section) instead of the customer.
Bills also store `source_file_path` so you can view the PDF back later.

### Workflow D — Importing a bank statement

1. Bank Accounts → click the account card → "Import statement"
2. Pick a CSV or PDF file
3. CSV: passthrough parsing (date, description, amount columns)
4. PDF: text extraction via PyMuPDF → LLM structured output via Gemini
5. Backend creates `StatementLine` rows with split spent/received columns
6. Account's `statement_balance` updates to the latest balance_after
7. Pending count badge appears on the card

### Workflow E — Reconciling (the main loop)

For each pending statement line, you see a split-pane card. The right side
has four sub-tabs:

**Match tab** (default):
- Hits `/suggestions` endpoint → backend scores all open invoices (for inflows)
  or open bills (for outflows) by amount + date proximity + name overlap
- Top 5 returned, sorted by confidence
- Pick one + click OK → calls `/match-invoice` or `/match-bill`
- Side effects: invoice/bill `paid_amount` increases, status flips to PAID
  when fully paid, `ooo_balance` on the account updates by the signed delta

**Create tab**:
- Inline form: Who (contact), What (account code), Why (description)
- Submit → creates a `JournalEntry` linked to the line
- `ooo_balance` updates

**Transfer tab**:
- Dropdown of your other bank accounts → submit
- Both accounts' `ooo_balance` update (one +, one −)

**Discuss tab**:
- Attach a note → status flips to "discussed" (still pending until matched)

Every reconcile action has a corresponding `unreconcile` endpoint that
**reverses all side effects** — the invoice goes back to awaiting_payment,
the balance moves back, the journal entry is deleted. Audit-safe.

---

## 6. Important pipelines

### Pipeline 1 — PDF invoice/bill extraction

```
PDF/image upload
   │
   ▼
multipart/form-data → POST /api/v1/{invoices,bills}/upload
   │
   ▼
engine.file_store.save_upload()        ← content-addressed (SHA-256), idempotent
   │
   ▼
mcp_server.tools.invoice_extractor.extract_invoice(doc_type='sales'|'purchase')
   │
   ├─→ Gemini (native PDF support, schema-enforced JSON)
   │     prompt selects:
   │       sales    → find COUNTERPARTY in BILL TO
   │       purchase → find COUNTERPARTY in FROM / VENDOR
   │
   └─→ OpenRouter (Claude) fallback for images / Gemini failures
   │
   ▼
ExtractionResult { vendor, invoice_id, date, amount, currency, confidence }
   │
   ▼
Create Invoice or Bill in DRAFT status with single line item
   │
   ▼
Return to UI for user review
```

**Why this design:** Gemini handles PDFs natively (no rendering needed), and
the schema-enforced output means we get structured fields not free-text.
LLM doesn't extract line items in v1 — that's a future enhancement.

### Pipeline 2 — Bank statement parsing

```
CSV/PDF upload
   │
   ▼
multipart/form-data → POST /api/v1/statement-lines/upload (bank_account_id, file)
   │
   ▼
engine.bank_statement_parser.parse_bank_statement(bytes, mime)
   │
   ├─→ CSV path: pandas passthrough (date, description, signed amount)
   │
   └─→ PDF path:
         1. PyMuPDF text extraction (free, fast, works for ~80% of bank PDFs)
         2. If meaningful text → send to Gemini for structured parsing
         3. If text extraction fails → send PDF bytes to Gemini directly
   │
   ▼
DataFrame { date, description, amount (signed) }
   │
   ▼
Convert to StatementLine rows:
   - amount > 0 → received = amount
   - amount < 0 → spent = abs(amount)
   - status = PENDING
   - balance_after carried through
   │
   ▼
Update BankAccount.statement_balance to last balance_after
```

### Pipeline 3 — Match suggestion ranking

When the Reconcile screen renders a statement line, each `ReconcileRow`
fetches its own suggestions:

```
GET /api/v1/statement-lines/{id}/suggestions
   │
   ▼
direction = inflow (received > 0) or outflow (spent > 0)
   │
   ▼
candidates = all open Invoices (inflow) or all open Bills (outflow)
   │
   ▼
For each candidate, score(0–1):
   • amount match:    0.6 exact / 0.4 within 1%
   • date proximity:  0.3 same day / 0.25 ≤3d / 0.15 ≤14d / 0.05 ≤30d
   • name overlap:    +0.1 if contact_name appears in bank description
   │
   ▼
Top 5 returned, each with a `reason` string ("exact amount, 8d apart, name match")
```

UI shows confidence badges color-coded: ≥90% green, 60-89% amber, <60% grey.

### Pipeline 4 — Reconcile-and-update (the core write path)

```
User picks a suggestion → POST /api/v1/statement-lines/{id}/match-invoice
                                                              {invoice_id: X}
   │
   ▼
Verify line is PENDING (409 if not — must unreconcile first)
   │
   ▼
   ┌──────────────────────────────────────────────────────┐
   │ Transactional (single DB commit):                    │
   │                                                      │
   │   line.matched_invoice_id = invoice.id               │
   │   line.status = MATCHED                              │
   │   line.reconciled_at = now                           │
   │                                                      │
   │   invoice.paid_amount += amount                      │
   │   if paid_amount >= total → invoice.status = PAID    │
   │                                                      │
   │   bank_account.ooo_balance += signed_amount          │
   └──────────────────────────────────────────────────────┘
   │
   ▼
TanStack Query invalidates ['statement-lines', accountId, 'pending']
and ['bank-accounts'] — UI updates: card disappears, balance bar shifts
```

Same shape for `match-bill`, `create-entry`, `transfer`. `unreconcile` runs
this in reverse.

---

## 7. Tech stack

### Backend
- **FastAPI** + **uvicorn** — async REST API
- **SQLModel** — Pydantic models that double as SQLAlchemy ORM
- **SQLite** — single-file DB (production would be Postgres; SQLite is fine for dev/demo)
- **Qdrant** + **fastembed** — vector knowledge base for the legacy matching engine
- **pandas** — CSV/DataFrame ops for statement parsing
- **PyMuPDF (fitz)** — PDF text extraction
- **pydantic** — request/response schema validation

### LLM layer (engine/llm/)
- **Gemini** — primary provider, native PDF support, schema-enforced JSON
- **OpenRouter** (Claude) — fallback for image-based extraction
- Fallback chain in `engine/llm/factory.py`

### Frontend
- **React 18** + **TypeScript** + **Vite** — base
- **Tailwind 3** + **shadcn/ui** — component system (indigo primary, Outfit font)
- **TanStack Query v5** — server state, optimistic updates, cache invalidation
- **React Router v6** — `/sales`, `/reconciliation?account=1`, etc.
- **Zustand** — small UI state where useState isn't enough
- **Axios** — HTTP client with response interceptor
- **Lucide React** — icons
- **date-fns** — date math

### Dev infra
- **Docker Compose** — 6 services (qdrant, ingest, mcp_server, api, ui (Streamlit), frontend)
- **Streamlit** — legacy UI on :8501, being phased out

---

## 8. Project structure

```
Bank_reconcillation_model/
├── api/                       # FastAPI backend
│   ├── main.py                # entry point, router registration
│   ├── deps.py                # DB session dependency
│   ├── schemas/models.py      # Pydantic request/response models
│   └── routers/               # one file per resource group
│       ├── bank_accounts.py
│       ├── invoices.py        # incl. /upload for PDFs
│       ├── bills.py           # incl. /upload for PDFs
│       ├── statement_lines.py # incl. /upload, /suggestions, /match-*, /transfer, /create-entry, /discuss, /unreconcile
│       ├── journal_entries.py
│       ├── contacts.py
│       ├── company.py         # company + services
│       ├── aliases.py
│       ├── audit.py
│       ├── dashboard.py
│       ├── runs.py            # legacy run-based reconciliation
│       ├── matches.py         # legacy match-record approval
│       ├── profile.py
│       └── health.py
│
├── frontend/                  # React + TypeScript
│   ├── src/
│   │   ├── App.tsx            # routing
│   │   ├── components/
│   │   │   ├── layout/        # Sidebar, AppShell
│   │   │   └── ui/            # button, badge, card, input, textarea, native-select, skeleton, separator
│   │   ├── pages/             # one folder per page
│   │   │   ├── Dashboard/
│   │   │   ├── Sales/
│   │   │   ├── Purchases/
│   │   │   ├── BankAccounts/
│   │   │   ├── Reconciliation/  # the headline screen
│   │   │   ├── ReviewQueue/
│   │   │   ├── Contacts/
│   │   │   ├── AuditTrail/
│   │   │   ├── Aliases/
│   │   │   └── Settings/
│   │   ├── types/index.ts     # shared TypeScript types
│   │   └── lib/
│   │       ├── api.ts         # axios instance pointing at /api/v1
│   │       └── utils.ts       # cn, formatCurrency, formatDate, formatPct
│   ├── vite.config.ts         # proxies /api/* → http://localhost:8000 (or http://api:8000 in Docker)
│   └── Dockerfile
│
├── engine/                    # matching engine + LLM + file store
│   ├── file_store.py          # content-addressed file storage
│   ├── bank_statement_parser.py
│   ├── llm/                   # Gemini + OpenRouter providers, fallback factory
│   └── vendor_matching/       # legacy fuzzy matcher
│
├── mcp_server/                # MCP tools (extraction, matching)
│   └── tools/invoice_extractor.py
│
├── memory/                    # database layer
│   ├── models.py              # all SQLModel tables
│   └── db.py                  # engine + init_db()
│
├── app/                       # legacy Streamlit UI (being cut)
├── knowledge/                 # RAG sources (rules, SOPs, alias lists)
├── knowledge_base/            # Qdrant ingest scripts
├── config/                    # settings, env loading
├── docker-compose.yml         # 6 services
└── data/bank_recon.db         # SQLite (or ./bank_recon.db locally)
```

---

## 9. API reference (the most important routes)

### Bank accounts
- `GET    /api/v1/bank-accounts/` — list with balance_difference + pending_count computed
- `POST   /api/v1/bank-accounts/` — create
- `PATCH  /api/v1/bank-accounts/{id}` — update
- `DELETE /api/v1/bank-accounts/{id}` — soft-delete (sets is_active=False)

### Invoices (Sales)
- `GET    /api/v1/invoices/?status=...` — list (status filter optional)
- `POST   /api/v1/invoices/` — create with line items
- `PATCH  /api/v1/invoices/{id}` — update header (incl. status)
- `DELETE /api/v1/invoices/{id}` — cascade-delete lines
- `POST   /api/v1/invoices/upload` — **PDF/image upload → LLM extract → draft invoice**

### Bills (Purchases) — mirror of invoices
- `GET / POST / PATCH / DELETE /api/v1/bills[/...]`
- `POST   /api/v1/bills/upload` — PDF/image upload with the purchase-side prompt

### Statement lines (the reconcile screen)
- `GET    /api/v1/statement-lines/?bank_account_id=X&status=pending`
- `POST   /api/v1/statement-lines/upload` (multipart) — **CSV/PDF statement import**
- `POST   /api/v1/statement-lines/import` (JSON) — structured bulk insert
- `GET    /api/v1/statement-lines/{id}/suggestions` — top 5 ranked matches with reason
- `POST   /api/v1/statement-lines/{id}/match-invoice` — reconcile against an invoice
- `POST   /api/v1/statement-lines/{id}/match-bill` — reconcile against a bill
- `POST   /api/v1/statement-lines/{id}/create-entry` — manual journal entry inline
- `POST   /api/v1/statement-lines/{id}/transfer` — cross-account transfer
- `POST   /api/v1/statement-lines/{id}/discuss` — attach a note
- `POST   /api/v1/statement-lines/{id}/unreconcile` — undo any of the above

### Supporting
- `/api/v1/journal-entries/` — CRUD for manual entries
- `/api/v1/contacts/` — full CRUD
- `/api/v1/company` + `/api/v1/services` — company profile + service catalogue
- `/api/v1/aliases/` — vendor name aliases
- `/api/v1/audit/` + `/api/v1/audit/export` — match history + CSV download
- `/api/v1/dashboard/stats` — overall metrics

Full interactive docs at **http://localhost:8000/api/docs**.

---

## 10. Running it locally

### Quick path — both servers, no Docker

```bash
# API
python -m uvicorn api.main:app --port 8000 --reload

# Frontend (separate terminal)
cd frontend
npm install   # first time only
npm run dev
```

Browse to **http://localhost:5173**. The Vite proxy forwards `/api/*` to the
FastAPI server.

### Full stack — Docker Compose

```bash
docker compose up -d                # qdrant, mcp_server, api, ui (Streamlit), frontend
docker compose run --rm ingest      # one-shot: populate Qdrant with knowledge base
docker compose run --rm tests       # one-shot: pytest suite
```

Services:
- `http://localhost:5173` — React UI (OOO)
- `http://localhost:8000/api/docs` — FastAPI Swagger UI
- `http://localhost:8501` — Streamlit (legacy, will be cut)
- `http://localhost:6333` — Qdrant dashboard

### Environment

Required for PDF extraction to work:
- `GEMINI_API_KEY` — primary LLM provider
- `OPENROUTER_API_KEY` — fallback for image-based extraction

Optional:
- `DATABASE_URL` — defaults to `sqlite:///./bank_recon.db`
- `UPLOAD_DIR` — where uploaded files land (default: `./uploads`)

---

## 11. Design decisions worth knowing

1. **Spent/Received split on StatementLine** — two columns instead of one
   signed amount. Matches Xero's UI; avoids sign-juggling in the frontend.

2. **`contact_name` snapshot on invoices/bills** — alongside `contact_id`. If
   a contact gets renamed or deleted, historical documents preserve the
   original name.

3. **Soft-delete on bank accounts** (`is_active=False`) — preserves
   historical reconciliation links. Hard delete would break audit trails.

4. **Optimistic UI updates** in the Review Queue + Reconcile screen — items
   disappear immediately on action, with TanStack Query rolling back on
   error. Snappy feel even when the LLM call is slow.

5. **No multi-currency conversion** in v1 — currency stored on every entity
   but no FX logic. Mixing currencies on one account is undefined behaviour.

6. **Float for money, not Decimal** — consistent with the existing codebase.
   Refactoring to Decimal is a contained migration we can do later if
   precision matters.

7. **LLM doesn't extract line items** — only the header total. Each PDF
   upload creates a single-line draft. User breaks it out manually before
   approving. Future work: multi-line extraction.

8. **The matching cascade has two tiers**:
   - **Lightweight ranker** (in `statement_lines.py`) — amount + date + name overlap. Fast, runs on every Reconcile render.
   - **Vector-based matcher** (in `engine/vendor_matching/`) — legacy, used by the older run-based engine. Will eventually be plugged into the suggestion endpoint for fuzzier matches.

---

## 12. Roadmap

### Done

- **Phase 1** — FastAPI scaffold, React/TypeScript shell, OOO branding, sidebar nav
- **Phase 2** — Review Queue (optimistic approve/reject + bulk + kbd shortcuts), Audit Trail (paginated + CSV export), Contacts CRUD
- **Phase 3** — Aliases, Settings (Profile/Company/Services tabs)
- **Phase 4a** — Data layer: BankAccount, Invoice, Bill, StatementLine, JournalEntry tables + APIs
- **Phase 4b** — Sales + Purchases UIs with status tabs, slide-in forms, line items, totals
- **Phase 4b.5** — PDF import wired into Sales & Purchases (LLM extraction)
- **Phase 4c** — Bank Accounts page with CSV/PDF statement upload, statement vs OOO cards
- **Phase 4d** — **Reconcile split-pane screen with Match/Create/Transfer/Discuss** ← headline

### Up next

- **Phase 4e** — Dashboard rebuild (bank account cards, invoices owed aging, bills due aging, tasks widget — Xero homepage parity)
- **Phase 5** — PDF view-back on bills (`source_file_path` is already stored)
- **Phase 6** — Multi-line LLM extraction (currently one line per PDF)
- **Phase 7** — Period locking (month-end close)
- **Phase 8** — Multi-currency conversion
- **Phase 9** — API sync (QuickBooks, Stripe pulls)
- **Phase 10** — Cut Streamlit entirely

### Open ideas

- **Drag-and-drop PDF import** anywhere on Sales / Purchases pages (not just the button)
- **"Suggested aliases"** — when bank descriptions don't match contact names, surface a one-click "Add alias" inline in the Reconcile screen
- **Bulk reconcile** — Xero has "OK all above 90% confidence" — we have the data, just need the button
- **Email forwarding for bills** — Xero lets you forward bills to a special email address. Inbound webhook + LLM extraction would be a clean addition.
- **Reconciliation report** PDF export — for end-of-period sign-off

---

## 13. Key invariants & guarantees

These hold true across the entire app:

1. **Balance invariant**: `statement_balance == ooo_balance` when every line on an account is reconciled.
2. **Audit invariant**: every reconcile action is reversible via `unreconcile`. No data is lost on undo.
3. **File invariant**: same PDF uploaded twice = same content-addressed hash = same on-disk file. Idempotent.
4. **Document invariant**: an invoice/bill's `status` is derived from `paid_amount` (`PAID` iff `paid_amount >= total`).
5. **Single-source invariant**: exactly one of `matched_invoice_id`, `matched_bill_id`, `matched_journal_id`, or `transfer_to_account_id` is set on a reconciled `StatementLine`. (Enforced at the app layer, not the DB layer.)

---

*Generated 2026-05-26. Reflects the state after Phase 4d.*
