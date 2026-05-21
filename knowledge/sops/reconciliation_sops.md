# Standard Operating Procedures (SOPs) for Bank Reconciliation

## SOP-001: How to Handle Bank Fees Not in Ledger

**Trigger**: A bank debit appears in the statement with a description containing keywords like:
"FEE", "CHARGE", "BANK FEE", "WIRE FEE", "SERVICE CHARGE", "OVERDRAFT"

**Procedure**:
1. Mark the transaction as `unmatched`.
2. Flag it with reason: "Probable bank fee — not in company ledger."
3. Suggest the accountant create a ledger entry under Account: "6100 - Bank Charges".
4. Ask the human to confirm before posting.

---

## SOP-002: How to Handle Duplicate Bank Transactions

**Trigger**: Two bank transactions with identical date, amount, and description within the same period.

**Procedure**:
1. Match the first occurrence to its ledger counterpart (if found).
2. Flag the second occurrence as `requires_human_review = True`.
3. Reasoning path must include: "Potential duplicate detected — same date, amount, description."
4. Never auto-match a suspected duplicate.

---

## SOP-003: How to Handle FX (Foreign Currency) Transactions

**Trigger**: Bank description contains currency codes like "USD", "EUR", "GBP", "AUD"
or keywords like "CURRENCY CONVERSION", "FX", "FOREX".

**Procedure**:
1. Apply a relaxed amount tolerance of 2% (not the default 5 cents flat).
2. Widen the date window to 5 days for FX settlements.
3. Always flag for human review regardless of match level.
4. Note in reasoning_path: "FX transaction — exchange rate rounding may cause amount differences."

---

## SOP-004: How to Handle Reversed / Voided Transactions

**Trigger**: A credit in the bank statement that matches a previous debit exactly
(same amount, similar description, within 30 days).

**Procedure**:
1. Identify the original debit in the same bank statement period.
2. Check the ledger for a corresponding reversal/void entry.
3. If ledger has the void entry: match both (debit + credit) to respective ledger entries.
4. If ledger does NOT have the void entry: flag both as unmatched and alert the accountant.

---

## SOP-005: End-of-Period Timing Differences

**Trigger**: Ledger has an entry on December 31 but the bank only shows it on January 2.

**Procedure**:
1. Extend the date window search to 7 days for transactions dated within 5 days of month-end.
2. Match if amount is identical.
3. Record in reasoning_path: "Timing difference — cross-period posting."
4. Human review required.

---

## SOP-006: Payroll Reconciliation

**Trigger**: Bank shows one large debit labelled "PAYROLL" or "SALARY" or "ADP" or "PAYCHEX".

**Procedure**:
1. This is typically a one-to-many match (one bank transfer = multiple employee ledger entries).
2. Sum all ledger entries under Account "5000 - Salaries" within the same week.
3. If the sum matches (within $1.00 tolerance for rounding across employees): flag as one-to-many.
4. ALWAYS require human approval for payroll matches.
