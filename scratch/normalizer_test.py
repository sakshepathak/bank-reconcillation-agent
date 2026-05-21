"""Spot-check the vendor normalizer on real bank description patterns."""
import sys
sys.path.insert(0, "/app")

from engine.vendor_matching.normalizer import canonicalize

CASES = [
    "AMZN MKTPL*Z89K3KS",
    "SQ *COFFEE NETWO SAN FRANCISCO CA",
    "PYPL *EBAY",
    "STRIPE *ACME CORP",
    "POS PURCHASE DEBIT CARD AMAZON.COM*1A2B3C",
    "ACH DEBIT NETFLIX.COM 03/12 #1234567",
    "Amazon.com, Inc.",
    "Stripe Inc",
    "The Daily Bean Pvt. Ltd.",
    "UBER *TRIP 12MAR LONDON UK",
    "GOOGLE *YOUTUBE PREMIUM",
    "WIRE TRANSFER ACME PVT LTD REF# ABCD1234",
]

w = max(len(c) for c in CASES)
print(f"{'raw'.ljust(w)} | canonical")
print("-" * (w + 25))
for raw in CASES:
    n = canonicalize(raw)
    print(f"{raw.ljust(w)} | {n.canonical}")
