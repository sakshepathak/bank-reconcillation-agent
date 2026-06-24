# Demo Points & Development Log

> **What this document is.** A running, plain-English log of everything we do, decide, or
> discover while getting this app ready — and keeping it healthy. It's written so a
> **non-technical reader can follow it**, but every entry also has an *"Under the hood"*
> note so that by the end you also understand the **technical** side. We update it at
> **every step**. Newest progress is added to the bottom of the **Development Log**.
>
> Audience: the person giving the demo (you), and anyone — technical or not — who needs
> to understand what this system is and what state it's in.

---

## 1. The app in one minute (plain English)

This is a **bank reconciliation tool** for small businesses and accountants. "Reconciliation"
just means: *matching the lines on your bank statement to the invoices and bills in your books,
so you know every payment is accounted for.*

The hard part is that bank statements are messy — a payment from "Brooklyn Coffee Roasters"
might show up as `BK COFFEE ROASTERS CAFE SUPPLIES 0099`. The app's job is to look at each
bank line and confidently say *"this is the payment for invoice INV-014 from Acme Ltd"* — and
to **ask a human** whenever it isn't sure.

It also:
- Keeps **separate books for each business** ("organisation") — fully isolated from each other.
- **Learns** as you use it (remembers messy vendor names, learns who tends to pay late).
- Has an **AI assistant** you can ask questions like *"how much does Acme still owe me?"*.
- Handles **over/prepayments** (credits) the way Xero does.

> **Under the hood.** FastAPI (Python) backend + React/TypeScript frontend. A *deterministic*
> matching engine (plain Python maths — not AI) does the matching; AI is used only for
> reading PDFs, the chat assistant, and plain-English narration. Data lives in a single
> **SQLite** file (`bank_recon.db`). See `README.md` and `docs/WALKTHROUGH.md` for the deep dive.

---

## 2. Current status (live snapshot — kept up to date)

| Thing | State |
|---|---|
| Database | **SQLite** (`bank_recon.db`) — Postgres migration parked |
| Backend | Runs on `http://localhost:8765` |
| Frontend | Runs on `http://localhost:5173` |
| Data | 12 orgs, 511 statement lines, 186 invoices, 130 bills, 273 contacts, 20 aliases, 1 credit |
| Tests | 169 passing, 1 failing (a *stale test*, not a real bug — see 2026-06-24 entries) |
| Best demo orgs | **"my zoo"** and **"Brooklyn Book store"** (richest match results) |

---

## 3. How to run it (quick reference for demo day)

Two pieces have to be running at once: the **backend** (the brain) and the **frontend** (the screen).
Open **two** terminals in the project folder.

**Terminal 1 — backend:**
```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8765
```
Wait for `Application startup complete`.

**Terminal 2 — frontend:**
```powershell
$env:VITE_API_TARGET = "http://localhost:8765"
npm --prefix frontend run dev
```
Then open **http://localhost:5173** and log in.

> **Under the hood.** The backend serves a REST API under `/api/v1/...`. The frontend dev
> server (Vite) *proxies* anything starting with `/api` to the backend, so the browser sees a
> single origin and there are no cross-origin (CORS) headaches. Port **8765** is used because
> Windows + Hyper-V reserves 8000/8001. `--reload` is omitted on purpose for a stable demo;
> if backend code changes, stop it (Ctrl+C) and start it again.

---

## 4. Development Log

Each entry: **What we did** (plain) → **Why it mattered** → **Under the hood** (technical).

### 2026-06-24 — Get the app running on SQLite after the reverted Postgres migration

**Context.** A previous attempt to migrate the database from SQLite to PostgreSQL didn't pan
out and was reverted from GitHub. Decision: **stay on SQLite** and make the current app
rock-solid for tomorrow's demo. The git code was reverted cleanly, but a couple of leftovers
remained that would have broken the app.

**1. Fixed the database setting (the real blocker).**
- *What:* The app was still pointed at the (non-working) Postgres database, not SQLite.
- *Why it mattered:* Without this, the app would fail to start or show no data — your invoices,
  bills and orgs all live in the SQLite file.
- *Under the hood:* Config lives in `.env` (which is **not** tracked by git, so the revert
  didn't touch it). Its `DATABASE_URL` line still read
  `postgresql://...@localhost:5432/bank_recon`, with the SQLite line commented out. We flipped
  it back to `DATABASE_URL=sqlite:///./bank_recon.db` and parked the Postgres line as a comment.

**2. Fixed the frontend→backend connection.**
- *What:* The screen wasn't wired to talk to the brain on the right port.
- *Why it mattered:* Every action in the UI (login, lists, reconcile) would have silently failed.
- *Under the hood:* `frontend/vite.config.ts` had its proxy target **hardcoded to port 8000**
  and ignored the `VITE_API_TARGET` variable the README tells you to set. But the backend can't
  use 8000 on this machine (Hyper-V reserves it) — it runs on **8765**. We changed the proxy to
  `process.env.VITE_API_TARGET || 'http://localhost:8765'`, so it now matches the backend and
  still respects the env var.

**3. Confirmed the data is all there.**
- *What:* Checked the SQLite file actually contains the books.
- *Result:* 12 organisations, 511 bank statement lines, 186 invoices, 130 bills, 273 contacts,
  20 learned vendor aliases, 1 credit note. Both demo-favourite orgs ("my zoo", "Brooklyn Book
  store") are present.

**4. Ran the test suite — 163 pass, 1 fails (and the failure is harmless).**
- *What:* One test in `tests/test_reconcile_money.py` fails.
- *Why it's not scary:* The actual money maths is correct. The test only fails because it
  checks the **shape of a response** that intentionally changed when the over/prepayment
  "credits" feature was added. The unreconcile endpoint now returns a friendly summary
  (`{line_id, reverted_label, removed_alias, message}`) instead of the raw line, and this one
  test wasn't updated to match.
- *Under the hood:* `POST /unreconcile` switched its `response_model` to `UnreconcileResult`
  (commit `857ab3a`). The test asserts `line["status"] == "pending"` on that summary, which has
  no `status` field → `KeyError`. The money assertions just above it (re-fetching the invoice and
  account) **pass**. Fix when convenient: re-fetch the line via `GET /statement-lines/{id}` for
  those last three assertions. *(Not yet applied — flagged for a decision.)*

**Result of this step:** ✅ Backend healthy on 8765 (SQLite), ✅ frontend on 5173, ✅ the
`/api` proxy reaches the backend (verified: `/api/v1/auth/me` returns 401 = reachable, just not
logged in yet). The app is ready to open at **http://localhost:5173**.

### 2026-06-24 — Two missing UI files (lost in the revert) — recreated; whole frontend now builds

**What we did (plain English).** The app crashed in the browser with *"Failed to resolve import
@/components/ConfirmProvider"*. Two small but important building blocks were **missing from the
project**: the pop-up that asks *"Are you sure?"* before deletes (**ConfirmProvider**) and the
little *"Saved / Error"* notifications that flash in the corner (**ToastProvider**). We rebuilt
both, plugged them back into the app, and then did a **full build of the entire frontend** to
prove nothing else is missing. It builds cleanly now.

**Why it mattered.** Four screens use the "Are you sure?" pop-up (Contacts, Sales, Purchases,
Reconcile) and two use the notifications (Reconcile, the Credits list). Without these files those
screens would crash mid-demo. The full build also guarantees there are **no other** hidden
missing files of this kind.

**Why it happened (the real lesson).** These two files were **created on disk but never saved
into version control** (`git add` was never run on them). They worked on the original machine
because the files were sitting in the folder — but git never knew about them. When the project
was cleaned up / reset during the Postgres rollback, anything git didn't know about was wiped,
while the files that *use* them (which were committed) stayed. Result: committed code importing
files that no longer exist.

**Under the hood.**
- Confirmed via `git log --all -- <file>` that **neither file was ever in any commit** (zero
  history) — so they couldn't be recovered from git; they had to be rebuilt from how they're used.
- Rebuilt `frontend/src/components/ConfirmProvider.tsx`: a React context + `useConfirm()` hook
  returning `confirm(opts) => Promise<boolean>`. Matched the exact options the four call sites
  pass (`title, description, confirmText, cancelText, destructive, rememberKey, persistChoice`),
  including the "Don't ask again" behaviour. Self-contained modal (no external dialog lib) so it
  can't break the build on a library API change.
- Rebuilt `frontend/src/components/ToastProvider.tsx`: context + `useToast()` returning
  `toast(message, variant?)`; auto-dismissing corner notifications, success + `'error'` variants.
- Wired both into `frontend/src/main.tsx` so every page can use them
  (`<ToastProvider><ConfirmProvider><App/></ConfirmProvider></ToastProvider>`).
- **Verification = the compiler, not guesswork:** `npm run build` (`tsc` type-check + Vite
  bundle) went from 2 "Cannot find module" errors → **0 errors, 1810 modules transformed,
  built in ~30s**. The first build run is what *found* the second missing file (ToastProvider) —
  the running dev server alone wouldn't have shown it until someone opened those screens.
- Live dev server re-checked: the previously-crashing modules now serve HTTP 200.

> **✅ Separate finding — lost work, now RESTORED.** The same `git reset --hard` had also
> discarded a **real, unrelated commit**: `9d7e6ff` *"Credits: fix manual allocation finding no
> matching bills/invoices"* (Jun 19) — **not** Postgres-related. It fixes the *Allocate credit*
> dialog showing no eligible bills/invoices, and adds `GET /credits/{id}/targets`,
> `tests/test_credit_targets.py`, and `scripts/backfill_credit_contacts.py`.
>
> *Restored* by a clean fast-forward (`git merge --ff-only 9d7e6ff` — its parent was exactly the
> current HEAD, so zero conflict risk). Re-verified after restoring: frontend build still green
> (1810 modules), backend suite **169 passing / 1 failing** (the same harmless stale test), and
> the live backend now serves `/credits/{id}/targets` (404 → 401, i.e. registered). The recreated
> providers + proxy fix + this log were then committed locally so nothing is left untracked to
> lose again.

---

## 5. Known things to watch (for the demo)

- **Two terminals must stay open** (backend + frontend). If the screen suddenly shows errors,
  check the backend terminal is still running.
- **Pick a data-rich org** for live matching: "my zoo" or "Brooklyn Book store" give the most
  convincing results. Other orgs may show few or no strong matches.
- **AI features need internet + API keys** (PDF extraction, the chat assistant, trace narration).
  The core matching/reconcile flow is fully offline and deterministic — it does **not** need any
  AI to work, so it's the safest thing to demo.
- The 1 failing test above is cosmetic; it does not affect anything you'll show.
