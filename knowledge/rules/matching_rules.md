# Reconciliation Matching Rules

How the engine decides whether a bank statement line matches an open invoice or
bill. This is the single source of truth — the code in `engine/reconcile_rules.py`,
`engine/vendor_matching/`, and the `/suggestions` endpoint all implement what's
described here.

## How a match is scored

Each candidate (an open invoice for money in, an open bill for money out) gets a
single **composite score from 0 to 1**, made of three parts:

| Part | Max | How it's earned |
|------|-----|-----------------|
| **Amount** | 0.50 | exact → 0.50 · within 1% → 0.40 · within 5% → 0.25 · otherwise 0 |
| **Date** | 0.20 | see "the fair payment window" below |
| **Name** | 0.30 | the vendor-name score (0–1) × 0.30, from the name matcher below |

The three add up (capped at 1.0) and the candidates are ranked by it.

### The name matcher (the 0–1 vendor-name score)

The bank description rarely equals the vendor name on the invoice, so names are
matched in layers, best signal wins:

1. **Learned alias** — an exact/substring hit in the org's `VendorAlias` table
   (mappings the user has trained). Scores 1.0, method `alias-exact`.
2. **Same name** — after normalising both (strip processor prefixes, bank noise,
   transaction IDs), the canonical forms are identical. Scores ~1.0, method
   `canonical-exact`.
3. **Similar name** — a weighted blend of fuzzy string metrics (Jaro-Winkler,
   token-set, token-sort, partial). Method `fuzzy`.
4. **Meaning** — only if spelling is inconclusive, a semantic embedding cosine
   catches matches spelling misses ("DAILYBEAN" ↔ "The Daily Bean"). Method
   `fuzzy+embed`.

### The fair payment window (the date part)

A bill is meant to be paid any time between its **invoice date** and its **due
date**, so that whole span earns **full date credit** — a normal payment delay is
never penalised.

- Paid any time from the invoice date through the due date (+ ~2 weeks grace) → full credit.
  - A coffee/restaurant bill paid the same day → full credit.
  - A subscription/supplier bill paid weeks later, within terms → full credit.
- When a bill has no due date, a sensible default term is assumed (net-30 + grace).
- The score only drops *outside* that window, and the two sides differ:
  - **Paid before the invoice existed** → near-zero credit. This is a red flag that
    it's the *wrong* invoice, and it caps the composite below auto-approve quality.
  - **Paid long after the due date** → a mild reduction only (late payments are real),
    never a hard zero until the gap is implausibly large (> ~1 year).

## Name similarity caps the confidence label

A matching amount and date are **not enough on their own** — the vendor name has
to agree too. The name score sets the highest label a match can reach:

| Vendor names | Highest label allowed |
|--------------|-----------------------|
| clearly match (score ≥ 0.80) | **Strong** |
| partly match (0.50–0.80) | **Likely** |
| barely match (< 0.50) | a **low match** (Possible / Weak) |

So an exact-amount, on-time payment against the *wrong* vendor can't read as
"Likely" or "Strong" — it stays a low match. If a low-match candidate is in fact
the correct one, it still appears under **"show more suggestions"**; nothing is lost.

Confidence labels by score: **Strong ≥ 0.90 · Likely ≥ 0.75 · Possible ≥ 0.65 · Weak < 0.65.**

## Ambiguity

If two open documents score near-identically near the top (same amount + same
vendor), both are flagged **ambiguous**. The UI warns, and neither qualifies for
hands-off auto-reconcile — we never silently pick one of a tie.

## Hands-off auto-reconcile (strict)

Most matches are suggested for a human to approve with one click. A 1-to-1 match
is flagged **auto-eligible** (safe to apply with no human) only when *every* one
of these holds:

- **Amount is exact** (the 0.50 tier — not "≈", not "within 5%").
- **Vendor is known, not guessed** — a learned alias or an exact name
  (`alias-exact` / `canonical-exact`), never a fuzzy/meaning guess.
- **Date is within the fair payment window** (full date credit).
- **Same currency** as the bank line.
- **It is the only candidate** that meets the above (not ambiguous).
- The line is a single document (not a split) and still pending.

Everything else goes to a human. A human approving a *similar-name* match (with
"remember this vendor") promotes it to a learned alias — so the next identical
line clears the "vendor known" bar and can flow hands-free. Humans teach the
identities once; the engine reconciles them from then on.

## Splits (one bank line, several documents)

A single bank transfer can settle several documents at once (e.g. one payment for
three invoices). A split must be **one vendor** settling several of *their own*
documents whose outstanding amounts sum to the bank amount — never a mix of
vendors whose amounts merely happen to add up. Splits always require human review.

## Unmatched

A line is left unmatched when nothing clears the bar. Common reasons: the entry was
never recorded in the ledger, a bank fee, a duplicate or voided payment, or timing
that lands in a different period. All unmatched lines require human review.

## Roadmap (not yet active)

- **Learned per-vendor payment timing** — if you regularly pay a vendor late, the
  engine will learn that vendor's typical window so their habitual late payments
  stop being marked down. (Date-side twin of learned aliases.)
- **Reference-number lock** — when an invoice/bill number appears in the bank text,
  treat it as a certain vendor identity.
