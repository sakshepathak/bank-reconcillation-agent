"""
Sync an organisation's own data (company profile + contacts) into the
knowledge base as ORG-SCOPED chunks, so the in-app assistant can answer
questions about *this* business — what it does, who its contacts are.

Quantitative questions (who owes what, balances) are deliberately NOT synced
here — those are answered live and exactly by the assistant's SQL tools. The
KB holds the qualitative, slow-changing context only (see the project's
"deterministic over LLM" principle).

Chunks are written with deterministic ids (HybridRetriever.upsert_chunk), so a
re-sync overwrites in place; the org's existing company/contact chunks are
cleared first, so a deleted contact doesn't linger as a stale chunk.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from memory.models import Organization, CompanyProfile, Contact


@dataclass(frozen=True)
class OrgChunk:
    key: str          # stable logical key -> deterministic Qdrant point id
    text: str
    chunk_type: str   # "company" | "contact"


def build_company_chunk(org, profile) -> OrgChunk | None:
    """One chunk describing the business. Returns None if there's nothing
    worth saying (no name, industry, or about text)."""
    name = (getattr(org, "name", None) if org else None) or (
        getattr(profile, "company_name", None) if profile else None
    )
    industry = (getattr(profile, "industry", None) if profile else None) or (
        getattr(org, "industry", None) if org else None
    )
    about = getattr(profile, "about", None) if profile else None
    website = getattr(profile, "website", None) if profile else None

    parts: list[str] = []
    if name:
        parts.append(f"The organisation is {name}.")
    if industry:
        parts.append(f"Industry: {industry}.")
    if about:
        parts.append(f"About the business: {about}")
    if website:
        parts.append(f"Website: {website}.")
    if not parts:
        return None

    org_id = (getattr(org, "id", None) if org else None) or (
        getattr(profile, "org_id", None) if profile else None
    )
    return OrgChunk(key=f"org:{org_id}:company", text=" ".join(parts), chunk_type="company")


def build_contact_chunk(org_id: int, c) -> OrgChunk:
    """One short chunk per contact, so the assistant can recognise and talk
    about them by name."""
    bits = [f"{c.full_name} is a {c.contact_type}."]
    if getattr(c, "company", None):
        bits.append(f"Company: {c.company}.")
    if getattr(c, "email", None):
        bits.append(f"Email: {c.email}.")
    if getattr(c, "phone", None):
        bits.append(f"Phone: {c.phone}.")
    if getattr(c, "notes", None):
        bits.append(f"Notes: {c.notes}")
    return OrgChunk(key=f"org:{org_id}:contact:{c.id}", text=" ".join(bits), chunk_type="contact")


def build_org_chunks(org, profile, contacts) -> list[OrgChunk]:
    """Pure: assemble all org-scoped chunks from the given rows. Testable with
    no database and no Qdrant."""
    chunks: list[OrgChunk] = []
    company = build_company_chunk(org, profile)
    if company:
        chunks.append(company)
    org_id = getattr(org, "id", None) if org else None
    for c in contacts:
        chunks.append(build_contact_chunk(org_id, c))
    return chunks


def sync_org_to_kb(db: Session, org_id: int) -> dict:
    """Refresh this org's company + contact chunks in the KB. Returns counts."""
    from knowledge_base.retriever import get_retriever

    org = db.get(Organization, org_id)
    profile = db.exec(
        select(CompanyProfile).where(CompanyProfile.org_id == org_id)
    ).first()
    contacts = db.exec(select(Contact).where(Contact.org_id == org_id)).all()

    chunks = build_org_chunks(org, profile, contacts)

    retriever = get_retriever()
    # Clear old company/contact chunks first so removed rows don't linger.
    retriever.delete_org_chunks(org_id, "company")
    retriever.delete_org_chunks(org_id, "contact")
    for ch in chunks:
        retriever.upsert_chunk(
            point_key=ch.key, text=ch.text, chunk_type=ch.chunk_type,
            org_id=org_id, source="org-sync",
        )

    return {
        "synced": True,
        "company_chunks": sum(1 for c in chunks if c.chunk_type == "company"),
        "contact_chunks": sum(1 for c in chunks if c.chunk_type == "contact"),
    }
