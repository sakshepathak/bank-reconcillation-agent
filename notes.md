# Project Notes

---

## Overpayment / Prepayment

### How It Works

When we reconcile, we're just matching a bank line to a document (a bill or an invoice). Usually the amounts agree and it's a clean match. But what if there is a payment that is actually associated with the payment falls under the category where its not identified — sometimes they don't identify. There are exactly three interesting cases:

| You paid… | …compared to the bill | What it's called | What the app does |
|---|---|---|---|
| Less than the bill | bill not fully covered | Partial / split | Bill stays open for the rest |
| More than the bill | extra money left over | Overpayment | Bill marked Paid, the extra becomes a credit |
| Before any bill exists | no document yet | Prepayment | The whole amount becomes a credit |

A credit is simply money sitting in your favour against that supplier (or customer), waiting to be used on a future bill. Think of it as store credit.

### The Bank Line Lifecycle

1. **Bank Line Appears:** Money comes in or goes out.
2. **Check for Bill/Invoice:**
   - No Document Yet → Book a Prepayment. Hold the whole amount as a credit.
   - Yes, Document Exists → Compare the amounts.
3. **Evaluate Amount:**
   - Equal → Normal match. Bill becomes Paid.
   - Paid Less → Partial payment. Bill stays open.
   - Paid More → Book an Overpayment. Bill becomes Paid, extra becomes credit.
4. **Outcome:** A credit now sits against that contact to be applied later to a future bill.

### Case 1: Overpayment (You paid more than the bill)

**Story:** A bill from Correct Limited is for £1,200, but the bank shows you actually paid them £2,000. The bill should be fully paid, and the extra £800 is money they now owe you back.

**Step-by-Step:**
1. You match the £2,000 bank line to the £1,200 bill.
2. The screen shows you're "out by £800" and halts saving.
3. You select "book the remaining £800 as an overpayment."
4. The app executes atomically:
   - Marks the £1,200 bill as Paid.
   - Creates an £800 credit against Correct Limited.
   - Records the full £2,000 leaving the bank.

### Case 2: Prepayment (You paid before any bill existed)

**Story:** You sent a supplier £800 in advance. There's no bill in the system yet. The whole £800 must be parked as a credit until the bill arrives.

**Step-by-Step:**
1. The bank line has no bill to match against.
2. You choose "book as prepayment" and pick the supplier.
3. The app creates an £800 credit for that supplier and records £800 leaving the bank.
4. When the real bill turns up, you apply the credit to it.

> **Core Difference:** Both overpayments and prepayments result in a credit. The only difference is whether a bill existed in the system at the exact moment the money went out.

### Case 3: Using the credit later (Apply to a future bill)

**Story:** Correct Limited has an £800 credit. A new bill comes in for £1,200. You put the credit towards it, so you only owe £400.

**Step-by-Step:**
1. Open the new bill and choose Apply credit.
2. The app runs system checks: same supplier, same currency, and sufficient remaining credit balance.
3. It reduces the bill by the credit used (noted as "Less Overpayment £800"), leaving an Amount Due of £400.
4. No new money moves — the bill is settled using existing credit. Credits can be split across several bills and used bit by bit.

### Case 4: A bill gets cancelled after credit was applied

**Story:** You used £500 of a credit on a bill, then that bill is deleted or voided by mistake. The £500 automatically and atomically reverts back to the available credit pool, making the credit available balance return to its original state.

### Case 5: Undoing a credit (And when you can't)

You can cleanly undo a booked credit only if nothing has been built on top of it yet.

- **Untouched Credit:** Clean undo. Credit is removed, the original bill reopens, and the bank balance restores.
- **Partly/Fully Used Credit:** Blocked. You must remove the specific allocations from the bills first, then undo the core credit booking.

### System Guarantees & Promises

| Situation | What's guaranteed |
|---|---|
| Splitting a credit | The pieces always add back to exactly the original — to the penny. |
| Over-spending | You can never apply more credit than remains, or more than a bill owes. |
| Different currencies | A GBP credit cannot be applied to a USD bill; the system blocks it with a clear validation message. |
| Two clicks at once | The same money cannot be double-spent; concurrency checks guarantee consistent outcomes. |
| Separate businesses | One organization can never see or touch another's credits. Isolation is strictly enforced. |
| Balanced books | If any action breaks accounting rules, it fails completely rather than saving a broken state. |
| Audit trail | Every booking, allocation, and reversal records the timestamp and identity of the actor. |

### App Navigation & Visibility

- **Reconcile Screen:** Use the Credit tab to book an overpayment or prepayment directly from a bank line.
- **Purchases / Sales Dashboards:** An "Overpayments & Prepayments" tab lists every outstanding credit and lets you manually allocate them.
- **Contact Page:** A dedicated "Credits on account" card displays what each individual supplier or customer holds.

---

### How to handle credits?

> "Credits are modeled separately from standard Bill and Invoice documents because they are contra-liability/contra-asset balances rather than standard ledger items."

- **What they are:** A credit is money waiting to be used against a future bill or invoice, functioning like "store credit" for a specific supplier or customer.
- **Why they are separate:** Credits don't follow the same accounting rules as standard bills or invoices, so they are stored in their own separate table rather than being mixed with regular documents.
- **Allocation and Restoration logic:** When credit is applied, the bank balance doesn't change. What changes is the ledger — the invoice's paid amount goes up, the credit's allocated amount goes up. It's purely a bookkeeping adjustment, not a cash transaction.
- **AllocateDialog** fetches valid targets using `/credits/{id}/targets`: The backend applies all the rules — same currency, same contact, same direction, sufficient outstanding balance.

**Exceptions:**

- **Automatic Restoration on Delete/Void:** If you void an invoice with an applied credit, the system atomically reverses the allocation, restores the credit's balance, and cleans up the audit link, preventing any broken states.
- **Allocation Guard:** Cannot unreconcile if credit has been allocated. The user must first remove the credit allocation from the invoice, then unreconcile the bank line. When unreconciled the credit gets deleted.
- The credit UI currently supports one overpayment target per booking. Multiple documents in one payment requires the API directly or sequential allocation. It's a UI gap, not a data model limitation.

---

## Self Learning

### Implementation of Self Learning

*To remove repeated human judgment on the same boring problem.*

Self-learning solves this by turning each human decision into a persistent signal that makes the engine smarter — so humans gradually stop being interrupted by things they've already taught the system.

**Two distinct problems it's solving:**

1. **Vendor Alias:** On the next reconciliation, `get_suggestions` resolves that bank description to `alias-exact` — the highest-confidence name method. That vendor is now "known," which matters for the auto-reconcile gate. The alias is atomic with the match and reversible — unreconciling removes it.

2. **Late payment trend:** A vendor who always pays 45 days late isn't a bad match — they're just that vendor. Without memory, the date scorer keeps penalizing them even though it's their known pattern.

**More memory dimensions to build:**

- **Amount profile:** Is their amount fixed (£2,000 rent), range-bound (utility £80–120), or free? Plus typical value + variance. Show on contact page.
- **Self-Learning Digest:** "This week the system learned 7 new vendor aliases. 43 transactions were auto-matched using learned aliases (up from 31 last week). Your top late-payer profile: Penguin Random House, avg 52 days after invoice date." Makes the invisible learning visible, builds user trust.
- **Settlement structure:** Full vs part payments — do they (or we) habitually settle one document in installments?
- **Direction of payment:** Typically money-in (customer) or money-out (vendor), or both?
- **Recurring payment trend:** Should be detected and auto-reconciled. Use reconciled history to find recurring patterns, improve the score.

### Org-level memory (policy / set rules)

- **Default terms & grace** (net-30, 14-day grace): currently constants in `engine/reconcile_rules.py`.
- **Risk appetite** — how aggressive auto-reconcile is allowed to be.
- **Declared recurring obligations prior:** rent/payroll/loans/subscriptions the user knows about.
- **Company profile / prose facts:** what the business does. (Qdrant KB + `remember_fact`)

### More Ideas

- If recurring payments are defined, should the system suggest a match without the presence of a valid doc, and can that be a basis of auto-reconciliation?
- **Active memory management layer:** Add a "Last Verified" timestamp to every learned alias. If an alias hasn't been verified by a human or a secondary high-confidence signal in over 6 months, degrade its trust score. Instead of an automatic 100% pass, force the system to drop to Step 3 (Spelling) or Step 4 (Meaning) to re-validate.
- **Normalization Over-Stripping:** Sometimes what looks like noise is the only differentiating factor. If you strip "Store #402" and "Store #819" use a Named Entity Recognition (NER) prompt to extract the core vendor name while retaining the original string as metadata. The spelling algorithms can compare the extracted names, but the metadata remains intact as a tie-breaker.
- **Monobit/Bitap Algorithm:** If a string matches a pattern up to a certain number of allowed mistakes (substitutions, insertions, deletions).

---

## The Recurrence / Expectation Engine

*The new capability.*

**Pipeline:** observation log → detection → expectations → matching → chatbot surface

**IMP Q:** How similar do reconciliation stats need to be to make them recurring?
**IMP Q:** Recurring vs. frequent

### (a) Detection

From the observation log per vendor: compute gaps between consecutive payment dates. If they cluster around ~30/7/91/365 days with low variance and ≥3 occurrences → propose a MATCH. Amount stability = coefficient of variation (low → fixed, high → range). Anchor = modal day-of-month with ±tolerance for weekends/bank holidays. Output is a candidate expectation, surfaced for confirmation — never silently created.

### (b) Prediction / Matching

When an unmatched bank line has no document, check it against active expectations: does it fall in the date window, is the amount within tolerance, does direction match? If yes → propose reconciling against the expectation instead of a document.

**Three outcomes when recurrence is detected:**

1. **Match** — existing invoice/bill (what you have today)
2. **Code / Create** — generate a bill or invoice for category/expectation; posts to the GL account (or generates the missing bill/invoice on the fly). This is exactly Xero's "Match vs Create transaction" split.
3. **Absence detection** (the inverse, and a sleeper hit) — because you now know what *should* arrive, you can flag what didn't: *"Rent usually clears by the 5th — it's the 7th and I don't see it."* Document matching alone can never do this; only memory can. Implemented as a scheduled scan over expectations where `now > window_end` and nothing matched.

---

## Structural Enhancements: Decision-Making Algorithms

Right now, a manual **Linear Weighted Combination** produces the composite score (`0.50 + 0.20 + 0.30`). To move away from manually guessing those weights, introduce a lightweight ML classifier.

### Logistic Regression / Random Forest (For Stage 6 Verdicts)

- **How it works:** Instead of hardcoding that Amount is worth 50% and Date is 20%, train a small, explainable ML model on historical matching data. The model learns the optimal weights automatically based on past human-in-the-loop approvals.
- **Why use it:** Maintains full explainability (extract exact feature importance weights to show on UI) but adapts dynamically to real-world data patterns without manual tweaking.

---

## Reconciliation Logic

### How reconciliation works

*"What does this money movement correspond to in our books?"*

The engine never decides alone — it ranks candidates and explains itself, then a human picks the action. Every action keeps one invariant true: the bank account's `ooo_balance` moves to meet `statement_balance`, so when every line is reconciled the two are equal.

### Features

- Upload a bank statement as CSV or PDF (PDF is LLM-extracted into rows).
- Auto-handle ambiguous dates (DD/MM vs MM/DD) using the org's country.
- Import the ledger (invoices + bills) and track each one's outstanding balance.
- Maintain the statement ↔ OOO balance invariant so a fully reconciled account ties out to zero.
- Route by direction — money in → open invoices, money out → open bills.
- Score every candidate on a composite (amount 0.5 + date 0.2 + name 0.3) and rank them.
- Amount tolerance: exact / ≈1% / within 5% / differs.
- Smart date logic — rewards normal payment delay, red-flags paid before invoice, assumes net-30 + grace.
- Label each match with a confidence band (Strong / Likely / Possible / Weak).
- Split / bulk payment for one transfer settling several of one vendor's docs (subset-sum; cross-vendor mixes rejected).
- Bank fees / no document → create a journal entry.
- Transfers between own accounts.
- Overpayment / prepayment → book a credit note.
- Ambiguity detection — flags two near-identical candidates so neither is silently chosen.
- Discuss tab — take notes, leave it pending.
- Plain-English narration of any trace (LLM narrates; the match stays deterministic).

---

## Best Use of Memory

- The metric memory should optimise is **% of reconciliations automated**. Every time a human makes the same judgment twice, that's a learning failure.
- Setting rules must be encouraged — the system doesn't need to learn after the 5th rent payment that it's periodic.
- Memory must be **explainable, attributable, and reversible** or it destroys trust. If we are auto-reconciling without a document it must prove itself. Make all this visible on the Contact page and Org details as company insight.
- Should we remove so many pages and just have the chatbot in the center orchestrating the memory? We will create a less obvious place to store vendor alias, memory, details and everything.

**Chatbot already exists**, works by calling tools, small functions to register with it (~6 already built: `financial_summary`, `find_contact`, `add_vendor_alias`, etc.). The LLM decides when to call them; the code runs the actual SQL.

So instead of five screens, we add a handful of tools that read and write the memory tables, and the user just talks:

| User says | Tool that fires | What happens underneath |
|---|---|---|
| "what do you know about Penguin?" | `get_vendor_profile` | reads their timing, typical amount, aliases, recurrence → answers in plain English |
| "rent went up to £2,200" | `update_expectation` | changes the stored amount on the rent rule |
| "stop expecting the Adobe payment, we cancelled it" | `update_expectation` | deactivates that recurring expectation |
| "approve everything you're 100% sure about" | bulk match (auto_eligible ones) | reconciles all the certain matches at once |

---

## To Do

### P0 — Foundational (unblocks honest tuning of everything else)

- [ ] Build an **evaluation harness** — labelled fixture (bank line → correct doc, incl. hard negatives) + a test that prints precision/recall per band & method. `[Medium]`

### P1 — High impact, mostly cheap

- [ ] **Penalize currency mismatch** in the amount score — today £100 vs $100 reads "exact"; currency only gates auto, not the visible score. `[Easy]`
- [ ] **Make import idempotent** — content-hash each line; skip dupes on re-upload (currently re-importing double-counts). `[Easy]`
- [ ] **Stop embedding noise inflating the name cap** — use lexical/alias score for `cap_by_name`, or require lexical corroboration. `[Easy]`
- [ ] **Wire up auto-reconcile** — "apply all auto-eligible" behind a setting (the gate is already computed, just unused). `[Medium]`

### P2 — Real, but deferrable

- [ ] **Calibrate the confidence bands** — set Strong/Likely where measured precision actually crosses 90/75% (needs P0 first). `[Easy]`
- [ ] **Add a partial/installment payment tier** — line < outstanding + vendor match → "partial," leave remainder open. `[Medium]`
- [ ] **Per-org payment terms + decay on learned timing** — replace global net-30/14 grace; let stale late-payer behavior fade. `[Medium]`
- [ ] **Pre-filter candidates before the name match** — amount-bucket/index + cache canonical forms; kills the O(lines×docs) scan. `[Medium]`
- [ ] **Validate PDF parse against a control total** — reconcile extracted rows to the closing balance so a hallucinated figure can't slip in. `[Easy]`
- [ ] **Concurrency-safe `paid_amount`** — optimistic lock / conditional update (latent now on SQLite, breaks on Postgres/multi-user). `[Medium]`
- [ ] **Switch money to integer pence / Decimal** — important for a finance product, but a heavy cross-cutting refactor; mitigated by rounding today. `[Hard]`

### P3 — Low / later

- [ ] **Batch + background the Pipeline Run** — currently one full scan per line, synchronous. `[Medium]`
- [ ] **Bound the subset-sum search** — cap input size / use bounded DP (fine at demo scale). `[Easy]`
- [ ] **Word-boundary alias matching** — stop short aliases mis-firing inside unrelated strings. `[Easy]`

---

## Presentation Notes

### Opening — the Pipeline Run page

- "lets me do is upload a bank statement along with the invoices and bills"
- "this uses the exact same matching logic that the live Reconcile screen uses. It's not a separate demo version."

### The Run Summary

"It processed X lines. Of those, Y were strong auto-matches — the engine is confident, no human needed. Z need review — it found candidates but wasn't confident enough to commit on its own. And 0 had no candidate — meaning every single line found at least something to match against. And the auto-match rate is X%."

"And down here this little breakdown is nice. Which tier did the work. It's telling us how those matches were found: 11 by similar meaning (the AI), 5 by a known alias, 7 by similar spelling, and 1 by exact same name. So at a glance I can see which part of the engine is pulling the weight."

*(Pause.)* "All the amounts, dates, and text scoring are done by plain, predictable code. The AI only helps on the meaning comparison. I'll show you exactly what that means now."

### Every Entry, Step by Step

"Every transaction gets shown with the full six-stage cascade and the score at each stage."

### Walking the Six Steps

**Step 1 — Normalise.** Before comparing, it cleans up both names. Bank statements are messy — full of extra words, transaction IDs, things like 'LLC'. So 'Brooklyn Realty LLC Rent January' gets stripped down to just meaningful content.

**Step 2 — Alias lookup.** This checks: have we matched this exact vendor before? If yes, it's an instant hit — no calculation needed for name. Also we add to the alias memory with user consent so we know it's reliable to make the name match max.

**Step 3 — Spelling similarity.** When there's no learned alias, it compares how similar the two names look. It blends four different algorithms, because each catches a different kind of difference:
- **Jaro-Winkler** (35%): rewards names that start the same way — good for typos.
- **Token-set** (25%): compares words ignoring order and duplicates.
- **Token-sort**: sorts words alphabetically first, so "Daily Bean" and "Bean Daily" come out equal.
- **Partial**: finds a short name sitting inside a longer one.

**Step 4 — Meaning check.** This is the AI part. It only fires when spelling alone wasn't already a lock. It turns each name into a vector that represents its meaning, and compares them (cosine similarity). This is what catches matches that spelling completely misses — like if the bank says "cold brew and co" but the invoice says "coffee" — different letters, same meaning. Uses a local embedding model (e.g. BGE-small).

**Step 5 — Best signal wins.** Takes the strongest one — the highest of alias, spelling, or meaning. If any one reliable method is very confident, that's enough.

**Step 6 — Composite score.** The final number the app actually acts on. Combines three things:
- Amount match: worth up to 0.50
- Date match: up to 0.20
- Name: weighted at 0.30

**Step 7 — Verdict.** Bands the score. 90%+ = auto-approve quality. Anything lower waits for a human.
