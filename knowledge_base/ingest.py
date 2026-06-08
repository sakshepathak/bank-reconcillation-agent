"""
Ingestion pipeline for the Bank Reconciliation Knowledge Base.

Pipeline per document:
  1. Read markdown file.
  2. Split into chunks (paragraph-aware, respects heading boundaries).
  3. For each chunk: generate contextual summary via LLM (Contextual Retrieval).
  4. Embed enriched text with dense + sparse models.
  5. Upsert into Qdrant with rich payload metadata.

Idempotent: uses deterministic UUID5 chunk IDs — re-running never creates
duplicates; it just overwrites existing points.

Usage:
    python -m knowledge_base.ingest
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glob
import re
import uuid
from pathlib import Path
from typing import Optional

from fastembed import SparseTextEmbedding, TextEmbedding
from groq import Groq
from qdrant_client import QdrantClient, models
from rich.console import Console
from rich.progress import track

from config.settings import settings

console = Console()

# ── Chunk type inference ──────────────────────────────────────────────────────
# We tag each chunk with a type based on the folder it came from.
# This enables filtered retrieval later ("give me only rules").
_FOLDER_TO_TYPE: dict[str, str] = {
    "rules": "rule",
    "sops": "sop",
    "aliases": "alias",
    "historical": "historical",
    "policies": "policy",
}

# Standalone app docs to ingest as GLOBAL "doc" knowledge, so the assistant can
# explain what the software does and how to use it. User-facing docs only —
# internal dev docs (TEST_PLAN, design notes) are deliberately excluded.
_APP_DOC_FILES = [
    "README.md",
    "docs/FEATURES.md",
    "docs/WALKTHROUGH.md",
    "docs/DEMO_CHEATSHEET.md",
]


def _infer_chunk_type(file_path: str) -> str:
    parts = Path(file_path).parts
    for part in parts:
        if part.lower() in _FOLDER_TO_TYPE:
            return _FOLDER_TO_TYPE[part.lower()]
    return "general"


# ── Text splitting ────────────────────────────────────────────────────────────

def _split_into_chunks(text: str, max_chars: int = 600, overlap: int = 80) -> list[str]:
    """
    Paragraph-aware chunker that respects markdown heading boundaries.

    Strategy:
    - Split on blank lines first (paragraphs).
    - If a paragraph exceeds max_chars, split further by sentences.
    - Prepend `overlap` chars from the previous chunk to each new chunk
      so context isn't lost at boundaries.

    This is more reliable than fixed-token chunking for financial rules
    which are typically short, self-contained paragraphs.
    """
    # Split on markdown headings and blank lines
    raw_blocks = re.split(r"\n{2,}|(?=^#{1,3} )", text, flags=re.MULTILINE)
    blocks = [b.strip() for b in raw_blocks if b.strip()]

    chunks: list[str] = []
    carry = ""  # overlap carry-over

    for block in blocks:
        combined = (carry + "\n\n" + block).strip() if carry else block
        if len(combined) <= max_chars:
            chunks.append(combined)
            carry = combined[-overlap:] if len(combined) > overlap else combined
        else:
            # Long block: sentence-split
            sentences = re.split(r"(?<=[.!?])\s+", combined)
            current = carry
            for sentence in sentences:
                if len(current) + len(sentence) + 1 <= max_chars:
                    current = (current + " " + sentence).strip()
                else:
                    if current:
                        chunks.append(current)
                        carry = current[-overlap:] if len(current) > overlap else current
                    current = (carry + " " + sentence).strip()
            if current:
                chunks.append(current)
                carry = current[-overlap:] if len(current) > overlap else current

    return [c for c in chunks if c]


# ── Ingestor ──────────────────────────────────────────────────────────────────

class Ingestor:
    """Handles the full ingest pipeline for a directory of markdown files."""

    def __init__(self) -> None:
        self._qdrant = QdrantClient(url=settings.QDRANT_URL)
        self._dense = TextEmbedding(model_name=settings.DENSE_MODEL)
        self._sparse = SparseTextEmbedding(model_name=settings.SPARSE_MODEL)

        # Contextual retrieval is optional (needs Groq key)
        self._groq: Optional[Groq] = None
        if settings.GROQ_API_KEY:
            self._groq = Groq(api_key=settings.GROQ_API_KEY)
        else:
            console.print(
                "[yellow]GROQ_API_KEY not set — contextual retrieval disabled. "
                "Chunks will still be ingested without context enrichment.[/]"
            )

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self, knowledge_dir: str = "knowledge") -> None:
        """Ingest markdown under `knowledge_dir` plus the user-facing app docs."""
        self._setup_collection()

        files = glob.glob(f"{knowledge_dir}/**/*.md", recursive=True)
        if files:
            console.print(f"[bold green]Found {len(files)} knowledge files to ingest...[/]")
            for file_path in track(files, description="Ingesting..."):
                self._process_file(file_path)
        else:
            console.print(f"[yellow]No markdown files found in {knowledge_dir}/[/]")

        # App docs → global "doc" chunks (what the software does / how to use it)
        doc_files = [f for f in _APP_DOC_FILES if os.path.exists(f)]
        if doc_files:
            console.print(f"[bold green]Ingesting {len(doc_files)} app docs as global knowledge...[/]")
            for file_path in track(doc_files, description="Ingesting docs..."):
                self._process_file(file_path, chunk_type="doc")

        console.print("[bold green]✓ Ingestion complete.[/]")

    # ── Private ───────────────────────────────────────────────────────────────

    def _setup_collection(self) -> None:
        """Create Qdrant collection with hybrid (dense + sparse) config."""
        if self._qdrant.collection_exists(settings.QDRANT_COLLECTION):
            console.print(
                f"[dim]Collection '{settings.QDRANT_COLLECTION}' already exists — upserting.[/]"
            )
            return

        console.print(f"[bold]Creating collection '{settings.QDRANT_COLLECTION}'...[/]")
        self._qdrant.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config={
                "dense": models.VectorParams(
                    size=384,  # BAAI/bge-small-en-v1.5 output dim
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(),
                    modifier=models.Modifier.IDF,
                )
            },
        )

    def _get_contextual_description(self, doc_text: str, chunk_text: str) -> str:
        """
        Anthropic's Contextual Retrieval technique.
        Generates a 1-2 sentence context that situates the chunk within the
        full document. This is prepended to the chunk before embedding.
        """
        if not self._groq:
            return ""

        prompt = (
            f"<document>\n{doc_text}\n</document>\n\n"
            f"Here is the chunk we want to situate within the whole document:\n"
            f"<chunk>\n{chunk_text}\n</chunk>\n\n"
            "Give a SHORT (1-2 sentence) context that situates this chunk within "
            "the overall document for the purpose of improving search retrieval. "
            "Answer ONLY with the context, nothing else."
        )
        try:
            resp = self._groq.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=settings.CONTEXT_MODEL,
                max_tokens=120,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            console.print(f"[red]Context generation failed: {exc}[/]")
            return ""

    def _process_file(self, file_path: str, chunk_type: str | None = None) -> None:
        console.print(f"  [blue]→ {file_path}[/]")
        if chunk_type is None:
            chunk_type = _infer_chunk_type(file_path)

        with open(file_path, "r", encoding="utf-8") as fh:
            full_text = fh.read()

        chunks = _split_into_chunks(full_text)
        if not chunks:
            return

        points: list[models.PointStruct] = []

        for i, chunk in enumerate(chunks):
            context = self._get_contextual_description(full_text, chunk)
            enriched = f"{context}\n\n{chunk}".strip() if context else chunk

            dense_vec = list(self._dense.embed([enriched]))[0].tolist()
            sparse_obj = list(self._sparse.embed([enriched]))[0]
            sparse_vec = models.SparseVector(
                indices=sparse_obj.indices.tolist(),
                values=sparse_obj.values.tolist(),
            )

            # Deterministic ID — re-ingesting the same file never duplicates
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file_path}::{i}"))

            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={"dense": dense_vec, "sparse": sparse_vec},
                    payload={
                        "text": chunk,
                        "enriched_text": enriched,
                        "context": context,
                        "source": file_path,
                        "chunk_type": chunk_type,
                        "chunk_index": i,
                    },
                )
            )

        if points:
            self._qdrant.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=points,
            )
            console.print(
                f"    [green]✓ {len(points)} chunks ({chunk_type})[/]"
            )


if __name__ == "__main__":
    Ingestor().run()
