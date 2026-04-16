import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from assistant.services import build_shorten_generation, _normalize_shorten_candidate

src = """Season 2 Rugpul Bakery на @AbstractChain завершается. 
Спасибо @OnchainChemists за организацию. 

Сезон испорчен автоматизацией и мультиаккаунтами. 
Прошу @AbstractChain и @OnchainChemists разобраться и наказать виновных, как указал @Azino_x. 

Моя команда Abstract CIS была сильна, но борьба с нечестными игроками испортила впечатление. 
В пекарне @0xCygaar тоже много читеров. Прошу забанить нарушителей правил."""

request_data, results = build_shorten_generation(source_text=src, language='ru', variant_count=1, target_length=300)

print("SOURCE HAS NEWLINES?", "\n" in src)
print("FIRST RESULT REPR:")
print(repr(results[0]))
print("\nFIRST RESULT CONTENT:")
print(results[0])
