"""
LLM abstraction layer.

Public API:
    from engine.llm import get_llm
    llm = get_llm()
    result = llm.complete_pdf(prompt, pdf_bytes, schema=SomePydanticModel)
    data = SomePydanticModel.model_validate_json(result.text)

Default chain: Gemini 2.5 Flash → OpenRouter (Claude Haiku) fallback.
"""
from .base import LLMClient, LLMResult, LLMError, LLMRateLimitError
from .factory import get_llm

__all__ = ["LLMClient", "LLMResult", "LLMError", "LLMRateLimitError", "get_llm"]
