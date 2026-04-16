import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from assistant.services import build_shorten_generation

src = """Onchain Heroes - Devlog #5

> Marketplace launching soon 
> New stable currency: Valor (pegged to $USD, bought with USDC) 
> $HERO transitions to premium currency with exclusive access 
> Energy earned in MoG carries over to OCH World
> Ringbearers awaken - weekly caches for Ring holders Item system in MoG drops tomorrow

One universe. One economy. 🔗"""

print(build_shorten_generation(source_text=src, language='en', variant_count=3, target_length=220))
