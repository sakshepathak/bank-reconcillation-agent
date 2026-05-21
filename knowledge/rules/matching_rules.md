# Reconciliation Matching Rules

## Rule 1: Exact Match (Highest Confidence)

An exact match occurs when BOTH of the following conditions are true:
- The transaction date on the bank statement equals the date on the ledger entry.
- The transaction amount on the bank statement equals the amount on the ledger entry (rounded to 2 decimal places).

Exact matches require NO human review and can be auto-approved.

## Rule 2: Fuzzy Amount Match

A fuzzy amount match applies when:
- The absolute difference between the bank amount and the ledger amount is less than or equal to the configured tolerance (default: $0.05).
- The dates are within a 3-day window of each other.
- The description similarity score is above 60%.

Reason for tolerance: Foreign exchange transactions may have rounding differences of a few cents due to exchange rate conversion. Bank posting dates may also differ from the ledger booking date by 1-3 days.

These matches REQUIRE human review before finalisation.

## Rule 3: Description Fuzzy Match

A description fuzzy match applies when:
- The token set ratio between the bank description and the ledger description is >= 80%.
- The amount is within 10% relative tolerance.

This handles cases like:
- "AMZN MKTPL *1A2B3" matches "Amazon Marketplace"
- "SQ *COFFEE" matches "Square Coffee Shop"
- "PAYPAL *SOFTWARESUB" matches "PayPal Software Subscription"

These matches ALWAYS require human review.

## Rule 4: One-to-Many Match

A one-to-many match applies when a single bank transaction equals the SUM of multiple ledger entries.

Common cases:
- A single bank withdrawal covers multiple vendor invoices.
- Bank consolidates daily card transactions into one settlement.
- Payroll bank transfer = sum of individual employee ledger entries.

The agent will use a greedy subset-sum algorithm over a 7-day window.
All one-to-many matches REQUIRE human review.

## Rule 5: Unmatched Transactions

A transaction is marked unmatched when all 4 levels fail. Common reasons:
- Timing: bank posted in a different accounting period.
- Missing entry: the transaction was not recorded in the ledger.
- Bank fee: fees charged by the bank that are not in the company ledger.
- Duplicate payment: the same invoice was paid twice.
- Void/reversal: a ledger entry was voided but the bank still shows it.

All unmatched transactions REQUIRE human review.
