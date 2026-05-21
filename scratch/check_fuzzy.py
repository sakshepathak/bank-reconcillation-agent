from rapidfuzz import fuzz
s1 = "amzn mktpl *1a2b"
s2 = "amazon marketplace"
print(f"Token Set Ratio: {fuzz.token_set_ratio(s1, s2)}")
