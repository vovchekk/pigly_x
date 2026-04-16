import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from assistant.services import _call_gemini_text, _build_shorten_prompt, _parse_numbered_items, _normalize_shorten_candidate, _looks_like_weak_shorten, _drops_required_shorten_signals, _drops_multi_section_balance, _is_overcompressed_shorten

src = """Onchain Heroes - Devlog #5

> Marketplace launching soon 
> New stable currency: Valor (pegged to $USD, bought with USDC) 
> $HERO transitions to premium currency with exclusive access 
> Energy earned in MoG carries over to OCH World
> Ringbearers awaken - weekly caches for Ring holders Item system in MoG drops tomorrow

One universe. One economy. 🔗"""

prompt = _build_shorten_prompt(source_text=src, language='en', variant_count=1, target_length=220)
print("PROMPT INSTRUCTION (check if list_instruction is there):\n", prompt[:1500])

raw = _call_gemini_text(prompt=prompt, max_output_tokens=600, temperature=0.25, top_p=0.75)
print("\nRAW Output:\n", repr(raw))

parsed = _parse_numbered_items(raw, 3)
print("\nParsed Items:\n", parsed)

for p in parsed:
    norm = _normalize_shorten_candidate(p, 220)
    print("\nNorm:\n", repr(norm))
    print("Drops signals:", _drops_required_shorten_signals(norm, src))
    print("Drops balance:", _drops_multi_section_balance(norm, src))
    print("Is overcompressed:", _is_overcompressed_shorten(norm, src))
    print("Is weak:", _looks_like_weak_shorten(norm, src))
