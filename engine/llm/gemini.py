"""
Gemini client — primary provider with API-key rotation.

Key advantages over Groq vision:
  - Native PDF input (no PNG rendering required)
  - First-class structured output via Pydantic schemas
  - Deterministic with temperature=0
  - 1M-token context handles multi-page bank statements in one call

Rate-limit strategy:
  - The free tier is 5 req/min per key per model. We rotate round-robin
    across up to 3 keys (GEMINI_API_KEY + 2 backups). With 3 keys we
    effectively get 15 req/min.
  - On 429, we immediately try the next key. Only after all keys 429 do
    we raise LLMRateLimitError so the fallback chain takes over.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .base import LLMClient, LLMError, LLMRateLimitError, LLMResult


log = logging.getLogger(__name__)


def _is_recoverable_key_error(e: Exception) -> bool:
    """
    True for errors where trying the NEXT key might work:
      - 429 / rate / quota / resource_exhausted  (per-key rate limit)
      - 403 / permission_denied / leaked         (this key dead, others may live)
      - 401 / unauthorized / invalid             (this key dead)
    """
    msg = str(e).lower()
    return any(t in msg for t in (
        "429", "rate", "quota", "resource_exhausted",
        "403", "permission_denied", "leaked", "401", "unauthorized",
    ))


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(
        self,
        api_keys: list[str],
        *,
        vision_model: str = "gemini-2.5-flash",
        text_model: str = "gemini-2.5-flash",
    ) -> None:
        from google import genai

        clean = [k for k in api_keys if k]
        if not clean:
            raise LLMError("GeminiClient: no api_keys provided")

        self._clients = [genai.Client(api_key=k) for k in clean]
        self._key_count = len(self._clients)
        self._idx = 0
        self._lock = threading.Lock()
        self._vision_model = vision_model
        self._text_model = text_model

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _next_client(self):
        """Round-robin next client. Thread-safe so parallel extract calls
        spread across keys instead of all hitting the first one."""
        with self._lock:
            client = self._clients[self._idx]
            self._idx = (self._idx + 1) % self._key_count
            return client

    def _build_config(
        self, max_tokens: int, json_mode: bool, schema: Optional[Any]
    ):
        from google.genai import types

        cfg: dict = {
            "max_output_tokens": max_tokens,
            "temperature": 0,
        }
        if json_mode or schema is not None:
            cfg["response_mime_type"] = "application/json"
        if schema is not None:
            cfg["response_schema"] = schema
        return types.GenerateContentConfig(**cfg)

    def _wrap_call(self, call_fn, model: str) -> LLMResult:
        """
        `call_fn(client)` runs the actual generate_content call.
        On 429, rotates to next key and retries — up to once per key.
        """
        last_err: Optional[Exception] = None
        for attempt in range(self._key_count):
            client = self._next_client()
            try:
                response = call_fn(client)
                text = (response.text or "").strip()
                return LLMResult(text=text, provider=self.name, model=model)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if _is_recoverable_key_error(e):
                    if attempt + 1 < self._key_count:
                        log.info("gemini key #%d failed (%s), rotating",
                                 self._idx, type(e).__name__)
                        continue
                    # all keys exhausted — bubble up so fallback chain takes over
                    raise LLMRateLimitError(str(e)) from e
                # non-recoverable error (e.g. schema mismatch, malformed request)
                raise LLMError(f"gemini call failed: {e}") from e

        # Defensive — shouldn't reach here
        raise LLMRateLimitError(str(last_err) if last_err else "all gemini keys exhausted")

    # ── Public API ───────────────────────────────────────────────────────────

    def complete_text(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        json_mode: bool = False,
        schema: Optional[Any] = None,
    ) -> LLMResult:
        config = self._build_config(max_tokens, json_mode, schema)
        return self._wrap_call(
            lambda client: client.models.generate_content(
                model=self._text_model, contents=prompt, config=config,
            ),
            self._text_model,
        )

    def complete_image(
        self,
        prompt: str,
        image_bytes: bytes,
        mime: str,
        *,
        max_tokens: int = 2000,
        json_mode: bool = False,
        schema: Optional[Any] = None,
    ) -> LLMResult:
        from google.genai import types

        config = self._build_config(max_tokens, json_mode, schema)
        contents = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            prompt,
        ]
        return self._wrap_call(
            lambda client: client.models.generate_content(
                model=self._vision_model, contents=contents, config=config,
            ),
            self._vision_model,
        )

    def complete_pdf(
        self,
        prompt: str,
        pdf_bytes: bytes,
        *,
        max_tokens: int = 4000,
        json_mode: bool = False,
        schema: Optional[Any] = None,
    ) -> LLMResult:
        """Native PDF — no rendering, sends bytes directly."""
        from google.genai import types

        config = self._build_config(max_tokens, json_mode, schema)
        contents = [
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            prompt,
        ]
        return self._wrap_call(
            lambda client: client.models.generate_content(
                model=self._vision_model, contents=contents, config=config,
            ),
            self._vision_model,
        )
