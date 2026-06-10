# Brooklyn Bookstore — demo reconciliation dataset (January 2026)

A complete, hand-crafted test dataset for an independent bookshop with a small
café. It deliberately exercises **every level** of the matching cascade plus the
messy real-world cases: split payments, bulk payments made in instalments,
duplicate bank postings, partial payments, near-amount (fee) differences, vendor
name variants, and lines/documents that should stay unmatched.

The numbers below are **validated** against the real engine
([`mcp_server/tools/matching.py`](../../mcp_server/tools/matching.py)) — see
[Self-check](#self-check).

---

## Files

| File | Convention | Used by |
|------|-----------|---------|
| `bank_statement.csv` | amounts as **positive magnitudes** | the **engine cascade** (`run_matching_cascade`) — matches the shipped `sample_data/*.csv` convention |
| `company_ledger.csv` | amounts as **positive magnitudes** | the **engine cascade** — combined ledger (invoices + bills in one file) |
| `bank_statement_signed.csv` | **signed** (`+` credit / `−` debit) | the **app** bank upload (`POST /statement-lines/upload`) — signs route credits→invoices, debits→bills |
| `invoices.csv` | positive | the **app** (`POST /invoices/upload-csv`) — sales / money-in |
| `bills.csv` | positive | the **app** (`POST /bills/upload-csv`) — purchases / money-out |
| `_validate.py` | — | optional script that re-runs the cascade and prints the result |

> **Why two bank files?** The engine cascade matches a *single same-sign ledger*
> by magnitude (its Level-4 subset-sum solver would otherwise net positive
> invoices against negative bills and produce spurious matches). The app instead
> needs the *sign* to decide whether a line is money-in (match invoices) or
> money-out (match bills). Both files describe the identical 24 transactions.

---

## The business

**Brooklyn Bookstore** — indie bookshop + café in Brooklyn, NY. Currency: USD.

* **Money in (invoices):** wholesale book orders to schools, libraries and cafés;
  event book sales; card-settlement payouts (Stripe online, Square in-store).
* **Money out (bills):** stock from publishers/distributors (Penguin Random
  House, HarperCollins, Macmillan, Ingram, Simon & Schuster), rent, utilities,
  café supplies, software, postage, bank fees.

---

## Scenarios & expected reconciliation

24 bank lines (`B001`–`B024`) against 20 ledger documents (10 invoices + 10 bills).

### ✅ Exact match — Level 1 (date == date, amount == amount)
| Bank | Amount | Ledger | Note |
|------|-------:|--------|------|
| B001 | 4,800.00 | BILL-2026-006 | Brooklyn Realty — January rent |
| B002 | 1,240.00 | INV-2026-001 | PS 58 Elementary School order |
| B003 | 2,150.00 | BILL-2026-001 | Penguin Random House stock |
| B010 | 530.00 | INV-2026-007 | Brooklyn Brewery event sales |
| B015 | 79.00 | BILL-2026-008 | Shopify subscription |
| B016 | 145.00 | BILL-2026-009 | Brooklyn Coffee Roasters |

### 🔶 Fuzzy match — Level 2/3 (amount within tolerance + date window / vendor-name variant)
| Bank | Amount | Ledger | Why it's fuzzy |
|------|-------:|--------|----------------|
| B004 | 865.50 | INV-2026-002 | "GREENPOINT BRANCH LIBRARY ACH" vs "Greenpoint Library", 2 days late |
| B006 | 1,432.75 | BILL-2026-002 | "INGRAM CONTENT GRP NASHVILLE" vs "Ingram Content Group", 2 days late |
| B007 | 312.40 | BILL-2026-007 | "CON EDISON ELECTRIC" vs "Con Edison", 2 days late |
| B022 | 474.50 | INV-2026-010 | Fort Greene Café paid **$474.50** on a **$475.00** invoice — $0.50 processor fee → Level-3 description-fuzzy, flagged for review |

### 🟦 Split payment — Level 4 one-to-many (one bank line = sum of several documents)
| Bank | Amount | Ledger group | |
|------|-------:|--------------|--|
| B008 | 750.00 | INV-2026-003 (320) + INV-2026-004 (180) + INV-2026-005 (250) | Park Slope Café clears 3 invoices in one transfer |
| B012 | 2,200.00 | BILL-2026-003 (980) + BILL-2026-004 (1,220) | One wire pays 2 HarperCollins bills |

### 🟪 Bulk payment in parts — Level 5 many-to-one (several bank lines = one document)
| Bank lines | Each | Document | Total |
|-----------|-----:|----------|------:|
| B005 + B013 + B018 | 1,500.00 | INV-2026-006 (Brooklyn Public Schools) | 4,500.00 in 3 instalments |
| B009 + B020 | 1,350.00 | BILL-2026-005 (Macmillan Publishers) | 2,700.00 in 2 instalments |

### ♻️ Duplicate bank postings → flagged
| Bank | Amount | Note |
|------|-------:|------|
| B011 | 530.00 | exact duplicate of **B010** — the bank posted it twice. B010 matches INV-2026-007; B011 has no remaining document → **unmatched / review** |
| B017 | 145.00 | exact duplicate of **B016** — matches nothing left → **unmatched / review** |

### ⚠️ Unmatched on purpose (no counterpart → human action)
| Bank | Amount | Reason / expected action |
|------|-------:|--------------------------|
| B014 | 1,875.32 | Stripe online-sales settlement — no invoice → **Create** a journal entry |
| B023 | 642.18 | Square in-store POS deposit — no invoice → **Create** |
| B021 | 88.50 | USPS postage — no bill → **Create** |
| B024 | 35.00 | Monthly account fee — no bill → **Create** |
| B019 | 900.00 | **Partial payment**: Williamsburg HS pays half of the $1,800 INV-2026-009. No exact/subset match → review (engine leaves unmatched; in the app, do a partial match so $900 stays outstanding) |

### 📄 Open documents with no January payment (unmatched ledger)
* **INV-2026-008** — Cobble Hill Café, $410.00 (still awaiting payment)
* **BILL-2026-010** — Simon & Schuster, $760.00 (not yet paid)
* **INV-2026-009** — Williamsburg HS, $1,800.00 (only the $900 partial arrived)

---

## Validated engine output

Running the cascade over `bank_statement.csv` + `company_ledger.csv`:

```
24 bank rows, 20 ledger rows.
Matched: 6 exact, 4 fuzzy, 2 one-to-many (split), 5 lines many-to-one (bulk, 2 groups).
Unmatched bank: 7  (2 duplicates + Stripe + Square + USPS + fee + partial)
Unmatched ledger: 3 (Cobble Hill, Simon & Schuster, Williamsburg HS remainder)
Match rate: 70.8%
```

> The deterministic levels (1–5) are stable. The optional Level-6b LLM verifier
> may *speculatively* tag some of the 7 unmatched lines as `possible` (always
> flagged for review) when LLM credentials are configured — it never changes the
> deterministic matches above.

---

## How to load

**Engine / agent cascade** (Python):
```python
import pandas as pd
from mcp_server.tools.matching import run_matching_cascade, normalise_df

bank   = normalise_df(pd.read_csv("sample_data/brooklyn_bookstore/bank_statement.csv"),   is_ledger=False)
ledger = normalise_df(pd.read_csv("sample_data/brooklyn_bookstore/company_ledger.csv"),   is_ledger=True)
report = run_matching_cascade(bank, ledger, run_id="brooklyn-demo")
print(report.summary_text())
```

**App (FastAPI + React):**
1. `POST /invoices/upload-csv` → `invoices.csv`
2. `POST /bills/upload-csv` → `bills.csv`
3. `POST /statement-lines/upload` (form: `bank_account_id`, `file`) → `bank_statement_signed.csv`
4. Open the **Reconcile** screen and review the suggested matches / bulk groups.

---

## Self-check

```bash
py -3.13 sample_data/brooklyn_bookstore/_validate.py
```
Prints the per-line status so you can confirm the dataset still behaves as
documented after any engine change.
