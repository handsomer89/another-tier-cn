#!/usr/bin/env python3
"""Check that cached nested modules cannot survive a collection code update."""

import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
apply_versions = runpy.run_path(str(ROOT / "scripts/version-collection-assets.py"))["apply_versions"]


class CollectionAssetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "assets").mkdir()
        (self.root / "collection").mkdir()
        for name, source in {
            "assets/collection.js": "import {render} from './collection-export.js';\nrender();\n",
            "assets/collection-export.js": 'import {status} from "./collection-data.js";\nexport const render = () => status;\n',
            "assets/collection-data.js": "export const status = 'owned';\n",
            "assets/collection.css": "body { color: black; }\n",
            "collection/index.html": '<link href="/another-tier-cn/assets/collection.css"><script type="module" src="/another-tier-cn/assets/collection.js"></script>',
        }.items():
            (self.root / name).write_text(source)

    def contents(self):
        return {str(path.relative_to(self.root)): path.read_text() for path in self.root.rglob('*') if path.is_file()}

    def test_nested_code_change_updates_imports_and_entry_url(self):
        apply_versions(self.root)
        before = self.contents()
        (self.root / "assets/collection-data.js").write_text("export const status = 'awakened';\n")
        with self.assertRaisesRegex(ValueError, "versions are stale"):
            apply_versions(self.root, check=True)
        apply_versions(self.root)
        after = self.contents()
        for name in ['assets/collection-export.js', 'assets/collection.js', 'collection/index.html']:
            self.assertNotEqual(before[name], after[name], name)
        self.assertEqual(before['assets/collection.css'], after['assets/collection.css'])
        for source in [after['assets/collection-export.js'], after['assets/collection.js'], after['collection/index.html']]:
            self.assertRegex(source, r'\.js\?v=[0-9a-f]{12}')
        self.assertEqual(apply_versions(self.root), 0)
        self.assertEqual(apply_versions(self.root, check=True), 0)

    def test_css_change_updates_stylesheet_url_without_changing_entry_version(self):
        apply_versions(self.root)
        before = self.contents()
        (self.root / "assets/collection.css").write_text("body { color: white; }\n")
        apply_versions(self.root)
        after = self.contents()
        self.assertEqual(before['assets/collection.js'], after['assets/collection.js'])
        self.assertNotEqual(before['collection/index.html'], after['collection/index.html'])
        self.assertRegex(after['collection/index.html'], r'\.css\?v=[0-9a-f]{12}')

    def test_check_and_invalid_html_do_not_partially_rewrite_modules(self):
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "versions are stale"):
            apply_versions(self.root, check=True)
        self.assertEqual(before, self.contents())
        (self.root / 'collection/index.html').write_text('<html></html>')
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "Expected one collection asset URL"):
            apply_versions(self.root)
        self.assertEqual(before, self.contents())


if __name__ == '__main__':
    unittest.main(verbosity=2)
