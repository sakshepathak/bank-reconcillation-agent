# Module Guide — Multi-Tenant Bank Reconciliation

A plain-language guide to what this module does, how each part works, and the
decisions behind the design. For setup and run instructions, see the
[README](../README.md). For a live demo of the matching engine, see
[DEMO_CHEATSHEET.md](DEMO_CHEATSHEET.md).

---

## Overview

This module turns the bank-reconciliation app into a **multi-tenant** product —
similar in spirit to Xero. Each organisation gets its own fully isolated set of
books: invoices, bills, contacts, bank accounts, statement lines, and
reconciliations.

A single login can hold several organisations (for example, your own books and a
client's books). The session always tracks which organisation is active through a
single field, `current_org_id`. This field is the backbone of the system:

- Every API read and write is filtered by `current_org_id`.
- The frontend clears its cached data whenever the active organisation changes, so
  one organisation's data can never appear under another's.

Everything below either strengthens this isolation, defines how data flows through
the system, or describes where the module is heading next.

---

## 1. Multi-tenant organisations (the foundation)

**What it does.** Keeps every organisation's data completely separate, while
letting one user belong to many organisations.

**How it works.**
- Every business table carries an `org_id` column.
- A FastAPI dependency, `get_current_org_id`, reads the active organisation from
  the session and every endpoint filters by it.
- Switching organisations updates `current_org_id` and the frontend drops all
  cached data, so the next screen loads fresh for the new organisation.

**Why it matters.** In a multi-tenant product, isolation *is* the product. A single
missed filter would leak one customer's data to another, so the `org_id` rule is
applied everywhere without exception.

---

## 2. Importing invoices and bills

Invoices and bills can be added manually, imported from a **CSV**, or extracted
from a **PDF**. Two behaviours in the CSV importer are worth documenting.

### Date handling — ISO dates are stored exactly as written

The importer recognises dates already in ISO format (`YYYY-MM-DD`) and stores them
**verbatim**. It does not pass them through any locale-based interpreter that might
read `2026-05-01` as the 5th of January instead of the 1st of May.

- If a date matches `YYYY-MM-DD`, it is stored as-is.
- Only non-ISO formats (e.g. `DD/MM/YYYY`) fall through to flexible parsing, with
  day-first detection.

This guarantees an unambiguous ISO date can never be misread, which removes a whole
class of "the day and month are swapped" errors.

### Duplicate-safe re-imports

Re-importing the same CSV does **not** create duplicates. Before inserting, the
importer looks up an existing invoice or bill with the same number within the
organisation:

- If found, it **updates the existing record** in place.
- If not, it creates a new one.

The single imported line item is refreshed as well, so amounts always stay
consistent. *Verified by importing the same file twice against a copy of the live
database and confirming the record count and all dates were unchanged.*

---

## 3. Document extraction (in-house)

Extraction of invoice and bill data from PDFs is handled **inside this codebase**
rather than by an external service. This keeps the pipeline under our control, adds
no third-party dependency to maintain, and keeps customer data within our own
boundary — which becomes important for the knowledge base described in section 6.

---

## 4. Deleting an organisation

**What it does.** Permanently removes an entire organisation and everything in it,
then returns the app to a clean "no organisation selected" state so the user can
pick another organisation or start fresh.

Because this is irreversible and touches many tables, it is built carefully.

**Backup before delete.** A separate endpoint, `GET /orgs/{id}/export`, returns the
organisation's full data as JSON. The UI offers this download before the delete
proceeds, so there is always a recovery file.

**Deliberate confirmation.** The delete dialog requires the user to **type the
organisation's name** before the button activates. This prevents an accidental
click from destroying data.

**The wipe, in the right order.** Business tables reference each other through
foreign keys (for example, statement lines reference invoices, bills, and bank
accounts). Records must therefore be deleted **children first**. The delete
endpoint walks an explicit, ordered list of the 14 organisation-scoped tables
inside a single transaction, so the operation is all-or-nothing. It then:

1. Removes the organisation's knowledge-base vectors (best-effort — a failure here
   never blocks the database wipe).
2. Removes every user's membership of the organisation.
3. Clears `current_org_id` on any session pointing at it.
4. Deletes the organisation record itself.

**The reset.** Clearing the session's active organisation drops the user onto the
onboarding screen, which doubles as an organisation picker: if other organisations
exist, it lists them to switch into; if none remain, it shows the create form.

*Verified by deleting a real organisation (88 records) against a copy of the live
database and confirming all of its records were gone, its memberships removed, the
session reset — and every other organisation left completely untouched.*

---

## 5. Organisation settings

The **Settings → Organisation** tab is the single place to edit an organisation's
details: name, country, currency, the plain-language description of what the
business does, contact details, and VAT/tax settings.

Saving writes to two places at once (`PATCH /orgs/current` for identity fields and
`PUT /company` for the richer profile) and keeps overlapping fields in sync, so the
user sees one clean form regardless of the underlying storage.

All organisation data — including the services-and-products catalogue — is scoped
by `org_id`, so each organisation only ever sees its own profile and catalogue.

---

## 6. Knowledge base and assistant (planned)

The plain-language business description from Settings, together with the data the
system already holds (contacts, invoices, bills, reconciliation history), is
intended to feed a per-company **knowledge base**. On top of it will sit an
**assistant** that can answer questions such as "how much have I paid this supplier
this quarter?" or "which invoices are unpaid?", and accept new facts taught through
chat.

A key design decision shapes this work: **the data has two shapes and needs two
tools.**

- **Unstructured information** (the company description, notes, policies) is a
  semantic-search problem, handled by retrieval over embeddings (RAG).
- **Structured, numeric information** (totals, balances, lists) needs exact
  answers, handled by direct database queries — not embeddings, which can produce
  inaccurate numbers.

So the assistant will choose the right tool per question rather than running every
question through retrieval. This mirrors a principle used throughout the codebase:
**use a language model only where the data cannot answer for itself.**

**Implementation notes.**
- The repository already includes a hybrid retrieval pipeline (`knowledge_base/`)
  using a local vector store, so the assistant extends proven components rather
  than adding a new external service.
- **Open requirement:** the knowledge base is currently global. Before the
  assistant ships, it must be scoped by `org_id` on every query, so one
  organisation can never retrieve another's information. The organisation-delete
  flow already removes vectors by `org_id`, so it is ready for this change.

---

## Design principles

A few principles run through the whole module:

- **Isolation is the product.** Every feature is scoped to one organisation, and
  isolation is verified, not assumed.
- **Remove ambiguity rather than guess.** ISO dates are stored exactly; the delete
  order is explicit; destructive actions are confirmed and backed up.
- **Use a model only when the data can't answer for itself.** Exact figures come
  from the database; semantic recall comes from retrieval; deterministic logic does
  the reconciliation matching, with a model only as a last resort.
- **Prove changes against real data.** Imports, deletes, and migrations are tested
  against copies of the live database before being trusted.
