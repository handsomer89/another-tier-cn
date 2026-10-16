#!/usr/bin/env python3
"""Check first-load URLs and cache invalidation when snapshot pixels change."""
import json
import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
images = runpy.run_path(str(ROOT / 'scripts/optimize-images.py'))
download = runpy.run_path(str(ROOT / 'scripts/download-images.py'))


class ImageSnapshots(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'assets').mkdir()
        for name, binding in images['RUNTIMES'].items():
            (self.root / 'assets' / name).write_text(f'var {binding}=e();')
        self.url = images['CDN'] + 'dpr_2.0/q_auto:low/portrait'
        self.snapshot = self.root / 'mirror-images/dpr_2.0/q_auto_low/portrait.webp'
        self.snapshot.parent.mkdir(parents=True)
        self.snapshot.write_bytes(b'first pixels')
        self.page = self.root / 'index.html'
        self.page.write_text(f'<link rel="preload" as="image" href="{self.url}"><img src="{self.url}" loading="lazy">')

    def manifest(self):
        return json.loads((self.root / 'assets/image-manifest.js').read_text().split('Object.freeze(', 1)[1][:-3])

    def test_html_and_preloads_use_versioned_snapshots_before_browser_loading(self):
        images['apply_images'](self.root)
        page = self.page.read_text()
        version = self.manifest()['dpr_2.0/q_auto_low/portrait.webp']
        local = '/another-tier-cn/mirror-images/dpr_2.0/q_auto_low/portrait.webp?v=' + version
        self.assertIn(f'src="{local}"', page)
        self.assertIn(f'href="{local}"', page)
        self.assertEqual(page.count(f'data-original-src="{self.url}"'), 2)
        self.assertEqual(images['apply_images'](self.root, check=True), 0)
        parser = download['Images']()
        parser.feed(page)
        self.assertEqual(parser.urls, {self.url}, 'download refresh still finds original CDN URLs')

    def test_same_url_image_refresh_changes_content_version_and_html(self):
        images['apply_images'](self.root)
        old_page, old_manifest = self.page.read_text(), self.manifest()
        self.snapshot.write_bytes(b'updated pixels at the same source URL')
        with self.assertRaisesRegex(ValueError, 'snapshots are stale'):
            images['apply_images'](self.root, check=True)
        self.assertEqual(self.page.read_text(), old_page, 'check mode never partially writes')
        images['apply_images'](self.root)
        self.assertNotEqual(self.manifest(), old_manifest)
        self.assertNotEqual(self.page.read_text(), old_page)
        self.assertEqual(self.page.read_text().count('data-original-src'), 2)

    def test_new_unmirrored_characters_remain_loadable_from_original_source(self):
        new_url = images['CDN'] + 'characters/new-character/portrait'
        self.page.write_text(f'<img src="{new_url}">')
        images['apply_images'](self.root)
        self.assertEqual(self.page.read_text(), f'<img src="{new_url}">')


if __name__ == '__main__':
    unittest.main(verbosity=2)
