from assistant.services import _normalize_shorten_candidate, _extract_single_shorten_candidate

text = """1. - First point
- Second point
- Third point"""

print("SINGLE CANDIDATE EXTRACTION:")
extracted = _extract_single_shorten_candidate(text)
print(repr(extracted))

print("\nNORMALIZATION:")
norm = _normalize_shorten_candidate(extracted, 220)
print(repr(norm))

text2 = """1. First major point
2. Second major point"""
print("\nMULTIPLE POINTS IN ONE VARIANT:")
extracted2 = _extract_single_shorten_candidate(text2)
print(repr(extracted2))
