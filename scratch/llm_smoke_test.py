"""One-shot smoke test: verify Gemini chain works inside the UI container."""
import sys
sys.path.insert(0, "/app")

from engine.llm import get_llm, LLMError

try:
    llm = get_llm()
    print("Primary provider:", llm.name)
    if hasattr(llm, "_clients"):
        print("Chain:", [c.name for c in llm._clients])

    r = llm.complete_text(
        'Reply with valid JSON: {"hello":"world","status":"ok"}',
        json_mode=True, max_tokens=40,
    )
    print(f"OK — response from {r.provider} ({r.model}):", r.text[:200])
except LLMError as e:
    print("LLM ERROR:", e)
except Exception as e:
    print("UNEXPECTED:", type(e).__name__, e)
