"""Verify the LLM chain is correctly configured with 3 Gemini keys + OpenRouter vision fallback."""
import sys
sys.path.insert(0, "/app")

from engine.llm import get_llm
from engine.llm.gemini import GeminiClient
from engine.llm.openrouter import OpenRouterClient

llm = get_llm()
print("Top-level provider:", llm.name)

if hasattr(llm, "_clients"):
    for i, c in enumerate(llm._clients):
        if isinstance(c, GeminiClient):
            print(f"  [{i}] gemini — {c._key_count} key(s), vision_model={c._vision_model}")
        elif isinstance(c, OpenRouterClient):
            print(f"  [{i}] openrouter — model={c._model}")
        else:
            print(f"  [{i}] {c.name}")
