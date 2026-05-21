# GBrains Integration Plan for Bank Reconciliation Agent

## Overview
Based on research, **GBrain** is a "compiled intelligence" system designed to provide AI agents with persistent, structured, and scalable long-term memory. It transforms data into a structured repository of markdown files and creates a self-wiring knowledge graph.

In the context of the Bank Reconciliation Agent, GBrain will serve as the **Self-Learning Knowledge Base** for complex patterns, human corrections, and specific "skills" needed for handling messy financial data.

## Integration Strategy

### 1. Hybrid Memory Architecture
We will use a hybrid approach combining the structured power of PostgreSQL (with pgvector) and the flexible, compounding knowledge of GBrain.

*   **PostgreSQL (pgvector)**: Best for structured data, exact matches, transaction records, and fast vector search on vendor aliases.
*   **GBrain**: Best for storing "skills" (e.g., "How to handle Vendor X's weird fees"), human corrections, and complex relationship mappings that are not easily fit into a rigid DB schema.

### 2. Learning Loop (Human-in-the-Loop)
When a human corrects a match or identifies a new pattern (e.g., "AMZN MKTPL is actually Amazon"):
1.  The Agent will update the structured alias in PostgreSQL.
2.  The Agent will also write/update a markdown file in the GBrain repository capturing the context: "User corrected match for AMZN MKTPL on 2026-05-13. Reason: standard vendor alias."
3.  Over time, GBrain's maintenance cycles will consolidate these files into a refined "Skill" or "Rule".

### 3. Agent Workflow with GBrain
1.  **Ingestion**: Load bank statement and ledger.
2.  **Querying**: The Agent queries GBrain to check for any specific "rules" or "skills" related to the vendors or transaction types present in the current batch.
3.  **Execution**: Apply standard matching logic (M1 tool) AND any specific GBrain-derived rules.
4.  **Reporting**: Log the reasoning path, including if a GBrain rule was applied.

## Action Plan for Implementation

### Phase 1: Knowledge Base & Advanced RAG (Current Focus)
*   Implement Advanced RAG system (Hybrid Search with Qdrant, Contextual Retrieval) as the foundational Knowledge Base.
*   Setup the collection for reconciliation rules, SOPs, and historical data.
*   Integrate this RAG system as an MCP tool for the agent.

### Phase 2: Foundation & Base Matching
*   Set up the SDK and the base MCP matching tool.
*   Define the structure for GBrain markdown files (e.g., `skills/` and `knowledge/` directories).

### Phase 3: GBrains Setup (Post M1)
*   Create the interface for reading/writing to the GBrain markdown repository.
*   Implement the "Self-Learning" logic that triggers a GBrain update on human correction.


---
*Prepared by Senior Principal AI Engineer*
