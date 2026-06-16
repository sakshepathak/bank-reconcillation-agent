"""
Learned per-vendor payment timing (the date-side twin of learned aliases).

The engine passively records how many days after a document's issue date each
vendor's payments actually land. Once it has seen enough consistent payments, it
widens that vendor's "fair payment window" so their habitual late payments stop
being marked down — but it only ever WIDENS, never narrows, and "paid before the
invoice" stays a red flag regardless.
"""
import os
from contextlib import contextmanager

from engine.reconcile_rules import (
    score_date, DATE_MAX, payment_lag_days, learned_window_days, LEARN_MIN_OBS,
)


# ── Unit: the pure helpers ────────────────────────────────────────────────────

def test_payment_lag_days():
    assert payment_lag_days("2026-02-01", "2026-01-10") == 22
    assert payment_lag_days("2026-01-05", "2026-01-10") == -5   # paid before issue
    assert payment_lag_days("nonsense", "2026-01-10") is None


def test_learned_window_needs_enough_observations():
    # Below the minimum, we don't trust a pattern yet.
    assert learned_window_days([50] * (LEARN_MIN_OBS - 1)) is None
    # At/above it, the window is a high percentile of the observed lags.
    assert learned_window_days([40, 45, 50, 52, 60]) in (52, 60)


def test_learned_window_floors_early_payments():
    # Paying early (negative lag) never shrinks the window.
    assert learned_window_days([-3, 0, 1]) == 1


def test_learned_window_widens_but_never_narrows_score_date():
    # Net-30 invoice paid 50 days after issue → normally "late" (not full credit)…
    assert score_date("2026-03-01", "2026-01-10", "2026-02-09")[0] < DATE_MAX
    # …but with a learned 55-day window it earns full credit.
    comp, reason = score_date("2026-03-01", "2026-01-10", "2026-02-09", learned_window=55)
    assert comp == DATE_MAX
    assert "usual window" in reason
    # A tiny learned window can't narrow an otherwise-in-terms payment.
    assert score_date("2026-02-04", "2026-01-10", "2026-02-09", learned_window=1)[0] == DATE_MAX
    # Paid-before stays a red flag no matter what is learned.
    assert score_date("2026-01-05", "2026-01-10", learned_window=99)[0] == 0.0


# ── Integration harness (mirrors test_reconcile_rules) ────────────────────────

@contextmanager
def _allow_registration():
    prev = os.environ.get("ALLOW_REGISTRATION")
    os.environ["ALLOW_REGISTRATION"] = "true"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("ALLOW_REGISTRATION", None)
        else:
            os.environ["ALLOW_REGISTRATION"] = prev


def _setup(client) -> int:
    with _allow_registration():
        r = client.post("/api/v1/auth/register", json={
            "email": "t@t.com", "password": "password1", "name": "T", "org_name": "Co",
        })
    assert r.status_code == 200, r.text
    return client.post("/api/v1/bank-accounts/", json={"name": "Checking"}).json()["id"]


def _invoice(client, name, amount, number, issue, due=None):
    body = {
        "number": number, "contact_name": name, "issue_date": issue,
        "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}],
    }
    if due:
        body["due_date"] = due
    r = client.post("/api/v1/invoices/", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _line(client, acc, desc, received, date):
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc,
        "lines": [{"date": date, "description": desc, "received": received}],
    })
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


def _match_invoice(client, line_id, invoice_id):
    r = client.post(f"/api/v1/statement-lines/{line_id}/match-invoice",
                    json={"invoice_id": invoice_id})
    assert r.status_code == 200, r.text


def _top(client, line_id):
    return client.get(f"/api/v1/statement-lines/{line_id}/suggestions").json()[0]


# Three net-30 invoices each paid ~50 days after issue (issue, due, payment).
_LATE_HISTORY = [
    ("2026-01-01", "2026-01-31", "2026-02-20"),
    ("2026-02-01", "2026-03-03", "2026-03-23"),
    ("2026-03-01", "2026-03-31", "2026-04-20"),
]


# ── Integration: learning lifts a habitually-late vendor ──────────────────────

def test_learned_window_lifts_a_habitually_late_vendor(client):
    acc = _setup(client)

    # Baseline: an untrained vendor paid 50 days late reads as "late".
    _invoice(client, "NewVendor", 100.0, "INV-N", "2026-04-01", due="2026-05-01")
    base = _top(client, _line(client, acc, "NewVendor", 100.0, "2026-05-21"))
    assert "late" in base["reason"]
    assert "usual window" not in base["reason"]

    # Train LateCo with three consistent ~50-day-late payments.
    for i, (issue, due, pay) in enumerate(_LATE_HISTORY):
        inv = _invoice(client, "LateCo", 100.0, f"INV-T{i}", issue, due=due)
        _match_invoice(client, _line(client, acc, "LateCo", 100.0, pay), inv)

    # A fresh 50-day-late LateCo payment now lands inside its LEARNED window →
    # full date credit, so it scores higher than the identical untrained case.
    _invoice(client, "LateCo", 100.0, "INV-NEW", "2026-04-01", due="2026-05-01")
    learned = _top(client, _line(client, acc, "LateCo", 100.0, "2026-05-21"))
    assert "usual window" in learned["reason"]
    assert learned["score"] > base["score"]


def test_single_late_payment_does_not_yet_widen(client):
    # One observation is below the minimum — the window must not move yet.
    acc = _setup(client)
    inv = _invoice(client, "Solo", 100.0, "INV-1", "2026-01-01", due="2026-01-31")
    _match_invoice(client, _line(client, acc, "Solo", 100.0, "2026-02-20"), inv)  # 50d late

    _invoice(client, "Solo", 100.0, "INV-2", "2026-03-01", due="2026-03-31")
    top = _top(client, _line(client, acc, "Solo", 100.0, "2026-04-20"))  # 50d late again
    assert "usual window" not in top["reason"]
    assert "late" in top["reason"]


def test_bulk_match_also_learns_timing(client):
    # A split payment settles several invoices at once — each is an observation.
    acc = _setup(client)
    ids = [
        _invoice(client, "LateCo", 100.0, "B1", "2026-01-01", due="2026-01-31"),
        _invoice(client, "LateCo", 200.0, "B2", "2026-01-01", due="2026-01-31"),
        _invoice(client, "LateCo", 300.0, "B3", "2026-01-01", due="2026-01-31"),
    ]
    line = _line(client, acc, "LateCo", 600.0, "2026-02-20")  # all 50 days after issue
    r = client.post(f"/api/v1/statement-lines/{line}/match-bulk-invoices",
                    json={"invoice_ids": ids})
    assert r.status_code == 200, r.text

    # One bulk settled three invoices → three observations (>= the minimum).
    _invoice(client, "LateCo", 100.0, "B-NEW", "2026-04-01", due="2026-05-01")
    top = _top(client, _line(client, acc, "LateCo", 100.0, "2026-05-21"))  # 50d late
    assert "usual window" in top["reason"]


def test_unreconcile_unlearns_the_timing(client):
    # Undoing a match must stop it from teaching the date rule.
    acc = _setup(client)
    train_lines = []
    for i, (issue, due, pay) in enumerate(_LATE_HISTORY):   # exactly the minimum (3)
        inv = _invoice(client, "LateCo", 100.0, f"INV-T{i}", issue, due=due)
        ln = _line(client, acc, "LateCo", 100.0, pay)
        _match_invoice(client, ln, inv)
        train_lines.append(ln)

    # With 3 observations, a fresh 50-day-late payment is credited.
    _invoice(client, "LateCo", 100.0, "INV-A", "2026-04-01", due="2026-05-01")
    before = _top(client, _line(client, acc, "LateCo", 100.0, "2026-05-21"))
    assert "usual window" in before["reason"]

    # Undo one training match → only 2 observations remain → the window un-learns.
    r = client.post(f"/api/v1/statement-lines/{train_lines[0]}/unreconcile")
    assert r.status_code == 200, r.text

    _invoice(client, "LateCo", 100.0, "INV-B", "2026-04-01", due="2026-05-01")
    after = _top(client, _line(client, acc, "LateCo", 100.0, "2026-05-21"))
    assert "usual window" not in after["reason"]
    assert "late" in after["reason"]
