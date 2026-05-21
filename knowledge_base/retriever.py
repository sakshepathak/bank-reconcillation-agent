"""
Hybrid retriever for the Bank Reconciliation Knowledge Base.

Architecture:
  1. Embed query with dense (BGE-small) and sparse (BM25) models.
  2. Run two independent searches against Qdrant.
  3. Fuse results with Reciprocal Rank Fusion (RRF) — proven superior to
     simple score averaging because it is rank-agnostic and handles
     score-scale mismatches between dense and sparse results.

This class is stateless after __init__ and fully thread-safe.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass
from typing import Any

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import QdrantClient, models

from config.settings import settings


@dataclass
class RetrievedChunk:
    """A single retrieved knowledge chunk with full provenance."""

    text: str
    context: str          # contextual summary generated at ingest time
    source: str           # file path of the originating document
    score: float          # RRF fusion score (higher = more relevant)
    chunk_type: str       # e.g. "rule", "sop", "alias", "historical"


class HybridRetriever:
    """
    Stateless retriever. Instantiate once and call `search()` many times.
    """

    def __init__(self) -> None:
        self._qdrant = QdrantClient(url=settings.QDRANT_URL)
        self._dense = TextEmbedding(model_name=settings.DENSE_MODEL)
        self._sparse = SparseTextEmbedding(model_name=settings.SPARSE_MODEL)

    # ── Public API ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int | None = None,
        chunk_type_filter: str | None = None,
    ) -> list[RetrievedChunk]:
        """
        Hybrid search with optional chunk_type filtering.

        Args:
            query: Natural-language or keyword query.
            top_k: Override RERANK_TOP_K from settings.
            chunk_type_filter: If set, only return chunks with this type
                               (e.g. "rule" to get only matching rules).

        Returns:
            List of RetrievedChunk sorted by relevance (best first).
        """
        k = top_k or settings.RERANK_TOP_K

        query_filter = None
        if chunk_type_filter:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="chunk_type",
                        match=models.MatchValue(value=chunk_type_filter),
                    )
                ]
            )

        dense_hits = self._dense_search(query, query_filter)
        sparse_hits = self._sparse_search(query, query_filter)
        fused = self._rrf_fuse(dense_hits, sparse_hits, k=k)

        return [self._to_chunk(hit) for hit in fused]

    def collection_exists(self) -> bool:
        return self._qdrant.collection_exists(settings.QDRANT_COLLECTION)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _dense_search(
        self, query: str, query_filter: models.Filter | None
    ) -> list[Any]:
        dense_vec = list(self._dense.embed([query]))[0].tolist()
        return self._qdrant.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=dense_vec,
            using="dense",
            limit=settings.HYBRID_TOP_K,
            query_filter=query_filter,
        ).points

    def _sparse_search(
        self, query: str, query_filter: models.Filter | None
    ) -> list[Any]:
        sparse_obj = list(self._sparse.embed([query]))[0]
        query_sparse = models.SparseVector(
            indices=sparse_obj.indices.tolist(),
            values=sparse_obj.values.tolist(),
        )
        return self._qdrant.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_sparse,
            using="sparse",
            limit=settings.HYBRID_TOP_K,
            query_filter=query_filter,
        ).points

    @staticmethod
    def _rrf_fuse(
        dense_hits: list[Any],
        sparse_hits: list[Any],
        k: int,
        rrf_k: int = 60,
    ) -> list[Any]:
        """
        Reciprocal Rank Fusion.
        score(doc) = Σ  1 / (rank + rrf_k)  across all ranked lists.
        rrf_k=60 is the standard constant that prevents early ranks from
        dominating; empirically shown to work well across domains.
        """
        scores: dict[str, float] = {}
        all_hits: dict[str, Any] = {}

        for rank, hit in enumerate(dense_hits):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (rank + rrf_k)
            all_hits[hit.id] = hit

        for rank, hit in enumerate(sparse_hits):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (rank + rrf_k)
            all_hits[hit.id] = hit

        sorted_ids = sorted(scores, key=lambda i: scores[i], reverse=True)[:k]
        # Attach the RRF score to hits so callers can see relative ranking
        result = []
        for sid in sorted_ids:
            hit = all_hits[sid]
            hit._rrf_score = scores[sid]
            result.append(hit)
        return result

    @staticmethod
    def _to_chunk(hit: Any) -> RetrievedChunk:
        payload = hit.payload or {}
        return RetrievedChunk(
            text=payload.get("text", ""),
            context=payload.get("context", ""),
            source=payload.get("source", "unknown"),
            score=getattr(hit, "_rrf_score", 0.0),
            chunk_type=payload.get("chunk_type", "general"),
        )
