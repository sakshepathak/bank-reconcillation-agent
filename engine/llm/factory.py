"""
LLM factory — builds the default chain from settings.

Default topology:
    Gemini (primary)  →  OpenRouter (fallback)

If only one is configured, returns that single client directly (no overhead).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import settings

from .base import LLMClient, LLMError
from .fallback import FallbackChain


_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    """
    Return the configured LLM client. Cached after first call.

    Raises LLMError if no provider is configured.
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    clients: list[LLMClient] = []

    gemini_keys = [
        settings.GEMINI_API_KEY,
        settings.GEMINI_API_KEY_BACKUP_1,
        settings.GEMINI_API_KEY_BACKUP_2,
    ]
    # Deduplicate while preserving order (in case user set same key in multiple slots)
    seen: set[str] = set()
    gemini_keys_unique = [k for k in gemini_keys if k and not (k in seen or seen.add(k))]

    if gemini_keys_unique:
        try:
            from .gemini import GeminiClient
            clients.append(GeminiClient(
                api_keys=gemini_keys_unique,
                vision_model=settings.GEMINI_VISION_MODEL,
                text_model=settings.GEMINI_TEXT_MODEL,
            ))
        except Exception:  # noqa: BLE001
            pass

    if settings.OPENROUTER_API_KEY:
        from .openrouter import OpenRouterClient
        clients.append(OpenRouterClient(
            api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_FALLBACK_MODEL,
        ))

    if not clients:
        raise LLMError(
            "No LLM provider configured. Set GEMINI_API_KEY and/or OPENROUTER_API_KEY."
        )

    _singleton = clients[0] if len(clients) == 1 else FallbackChain(*clients)
    return _singleton


def reset_llm() -> None:
    """Test hook — clears the cached singleton."""
    global _singleton
    _singleton = None
