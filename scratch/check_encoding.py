import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from history.models import GenerationRequest

req = GenerationRequest.objects.filter(kind='shorten').order_by('-created_at').first()
if req:
    print('SOURCE TEXT:\n', req.source_text)
    print('\nENGINE:\n', req.request_data.get('engine'))
    for res in req.results.all():
        content = res.content
        print(f'\nRESULT {res.position}:')
        print('REPR:', repr(content))
        print('HEX:', ' '.join(hex(ord(c)) for c in content[:20]))
        print('TEXT:', content)
else:
    print('No shorten requests found.')
