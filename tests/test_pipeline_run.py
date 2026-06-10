"""
End-to-end test for the Pipeline Run demo surface.

Guards the whole flow the UI drives: register → create bank account → import
invoices/bills/statement → list pipeline lines → score one line → narrate it.

The reason this test exists: the static routes `/statement-lines/pipeline` and
`/statement-lines/pipeline-lines` MUST be declared before `/statement-lines/{line_id}`,
or FastAPI captures them with the int `line_id` route and returns 422 ("unable to
parse 'pipeline-lines' as an integer"). That regression shipped once; this locks it.

The LLM is stubbed so `/narrate` doesn't make a network call.
"""
from __future__ import annotations

import io
import os
from contextlib import contextmanager

import api.routers.statement_lines as sl


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


_INVOICES_CSV = (
    "number,customer,date,due_date,amount,currency,status\n"
    "INV-001,Park Slope Cafe,2026-01-05,2026-01-19,320.00,GBP,awaiting_payment\n"
    "INV-002,Greenpoint Library,2026-01-06,2026-01-20,865.50,GBP,awaiting_payment\n"
)
_BILLS_CSV = (
    "number,supplier,date,due_date,amount,currency,status\n"
    "BILL-001,Con Edison,2026-01-09,2026-01-23,312.40,GBP,awaiting_payment\n"
    "BILL-002,Penguin Random House,2026-01-05,2026-01-19,2150.00,GBP,awaiting_payment\n"
)
# Signed amounts: +credit (matches an invoice), -debit (matches a bill).
# T3 is the alias scenario: bank says "...WHOLESALE", the bill is "Penguin Random House".
_STATEMENT_CSV = (
    "txn_id,date,description,amount\n"
    "T1,2026-01-05,PARK SLOPE CAFE CONSOLIDATED PMT,320.00\n"
    "T2,2026-01-09,CON EDISON ELECTRIC,-312.40\n"
    "T3,2026-01-05,PENGUIN RANDOM HOUSE WHOLESALE,-2150.00\n"
)


def _seed(client) -> int:
    """Register, create an account, import invoices+bills+statement. Returns account id."""
    with _allow_registration():
        r = client.post("/api/v1/auth/register", json={
            "email": "demo@demo.com", "password": "password1",
            "name": "Demo", "org_name": "Brooklyn Books",
        })
    assert r.status_code == 200, r.text

    r = client.post("/api/v1/bank-accounts/", json={"name": "Brooklyn Checking"})
    assert r.status_code == 201, r.text
    acc_id = r.json()["id"]

    def _csv(text: str):
        return {"file": ("data.csv", io.BytesIO(text.encode()), "text/csv")}

    assert client.post("/api/v1/invoices/upload-csv", files=_csv(_INVOICES_CSV)).status_code == 201
    assert client.post("/api/v1/bills/upload-csv", files=_csv(_BILLS_CSV)).status_code == 201
    r = client.post(
        "/api/v1/statement-lines/upload",
        files=_csv(_STATEMENT_CSV),
        data={"bank_account_id": str(acc_id)},
    )
    assert r.status_code == 201, r.text
    assert len(r.json()) == 3
    return acc_id


def test_pipeline_lines_is_not_shadowed_by_line_id_route(client):
    """The exact 422 regression: GET /pipeline-lines must not hit /{line_id}."""
    acc_id = _seed(client)

    r = client.get("/api/v1/statement-lines/pipeline-lines", params={"bank_account_id": acc_id})
    assert r.status_code == 200, r.text          # NOT 422
    lines = r.json()
    assert len(lines) == 3
    assert {"id", "date", "description", "amount", "direction"} <= set(lines[0].keys())


def test_pipeline_batch_returns_summary_and_traces(client):
    acc_id = _seed(client)

    r = client.get("/api/v1/statement-lines/pipeline", params={"bank_account_id": acc_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total"] == 3
    assert len(body["entries"]) == 3
    # Every entry that found a candidate carries a full 7-step trace.
    for e in body["entries"]:
        if e["top_candidate"] is not None:
            assert [s["n"] for s in e["trace"]["steps"]] == [1, 2, 3, 4, 5, 6, 7]


def test_pipeline_entry_and_narrate(client, monkeypatch):
    acc_id = _seed(client)

    lines = client.get("/api/v1/statement-lines/pipeline-lines", params={"bank_account_id": acc_id}).json()
    line_id = lines[0]["id"]

    r = client.get(f"/api/v1/statement-lines/{line_id}/pipeline-entry")
    assert r.status_code == 200, r.text
    entry = r.json()
    assert entry["line"]["id"] == line_id
    assert entry["trace"] is not None

    # Stub the LLM so narrate is deterministic and offline.
    class _Res:
        text = "Plain-English narrative."
        provider = "stub"
        model = "stub"

    class _LLM:
        def complete_text(self, *a, **k):
            return _Res()

    monkeypatch.setattr(sl, "get_llm", lambda: _LLM())

    r = client.post("/api/v1/statement-lines/narrate", json=entry["trace"])
    assert r.status_code == 200, r.text
    assert r.json()["narrative"] == "Plain-English narrative."


def _penguin_entry(client, acc_id: int) -> dict:
    lines = client.get("/api/v1/statement-lines/pipeline-lines", params={"bank_account_id": acc_id}).json()
    penguin = next(l for l in lines if "PENGUIN" in l["description"])
    return client.get(f"/api/v1/statement-lines/{penguin['id']}/pipeline-entry").json()


def test_alias_drives_an_exact_match(client):
    """The matcher must consult the VendorAlias list: once an alias maps the
    statement variant to the real vendor, the line becomes a 100% alias-exact match."""
    acc_id = _seed(client)

    r = client.post("/api/v1/aliases/", json={
        "alias": "PENGUIN RANDOM HOUSE WHOLESALE", "canonical_name": "Penguin Random House",
    })
    assert r.status_code == 201, r.text

    trace = _penguin_entry(client, acc_id)["trace"]
    step2 = next(s for s in trace["steps"] if s["n"] == 2)
    assert step2["hit"] is True
    assert step2["resolved_to"] == "Penguin Random House"
    assert trace["final"]["method"] == "alias-exact"
    assert trace["final"]["score_pct"] == 100


def test_add_vendor_alias_tool_is_used_by_the_matcher(client, test_engine):
    """The assistant's add_vendor_alias tool writes a real alias the engine uses —
    and it figures out the canonical vendor regardless of argument order."""
    from sqlmodel import Session
    from engine.assistant.tools import add_vendor_alias

    acc_id = _seed(client)
    org_id = client.get("/api/v1/auth/me").json()["current_org_id"]

    # Pass the messy variant FIRST — the tool must still pick the bill's vendor as canonical.
    with Session(test_engine) as db:
        res = add_vendor_alias(db, org_id, "Penguin Random House Wholesale", "Penguin Random House")
    assert res["saved"] is True
    assert res["canonical_vendor"] == "Penguin Random House"
    assert res["statement_name"] == "Penguin Random House Wholesale"

    trace = _penguin_entry(client, acc_id)["trace"]
    assert next(s for s in trace["steps"] if s["n"] == 2)["hit"] is True
    assert trace["final"]["method"] == "alias-exact"


def test_substring_alias_is_picked_up(client):
    """A user-added alias should match as a SUBSTRING of the bank text, not only
    on an exact full-string match (the Aliases page tells users to do this)."""
    acc_id = _seed(client)
    # Distinctive part only — bank text is "PENGUIN RANDOM HOUSE WHOLESALE".
    r = client.post("/api/v1/aliases/", json={
        "alias": "penguin random house", "canonical_name": "Penguin Random House",
    })
    assert r.status_code == 201, r.text
    trace = _penguin_entry(client, acc_id)["trace"]
    assert next(s for s in trace["steps"] if s["n"] == 2)["hit"] is True
    assert trace["final"]["method"] == "alias-exact"


def test_bills_csv_reimport_does_not_duplicate(client):
    """Re-importing the same bills CSV must update in place, not pile up
    duplicate rows (regression: bills used to always insert)."""
    with _allow_registration():
        client.post("/api/v1/auth/register", json={
            "email": "demo@demo.com", "password": "password1",
            "name": "Demo", "org_name": "Brooklyn Books",
        })
    files = {"file": ("bills.csv", io.BytesIO(_BILLS_CSV.encode()), "text/csv")}
    assert client.post("/api/v1/bills/upload-csv", files=files).status_code == 201
    files = {"file": ("bills.csv", io.BytesIO(_BILLS_CSV.encode()), "text/csv")}
    assert client.post("/api/v1/bills/upload-csv", files=files).status_code == 201
    # _BILLS_CSV has 2 numbered rows — re-import must keep it at 2, not 4.
    assert len(client.get("/api/v1/bills/").json()) == 2
