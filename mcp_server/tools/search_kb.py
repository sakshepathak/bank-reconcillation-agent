"""
Knowledge Base search tool — wraps HybridRetriever for MCP exposure.

Formats retrieved chunks into clean, structured text that the agent
can directly use in its reasoning. Handles the "no KB" edge case gracefully
so the agent always gets a usable response even if Qdrant is down.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from knowledge_base.retriever import HybridRetriever, RetrievedChunk

# Module-level singleton — initialised once, reused across all tool calls.
# This avoids re-loading embedding models on every request (expensive).
_retriever: HybridRetriever | None = None


def _get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


def search_knowledge_base(
    query: str,
    top_k: int = 5,
    chunk_type_filter: str | None = None,
) -> str:
    """
    Search the reconciliation knowledge base using hybrid (dense + sparse) search.

    Use this for:
    - Looking up matching rules ("how should I handle AMZN fees?")
    - Finding SOPs for unmatched transactions
    - Checking historical reconciliation patterns
    - Resolving vendor alias ambiguity

    Args:
        query:             Natural-language question or search phrase.
        top_k:             Number of results to return (default 5).
        chunk_type_filter: Optional filter: "rule", "sop", "alias", "historical",
                           "policy", or "general". Leave empty for all types.

    Returns:
        Formatted string of the most relevant knowledge chunks.
    """
    retriever = _get_retriever()

    if not retriever.collection_exists():
        return (
            "Knowledge base is not yet initialised. "
            "Run `python -m knowledge_base.ingest` to build it first. "
            "Proceeding with agent's built-in knowledge only."
        )

    try:
        chunks: list[RetrievedChunk] = retriever.search(
            query=query,
            top_k=top_k,
            chunk_type_filter=chunk_type_filter or None,
        )
    except Exception as exc:
        return f"Knowledge base search failed: {exc}. Proceeding without KB context."

    if not chunks:
        return "No relevant knowledge found for this query. Proceeding with built-in reasoning."

    sections = []
    for i, chunk in enumerate(chunks, 1):
        section = (
            f"[Result {i} | type={chunk.chunk_type} | relevance={chunk.score:.4f}]\n"
            f"Source: {chunk.source}\n"
        )
        if chunk.context:
            section += f"Context: {chunk.context}\n"
        section += f"Content:\n{chunk.text}"
        sections.append(section)

    return "\n\n" + ("-" * 60 + "\n").join(sections)
