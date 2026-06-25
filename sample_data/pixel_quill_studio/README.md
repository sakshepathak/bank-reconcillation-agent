# Pixel & Quill Studio — two-month demo dataset (March + April 2026)

A realistic, hand-traced dataset for a UK design studio. It exercises **every**
reconcile theme — exact/good, close (≈ and within-5%), similar names, different
names with identical amount+date, split/bulk, overpayment, prepayment, missing
document, recurring payments, and self-learning (an alias learned in **March**
auto-matches in **April**).

Every bank line was traced through the live engine (`get_suggestions` +
`engine/reconcile_rules.py`), so the outcomes below are what the app will
actually produce — not aspirations.

---

## 1. The company (use this to create the org + seed the chatbot)

| Field | Value |
|-------|-------|
| **Name** | Pixel & Quill Studio Ltd |
| **Country** | United Kingdom (GB) |
| **Base currency** | GBP |
| **Industry** | Creative / branding & web design agency |
| **About** | Bristol-based studio. Revenue = monthly **retainers** (Northwind, Meridian) + one-off **branding/website projects** (Summit, Harbourline, Castlebridge, Zephyr, Acme). Costs = studio **rent**, **SaaS** (Slack, Microsoft 365, Adobe, Figma), **freelance contractors**, and **professional services** (accountant). Terms: invoices net-30, supplier bills net-15. |

> **Why GBP-only:** the score ignores currency today (a known gap), so a
> single-currency org keeps the demo honest and clean.

---

## 2. How to load (order matters)

1. Create the org with the details above.
2. Add a bank account (GBP), e.g. *"Studio Current Account"*.
3. **Upload the ledger** (once):
   - `Invoices → Import CSV` → `invoices.csv`
   - `Bills → Import CSV` → `bills.csv`
4. **Reconcile March:** upload `bank_statement_march.csv` → go to **Reconcile** → work the 20 lines (see §3).
5. **Reconcile April:** upload `bank_statement_april.csv` → work the 14 lines (see §4). Watch the aliases you saved in March now auto-match.

All 29 ledger docs are loaded up front. April-dated docs simply sit open during
March; the **asymmetric date rule red-flags "paid-before-issue,"** so they never
mis-match a March payment.

---

## 3. March — expected results (20 lines)

| Date | Bank line | Amount | Expected outcome | Theme demonstrated |
|------|-----------|-------:|------------------|--------------------|
| 03-01 | BRISTOL WORKSPACE LTD | −3,200 | **BILL-2001** · Strong · auto-eligible | recurring rent · exact |
| 03-02 | PAYPAL *SLACK | −180 | **BILL-2002** (Slack) · canonical-exact · auto | processor-prefix stripping (`PAYPAL *`) |
| 03-02 | ADOBE *MONTHLY | −79 | **BILL-2003** · canonical-exact · auto | canonicalisation (`ADOBE *`) |
| 03-03 | MSFT *MICROSOFT 365 | −220 | **BILL-2004** · canonical-exact · auto | canonicalisation (`MSFT →` Microsoft) |
| 03-05 | NORTHWIND TRADING LTD | +2,500 | **INV-1001** · Strong · auto | good/exact match (retainer) |
| 03-06 | FIGMA.COM SUBSCRIPTION | −150 | **BILL-2006** (£144) · "amount off by 6.00" | **close match** (within 5%) |
| 03-07 | PENHALIGON ACCOUNTANCY | −450 | **BILL-2005** · *fuzzy* → tick **Remember** | **similar name** + **learn alias** |
| 03-09 | MERIDIAN WHOLESALE FOODS | +1,840 | **INV-1002** · *fuzzy* → tick **Remember** | **similar name** + **learn alias** |
| 03-10 | TOM HARGREAVES | −1,350 | **BILL-2007** · Strong | good match (contractor) |
| 03-12 | SUMMIT OUTDOORS CO | +750 | **split → INV-1003+1004+1005** (320+180+250) | **split / bulk payment** (1→many) |
| 03-14 | HARBOURLINE MEDIA LTD | +1,200 | **INV-1006** (Acme's INV-1007 is also £1,200 same dates → shown low) | **different name, same amount+date** (name-gating) |
| 03-18 | STRIPE*QUAY ST BISTRO | +497.50 | **INV-1008** (£500) · "≈ amount (Δ2.50)" | **close match** (≈) + Stripe-prefix strip |
| 03-20 | ZEPHYR TECH SOLUTIONS | +3,250 | **INV-1009** (£3,000) in full + **£250 credit** | **overpayment** |
| 03-22 | DELTA HOLDINGS | +600 | **INV-1010 / INV-1011** both £600 → **flagged ambiguous**; pick one | **ambiguity** (identical docs) |
| 03-25 | STRIPE PAYOUT ONLINE STORE | +1,875.32 | no invoice → **Create** journal entry | **missing invoice** |
| 03-26 | BANK SERVICE CHARGE | −15 | no bill → **Create** | **missing bill** (bank fee) |
| 03-28 | BRIGHTWATER LABS DEPOSIT | +5,000 | new client, no invoice → **Prepayment** | **prepayment** |
| 03-28 | HMRC VAT Q4 2025 | −1,250 | no bill → **Create** | missing bill (tax) |
| 03-30 | CASTLEBRIDGE UNIVERSITY | +4,500 | **INV-1012** (£9,000) — match leaves £4,500 open | **partial payment** (instalment 1) |
| 03-31 | TRANSFER TO SAVINGS ACCOUNT | −5,000 | **Transfer** | transfer between own accounts |

**Left open on purpose after March:** Acme INV-1007 (£1,200), Delta INV-1011
(£600, the unpicked twin), Castlebridge INV-1012 (£4,500 remaining).

---

## 4. April — expected results (14 lines)

| Date | Bank line | Amount | Expected outcome | Theme demonstrated |
|------|-----------|-------:|------------------|--------------------|
| 04-01 | BRISTOL WORKSPACE LTD | −3,200 | **BILL-2010** · auto | recurring |
| 04-02 | PAYPAL *SLACK | −180 | **BILL-2011** (Slack) · auto | recurring |
| 04-02 | ADOBE *MONTHLY | −79 | **BILL-2012** · auto | recurring |
| 04-03 | MSFT *MICROSOFT 365 | −220 | **BILL-2013** · auto | recurring |
| 04-05 | NORTHWIND TRADING LTD | +2,500 | **INV-1014** · auto | recurring retainer |
| 04-07 | PENHALIGON ACCOUNTANCY | −450 | **BILL-2014** · **alias-exact** · auto | 🎯 **self-learning payoff** (learned in March) |
| 04-09 | MERIDIAN WHOLESALE FOODS | +1,840 | **INV-1013** · **alias-exact** · auto | 🎯 **self-learning payoff** |
| 04-10 | CASTLEBRIDGE UNIVERSITY | +4,500 | **INV-1012** now £4,500 out → **exact** · auto | **instalment 2 settles** the invoice |
| 04-12 | INKWELL PRINT CO | −2,200 | **split → BILL-2008+2009** (980+1,220) | **split / bulk** (money-out) |
| 04-15 | HARBOURLINE MEDIA LTD | +1,450 | **INV-1015** · Strong | good match |
| 04-18 | DELTA HOLDINGS | +600 | **INV-1011** — only one £600 left → **exact, no longer ambiguous** | ambiguity resolved next month |
| 04-20 | ADOBE *MONTHLY | −79 | no open Adobe bill → **unmatched / review** | **duplicate posting** |
| 04-22 | STRIPE PAYOUT ONLINE STORE | +2,140.18 | no invoice → **Create** | missing invoice (recurring payout) |
| 04-28 | BANK SERVICE CHARGE | −15 | no bill → **Create** | missing bill |

---

## 5. Theme coverage (your checklist)

- ✅ **Split / bulk payment** — Summit (1→3 invoices, Mar), Inkwell (1→2 bills, Apr)
- ✅ **Similar names** — *Meridian Wholesale Foods* → Meridian Foods Ltd; *Penhaligon Accountancy* → Penhaligon & Co Accountants
- ✅ **Different names, everything else same** — Harbourline vs Acme, both £1,200 on the same dates → name-gating picks the right one
- ✅ **Close match** — Figma (within 5%, "off by 6.00") and Quay St Bistro (≈, Stripe £2.50 fee)
- ✅ **Good / exact match** — Northwind, rent, SaaS, Tom Hargreaves
- ✅ **Missing invoice/bill** — Stripe online payout, bank charge, HMRC VAT
- ✅ **Overpayment** — Zephyr pays £3,250 on a £3,000 invoice (+£250 credit)
- ✅ **Prepayment** — Brightwater Labs £5,000 deposit, no invoice yet
- ✅ **Recurring / repeat payments** — rent, 3× SaaS, retainer, accountant — all in both months
- 🎁 **Bonus:** ambiguity, transfer, partial/instalment across months, duplicate posting, canonicalisation, auto-eligibility, **self-learning March→April**

---

## 6. Chatbot demo (org-scoped assistant)

**Seed a few facts first** (type in chat — the assistant saves them via `remember_fact`):
- "Pixel & Quill Studio is a branding and web design agency in Bristol, UK."
- "Our accountant is Penhaligon & Co; their fee is £450 a month by direct debit."
- "Office rent is £3,200 a month to Bristol Workspace Ltd."
- "Northwind Trading and Meridian Foods are our two monthly retainer clients."

**Then ask (these hit the SQL + KB + memory tools):**
- "What's my total outstanding from customers right now?" *(SQL)*
- "Which bills are overdue?" *(SQL)*
- "How much have we paid Bristol Workspace this year?" *(SQL)*
- "Who is Penhaligon & Co and what do we pay them?" *(KB fact)*
- "What does Pixel & Quill do?" *(KB profile)*
- "Brightwater Labs and Brightwater Laboratories are the same client" *(writes a vendor alias)*

---

## 7. Two honest talking points (for the manager)

- **Self-learning is real and visible:** Meridian and Penhaligon need a *fuzzy*
  match + "Remember" in March, then **auto-match in April** with zero effort.
  That's the headline.
- **Partial payments are the known gap:** the first Castlebridge instalment
  (03-30) scores *low* because £4,500 ≠ the £9,000 outstanding — you match it
  manually and it stays open. The second instalment (04-10) then matches exactly.
  This is on the backlog (a "partial settlement" amount tier) — call it out
  rather than hide it.
