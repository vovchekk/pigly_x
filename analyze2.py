import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from assistant.services import _looks_like_weak_shorten

src = """Onchain Heroes - Devlog #5

> Marketplace launching soon 
> New stable currency: Valor (pegged to $USD, bought with USDC) 
> $HERO transitions to premium currency with exclusive access 
> Energy earned in MoG carries over to OCH World
> Ringbearers awaken - weekly caches for Ring holders Item system in MoG drops tomorrow

One universe. One economy. 🔗"""

text = 'Onchain Heroes devlog: Marketplace launching soon, new stable currency Valor (pegged to $USD), $HERO becomes premium. Energy earned in MoG carries over to OCH World Ringbearers awaken - weekly caches for Ring holders Item system in MoG drops tomorrow.'
print("Result:", _looks_like_weak_shorten(text, src))
