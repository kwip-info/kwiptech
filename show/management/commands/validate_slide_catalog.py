"""Fail deployment checks on incomplete sources, duplicate IDs or missing local art."""
import json
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help = 'Validate the publishable slideshow content snapshot.'
    def handle(self, *args, **options):
        data = json.loads((settings.BASE_DIR / 'show/data/catalog.json').read_text())
        items = data['items']
        errors = []
        if len(items) < 892:
            errors.append('Catalog must contain at least 892 distinct items.')
        if len({item['id'] for item in items}) != len(items):
            errors.append('Duplicate item IDs.')
        for item in items:
            if item['kind'] not in ('image', 'prompt', 'chart') or not item['title']:
                errors.append(f"Invalid content: {item['id']}")
            if item['kind'] == 'chart':
                if len(item['labels']) != len(item['values']) or not all(0 <= n <= 100 for n in item['values']):
                    errors.append(f"Invalid chart: {item['id']}")
            if item['kind'] != 'image':
                continue
            for field in ('creator', 'source', 'license', 'license_url', 'credit', 'changes'):
                if field not in item or (field != 'credit' and not item[field]):
                    errors.append(f"Missing {field}: {item['id']}")
            image = urlparse(item['image'])
            if item.get('generated'):
                if not item['image'].startswith('/static/show/originals/') or '..' in Path(image.path).parts or not (settings.BASE_DIR / image.path.lstrip('/')).is_file():
                    errors.append(f"Missing local original: {item['id']}")
                if 'AI-generated' not in item['credit']:
                    errors.append(f"Missing AI disclosure: {item['id']}")
            elif image.scheme != 'https' or image.hostname not in ('www.artic.edu', 'upload.wikimedia.org', 'thumb.wikimedia.org'):
                errors.append(f"Unexpected image host: {item['id']}")
        if errors:
            raise CommandError('\n'.join(errors))
        self.stdout.write(self.style.SUCCESS(f'Validated {len(items)} distinct content items.'))
