"""Build a reviewed-source snapshot; never contact providers in the slide path."""
import html
import json
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import certifi
from django.core.management.base import BaseCommand, CommandError

TOPICS = {
    'nature': ['bird', 'butterfly', 'frog', 'beetle', 'mushroom', 'sloth'],
    'space': ['nebula', 'galaxy', 'planet', 'lunar crater', 'radio telescope'],
    'infrastructure': ['suspension bridge', 'aqueduct', 'hydroelectric dam', 'canal lock'],
    'objects': ['typewriter', 'teapot', 'clock mechanism', 'antique camera', 'mechanical calculator'],
    'food': ['citrus fruit', 'bread', 'spice', 'vegetable market'],
    'landscapes': ['sand dune', 'waterfall', 'volcano', 'glacier', 'cave'],
    'transport': ['steam locomotive', 'sailing ship', 'hot air balloon', 'bicycle', 'airship'],
    'architecture': ['lighthouse', 'spiral staircase', 'windmill', 'observatory', 'pagoda'],
    'microscopic': ['crystal microscopy', 'pollen microscopy', 'diatom'],
    'ocean': ['jellyfish', 'coral reef', 'octopus', 'deep sea fish'],
    'weather': ['lenticular cloud', 'lightning', 'aurora', 'rainbow'],
    'maps': ['historical map', 'celestial map', 'geological map'],
    'music': ['musical instrument', 'pipe organ', 'gramophone'],
    'patterns': ['tessellation', 'spiral shell', 'geometric tile'],
    'science': ['laboratory apparatus', 'orrery', 'pendulum', 'sundial'],
    'sport': ['curling sport', 'fencing sport', 'rowing boat'],
    'plants': ['cactus', 'orchid', 'fern', 'baobab'],
    'history': ['medieval manuscript', 'ancient coin', 'archaeological pottery'],
}
LICENSES = {'CC0': 'https://creativecommons.org/publicdomain/zero/1.0/', 'Public domain': 'https://creativecommons.org/publicdomain/mark/1.0/', 'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/', 'CC BY 3.0': 'https://creativecommons.org/licenses/by/3.0/', 'CC BY 2.0': 'https://creativecommons.org/licenses/by/2.0/'}

def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', '', value))).strip()

def fetch(url):
    req = Request(url, headers={'User-Agent': 'KwipSlides/0.1 (https://kwip.tech; tewert@kwip.info)'})
    with urlopen(req, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as response:
        return json.load(response)

def commons_item(page, topic):
    info = (page.get('imageinfo') or [{}])[0]
    meta = info.get('extmetadata', {})
    get = lambda k: plain(meta.get(k, {}).get('value', ''))
    license_name = get('LicenseShortName')
    image = info.get('thumburl', '')
    artist = get('Artist')
    title = get('ObjectName') or page.get('title', '').removeprefix('File:')
    if 'QS:' in title or len(title) > 180:
        title = page.get('title', '').removeprefix('File:').rsplit('.', 1)[0].replace('_', ' ')
    # Reject missing/ambiguous rights, SVG, unbounded credit blocks, and non-image records.
    if license_name not in LICENSES or not artist or len(artist) > 260 or not title or len(title) > 180:
        return None
    if info.get('mime') not in ('image/jpeg', 'image/png') or urlparse(image).hostname not in ('upload.wikimedia.org', 'thumb.wikimedia.org'):
        return None
    if info.get('width', 0) < 900 or info.get('height', 0) < 500 or get('Restrictions'):
        return None
    if re.search(r'\b(nude|naked|nudity|erotic|genital|sexual)\b', title, re.I):
        return None
    source = info.get('descriptionurl', '')
    if urlparse(source).hostname != 'commons.wikimedia.org':
        return None
    return {'id': f"commons-{page['pageid']}", 'kind': 'image', 'topic': topic, 'title': title, 'image': image, 'creator': artist, 'source': source, 'provider': 'Wikimedia Commons', 'license': license_name, 'license_url': LICENSES[license_name], 'credit': get('Credit'), 'changes': 'Unmodified image; scaled to fit.'}

class Command(BaseCommand):
    help = 'Refresh the bundled, attributed presentation catalog from approved public APIs.'
    def add_arguments(self, parser):
        parser.add_argument('--per-topic', type=int, default=50)
        parser.add_argument('--art-pages', type=int, default=8)
    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / 'data/catalog.json'
        old = json.loads(path.read_text()) if path.exists() else {'items': []}
        items = {item['id']: item for item in old['items']}
        added = 0
        for topic, query in [(topic, query) for topic, queries in TOPICS.items() for query in queries]:
            try:
                params = {'action': 'query', 'format': 'json', 'generator': 'search', 'gsrsearch': query + ' filetype:bitmap', 'gsrnamespace': 6, 'gsrlimit': max(1, min(50, options['per_topic'])), 'prop': 'imageinfo', 'iiprop': 'url|extmetadata|size|mime', 'iiurlwidth': 1600}
                pages = fetch('https://commons.wikimedia.org/w/api.php?' + urlencode(params)).get('query', {}).get('pages', {})
                for page in pages.values():
                    item = commons_item(page, topic)
                    if item:
                        items[item['id']] = item
                        added += 1
                self.stdout.write(f'{topic} / {query}: checked {len(pages)}; catalog {len(items)}')
            except Exception as exc:
                self.stderr.write(f'{topic}: {type(exc).__name__}; retained previous content')
            time.sleep(0.2)
        for page in range(1, max(1, min(20, options['art_pages'])) + 1):
            try:
                data = fetch('https://api.artic.edu/api/v1/artworks?' + urlencode({'page': page, 'limit': 100, 'fields': 'id,title,artist_display,date_display,image_id,is_public_domain,artwork_type_title'}))
                for art in data['data']:
                    if not art.get('is_public_domain') or not art.get('image_id') or not art.get('artist_display'):
                        continue
                    if re.search(r'\b(nude|naked|nudity|erotic|genital|sexual)\b', art['title'], re.I):
                        continue
                    item = {'id': f"aic-{art['id']}", 'kind': 'image', 'topic': 'art', 'title': art['title'], 'subtitle': art['date_display'], 'image': f"https://www.artic.edu/iiif/2/{art['image_id']}/full/1686,/0/default.jpg", 'creator': art['artist_display'], 'source': f"https://www.artic.edu/artworks/{art['id']}", 'provider': 'Art Institute of Chicago', 'license': 'CC0', 'license_url': LICENSES['CC0'], 'credit': 'Courtesy of the Art Institute of Chicago', 'changes': 'Unmodified image; scaled to fit.'}
                    items[item['id']] = item
                    added += 1
                self.stdout.write(f'art page {page}: catalog {len(items)}')
            except Exception as exc:
                self.stderr.write(f'art: {type(exc).__name__}; retained previous content')
            time.sleep(0.25)
        if added < 10:
            raise CommandError('Insufficient source responses; existing snapshot was not replaced.')
        generated_path = path.with_name('generated.json')
        if generated_path.exists():
            for item in json.loads(generated_path.read_text())['items']:
                item['generated'] = True
                items[item['id']] = item
        unique = {}
        seen = set()
        for item in items.values():
            if item['kind'] == 'image':
                key = (re.sub(r'\s+\(?\d+\)?$', '', item['title'].strip().lower()), item['creator'].lower())
                if key in seen:
                    continue
                seen.add(key)
            unique[item['id']] = item
        items = unique
        result = {'version': 1, 'refreshed_at': datetime.now(timezone.utc).isoformat(), 'items': list(items.values())}
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
        temporary.replace(path)
        self.stdout.write(self.style.SUCCESS(f'Saved {len(items)} items. Review the diff before publishing.'))
