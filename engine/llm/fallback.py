"""
FallbackChain — tries each underlying client in order until one succeeds.

Catches LLMError (and the LLMRateLimitError subclass) — anything else
propagates so we can see real bugs.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .base import LLMClient, LLMError, LLMResult


log = logging.getLogger(__name__)


class FallbackChain(LLMClient):
    name = "fallback-chain"

    def __init__(self, *clients: LLMClient) -> None:
        if not clients:
            raise ValueError("FallbackChain requires at least one client")
        self._clients = clients

    @property
    def primary(self) -> LLMClient:
        return self._clients[0]

    # ── Each method just iterates ────────────────────────────────────────────

    def _try_all(self, method: str, *args, **kwargs) -> LLMResult:
        last_err: Optional[LLMError] = None
        for client in self._clients:
            try:
                return getattr(client, method)(*args, **kwargs)
            except LLMError as e:
                last_err = e
                log.warning("[%s] %s failed (%s) — trying next", client.name, method, e)
        # All providers exhausted
        raise last_err or LLMError("all LLM providers failed")

    def complete_text(self, prompt: str, **kwargs) -> LLMResult:  # type: ignore[override]
        return self._try_all("complete_text", prompt, **kwargs)

    def complete_image(self, prompt: str, image_bytes: bytes, mime: str, **kwargs) -> LLMResult:  # type: ignore[override]
        return self._try_all("complete_image", prompt, image_bytes, mime, **kwargs)

    def complete_pdf(self, prompt: str, pdf_bytes: bytes, **kwargs) -> LLMResult:  # type: ignore[override]
        return self._try_all("complete_pdf", prompt, pdf_bytes, **kwargs)
