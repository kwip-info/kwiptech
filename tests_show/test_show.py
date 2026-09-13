from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from show.management.commands.refresh_slide_catalog import commons_item
from show.settings import MIDDLEWARE as SHOW_MIDDLEWARE

@override_settings(MIDDLEWARE=SHOW_MIDDLEWARE, STORAGES={'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}, ROOT_URLCONF='show.urls', SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'])
class SlideTests(SimpleTestCase):
    def test_home_and_catalog_need_no_database(self):
        self.assertContains(self.client.get('/'), 'Take it')
        data = self.client.get('/api/slides/catalog').json()
        self.assertGreaterEqual(len(data['items']), 892)
        ids = [i['id'] for i in data['items']]
        self.assertEqual(len(ids), len(set(ids)))
        for item in data['items']:
            if item['kind'] == 'image':
                for field in ('source', 'creator', 'license', 'license_url', 'image'):
                    self.assertTrue(item[field])
    def test_retirement_never_accepts_mutation(self):
        for url in ['/api/v2/datasets','/api/v2/billing/checkout','/integrations/stripe','/v1/sync/batch']:
            self.assertEqual(self.client.post(url, b'invalid', content_type='application/json').status_code, 410)
    def test_health_and_redirects(self):
        self.assertEqual(self.client.get('/healthz').json()['service'], 'kwip-slides')
        for url, target in [('/digest','digest/'),('/docs/migration.md','pyscoped/docs/migration/'),('/privacy','privacy/')]:
            self.assertEqual(self.client.get(url)['Location'], 'https://kwip.info/technology/'+target)
        self.assertEqual(self.client.get('/does-not-exist').status_code, 404)
    def test_commons_rejects_missing_rights_and_html_is_plain(self):
        self.assertIsNone(commons_item({'imageinfo':[{}]},'nature'))
        record={'pageid':1,'title':'File:Test','imageinfo':[{'mime':'image/jpeg','width':1600,'height':900,'thumburl':'https://upload.wikimedia.org/test.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:Test','extmetadata':{'Artist':{'value':'<a href="x">Creator</a>'},'LicenseShortName':{'value':'CC BY 4.0'}}}]}
        item=commons_item(record,'nature')
        self.assertEqual(item['creator'],'Creator')
        record['imageinfo'][0]['extmetadata']['LicenseShortName']['value']='CC BY-NC 4.0'
        self.assertIsNone(commons_item(record,'nature'))
    def test_catalog_served_without_upstream_calls(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            self.assertEqual(self.client.get('/api/slides/catalog').status_code,200)

    def test_content_disclosure_and_compression(self):
        self.assertContains(self.client.get('/about/content'), 'AI-generated illustration')
        response = self.client.get('/api/slides/catalog', HTTP_ACCEPT_ENCODING='gzip')
        self.assertEqual(response['Content-Encoding'], 'gzip')

    def test_generated_assets_are_local_and_labeled(self):
        from pathlib import Path
        from show.urls import catalog
        generated = [item for item in catalog()['items'] if item.get('generated')]
        self.assertEqual(len(generated), 4)
        for item in generated:
            self.assertTrue(item['image'].startswith('/static/show/originals/'))
            self.assertTrue(Path(item['image'].lstrip('/')).is_file())
            self.assertIn('AI-generated', item['credit'])

    def test_module_imports_are_fingerprinted(self):
        import tempfile
        from pathlib import Path
        from django.core.management import call_command
        from django.contrib.staticfiles.storage import staticfiles_storage
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(STATIC_ROOT=directory, STORAGES={'staticfiles': {'BACKEND': 'show.storage.SlideStaticStorage'}}):
                call_command('collectstatic', interactive=False, verbosity=0)
                storage = staticfiles_storage
                app = (Path(directory) / storage.stored_name('show/app.js')).read_text()
                engine = (Path(directory) / storage.stored_name('show/engine.mjs')).read_text()
                self.assertIn(Path(storage.stored_name('show/engine.mjs')).name, app)
                self.assertIn(Path(storage.stored_name('show/motion.mjs')).name, engine)
