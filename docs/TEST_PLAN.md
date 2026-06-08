# Test Plan — Bank Reconciliation

**Status:** active · **Last updated:** 2026-06-08 · **Suite:** 92 automated tests across 8 files, all passing.

This is the one-page strategy for *what* we test and *why*. The guiding principle is **risk-based testing**: we don't aim for 100% coverage of every line — we aim to cover the things that would hurt most if they broke, weighted by how likely they are to break. For an accounting product, that means money, reconciliation logic, and tenant isolation come first.

---

## 1. What we're protecting (by risk)

| # | Risk area | Why it matters | Status |
|---|-----------|----------------|--------|
| 1 | **Money & balances** | A wrong figure in an accounting tool destroys trust instantly | ✅ Covered — `test_reconcile_money.py` |
| 2 | **Matching-engine correctness** | The core value of the product; wrong matches mean wrong books | ✅ Covered — `test_matching.py` |
| 3 | **Tenant isolation (security)** | One org seeing another's data is catastrophic | ✅ Covered — `test_org_scoping.py`, `test_add_org_e2e_flow.py` |
| 4 | **Auth & the registration gate** | Controls who can get in; lock-down must actually lock down | ✅ Covered — `test_auth.py` |
| 5 | **Schema migrations** | A bad migration can corrupt or lose data | ✅ Covered — `test_migrations.py` |
| 6 | **Statement / CSV / date parsing** | Garbage-in at the import boundary corrupts everything downstream | ⚠️ Not yet — see §4 |
| 7 | **LLM extraction (PDF → data)** | External, non-deterministic; useful but not core arithmetic | ⛔ Out of the automated suite by design — see §4 |

---

## 2. How the tests are structured (the levels)

A standard test pyramid — many fast unit tests at the base, fewer broad ones on top:

| Level | What it isolates | Where |
|-------|------------------|-------|
| **Unit** | One function, no DB or network — fast | `test_matching.py` (engine cascade & gates) |
| **Integration** | Several components through the real API + a test database | `test_reconcile_money.py`, `test_org_scoping.py`, `test_auth.py`, `test_orgs_router.py`, `test_stage3_contacts_aliases.py`, `test_migrations.py` |
| **End-to-end** | A full user journey | `test_add_org_e2e_flow.py` (register → seed → add org → verify isolation → switch back) |

---

## 3. What's covered today

| File | What it checks |
|------|----------------|
| `test_matching.py` | The matching cascade: exact match is exact (rejects a 1-cent diff), the amount-tolerance and date-window gates hold at their edges, one-to-many subset-sum, duplicate prevention, input validation, idempotency |
| `test_reconcile_money.py` | Matching a line updates `paid_amount`; flips to **paid** only when fully paid; partial leaves the right outstanding; the account's **balance difference drives to 0** when reconciled and back when unreconciled; **unreconcile reverses the money exactly**; no double-reconcile; VAT/total arithmetic |
| `test_org_scoping.py` | 15 cross-tenant checks — every model, every verb: one org can never read or mutate another's data |
| `test_add_org_e2e_flow.py` | The whole "add a new organisation" flow stays isolated end-to-end |
| `test_auth.py` | Registration, login, sessions, and the `ALLOW_REGISTRATION` lock-down gate (open by default; closes after the first user when locked) |
| `test_orgs_router.py` | Organisation create / switch / list / update |
| `test_stage3_contacts_aliases.py` | Contact de-duplication, vendor-alias linkage, rename propagation |
| `test_migrations.py` | The numbered-migration runner is idempotent (safe to re-run) |

---

## 4. What we deliberately do **not** cover yet

Being explicit about the edges is part of the strategy. In rough priority order:

- **Statement / CSV / date parsing** (`engine/bank_statement_parser.py`) — the DD/MM-vs-MM/DD logic and malformed-file handling are tricky and untested. **Highest-value next addition.**
- **Vendor-name normalisation & similarity scoring** — exercised indirectly through the cascade, but not pinned down with direct unit tests.
- **LLM extraction & fallback** (Gemini → OpenRouter) — external and non-deterministic. Kept out of the fast suite on purpose; when added it will be **mocked** (no real API calls), testing our parsing/fallback logic, not the model.
- **Transfers between own accounts** — there is a known discrepancy between how a transfer moves the stored balance and how the API re-derives it; left unasserted until that's reconciled, rather than baking the quirk in as "correct."
- **CSV import de-duplication / re-import idempotency.**
- **Frontend (React)** — no automated tests yet.
- **Coverage measurement (`pytest-cov`) and CI (GitHub Actions)** — recommended next steps so the suite runs automatically and we can see a coverage trend.

---

## 5. How to run

```bash
pytest
```

- `pytest.ini` scopes collection to `tests/`, so this one command runs the whole suite (~40s) and skips the model-cache folder.
- Every test gets its **own fresh in-memory SQLite database** (`tests/conftest.py`), so tests never touch the real DB and can't pollute each other.
- **No network, API keys, or external services are required** — the suite runs fully offline and deterministically.

---

## 6. Conventions

- **Arrange–Act–Assert** structure; descriptive `test_<thing>_<scenario>_<expected>` names.
- Shared setup lives in fixtures (`conftest.py`).
- **Money is compared with `pytest.approx`** — amounts are floats, and exact `==` on floats is fragile.
- **Mock only at external boundaries** (e.g. the LLM client) — never mock our own internal logic, or the test just tests the mock.
- **Every fixed bug gets a regression test**, so it can't silently come back.
