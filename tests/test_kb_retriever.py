"""
Multi-tenant scoping for the knowledge-base retriever.

The security guarantee: when a search is org-scoped, it returns the SHARED
global knowledge (rules/SOPs/aliases, which carry no org_id) PLUS this org's
own facts/notes — but NEVER another organisation's private chunks.

This drives the real filter through an in-memory Qdrant, so it's an actual
isolation proof, not just a check on the filter object. No external services
and no embedding models are loaded — we call the static filter builder directly
and use tiny hand-made vectors.
"""
from __future__ import annotations


def test_kb_filter_returns_global_and_own_org_never_others():
    from qdrant_client import QdrantClient, models
    from knowledge_base.retriever import HybridRetriever

    client = QdrantClient(":memory:")
    client.create_collection(
        "t", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE)
    )
    client.upsert("t", points=[
        # shared/global knowledge — note: NO org_id on the payload
        models.PointStruct(id=1, vector=[1.0, 0.0],
                           payload={"text": "global rule", "chunk_type": "rule"}),
        # org 1's private fact
        models.PointStruct(id=2, vector=[1.0, 0.0],
                           payload={"text": "org1 fact", "chunk_type": "fact", "org_id": 1}),
        # org 2's private fact — must NEVER surface for org 1
        models.PointStruct(id=3, vector=[1.0, 0.0],
                           payload={"text": "org2 fact", "chunk_type": "fact", "org_id": 2}),
    ])

    org1_filter = HybridRetriever._build_filter(chunk_type_filter=None, org_id=1)
    points, _ = client.scroll("t", scroll_filter=org1_filter, limit=10, with_payload=True)
    ids = {p.id for p in points}

    assert 3 not in ids, "org 2's private fact leaked into org 1's search"
    assert ids == {1, 2}, f"org 1 should see global + its own only, got {ids}"


def test_kb_filter_unscoped_is_none():
    """No org_id => no filter (the search sees everything). Documents that an
    unscoped search is wide open, so any caller touching private data must pass
    an org_id."""
    from knowledge_base.retriever import HybridRetriever
    assert HybridRetriever._build_filter(chunk_type_filter=None, org_id=None) is None
