"""
Self-learning layer: approving a match in the Reconcile tab can save the bank
description → vendor as a VendorAlias, so future reconciliations match it
automatically — and the matcher actually uses it.

Rules under test:
  • opt-in only — no alias unless learn_alias=True is sent
  • the learned alias is reused by the matcher (next line → alias-exact)
  • never duplicated — re-learning the same pair is a no-op
"""
from __future__ import annotations

import os
from contextlib import contextmanager


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
            "email": "learn@demo.com", "password": "password1",
            "name": "L", "org_name": "Books",
        })
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/bank-accounts/", json={"name": "Checking"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _invoice(client, name: str, amount: float, number: str) -> int:
    r = client.post("/api/v1/invoices/", json={
        "number": number, "contact_name": name, "issue_date": "2026-01-05",
        "lines": [{"description": "x", "quantity": 1, "unit_price": amount, "tax_rate": 0.0}],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _line(client, acc_id: int, desc: str, received: float) -> int:
    r = client.post("/api/v1/statement-lines/import", json={
        "bank_account_id": acc_id,
        "lines": [{"date": "2026-01-05", "description": desc, "received": received}],
    })
    assert r.status_code == 201, r.text
    return r.json()[0]["id"]


_BANK_DESC = "PENGUIN RANDOM HOUSE WHOLESALE"
_VENDOR = "Penguin Random House"


def test_learn_creates_alias_and_matcher_reuses_it(client):
    acc = _setup(client)

    inv1 = _invoice(client, _VENDOR, 2150.0, "INV-1")
    line1 = _line(client, acc, _BANK_DESC, 2150.0)

    # The first match was INFERRED (not yet a known alias).
    sugg = client.get(f"/api/v1/statement-lines/{line1}/suggestions").json()
    assert sugg[0]["method"] in ("fuzzy", "fuzzy+embed")

    # Approve WITH learning on.
    r = client.post(f"/api/v1/statement-lines/{line1}/match-invoice",
                    json={"invoice_id": inv1, "learn_alias": True})
    assert r.status_code == 200, r.text

    # Reflected in the Vendor Aliases section.
    aliases = client.get("/api/v1/aliases/").json()
    assert len(aliases) == 1
    assert aliases[0]["canonical_name"] == _VENDOR

    # Put to use: a NEW line with the same bank text now matches by alias-exact.
    _invoice(client, _VENDOR, 2150.0, "INV-2")
    line2 = _line(client, acc, _BANK_DESC, 2150.0)
    sugg2 = client.get(f"/api/v1/statement-lines/{line2}/suggestions").json()
    assert sugg2[0]["method"] == "alias-exact"
    assert sugg2[0]["score"] >= 0.9


def test_no_learn_no_alias(client):
    acc = _setup(client)
    inv = _invoice(client, _VENDOR, 2150.0, "INV-1")
    line = _line(client, acc, _BANK_DESC, 2150.0)

    r = client.post(f"/api/v1/statement-lines/{line}/match-invoice",
                    json={"invoice_id": inv, "learn_alias": False})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/aliases/").json() == []

    # Default (flag omitted) must also NOT learn.
    inv2 = _invoice(client, _VENDOR, 2150.0, "INV-2")
    line2 = _line(client, acc, _BANK_DESC, 2150.0)
    r = client.post(f"/api/v1/statement-lines/{line2}/match-invoice", json={"invoice_id": inv2})
    assert r.status_code == 200, r.text
    assert client.get("/api/v1/aliases/").json() == []


def test_learning_is_idempotent(client):
    acc = _setup(client)
    for n in ("INV-1", "INV-2", "INV-3"):
        inv = _invoice(client, _VENDOR, 2150.0, n)
        line = _line(client, acc, _BANK_DESC, 2150.0)
        r = client.post(f"/api/v1/statement-lines/{line}/match-invoice",
                        json={"invoice_id": inv, "learn_alias": True})
        assert r.status_code == 200, r.text
    # Three approvals of the same pair → still exactly one alias.
    assert len(client.get("/api/v1/aliases/").json()) == 1
