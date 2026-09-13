from whitenoise.storage import CompressedManifestStaticFilesStorage

class SlideStaticStorage(CompressedManifestStaticFilesStorage):
    """Fingerprint the complete ES module graph, including .mjs dependencies."""
    support_js_module_import_aggregation = True

    def __init__(self, *args, **kwargs):
        self.patterns += (('*.mjs', self._js_module_import_aggregation_patterns[1]),)
        super().__init__(*args, **kwargs)
