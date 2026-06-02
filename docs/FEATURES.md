# Feature List — Multi-Tenant Bank Reconciliation

A complete inventory of what the module does, grouped by area. Items marked
*(planned)* are designed but not yet built. For how these work, see the
[Module Guide](WALKTHROUGH.md); for a setup reference, see the [README](../README.md).

---

## 1. Accounts & Authentication
- Email + password registration and login
- Secure password storage (bcrypt) and server-side sessions (httpOnly cookie, sliding renewal)
- Logout
- Registration can be toggled on/off; the first user can be bootstrapped via a script

## 2. Organisations (Multi-tenancy)
- One user can belong to multiple organisations
- Organisation switcher in the sidebar
- Add a new organisation (name, country, currency, VAT, financial year end)
- **Delete an organisation** — full data wipe across all 14 tables + knowledge-base vectors, with a JSON backup export first and a typed-name confirmation
- "No organisation selected" picker to switch into another org or create one
- Strict per-organisation data isolation (every read/write scoped by `org_id`)

## 3. Dashboard
- Summary statistics for the active organisation

## 4. Bank Accounts & Statement Import
- Create, list, reset, and delete bank accounts (unlimited per organisation)
- Import bank statements via **CSV** or **PDF** (PDFs parsed by AI extraction)
- Tracks statement balance vs reconciled balance and the difference

## 5. Sales (Invoices)
- Create, edit, and delete invoices with line items, VAT, and statuses (Draft, Awaiting Payment, Paid, Voided)
- **Import invoices from CSV** — automatic column detection, ISO-date-safe, duplicate-safe re-import
- **Extract invoices from a PDF** via AI
- Status tabs and outstanding totals

## 6. Purchases (Bills)
- Create, edit, and delete bills with line items and statuses
- **Import bills from CSV** (same safe importer)
- **Extract bills from a PDF** via AI

## 7. Contacts & Vendor Aliases
- Auto-created, de-duplicated contacts (normalised by name within the organisation)
- Contact detail page with linked invoices, bills, and aliases
- Renaming a contact propagates to its aliases
- **Vendor aliases** — learned mappings from raw bank text to a canonical contact, improving matching over time

## 8. Reconciliation
- Per-line match **suggestions** with confidence scores and plain-language reasons
- Four reconcile actions per statement line:
  - **Match** — link to an invoice or bill (updates the paid amount and bank balance)
  - **Create** — make a ledger/journal entry (for items with no invoice, such as a fee)
  - **Transfer** — mark as a transfer between two bank accounts
  - **Discuss** — attach a note and leave the line pending
- **Bulk match** — one bank line against multiple invoices/bills, with a live "amount needed" progress bar
- Matching pipeline: normalisation → learned aliases → spelling similarity → AI embedding (meaning) → amount/date checks → subset-sum solver for split/instalment payments → optional language-model check as a last resort
- Live progress indicator while matches are computed; the embedding model is pre-warmed at startup

## 9. Match Explainability (transparency / demo)
- **Terminal trace tool** (`scripts/explain_match.py`) — step-by-step scoring of any real entry
- **"How was this matched?" panel** in the app — the same trace, inline
- `GET /statement-lines/{id}/explain` endpoint powering both

## 10. Review Queue / Exceptions
- All non-exact matches wait for human approval
- Approve or reject individual matches
- Bulk-approve queue for high-confidence pending matches
- Duplicate detection

## 11. Audit Trail
- Every match decision recorded immutably (level, confidence, amount/date difference, reasoning, approval status)

## 12. Settings
- **Profile** — the user's name, role, and email
- **Organisation** — a single editable form: name, country, currency, "what the company does" description, contact details, VAT/tax (and the Danger Zone delete)
- **Services & Products** — a per-organisation catalogue used for VAT categorisation

## 13. Knowledge Base & Assistant *(planned)*
- A per-company knowledge base fed by the organisation profile and business data
- An assistant that answers questions, mixing semantic search (RAG) for descriptions with exact database queries for numbers
- Teach-it-facts-through-chat write-back
- *Prerequisite: scope the knowledge base by `org_id`*

## 14. Platform / Under the hood
- Automatic schema migrations on startup, plus a tracked numbered-migration runner
- Local, free AI embeddings (no per-call cost)
- AI providers with automatic fallback (Gemini → OpenRouter) for PDF extraction
