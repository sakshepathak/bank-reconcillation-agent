# Learnings from Advanced RAG Model

This document summarizes the key architectural patterns and techniques learned from the `adv-rag-model` project and how they will be applied to the Bank Reconciliation Agent.

## 1. Key Architectural Patterns Identified

### Hybrid Search (Dense + Sparse)
- **Concept**: Combining semantic search with keyword search.
- **Implementation**:
  - Dense vectors using `fastembed.TextEmbedding` (e.g., BGE-small).
  - Sparse vectors using `fastembed.SparseTextEmbedding`.
  - Stored in Qdrant with `vectors_config` and `sparse_vectors_config`.
  - Results combined using **Reciprocal Rank Fusion (RRF)**.
- **Benefit**: Captures both the semantic meaning of queries and exact keyword matches (like account numbers or specific codes), leading to higher retrieval accuracy.

### Anthropic's Contextual Retrieval
- **Concept**: Adding global document context to individual chunks.
- **Implementation**: Using a LLM (via Groq) to generate a short context summary for each chunk relative to the whole document before embedding it.
- **Benefit**: Prevents chunks from losing their meaning when retrieved out of context, which is crucial for financial documents where context (like the year or entity) matters.

### Pydantic-AI & FastMCP
- **Concept**: Modern framework for building production-ready agents and tools.
- **Implementation**:
  - `pydantic-ai` for agent definition, system prompts, and tool calling.
  - `FastMCP` for exposing tools (like search) over the Model Context Protocol.
- **Benefit**: High type safety, clean separation of concerns, and easy integration.

## 2. Application to Bank Reconciliation Agent

We will adopt this architecture for the Bank Reconciliation system to ensure high accuracy and reliability.

### Knowledge Base (KB) Content
The KB will store:
1. **Reconciliation Rules**: Business logic for matching (e.g., "If amount matches and description contains 'XYZ', match to Account A").
2. **Historical Successful Matches**: Examples that the agent can use as a reference for complex cases.
3. **SOPs**: Standard operating procedures for handling exceptions and discrepancies.

### Workflow Plan
1. **Setup KB**: Create a Qdrant collection with hybrid search support.
2. **Ingestion**: Create a script (similar to `ingest.py`) to process and store rules and historical data, using Contextual Retrieval where applicable.
3. **Agent Integration**: Build the reconciliation agent using `pydantic-ai` (or integrate with the existing Claude SDK setup), giving it access to a `search_kb` tool implemented with the hybrid search logic.

This ensures the agent is grounded in correct data before making reconciliation decisions.
