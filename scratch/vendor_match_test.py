"""End-to-end smoke test: normalize + similarity + matcher on realistic data."""
import sys
sys.path.insert(0, "/app")

from engine.vendor_matching import canonicalize, find_matches

# Simulated invoice vendor list extracted from PDFs
INVOICES = [
    "Amazon.com, Inc.",
    "Stripe Inc",
    "The Daily Bean Pvt. Ltd.",
    "Adobe Systems Software",
    "Netflix",
    "Uber Technologies",
    "Google Cloud",
]

# Bank descriptions — messy real-world strings
BANK_LINES = [
    "AMZN MKTPL*Z89K3KS",
    "STRIPE *ACME",
    "SQ *DAILYBEAN SF",
    "ADOBE *CREATIVE",
    "NETFLIX.COM",
    "UBER *TRIP 12MAR",
    "GOOGLE *CLOUD",
    "PYPL *EBAY",   # Should fail — eBay isn't in invoice list
    "WALMART STORES",   # Should fail — Walmart isn't there
]

# Sample alias_map (would come from VendorAlias DB in real use)
ALIASES = {
    "amzn mktpl*z89k3ks": "Amazon",
}

print("─── normalize ───")
for b in BANK_LINES[:3]:
    n = canonicalize(b)
    print(f"  {b:40s} → {n.canonical!r}")

print()
print("─── match each bank line ───")
for b in BANK_LINES:
    matches = find_matches(b, INVOICES, alias_map=ALIASES, threshold=0.5, top_k=2)
    if matches:
        top = matches[0]
        print(f"  {b:40s} → {top.invoice_vendor:30s} [{top.explain()}]")
    else:
        print(f"  {b:40s} → (no match above threshold)")
