"""
Unit tests for the org->KB chunk builders (pure: no DB, no Qdrant, no embedding
models). These pin down WHAT gets written into the knowledge base for a
business, so the assistant has the right context to answer "what do we do?" /
"who is X?".
"""
from __future__ import annotations

from types import SimpleNamespace

from knowledge_base.org_sync import (
    build_company_chunk, build_contact_chunk, build_org_chunks,
)


def _org(**kw):
    return SimpleNamespace(id=kw.get("id", 1), name=kw.get("name"), industry=kw.get("industry"))


def _profile(**kw):
    return SimpleNamespace(
        org_id=kw.get("org_id", 1), company_name=kw.get("company_name"),
        about=kw.get("about"), industry=kw.get("industry"), website=kw.get("website"),
    )


def _contact(**kw):
    return SimpleNamespace(
        id=kw.get("id", 10), full_name=kw.get("full_name", "Acme Ltd"),
        contact_type=kw.get("contact_type", "supplier"), company=kw.get("company"),
        email=kw.get("email"), phone=kw.get("phone"), notes=kw.get("notes"),
    )


def test_company_chunk_includes_name_industry_and_about():
    ch = build_company_chunk(
        _org(id=1, name="Brooklyn Bookstore", industry="Retail"),
        _profile(about="We sell rare books and host author events."),
    )
    assert ch is not None
    assert ch.chunk_type == "company"
    assert ch.key == "org:1:company"
    assert "Brooklyn Bookstore" in ch.text
    assert "Retail" in ch.text
    assert "rare books" in ch.text


def test_company_chunk_none_when_nothing_to_say():
    assert build_company_chunk(_org(id=1, name=None, industry=None), None) is None


def test_contact_chunk_format_and_key():
    ch = build_contact_chunk(
        1, _contact(id=7, full_name="Globex", contact_type="customer", email="ap@globex.com"),
    )
    assert ch.chunk_type == "contact"
    assert ch.key == "org:1:contact:7"
    assert "Globex" in ch.text
    assert "customer" in ch.text
    assert "ap@globex.com" in ch.text


def test_build_org_chunks_company_plus_one_per_contact():
    org = _org(id=2, name="Co", industry="Tech")
    profile = _profile(about="We build things.")
    contacts = [_contact(id=1, full_name="A"), _contact(id=2, full_name="B")]
    chunks = build_org_chunks(org, profile, contacts)

    types = [c.chunk_type for c in chunks]
    assert types.count("company") == 1
    assert types.count("contact") == 2

    keys = [c.key for c in chunks]
    assert len(keys) == len(set(keys))                      # deterministic + unique
    assert "org:2:contact:1" in keys and "org:2:contact:2" in keys
