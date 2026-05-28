# Multi-Tenant Refactor — Design Document

**Status**: Draft for review
**Author**: Claude (with user)
**Date**: 2026-05-27
**Scope**: v1 = Stages 1–3 (foundation). v2 = Stages 4–5 (peakeaze + dashboard) covered briefly in §8 for forward-compat only.

---

## TL;DR

We're rebuilding the bank-recon app so it can hold multiple separate businesses ("organizations"), with a real login, where each business has its own contacts, invoices, bills, bank accounts, and aliases — completely walled off from each other. Later (v2), peakeaze will publish into the right business automatically. This doc covers v1: the foundation. **No code yet — this doc is for you to read and push back on.**

---

## 1. Goals and Non-Goals

### What v1 delivers
- Multiple businesses in one app, each with isolated data
- Login screen (email + password)
- "Add your business" onboarding flow (matches Xero's UX)
- Org switcher dropdown in the header
- Contacts auto-created when invoices are uploaded
- Aliases linked to specific contacts (the AMZN MKTP → Amazon problem, but per-org)
- The matching engine continues to work, now org-scoped

### Explicitly NOT in v1
- Peakeaze integration (v2)
- Xero or QuickBooks (never)
- Dashboard redesign (v2)
- Email verification, password reset, MFA
- Inviting other users to your org (deferred)
- Soft-delete / undo (deferred — see §9)
- Data export / GDPR tools (deferred)

### Non-functional goals
- **Security**: org A literally cannot see org B's data, even by guessing IDs
- **Safety**: every migration is reversible, the database file is backed up before each one
- **Incremental**: app remains usable after each stage; we don't ship a broken intermediate

---

## 2. The New Shape of the Data

Today, your app assumes one business. Most tables don't have any column saying "which business does this row belong to". We're adding that.

### Picture

```
Organization (1) ─── (N) UserOrgMembership (N) ─── (1) User
       │
       ├──── (N) Contact ──── (N) VendorAlias
       │
       ├──── (N) BankAccount ──── (N) StatementLine
       │
       ├──── (N) Invoice ──── (N) InvoiceLine
       │
       ├──── (N) Bill ──── (N) BillLine
       │
       └──── (N) JournalEntry, ServiceOffered, etc.

User ──── (1) Session (current_org_id, expires_at)
```

Every business-data row gets an `org_id` column. The session remembers which org you're "in".

### New tables

| Table | Why it exists | Key columns |
|---|---|---|
| `organization` | The Xero "business" concept. Replaces the single-row `company_profile`. | `id`, `name`, `slug`, `country`, `currency`, `industry`, `vat_registered`, `vat_number`, `tax_treatment`, `financial_year_end_day` (int 1–31), `financial_year_end_month` (int 1–12), `peakeaze_company_id` (nullable, for v2), `created_at` |
| `user` | The person logging in. | `id`, `email` (unique), `password_hash` (bcrypt), `name`, `is_active`, `created_at` |
| `user_org_membership` | Many-to-many: one user can belong to multiple orgs. | `id`, `user_id`, `org_id`, `role` (admin/member), `created_at` |
| `session` | Server-side session tracking. Token in cookie, validated server-side. | `token` (PK, random 32 bytes hex), `user_id`, `current_org_id`, `expires_at`, `created_at` |

### Modified existing tables

Every existing business-data table gets an `org_id INTEGER NOT NULL` column with a foreign key to `organization.id`. List:

- `contact`, `vendor_alias`, `bank_account`, `statement_line`, `invoice`, `invoice_line`, `bill`, `bill_line`, `journal_entry`, `service_offered`, `match_record`, `extracted_invoice`, `manual_ledger_entry`

(`invoice_line` and `bill_line` already inherit org via their parent — but I'll add `org_id` directly anyway, so security queries don't need joins.)

### Modified `vendor_alias`

Two changes:
1. Add `org_id` (FK to organization)
2. Add `contact_id` (FK to contact, **nullable** so existing aliases without a matched contact still work)

The `canonical_name` string stays as a denormalized cache (faster reads, no join needed for the hot path in the matching engine), but the source of truth for "what's the real vendor" becomes the linked Contact row.

### What goes away

- `company_profile` table — replaced by `organization`. Existing row migrated to a default org.
- `user_profile` table — replaced by `user`. Existing row (if any) becomes the first user.

### Critical decision: why server-side sessions, not JWT?

I chose server-side session tokens (a `session` table) over JWT for two reasons:
1. **Revocation is trivial** — log someone out, delete the row. JWT revocation requires a blocklist anyway, which defeats the point of JWT.
2. **You're running locally** — there's no scaling argument for stateless auth.

Tradeoff: every request does one tiny DB lookup. Negligible at your scale. Worth it for the simpler mental model.

---

## 3. Migration Plan

This is the highest-risk part of v1. SQLite has limited `ALTER TABLE` support — you can add columns but you can't easily rename or drop them, so I'll be careful about ordering.

### Migration approach

I'll use **plain SQL migration files** in `memory/migrations/`, numbered sequentially:
- `0001_create_organization_user_session.sql`
- `0002_add_org_id_to_business_tables.sql`
- `0003_backfill_default_org.sql`
- `0004_alias_contact_fk.sql`
- `0005_enforce_org_id_not_null.sql`

A tiny `migration_history` table tracks which migrations have been run. We don't need Alembic for this — it's overkill for a SQLite app. We can graduate to it later if we move to Postgres.

### Per-migration backup

Every migration script:
1. Copies `bank_recon.db` → `bank_recon.db.backup-{timestamp}-pre-{migration_name}`
2. Runs the SQL in a transaction
3. On failure: rolls back transaction, leaves backup in place, logs error
4. On success: keeps backup for 7 days, then auto-cleans

This means at any point you can `cp backup → bank_recon.db` and you're back to before the migration.

### The order matters

```
1. Create new tables (organization, user, user_org_membership, session, migration_history)
2. Insert "Migration Org" + first user (you, with a temporary password we'll prompt you to change)
3. Add nullable org_id column to all existing tables
4. Backfill: UPDATE every existing row SET org_id = (the migration org's id)
5. Add nullable contact_id to vendor_alias
6. Backfill: for each vendor_alias, try to find a Contact whose name matches canonical_name → set contact_id; else leave NULL
7. Make org_id NOT NULL (recreate table since SQLite can't alter NULL constraint in place)
8. Drop company_profile and user_profile tables (only after manual verification)
```

Steps 1–6 are safe and reversible. Steps 7–8 are the point of no return — they happen only after you confirm v1 works for the migrated data.

### What about your existing data?

I'll inspect your current `bank_recon.db` before writing the migration scripts. Any existing invoices, bills, contacts, aliases — all migrated into "Migration Org". You can rename it through the UI later. **Nothing is deleted.**

---

## 4. How Login Works

### User flow

1. User visits app → no session cookie → redirected to `/login`
2. Enters email + password → POST `/api/v1/auth/login`
3. Server bcrypt-verifies password → creates session row → sets httpOnly cookie `session_token`
4. User redirected to `/select-org` if they have 2+ orgs, or straight to `/dashboard` if 1
5. Org switcher in the header lets them swap orgs without logging out

### First-user bootstrap

- If the `user` table is empty, the `/register` endpoint is enabled.
- The first user to register becomes admin of a freshly created org (or joins "Migration Org" if data was migrated).
- Once one user exists, `/register` returns 403.
- An env var `ALLOW_REGISTRATION=true` can re-enable it (e.g., to add a second user later).

This is a deliberate trade: it's safe enough for a personal/local app, and we don't need an email-invite system in v1.

### Cookie details

- `httpOnly: true` — JavaScript can't read it (XSS protection)
- `sameSite: lax` — protects against most CSRF
- `secure: false` in dev, `true` in production
- 30-day expiry, renewed on each request (sliding window)

### Password hashing

Using `passlib[bcrypt]`. Adding to `requirements.txt`. Cost factor 12 (default, ~250ms per hash, fine for a local app).

### What I'm NOT building

- "Forgot password" page — for v1, if you forget your password, we reset it via a CLI script. Adding email-based reset means SMTP config, token generation, expiry, security review. Too much for v1.
- Email verification — same reason.
- MFA — same reason.

If this app ever leaves your machine, we add all three. Until then, KISS.

---

## 5. Making Sure Org A Can't See Org B's Data (Security)

**This is the most security-critical part of the whole refactor.** Get it wrong and someone (or a bug) could leak one org's books into another.

### The approach: explicit, audited scoping

Every API endpoint gets a new FastAPI dependency:

```python
def require_org(session=Depends(get_session_from_cookie)) -> int:
    return session.current_org_id
```

Every query that touches business data must include `WHERE org_id = current_org_id`. No exceptions.

### Why not "magic" (auto-injected filters)?

SQLAlchemy supports event listeners that auto-inject filters. I considered it. **I'm rejecting it** because:
1. It's invisible to the reader. Auditing the code becomes "trust the framework", which is hard to verify.
2. It can be bypassed accidentally (`session.execute(raw_sql)` doesn't go through it).
3. When it breaks, it breaks silently — exactly the worst failure mode for a security boundary.

Explicit beats implicit when security depends on it.

### The audit

I'll go through every existing endpoint, file by file, and list:
- What tables it reads/writes
- Where the `org_id` filter goes
- Whether the test confirms cross-org isolation

That list becomes part of the Stage 1 PR — you can audit it row by row.

### Test plan

For every resource (bill, invoice, contact, etc.) I'll add a test:
1. Create org A with user A, org B with user B
2. Create a bill in org A
3. Log in as user B → GET /api/v1/bills/{billA.id} → must return 404 (not 403 — we don't leak existence)
4. Same for LIST, PATCH, DELETE, and every other verb

This becomes a regression suite that runs in CI.

---

## 6. Contacts and Aliases Rework

### Auto-create contacts on upload

Today: `/bills/upload` extracts a supplier name string, stores it as `contact_name` on the Bill, leaves `contact_id` as NULL.

After v1: extract supplier → call `upsert_contact(org_id, name, …)` → that function either finds an existing Contact in this org (by normalized name match) or creates one → link the Bill's `contact_id` to that Contact.

This means your contacts list automatically grows as you upload invoices. No manual data entry.

### Dedup logic

For v1, dedup is by **normalized name match within org**:
- Lowercase, strip punctuation, collapse whitespace, remove common suffixes (Ltd, Limited, Inc, Co)
- Same logic peakeaze already uses (I copied the approach from their `_normalize_contact_name` in their `XeroPublishService`)
- If two rows would normalize to the same value, the older one wins (we link to it)

For v2 (peakeaze), dedup will use peakeaze's `external_id` first, then fall back to name match.

### Alias rework

VendorAlias goes from `(alias, canonical_name)` to `(alias, contact_id, canonical_name_cache)`.

- **`contact_id`**: FK to Contact. The new source of truth.
- **`canonical_name_cache`**: same as today's `canonical_name`. Kept so the matching engine's hot path doesn't need a join. Updated whenever the Contact's name changes.

The matching engine in [mcp_server/tools/alias.py](mcp_server/tools/alias.py) needs three changes:
1. Add `org_id` to `lookup_vendor(raw_description, org_id)` — scope the query
2. Return `contact_id` (not just the name string), so callers can link
3. Fuzzy fallback loads only the current org's aliases into memory (was: all aliases globally)

### Contact detail page (new UI)

- `/contacts/:id` — view contact info, see invoices/bills linked to them, manage aliases
- "Aliases" section: list of `(alias string, confidence)`, an "Add alias" inline form, delete button per row

This is the only place the user adds aliases. The matching engine still auto-learns aliases at confidence < 1.0 ("we think AMZN MKTP is Amazon"), and the user can confirm them.

---

## 7. Frontend Changes

The React app at [frontend/src/App.tsx](frontend/src/App.tsx) needs new routes and an auth layer.

### New routes

- `/login` — email + password
- `/register` — only renders if `/api/v1/auth/register-enabled` returns true
- `/onboarding` — "Add your business" form, only after first registration with no orgs
- `/select-org` — shown after login if user has 2+ orgs
- `/contacts/:id` — contact detail with alias management

### Modified

- `AppShell` — wraps with `<RequireAuth>` that redirects to /login if no session
- Sidebar header — adds org switcher dropdown showing current org + list of user's orgs
- All API calls — include credentials (`fetch(url, { credentials: 'include' })` so cookies are sent)
- All API call hooks — handle 401 (redirect to login) and 403 (show "no access to this org" message)

### Auth state

A small `AuthContext` at the top of the tree. Holds: `{ user, currentOrg, orgs, isLoading }`. Refreshed by calling `/api/v1/auth/me` on app mount. Never put the session token in JS-accessible storage — it lives in the httpOnly cookie.

---

## 8. Forward-Compat for v2 (Peakeaze + Dashboard)

These are NOT being built in v1, but the v1 schema reserves space for them so we don't migrate twice.

### Reserved columns

| Table | Column | Why |
|---|---|---|
| `organization` | `peakeaze_company_id` | Pre-registered mapping. Stays NULL until you opt in to peakeaze. |
| `contact` | `external_id`, `external_source` | When peakeaze creates a contact, we remember its peakeaze ID. |
| `bill` | `external_id`, `external_source` | Same — for idempotency on re-publish. |
| `invoice` | `external_id`, `external_source` | Same. |
| `bill_line` / `invoice_line` | `tax_amount`, `tax_type`, `chart_of_account_code` | Per-line VAT detail peakeaze sends. v1 doesn't populate these from manual uploads, but the columns exist. |

These are nullable. Manual upload flow ignores them. Peakeaze integration in v2 will populate them.

### What v2 will add (not v1)

- `POST /api/v1/ingest/document` endpoint with HMAC verification
- `bank_recon_publish_history` table in peakeaze's codebase
- Peakeaze backend changes (BankReconPublishService, UseCase, Controller)
- Peakeaze frontend button
- Dashboard redesign (Xero card grid)

---

## 9. Open Questions (please answer these before I start Stage 1)

These are decisions I'd rather have your input on than guess.

1. **Session lifetime**: I proposed 30 days with sliding renewal. Too long? Too short?
2. **Password rules**: I'm planning min 8 characters, no other rules. Want more (uppercase, number, symbol)?
3. **Email format**: just check for `@`, or full RFC 5321 regex? (I'd lean toward `@` only — strict regex bounces real emails.)
4. **Org deletion**: do you want a "delete this organization" feature in v1, or never? If yes, hard-delete (gone forever) or soft-delete (archive + 30-day undo)?
5. **Showing record existence cross-org**: if user A tries to access org B's bill, do we return 404 ("not found") or 403 ("forbidden")? 404 doesn't leak that the record exists. I'd recommend 404.
6. **The "Migration Org" name**: I'll create an org during migration to hold your existing data. What should I name it by default? Something you'll recognize like "Default" or "My Business" — you can rename later.
7. **Should I add tests during Stage 1, or treat tests as a separate stage?** Memory says "no tests yet" — adding tests during Stage 1 doubles the time but means the security guarantees are actually verified. I strongly recommend tests in Stage 1 for the org-isolation checks at minimum.

---

## 10. What I'm Going To NOT Do (to keep scope honest)

A short list of tempting things I'll deliberately avoid in v1, even though they'd be nice:

- **Renaming columns or refactoring "while we're in there"** — only adding what's needed, leaving the rest alone. Less risk.
- **Improving the dashboard** — even if it's "useless" right now. That's v2.
- **Switching to Postgres** — SQLite stays. Multi-tenant works fine on SQLite for one user.
- **Adding role permissions beyond admin/member** — every member is effectively an admin in v1. Granular permissions can wait.
- **Replacing the LLM extractor** — manual upload still uses Gemini/OpenRouter. Peakeaze replaces it later.

---

## 11. Implementation Order (after you approve this doc)

For each stage, app remains usable at the end. We don't ship broken intermediate states.

1. **Add new tables** (organization, user, user_org_membership, session) — old code still works, just doesn't use them yet
2. **Add the migration script** that creates Migration Org and the first user
3. **Wire login + cookies + session middleware** — but don't enforce auth yet
4. **Add `org_id` to all business tables, backfill** — old code still works
5. **Update every API endpoint** to scope by `org_id` from session — this is where the security model goes live
6. **Add login page + onboarding + org switcher** in frontend
7. **Refactor VendorAlias → FK to Contact, update alias.py matching engine**
8. **Add contact detail page with alias UI in frontend**
9. **Upload flow auto-creates contacts**
10. **Drop `company_profile` and `user_profile` tables** (final cleanup, point of no return)

Each step is its own PR-sized chunk. You review each one before I move to the next.

---

## Next steps

1. You read this doc and push back on anything that feels wrong, even if you can't explain why
2. Answer the 7 questions in §9
3. I revise the doc based on your feedback
4. Only then do I touch code, starting with step 1 of the implementation order

**This doc is the contract.** If we agree on this, the code that follows is predictable.
