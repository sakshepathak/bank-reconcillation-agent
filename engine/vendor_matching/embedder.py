"""
Vendor name embedding — Tier 3 of the matcher.

Uses fastembed (already a project dependency for KB retrieval) with the
BGE-small-en-v1.5 model. 384 dims, normalized, cosine similarity works
directly on dot product.

Why we cache:
  - Same invoice vendor names recur across many runs (Amazon, Stripe, Adobe...)
  - Each embed() call is ~5-20 ms after model warmup; with cache it's free
  - First-ever call loads the model from disk (~5-10s) — we don't pay this
    during typical reconciliation runs because the matcher only uses
    embeddings as a fallback for ambiguous fuzzy scores

LRU cache size 2048 is generous — fits typical vendor universes comfortably
and uses ~3 MB of memory.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import lru_cache
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from config.settings import settings


log = logging.getLogger(__name__)


# ─── Lazy model singleton (thread-safe) ──────────────────────────────────────

_model = None
_model_lock = threading.Lock()


def _get_model():
    """Lazy-load fastembed model. First call ~5-10s; subsequent free."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding
            log.info("Loading vendor embedding model: %s", settings.DENSE_MODEL)
            _model = TextEmbedding(model_name=settings.DENSE_MODEL)
    return _model


# ─── Public API ──────────────────────────────────────────────────────────────

@lru_cache(maxsize=2048)
def embed(text: str) -> Optional[tuple]:
    """
    Return the unit-normalized embedding for `text` as a tuple
    (frozen so it's hashable and cacheable). Returns None on failure
    so callers can gracefully fall back to lexical similarity.
    """
    if not text:
        return None
    try:
        model = _get_model()
        vec = next(model.embed([text]))
        # Fastembed returns already-normalized vectors for BGE models
        return tuple(vec.tolist())
    except Exception as e:  # noqa: BLE001
        log.warning("embed(%r) failed: %s", text[:40], e)
        return None


def cosine(a: str, b: str) -> Optional[float]:
    """
    Cosine similarity between two strings in [0, 1] (clipped from [-1, 1]).
    Returns None if either input fails to embed — caller should treat as
    "no embedding signal" and rely on lexical scores alone.
    """
    ea = embed(a)
    eb = embed(b)
    if ea is None or eb is None:
        return None
    va = np.array(ea, dtype=np.float32)
    vb = np.array(eb, dtype=np.float32)
    dot = float(np.dot(va, vb))
    # BGE embeddings are unit-normalized → dot product is cosine.
    # Clip to [0, 1] for our use (negative similarity is meaningless here).
    return max(0.0, min(1.0, dot))


def warmup() -> None:
    """Trigger model load at app start, off the hot path."""
    embed("warmup")
