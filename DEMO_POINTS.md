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

### 2026-06-24 — UI polish: keep the cream, soften the blue, sharpen the nav

**What we did (plain English).** Made the app feel a little more polished *without* changing the
cream colour scheme you like. The blue was toned down (it read a touch loud against the cream), the
left-hand menu was reorganised into clear groups with **Reconcile pinned at the top showing a live
count** of items still to reconcile, and the typeface was switched to **Inter** (a cleaner, more
standard font for dense financial tools).

**Why it mattered.** A redesign brief proposed a full black/white "professional" repaint. After a
parallel feasibility review we judged that a half-finished repaint would look *worse* than the
current coherent cream theme — and you confirmed you want to keep the cream. So we kept your palette
and took only the safe, colour-neutral wins.

**Under the hood.**
- **Cream preserved:** reverted the earlier border / corner-radius / shadow experiments back to the
  warm "Parchment & Marine" values. Only the blue changed.
- **Blue softened:** `--primary` saturation 72% → 50% (same lightness, so white button text stays
  legible); sidebar gradient end `hsl(216 75% 34%)` → `hsl(216 50% 38%)`. One token recolours every
  blue element consistently.
- **Font:** Tailwind `sans` Outfit → Inter (+ the Google-Fonts import). Reversible in one line.
- **Sidebar** (`Sidebar.tsx`): nav regrouped into **Work / Reference / Admin**; Reconcile first with
  a pending badge that reuses the existing `['bank-accounts']` query (sum of `pending_count`) — zero
  backend change.
- **Verified:** `npm run build` green (1810 modules). **Deliberately NOT done** (higher-risk the
  night before a demo, parked for later): the full palette swap, removing red/green from money
  amounts, the Reconcile tab-relocation, and the Bank-Accounts table rebuild.

---

### 2026-06-24 — Reconcile page: compact (dense) view + fully-green confident matches

**What we did (plain English).** Made the Reconcile screen fit many more lines at once, like Xero.
Rows are **compact by default** with smaller text; a **toggle** (top-right of the list, "Expand" /
"Compact") flips back to the larger card view, and the app **remembers your choice**. And when a
suggested match is **very confident (over 90%)**, the **matched invoice/bill block** turns **green**
— your cue that it's safe to approve without reading carefully.

**Under the hood.**
- `ReconcileForAccount`: added a `compact` state (persisted in `localStorage['reconcile-compact']`,
  default on) + a toggle button beside the sort control; threaded `compact` into each `ReconcileRow`.
- `ReconcileRow`: density is class-conditional on `compact` (tab strip `py-0.5`, panes `py-1.5`,
  description `text-xs`, amount `text-sm` vs the roomy originals); inter-row gap tightens too.
- **Green confident match:** only the **matched invoice/bill block** turns green (`bg-emerald-50
  border-emerald-400`) at ≥90% — the first attempt greened the *whole card*, which looked too heavy,
  so it's confined to the block. Green stays the single accent; the cream theme is untouched.
- **OK button inlined + tighter:** OK moved *inside* the match block (stacked under the confidence
  score) instead of its own row; gaps/padding reduced — each card is shorter, less blank space.
- **Create tab condensed (Who/What/Why):** was three rows → now two — Who | What on row 1, then
  Why + VAT + Create together on row 2; inputs shrunk to `h-7`.
- **"How was this matched?" moved bottom-right:** it now shares one row with the "N more
  suggestions" link (suggestions left, trace-trigger right) instead of taking its own row. Its open
  state was lifted into `MatchTab`; the trace renders full-width below. Saves another row per card.
- Verified: `npm run build` green (1810 modules).

---

### 2026-06-25 — Sidebar: collapsible icon rail (hover-expand + pin), push layout

**What we did (plain English).** The left menu is now a slim **icon-only strip** by default, giving
the work area more width. **Hovering slides it open** to show labels, group headings, the org name
and the pending count; move away and it slides back. When it opens, the **page content slides right
to make room** (preferred over the menu floating on top). A small **pin button** locks it open for
anyone who dislikes pure hover. The scrollbar — previously a cream colour that looked off — is now a
soft on-brand blue.

**Under the hood.**
- The `<aside>` is a real flex item: `w-16 → hover:w-56`, so widening it **pushes** the content
  (`flex-1`) right; the width transition (200ms ease-out) animates the shift. Collapsed = 64px,
  expanded = 224px.
- **Pin:** a `pinned` state (persisted in `localStorage['sidebar-pinned']`) forces `w-56` and sets
  `data-pinned="true"` on the aside. All reveals key off `group-hover` **OR**
  `group-data-[pinned=true]`, so labels stay shown when pinned (not only on hover).
- Labels / group headers / user info share an `opacity-0 → opacity-100` reveal; `overflow-hidden`
  clips them when collapsed.
- Collapsed, the Reconcile icon carries a small **amber dot** when there's pending work; expanded,
  the full numbered badge shows instead.
- **Org switcher fix:** its name + the `<>` chevron are hidden when collapsed (they were overlapping
  the building icon) and reappear when expanded. Its dropdown is a Radix portal, so never clipped.
- **Scrollbars:** global thumb → `hsl(216 28% 80%)` (blue) + Firefox `scrollbar-color`; the blue
  sidebar gets a translucent-white thumb (`.sidebar-scroll`) so it stays visible on the gradient.
- Hover-expand is desktop-only (no hover on touch) — pin is the touch-friendly fallback.
- Verified: `npm run build` green (1810 modules).

---

### 2026-06-25 — Reconcile landing: a real overview instead of an empty screen

**What we did (plain English).** The Reconcile landing page (before you pick an account) looked
bare — a single small card stranded on a big empty canvas. It's now a proper **overview**: a row of
summary figures across the top and your bank accounts as full-width rows (balances + difference + a
Reconcile button). The screen now reads like real accounting software. *(A "Recent activity" side
panel was tried and then removed on 2026-06-25 — it looked visually off; the accounts list is
full-width instead.)*

**Under the hood.**
- New `ReconcileOverview` component (replaces the old account-picker grid) in `Reconciliation/index.tsx`.
- **Summary band:** Lines to reconcile · Out of balance · Bank accounts (+ reconciled count) · Last
  import — all derived from the existing `/bank-accounts` payload, so **no backend change**.
- **Account rows:** full-width `AccountRow` — Statement / OOO / Difference columns, a pending badge,
  and a prominent "Reconcile →" button. One account now fills the width instead of looking lost.
- **Recent activity:** reads the existing audit log (`GET /audit/?limit=8`); each row shows the
  action (colour-dotted), the target, description, amount and time. Tidy empty-state if there's none.
- Always shows the overview (no auto-skip), per the chosen option.
- Verified: `npm run build` green (1810 modules).

---

### 2026-06-25 — App-wide consistency pass (the 6 demo-critical pages)

**What we did (plain English).** The app looked inconsistent — different heading sizes on different
pages, uneven spacing, and single numbers floating in their own rounded cards ("children's book").
We defined **one house style** and applied it to the six demo pages so they share the same font
sizes, spacing, and a unified, grown-up look. (Audited every page first to standardise to what was
already most common — least churn.)

**The house style (cream theme untouched):**
- **Page title** — `text-2xl font-semibold tracking-tight` everywhere (was a mix of `text-xl bold`,
  `text-[22px]`, `text-2xl bold`).
- **Metrics** — one **StatStrip**: a single bordered bar with divided cells, every value at the same
  size (`text-lg`). Replaces the separate KPI cards.
- **Card padding** `p-4`, **page rhythm** `space-y-5`, one figure size.

**Under the hood.**
- New shared primitives so consistency is automatic + future-proof: `components/ui/page-header.tsx`
  (`PageHeader`) and `components/ui/stat-strip.tsx` (`StatStrip`).
- **Reconcile overview** & **Audit Trail:** KPI cards → `StatStrip`; header → `PageHeader`; deleted
  the old per-page `StatTile` / `KpiCard` components.
- **Sales / Purchases / Bank Accounts:** title → text-2xl semibold, rhythm → space-y-5; Bank
  Accounts card `p-5→p-4` and balance figures `text-xl→text-lg`.
- **Dashboard:** title → text-2xl, rhythm `space-y-8→space-y-5` (its metrics were already grouped at
  the right size, so minimal change).
- **Scope:** the 6 demo-critical pages only. The other 6 (Contacts, Settings, Review Queue, Aliases,
  Pipeline, Assistant) still use the old styling — bring them in line after the demo with the same
  two primitives.
- Verified: `npm run build` green (1812 modules).

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
