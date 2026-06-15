"""
Refined reconciliation rules:

1. Asymmetric DATE scoring — paying on/after the invoice within terms earns full
   credit (a normal payment delay is NOT penalised); paying before the invoice
   exists earns no credit, which caps the composite below auto-approve quality.

2. Split/bulk payments are single-vendor ONLY — the commit endpoints reject a
   group whose documents aren't all the same vendor, even if the amounts sum.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from engine.reconcile_rules import (
    score_date, DATE_MAX, cap_by_name, is_ambiguous, auto_match_ready,
    NAME_FOR_STRONG, BAND_STRONG, BAND_LIKELY,
)


# ── Unit: the date rule itself ────────────────────────────────────────────────

def test_payment_after_within_terms_is_full_credit():
    # Net-30 invoice paid 25 days later — normal, must not be penalised.
    score, _ = score_date("2026-02-04", "2026-01-10", "2026-02-09")
    assert score == DATE_MAX
    # Same day is also full.
    assert score_date("2026-01-10", "2026-01-10")[0] == DATE_MAX
    # A few days after, no due date (assume net-30) — still full.
    assert score_date("2026-01-24", "2026-01-10")[0] == DATE_MAX


def test_payment_before_invoice_loses_date_credit():
    # Clearly before the invoice exists → 0 (red flag), caps composite at 0.80.
    assert score_date("2026-01-05", "2026-01-10")[0] == 0.0
    # Tiny 1-day skew gets a small allowance, still far below full.
    assert 0.0 < score_date("2026-01-09", "2026-01-10")[0] < DATE_MAX


def test_payment_far_after_tapers():
    late = score_date("2026-03-25", "2026-01-10", "2026-02-09")[0]   # ~10 weeks → late band
    assert 0.0 < late < DATE_MAX
    assert score_date("2027-06-01", "2026-01-10")[0] == 0.0          # over a year → far


# ── Unit: name similarity caps the confidence label ──────────────────────────

def test_strong_name_is_uncapped():
    # Names clearly match → no cap, can reach Strong.
    assert cap_by_name(1.0, 1.0) == 1.0
    assert cap_by_name(0.95, NAME_FOR_STRONG) == 0.95


def test_partial_name_caps_at_likely():
    # Some similarity → at most Likely (below Strong, but still ≥ Likely allowed).
    capped = cap_by_name(1.0, 0.60)
    assert BAND_LIKELY <= capped < BAND_STRONG


def test_low_name_is_only_a_low_match():
    # Barely-matching name → low match (below Likely), even with exact amount+date.
    assert cap_by_name(0.95, 0.20) < BAND_LIKELY


def test_cap_never_raises_a_score():
    assert cap_by_name(0.30, 1.0) == 0.30


# ── Unit: ambiguity (near-tie at the top) ────────────────────────────────────

def test_is_ambiguous():
    assert is_ambiguous(0.92, 0.91) is True     # tied near the top
    assert is_ambiguous(0.92, 0.70) is False    # runner-up below Likely
    assert is_ambiguous(0.92, 0.80) is False    # gap too wide to be a tie


# ── Unit: the strict auto-reconcile gate ─────────────────────────────────────

def test_auto_match_ready_needs_every_signal():
    base = dict(amount_exact=True, name_method="alias-exact",
                date_component=DATE_MAX, same_currency=True)
    assert auto_match_ready(**base) is True
    assert auto_match_ready(**{**base, "name_method": "canonical-exact"}) is True
    # Any single failing signal disqualifies it.
    assert auto_match_ready(**{**base, "amount_exact": False}) is False
    assert auto_match_ready(**{**base, "name_method": "fuzzy"}) is False
    assert auto_match_ready(**{**base, "name_method": "fuzzy+embed"}) is False
    assert auto_match_ready(**{**base, "date_component": 0.10}) is False   # late, not full
    assert auto_match_ready(**{**base, "same_currency": False}) is False


# ── Integration harness ───────────────────────────────────────────────────────

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
            "email": "r@r.com", "password": "password1", "name": "R", "org_name": "Co",
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


def _top(client, line_id):
    return client.get(f"/api/v1/statement-lines/{line_id}/suggestions").json()[0]


# ── Integration: date asymmetry end-to-end ───────────────────────────────────

def test_after_scores_higher_than_before_and_before_cannot_auto_approve(client):
    acc = _setup(client)
    _invoice(client, "Acme", 100.0, "INV-1", "2026-01-10", due="2026-02-09")

    after = _top(client, _line(client, acc, "Acme", 100.0, "2026-02-01"))   # 22d after
    before = _top(client, _line(client, acc, "Acme", 100.0, "2026-01-05"))  # 5d before

    assert after["score"] > before["score"]
    assert after["score"] >= 0.9            # normal delayed payment is auto-approve quality
    assert before["score"] < 0.9            # paid-before can never auto-approve


# ── Integration: split must be single-vendor ─────────────────────────────────

def test_bulk_rejects_mixed_vendors(client):
    acc = _setup(client)
    a = _invoice(client, "Vendor A", 100.0, "INV-A", "2026-01-05")
    b = _invoice(client, "Vendor B", 200.0, "INV-B", "2026-01-05")
    line = _line(client, acc, "SOME PAYMENT", 300.0, "2026-01-06")

    r = client.post(f"/api/v1/statement-lines/{line}/match-bulk-invoices",
                    json={"invoice_ids": [a, b]})
    assert r.status_code == 422, r.text
    assert "same vendor" in r.json()["detail"].lower()


def test_bulk_allows_same_vendor(client):
    acc = _setup(client)
    a = _invoice(client, "Vendor A", 100.0, "INV-A1", "2026-01-05")
    b = _invoice(client, "Vendor A", 200.0, "INV-A2", "2026-01-05")
    line = _line(client, acc, "VENDOR A PAYMENT", 300.0, "2026-01-06")

    r = client.post(f"/api/v1/statement-lines/{line}/match-bulk-invoices",
                    json={"invoice_ids": [a, b]})
    assert r.status_code == 200, r.text


# ── Integration: name caps the label, and the auto gate ──────────────────────

def test_wrong_vendor_exact_amount_is_low_match_not_auto(client):
    # Exact amount + in-window date but a totally different name must NOT read as
    # confident — the name doesn't agree. Stays a low match, never auto-eligible.
    acc = _setup(client)
    _invoice(client, "Acme Industries", 100.0, "INV-1", "2026-01-10", due="2026-02-09")
    line = _line(client, acc, "ZZZ UNRELATED CORP", 100.0, "2026-02-01")

    top = _top(client, line)
    assert top["score"] < BAND_LIKELY          # capped — names don't match
    assert top["auto_eligible"] is False


def test_exact_known_unique_match_is_auto_eligible(client):
    acc = _setup(client)
    _invoice(client, "Acme", 100.0, "INV-1", "2026-01-10", due="2026-02-09")
    line = _line(client, acc, "Acme", 100.0, "2026-02-01")   # same name → canonical-exact

    top = _top(client, line)
    assert top["score"] >= BAND_STRONG
    assert top["method"] in ("canonical-exact", "alias-exact")
    assert top["ambiguous"] is False
    assert top["auto_eligible"] is True


def test_duplicate_amount_same_vendor_is_ambiguous_not_auto(client):
    # Two open invoices, same vendor + same amount → a genuine tie. Both flagged
    # ambiguous and neither may auto-reconcile (we never silently pick one).
    acc = _setup(client)
    _invoice(client, "Acme", 100.0, "INV-1", "2026-01-10", due="2026-02-09")
    _invoice(client, "Acme", 100.0, "INV-2", "2026-01-10", due="2026-02-09")
    line = _line(client, acc, "Acme", 100.0, "2026-02-01")

    sugg = client.get(f"/api/v1/statement-lines/{line}/suggestions").json()
    assert len(sugg) >= 2
    assert sugg[0]["ambiguous"] is True
    assert sugg[0]["auto_eligible"] is False
