"""
Base contract for LLM clients.

Every concrete client must support:
  - complete_text:   pure text in, text out (optional JSON-mode + schema)
  - complete_image:  prompt + single image  (vision)
  - complete_pdf:    prompt + PDF bytes     (default falls back to image of page 1)

Failures raise LLMError (or its RateLimit subclass) — never bare exceptions.
This is what lets FallbackChain catch and retry through the next provider.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


class LLMError(Exception):
    """Any LLM call failure."""


class LLMRateLimitError(LLMError):
    """Provider returned 429 / quota exhausted — caller should fall back."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str

    def json(self) -> dict:
        """Parse text as JSON. Best-effort recovery if model wraps in prose."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            start = self.text.find("{")
            end = self.text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(self.text[start:end + 1])
            # try array
            start = self.text.find("[")
            end = self.text.rfind("]")
            if start >= 0 and end > start:
                return json.loads(self.text[start:end + 1])
            raise


class LLMClient(ABC):
    """All providers implement this interface."""

    name: str = "abstract"

    @abstractmethod
    def complete_text(
        self,
        prompt: str,
        *,
        max_tokens: int = 2000,
        json_mode: bool = False,
        schema: Optional[Any] = None,
    ) -> LLMResult:
        ...

    @abstractmethod
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
        ...

    def complete_pdf(
        self,
        prompt: str,
        pdf_bytes: bytes,
        *,
        max_tokens: int = 4000,
        json_mode: bool = False,
        schema: Optional[Any] = None,
    ) -> LLMResult:
        """
        Default: render PDF page 1 → PNG and treat as an image.
        Providers with native PDF support (Gemini) should override this.
        """
        # Lazy import to avoid pulling fitz at module load
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            if doc.page_count == 0:
                raise LLMError("PDF has no pages")
            pix = doc.load_page(0).get_pixmap(dpi=150)
            png = pix.tobytes("png")
        finally:
            doc.close()
        return self.complete_image(
            prompt, png, "image/png",
            max_tokens=max_tokens, json_mode=json_mode, schema=schema,
        )
