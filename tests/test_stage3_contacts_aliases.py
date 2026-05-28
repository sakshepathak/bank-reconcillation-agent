"""
Stage 3 tests — auto-upsert Contact, VendorAlias→Contact FK, Contact detail page.

Three pieces:
  • engine/contacts.upsert_contact: dedup within org via normalized name match
  • migration _002_vendor_alias_contact_fk: backfills contact_id within-org only
  • API: GET /contacts/{id}/detail + alias create-by-contact_id + cross-tenant 404
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager

from sqlmodel import Session, SQLModel, create_engine

import memory.models  # registers models
from engine.contacts import _normalize, upsert_contact
from memory.migrations._runner import apply_pending
from memory.models import Contact, Organization


# ── upsert_contact (unit) ────────────────────────────────────────────────────

def _mem_engine_with_orgs():
    """In-memory SQLite + two orgs ready to use."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Organization(id=1, name="Acme", currency="GBP", created_at="2026-01-01"))
        s.add(Organization(id=2, name="Beta", currency="GBP", created_at="2026-01-01"))
        s.commit()
    return engine


def test_normalize_strips_suffix_and_punctuation():
    """Same business written different ways collapses to the same key."""
    assert _normalize("Acme Ltd") == _normalize("acme limited") == "acme"
    assert _normalize("AT&T, Inc.") == _normalize("AT T Incorporated") == "at t"
    # Empty / falsy
    assert _normalize("") == ""
    assert _normalize(None) == ""  # type: ignore[arg-type]


def test_upsert_returns_existing_when_normalized_match():
    """Second upsert with a noisy version of the name returns the first row."""
    engine = _mem_engine_with_orgs()
    with Session(engine) as s:
        first = upsert_contact(s, org_id=1, name="Acme Ltd", contact_type="supplier")
        second = upsert_contact(s, org_id=1, name="Acme Limited.", contact_type="supplier")
        assert first.id == second.id
        # The display name preserves the first-seen casing/spelling.
        assert first.full_name == "Acme Ltd"


def test_upsert_creates_when_no_match():
    engine = _mem_engine_with_orgs()
    from sqlmodel import select
    with Session(engine) as s:
        a = upsert_contact(s, org_id=1, name="Acme Ltd")
        b = upsert_contact(s, org_id=1, name="Beta Inc")
        assert a.id != b.id
        rows = s.exec(select(Contact)).all()
        assert len(rows) == 2


def test_upsert_isolates_orgs():
    """Same name in two different orgs → two separate Contact rows."""
    engine = _mem_engine_with_orgs()
    with Session(engine) as s:
        a = upsert_contact(s, org_id=1, name="Shared Vendor")
        b = upsert_contact(s, org_id=2, name="Shared Vendor")
        assert a.id != b.id
        assert a.org_id == 1
        assert b.org_id == 2


def test_upsert_rejects_empty_name():
    engine = _mem_engine_with_orgs()
    import pytest
    with Session(engine) as s, pytest.raises(ValueError):
        upsert_contact(s, org_id=1, name="   ")


# ── Migration 002 backfill ───────────────────────────────────────────────────

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


@contextmanager
def _temp_db_with_seed():
    """File-based SQLite DB with two orgs, contacts in each, and pre-existing
    aliases — some matchable to a contact, some not, some in the wrong org."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Stand up the full current schema first…
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    engine.dispose()

    # Then drop the contact_id column so migration 002 has work to do.
    # SQLite has limited ALTER — easier to rebuild vendor_alias without the col.
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            -- Seed orgs
            INSERT INTO organization (id, name, currency, vat_registered,
                                       tax_treatment, financial_year_end_day,
                                       financial_year_end_month, created_at, updated_at)
                VALUES (1, 'Acme', 'GBP', 0, 'exclusive', 31, 12,
                        '2026-01-01', '2026-01-01'),
                       (2, 'Beta', 'GBP', 0, 'exclusive', 31, 12,
                        '2026-01-01', '2026-01-01');

            -- Seed contacts
            INSERT INTO contact (id, org_id, full_name, contact_type,
                                  created_at, updated_at)
                VALUES (10, 1, 'Acme Vendor Ltd', 'supplier', '2026-01-01', '2026-01-01'),
                       (11, 1, 'Other Vendor',     'supplier', '2026-01-01', '2026-01-01'),
                       (20, 2, 'Acme Vendor',      'supplier', '2026-01-01', '2026-01-01');

            -- Drop & recreate vendor_alias without contact_id
            DROP TABLE vendor_alias;
            CREATE TABLE vendor_alias (
                id INTEGER PRIMARY KEY,
                org_id INTEGER,
                alias TEXT,
                canonical_name TEXT,
                confidence REAL,
                source TEXT,
                created_at TEXT
            );

            INSERT INTO vendor_alias (id, org_id, alias, canonical_name,
                                       confidence, source, created_at)
                VALUES
                    -- Matches contact 10 via normalized name (Ltd is stripped)
                    (1, 1, 'acme vndr', 'Acme Vendor Limited', 1.0, 'human', '2026-01-01'),
                    -- Matches contact 11
                    (2, 1, 'oth vnd', 'Other Vendor', 1.0, 'human', '2026-01-01'),
                    -- No matching contact in org 1
                    (3, 1, 'mystery', 'Unknown Vendor Co', 1.0, 'agent', '2026-01-01'),
                    -- Same canonical_name as alias 1 BUT in org 2 — should link to contact 20
                    (4, 2, 'acme', 'Acme Vendor', 1.0, 'human', '2026-01-01'),
                    -- NULL org_id — must be skipped
                    (5, NULL, 'orphan', 'Acme Vendor', 0.5, 'agent', '2026-01-01');
            """
        )
        # migration_history table is created by the runner on next apply_pending.
        # But we need migration 001 to be marked as already applied so 002 doesn't
        # blow up trying to add org_id columns that already exist (it would actually
        # be idempotent). Easier: just let the runner run both — 001 will no-op.
        conn.commit()
    finally:
        conn.close()

    try:
        yield path
    finally:
        os.unlink(path)


def test_migration_002_backfills_within_org_only():
    """Aliases must link to a contact in the SAME org. Cross-org name collisions
    must not leak. Note: when the runner applies both 001 and 002 in sequence
    (the real production path), 001 backfills NULL org_ids → 1, so any alias
    that was NULL ends up scoped to org 1 before 002 walks it."""
    with _temp_db_with_seed() as path:
        result = apply_pending(path)
        applied = {a["name"]: a for a in result["applied"]}
        assert "002_vendor_alias_contact_fk" in applied
        details = applied["002_vendor_alias_contact_fk"]["details"]
        assert details["column_added"] is True
        # 4 linked: ids 1, 2, 4 directly, plus id 5 (was NULL org → backfilled to 1
        # by migration 001, then matches contact 10 "Acme Vendor Ltd" by canonical).
        assert details["aliases_linked"] == 4
        # Only id 3 ("Unknown Vendor Co") has no matching contact.
        assert details["aliases_no_contact_match"] == 1
        # Migration 001 ran first, so no aliases reach 002 with NULL org_id.
        assert details["aliases_skipped_null_org"] == 0

        with closing(sqlite3.connect(path)) as conn:
            rows = dict(
                conn.execute("SELECT id, contact_id FROM vendor_alias ORDER BY id")
            )
            assert rows[1] == 10      # Acme Vendor Ltd in org 1
            assert rows[2] == 11      # Other Vendor in org 1
            assert rows[3] is None    # no match
            assert rows[4] == 20      # Acme Vendor in org 2 — NOT contact 10
            assert rows[5] == 10      # was NULL → 001 set org_id=1, links to Acme


def test_migration_002_idempotent():
    with _temp_db_with_seed() as path:
        apply_pending(path)
        second = apply_pending(path)
        # Second run skips both 001 and 002 (already in history).
        assert any(s["name"] == "002_vendor_alias_contact_fk" for s in second["skipped"])
        assert all(a["name"] != "002_vendor_alias_contact_fk" for a in second["applied"])


# ── API: contact detail + alias-by-contact_id + cross-tenant isolation ──────

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


def _register(client, email: str, org_name: str, *, allow: bool = False):
    payload = {"email": email, "password": "password1",
               "name": email.split("@")[0], "org_name": org_name}
    if allow:
        with _allow_registration():
            r = client.post("/api/v1/auth/register", json=payload)
    else:
        r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _login(client, email: str):
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "password1"})
    assert r.status_code == 200
    return r.json()


def test_invoice_upload_path_links_contact(client, monkeypatch):
    """A bill/invoice create with no contact_id auto-upserts a Contact."""
    _register(client, "alice@a.com", "Acme")

    # Manual create — exercises the create_invoice auto-upsert path.
    r = client.post("/api/v1/invoices/", json={
        "number": "INV-1", "contact_name": "Acme Cust Ltd",
        "issue_date": "2026-05-01", "lines": [
            {"description": "Work", "quantity": 1, "unit_price": 100.0},
        ],
    })
    assert r.status_code == 201
    inv = r.json()
    assert inv["contact_id"] is not None

    # Second invoice with a noisy version of the same name → same contact.
    r2 = client.post("/api/v1/invoices/", json={
        "number": "INV-2", "contact_name": "Acme Cust Limited.",
        "issue_date": "2026-05-02", "lines": [
            {"description": "Work", "quantity": 1, "unit_price": 50.0},
        ],
    })
    assert r2.status_code == 201
    inv2 = r2.json()
    assert inv2["contact_id"] == inv["contact_id"]


def test_contact_detail_returns_invoices_bills_aliases(client):
    _register(client, "alice@a.com", "Acme")
    inv_resp = client.post("/api/v1/invoices/", json={
        "number": "INV-1", "contact_name": "Acme Cust",
        "issue_date": "2026-05-01", "lines": [
            {"description": "Work", "quantity": 1, "unit_price": 100.0},
        ],
    }).json()
    contact_id = inv_resp["contact_id"]

    # Add an alias via contact_id
    r = client.post("/api/v1/aliases/", json={
        "alias": "ACME PAYMNT 0001", "contact_id": contact_id, "confidence": 1.0,
    })
    assert r.status_code == 201
    alias = r.json()
    # canonical_name auto-filled from Contact.full_name
    assert alias["canonical_name"] == "Acme Cust"
    assert alias["contact_id"] == contact_id

    detail = client.get(f"/api/v1/contacts/{contact_id}/detail")
    assert detail.status_code == 200
    body = detail.json()
    assert body["contact"]["id"] == contact_id
    assert len(body["invoices"]) == 1
    assert body["invoices"][0]["number"] == "INV-1"
    assert len(body["aliases"]) == 1
    assert body["aliases"][0]["alias"] == "acme paymnt 0001"


def test_alias_rejects_foreign_contact_id(client):
    """Creating an alias with a contact_id from another org must 404 (not link)."""
    _register(client, "alice@a.com", "Acme")
    alice_contact = client.post("/api/v1/contacts/", json={
        "full_name": "Alice Customer", "contact_type": "customer",
    }).json()

    # Bob tries to create an alias pointing at Alice's contact
    client.cookies.clear()
    _register(client, "bob@b.com", "Beta", allow=True)
    r = client.post("/api/v1/aliases/", json={
        "alias": "stealing-alice", "contact_id": alice_contact["id"], "confidence": 1.0,
    })
    assert r.status_code == 404


def test_contact_rename_refreshes_alias_cache(client):
    """Renaming a Contact must propagate to canonical_name on linked aliases."""
    _register(client, "alice@a.com", "Acme")
    c = client.post("/api/v1/contacts/", json={
        "full_name": "Acme Old Name", "contact_type": "supplier",
    }).json()

    client.post("/api/v1/aliases/", json={
        "alias": "ACME XYZ", "contact_id": c["id"], "confidence": 1.0,
    })

    # Rename
    client.patch(f"/api/v1/contacts/{c['id']}", json={"full_name": "Acme New Name"})

    detail = client.get(f"/api/v1/contacts/{c['id']}/detail").json()
    assert detail["aliases"][0]["canonical_name"] == "Acme New Name"


def test_contact_delete_unlinks_aliases(client):
    """Deleting a contact leaves aliases in place but with contact_id=NULL."""
    _register(client, "alice@a.com", "Acme")
    c = client.post("/api/v1/contacts/", json={
        "full_name": "Doomed", "contact_type": "supplier",
    }).json()
    client.post("/api/v1/aliases/", json={
        "alias": "doomy", "contact_id": c["id"], "confidence": 1.0,
    })

    client.delete(f"/api/v1/contacts/{c['id']}")
    rows = client.get("/api/v1/aliases/").json()
    # Alias still there, but unlinked.
    assert len(rows) == 1
    assert rows[0]["contact_id"] is None


def test_contact_detail_404_for_other_orgs_contact(client):
    """Bob cannot GET Alice's contact detail."""
    _register(client, "alice@a.com", "Acme")
    c = client.post("/api/v1/contacts/", json={
        "full_name": "Alice Co", "contact_type": "customer",
    }).json()

    client.cookies.clear()
    _register(client, "bob@b.com", "Beta", allow=True)
    r = client.get(f"/api/v1/contacts/{c['id']}/detail")
    assert r.status_code == 404


def test_aliases_filtered_by_contact_id_query(client):
    """GET /aliases/?contact_id=N filters to just that contact's aliases."""
    _register(client, "alice@a.com", "Acme")
    c1 = client.post("/api/v1/contacts/", json={
        "full_name": "C1", "contact_type": "supplier",
    }).json()
    c2 = client.post("/api/v1/contacts/", json={
        "full_name": "C2", "contact_type": "supplier",
    }).json()

    client.post("/api/v1/aliases/", json={"alias": "a1", "contact_id": c1["id"]})
    client.post("/api/v1/aliases/", json={"alias": "a2", "contact_id": c2["id"]})

    r = client.get(f"/api/v1/aliases/?contact_id={c1['id']}")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["alias"] == "a1"


def test_alias_legacy_canonical_name_still_works(client):
    """Old free-string flow: {alias, canonical_name} without contact_id still allowed."""
    _register(client, "alice@a.com", "Acme")
    r = client.post("/api/v1/aliases/", json={
        "alias": "OLDSTYLE", "canonical_name": "Amazon", "confidence": 1.0,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["canonical_name"] == "Amazon"
    assert body["contact_id"] is None


def test_alias_create_rejects_missing_both(client):
    _register(client, "alice@a.com", "Acme")
    r = client.post("/api/v1/aliases/", json={"alias": "nada", "confidence": 1.0})
    assert r.status_code == 400
