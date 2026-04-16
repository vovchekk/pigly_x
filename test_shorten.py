import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from assistant.services import (
    _extract_single_shorten_candidate, _normalize_shorten_candidate,
    _looks_like_hard_reject_shorten, _drops_required_shorten_signals,
    _is_overcompressed_shorten
)

src = """Season 3 of Rugpull Bakery is almost live. Here are the main changes coming to this season:

1) Solo bakeries. Group bakeries will return soon, but this season is focused on the individual baker.

2) The prize pool is now split between the top 100 users and a general activity user base. A large prize awaits the top users while casual players can participate throughout the season and still win.

3) Introducing the "Rug Reduction System". One of the main complaints in Season 2 has been rugs coming from alt accounts and small bakeries. Now, with the RRS, rugs effects are reduced from small attacking bakeries and rug costs spike if you try to land back to back rugs on the same bakery.

4) Only one boost and one rug can be applied to a bakery at a time. No more stacking of items. Instead, bakers will need to determine whether or not they want to take risks with expensive but better boosts, or play it safe with cheaper boosts.

5) Rug and boost cooldowns and costs have been adjusted to make for better pacing and less downtime."""

raw = '1. Rugpull Bakery Season 3 is live, featuring solo bakeries, a prize pool split between top 100 and general users, and a new "Rug Reduction System" to curb alt account rugs. 2. Only one boost/rug per bakery, no stacking. Rug/boost cooldowns and costs adjusted for better pacing.'

single = _extract_single_shorten_candidate(raw)
print("SINGLE:", repr(single))

norm = _normalize_shorten_candidate(single, 220)
print("NORM:", repr(norm))

print("hard_reject:", _looks_like_hard_reject_shorten(norm, src))
print("  drops_signals:", _drops_required_shorten_signals(norm, src))
print("  overcompressed:", _is_overcompressed_shorten(norm, src))
