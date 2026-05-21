"""Verify which Gemini key is loaded and whether it can hit the API."""
import sys, os
sys.path.insert(0, "/app")

from config.settings import settings

key = settings.GEMINI_API_KEY or ""
if key:
    print(f"Loaded key length: {len(key)} chars")
    print(f"Loaded key prefix...suffix: {key[:8]}...{key[-4:]}")
else:
    print("NO GEMINI_API_KEY LOADED")

# Direct hit to Gemini API, bypass our wrapper
import urllib.request, json
url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
body = {"contents": [{"parts": [{"text": "Reply with the single word OK."}]}]}

req = urllib.request.Request(
    url,
    data=json.dumps(body).encode(),
    headers={
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    },
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        print(f"Gemini said: {text!r}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:400]}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
