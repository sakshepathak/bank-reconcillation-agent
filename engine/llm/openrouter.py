"""
OpenRouter client — automatic fallback when Gemini errors / rate-limits.

OpenRouter exposes an OpenAI-compatible REST API and routes to many backend
providers (Claude, GPT, Llama, etc.) — defaults to Claude 3.5 Haiku for cheap
high-quality fallback. We don't add the `openai` dependency; httpx is already
present (transitive from anthropic/groq/qdrant).

Note: PDFs aren't natively supported by Claude via OpenRouter — the inherited
`complete_pdf` from LLMClient renders page 1 to PNG and uses complete_image.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

from .base import LLMClient, LLMError, LLMRateLimitError, LLMResult


log = logging.getLogger(__name__)

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def _json_schema_from(schema: Any) -> Optional[dict]:
    """Convert a Pydantic model class or dict into JSON-schema form."""
    if schema is None:
        return None
    if isinstance(schema, dict):
        return schema
    # Pydantic v2 model class
    if hasattr(schema, "model_json_schema"):
        return schema.model_json_schema()
    return None


class OpenRouterClient(LLMClient):
    name = "openrouter"

    def __init__(self, api_key: str, *, model: str = "anthropic/claude-3.5-haiku") -> None:
        self._api_key = api_key
        self._model = model
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://bank-recon-agent.local",
            "X-Title": "Bank Reconciliation Agent",
        }

    def _post(self, body: dict) -> dict:
        try:
            r = httpx.post(_ENDPOINT, headers=self._headers, json=body, timeout=90.0)
        except httpx.HTTPError as e:
            raise LLMError(f"openrouter network: {e}") from e

        if r.status_code == 429:
            raise LLMRateLimitError(f"openrouter 429: {r.text[:200]}")
        if r.status_code >= 400:
            raise LLMError(f"openrouter HTTP {r.status_code}: {r.text[:200]}")

        try:
            return r.json()
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"openrouter invalid JSON: {e}") from e

    def _build_response_format(
        self, json_mode: bool, schema: Optional[Any]
    ) -> Optional[dict]:
        schema_dict = _json_schema_from(schema)
        if schema_dict is not None:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": schema_dict,
                },
            }
        if json_mode:
            return {"type": "json_object"}
        return None

    def complete_text(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        json_mode: bool = False,
        schema: Optional[Any] = None,
    ) -> LLMResult:
        body: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        rf = self._build_response_format(json_mode, schema)
        if rf is not None:
            body["response_format"] = rf

        data = self._post(body)
        text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        return LLMResult(text=text, provider=self.name, model=self._model)

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
        b64 = base64.b64encode(image_bytes).decode("ascii")
        body: dict = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        rf = self._build_response_format(json_mode, schema)
        if rf is not None:
            body["response_format"] = rf

        data = self._post(body)
        text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        return LLMResult(text=text, provider=self.name, model=self._model)
