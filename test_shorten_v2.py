import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from assistant.services import (
    _call_gemini_text, _build_shorten_prompt, _extract_single_shorten_candidate,
    _normalize_shorten_candidate
)

src = """Season 3 of Rugpull Bakery is almost live. Here are the main changes coming to this season:

1) Solo bakeries. Group bakeries will return soon, but this season is focused on the individual baker.

2) The prize pool is now split between the top 100 users and a general activity user base. A large prize awaits the top users while casual players can participate throughout the season and still win.

3) Introducing the "Rug Reduction System". One of the main complaints in Season 2 has been rugs coming from alt accounts and small bakeries. Now, with the RRS, rugs effects are reduced from small attacking bakeries and rug costs spike if you try to land back to back rugs on the same bakery.

4) Only one boost and one rug can be applied to a bakery at a time. No more stacking of items. Instead, bakers will need to determine whether or not they want to take risks with expensive but better boosts, or play it safe with cheaper boosts.

5) Rug and boost cooldowns and costs have been adjusted to make for better pacing and less downtime."""

prompt = _build_shorten_prompt(source_text=src, language='en', variant_count=1, target_length=220)
raw = _call_gemini_text(prompt=prompt, max_output_tokens=600, temperature=0.4, top_p=0.8)

print("--- RAW AI OUTPUT ---")
print(raw)
print("---------------------")

single = _extract_single_shorten_candidate(raw)
norm = _normalize_shorten_candidate(single, 220)

print("\n--- NORMALIZED OUTPUT (SENT TO FRONTEND) ---")
print(norm)
print("--------------------------------------------")
