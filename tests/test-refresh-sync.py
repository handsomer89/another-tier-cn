#!/usr/bin/env python3
"""Offline refresh regression tests; all writes and fake responses stay in /tmp."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


refresh = load_script("refresh-rankings")
images = load_script("download-images")


def ranking_page(cards, timestamp=100, local=False, text="Ranking"):
    data = {
        "characterMap": {"map": [[card["slug"], card] for card in cards]},
        "personalitiesSet": {"set": []}, "rolesMap": {"map": []},
        "tierMap": {"map": [["S", {"set": [card["slug"] for card in cards]}]]},
    }
    base = refresh.BASE if local else ""
    articles = "".join(f'<article><a href="{base}/c/{card["slug"]}">{card["name"]}</a></article>' for card in cards)
    return (f'<html><head><title>Tier</title></head><body><p>{text}</p><section class="peer">{articles}</section>'
            f'<script>state:$R[1]={{data:{refresh.js_value(data)},dataUpdateCount:1,dataUpdatedAt:{timestamp}}};'
            f'u:{timestamp},s:"success",dehydratedAt:{timestamp}</script></body></html>')


def detail_page(detail, timestamp=100, text="Detail"):
    slug = detail["slug"]
    loader = {"title": detail["name"], "description": "Character detail", "slug": slug}
    query_hash = json.dumps(json.dumps(["character", slug], separators=(",", ":")))
    return (f'<html><head><title>{detail["name"]}</title></head><body><main><p>{text}</p></main>'
            f'<script>l:$R[2]={refresh.js_value(loader)},ssr:true;'
            f'state:$R[1]={{data:{refresh.js_value(detail)},dataUpdateCount:1,dataUpdatedAt:{timestamp}}};'
            f'queryKey:$R[3]=["character","{slug}"],queryHash:{query_hash};'
            f'u:{timestamp},s:"success",dehydratedAt:{timestamp}</script></body></html>')


class RefreshSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="tier-sync-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "mirror"
        self.source = Path(self.temporary.name) / "source"
        self.root.mkdir()
        self.source.mkdir()
        # Real cached card/detail fields exercise representation differences such
        # as ranking role strings versus the detail page's role objects.
        self.card = json.loads((ROOT / "data/characters/paid.json").read_text())[0]
        self.detail = json.loads((ROOT / f'data/characters/{self.card["slug"]}.json').read_text())
        self.assertEqual(refresh.character_changes(self.card, self.detail), [])
        self.root_patch = mock.patch.object(refresh, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.output_patch = mock.patch("sys.stdout", new=io.StringIO())
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)
        self.write_fixture([self.card], {self.card["slug"]: self.detail})

    def write(self, root, filename, source):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def write_fixture(self, cards, details):
        for filename, route in refresh.ROUTES.items():
            if not (self.root / filename).exists():
                self.write(self.root, filename, ranking_page([self.card], local=True))
            cached = "index.html" if route == "/" else route[1:] + ".html"
            self.write(self.source, cached, ranking_page(cards, timestamp=200))
        self.write(self.root, f'c/{self.card["slug"]}/index.html', detail_page(self.detail))
        for slug, detail in details.items():
            self.write(self.source, f"c/{slug}/index.html", detail_page(detail, timestamp=200))

    def test_default_incremental_skips_unchanged_details(self):
        # No cached detail must be needed by existing callers' default mode.
        (self.source / f'c/{self.card["slug"]}/index.html').unlink()
        outputs = refresh.prepare_outputs(self.source)
        self.assertEqual(len(outputs), 3)
        self.assertEqual(dict(outputs)["index.html"], (self.root / "index.html").read_text())

    def test_full_scan_accepts_detail_only_changes(self):
        changed = copy.deepcopy(self.detail)
        changed["commentary"] = "New commentary without any ranking edit"
        changed["otherVersions"] = [{"slug": "offline-new-version", "name": "Offline version"}]
        self.write_fixture([self.card], {self.card["slug"]: changed})
        outputs = dict(refresh.prepare_outputs(self.source, full_details=True))
        path = f'c/{self.card["slug"]}/index.html'
        match, data = refresh.extract_data(outputs[path])
        self.assertEqual(data, changed)
        self.assertEqual(match[4], "200")
        self.assertIn('u:200,s:"success",dehydratedAt:200', outputs[path])

    def test_full_scan_keeps_timestamps_but_accepts_html_changes(self):
        outputs = dict(refresh.prepare_outputs(self.source, full_details=True))
        for path, content in outputs.items():
            self.assertEqual(content, (self.root / path).read_text(), path)
            self.assertEqual(refresh.extract_data(content)[0][4], "100")
        upstream = detail_page(self.detail, timestamp=300, text="Updated rendered content")
        result = refresh.refresh_character(detail_page(self.detail), upstream, self.card)
        self.assertIn("Updated rendered content", result)
        self.assertEqual(refresh.extract_data(result)[0][4], "100")
        self.assertIn('u:100,s:"success",dehydratedAt:100', result)
        # A rendered ranking change must be copied even with identical data.
        upstream = ranking_page([self.card], timestamp=400).replace(self.card["name"] + "</a>", "Updated card</a>")
        result, _, _, timestamp = refresh.refresh(ranking_page([self.card], local=True), upstream)
        self.assertIn("Updated card</a>", result)
        self.assertEqual(timestamp, "100")

    def test_new_character_and_can_sa_changes_refresh_details_and_slugs(self):
        changed_card = {**self.card, "canSA": not self.card["canSA"]}
        changed_detail = {**self.detail, "canSA": changed_card["canSA"]}
        new_card = {**self.card, "slug": "offline-new-character", "canSA": True}
        new_detail = {**self.detail, "slug": new_card["slug"], "canSA": True}
        self.write_fixture([changed_card, new_card], {self.card["slug"]: changed_detail, new_card["slug"]: new_detail})
        outputs = dict(refresh.prepare_outputs(self.source))
        self.assertEqual(len(outputs), 5)
        for card in (changed_card, new_card):
            page = outputs[f'c/{card["slug"]}/index.html']
            self.assertEqual(refresh.extract_data(page)[1]["canSA"], card["canSA"])
            self.assertEqual(refresh.extract_data(page)[1]["slug"], card["slug"])
            self.assertIn(f'queryKey:$R[3]=["character","{card["slug"]}"]', page)

    def test_invalid_source_never_partially_writes(self):
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*.html")}
        self.write(self.source, f'c/{self.card["slug"]}/index.html', detail_page({**self.detail, "slug": "wrong-slug"}))
        with mock.patch.object(sys, "argv", ["refresh-rankings.py", "--source-dir", str(self.source), "--full-details"]), \
                mock.patch.object(refresh.subprocess, "run", wraps=subprocess.run) as run:
            with self.assertRaisesRegex(ValueError, "disagrees with rankings"):
                refresh.main()
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*.html")}
        self.assertEqual(after, before)
        self.assertTrue(all(call.args[0][0] == "node" for call in run.call_args_list))

    def test_rank_card_and_detail_consistency_checks_remain(self):
        invalid = ranking_page([self.card]).replace('/c/' + self.card["slug"], '/c/wrong-slug')
        with self.assertRaisesRegex(ValueError, "Rendered cards"):
            refresh.refresh(ranking_page([self.card]), invalid)
        invalid_detail = {**self.detail, "canSA": not self.card["canSA"]}
        with self.assertRaisesRegex(ValueError, "disagrees with rankings"):
            refresh.refresh_character(detail_page(self.detail), detail_page(invalid_detail), self.card)

    def test_flags_forward_image_refresh_and_preserve_default_command(self):
        for flags, expected in (([], []), (["--full-details", "--refresh-images"], ["--refresh"])):
            with self.subTest(flags=flags), \
                    mock.patch.object(sys, "argv", ["refresh-rankings.py", *flags]), \
                    mock.patch.object(refresh, "prepare_outputs", return_value=[]) as prepare, \
                    mock.patch.object(refresh.subprocess, "run") as run:
                refresh.main()
                prepare.assert_called_once_with(None, full_details="--full-details" in flags)
                commands = [call.args[0] for call in run.call_args_list]
                image_command = next(command for command in commands if Path(command[1]).name == "download-images.py")
                self.assertEqual(image_command[2:], expected)


class ImageSyncTests(unittest.TestCase):
    def test_collection_only_variants_are_downloadable_and_html_rules_stay(self):
        with tempfile.TemporaryDirectory(prefix="tier-image-test-") as directory:
            root = Path(directory)
            card = {"slug": "offline-new-character", "canSA": True, "elements": ["new-element"],
                    "lightShadow": "new-light", "weapon": "new-weapon", "armor": "new-armor"}
            (root / "data").mkdir()
            (root / "data/collection.json").write_text(json.dumps({"characters": [card]}))
            old_url = images.CDN + "static-only"
            (root / "index.html").write_text(f'<img src="{old_url}"><img src="{old_url}"><a href="{images.CDN}not-an-image">link</a>')
            (root / "dist").mkdir()
            (root / "dist/index.html").write_text(f'<img src="{images.CDN}excluded-dist">')
            with mock.patch.object(images, "ROOT", root):
                urls = images.image_urls()
                self.assertEqual(len(urls), 8)
                self.assertEqual(len(set(map(images.image_path, urls))), len(urls))
                self.assertIn(old_url, urls)
                self.assertTrue(any("elements/new-element" in url for url in urls))
                self.assertTrue(any("e_grayscale/" in url for url in urls))
                # Reuse the real catalog validator to ensure both scripts agree
                # on every collection image variant without circular imports.
                for url in urls:
                    path = images.image_path(url)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"cached")
                collection = load_script("generate-collection")
                self.assertEqual(collection.validate_images({"characters": [card]}, root), 7)

    def test_refresh_updates_same_url_and_default_skips_existing(self):
        with tempfile.TemporaryDirectory(prefix="tier-image-test-") as directory, \
                mock.patch.object(images, "ROOT", Path(directory)), \
                mock.patch.object(images, "urlopen") as fetch:
            url = images.CDN + "same-url"
            path = images.image_path(url)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"old image")
            self.assertFalse(images.download(url))
            fetch.assert_not_called()
            fresh = b"RIFF\x00\x00\x00\x00WEBPnew image"
            fetch.return_value.__enter__.return_value.read.return_value = fresh
            self.assertTrue(images.download(url, refresh=True))
            self.assertEqual(path.read_bytes(), fresh)
            fetch.return_value.__enter__.return_value.read.return_value = b"invalid response"
            with self.assertRaises(ValueError):
                images.download(url, refresh=True)
            self.assertEqual(path.read_bytes(), fresh)


class BrowserSnapshotTests(unittest.TestCase):
    def test_api_first_and_validated_snapshot_fallback_semantics(self):
        program = r"""
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { pathToFileURL } = require('node:url');
const source = readFileSync(process.argv[2], 'utf8');
const readSnapshot = new Function(source
  .replace('export async function', 'return async function')
  .replaceAll('import.meta.url', JSON.stringify(pathToFileURL(process.argv[2]).href)))();
(async () => {
  let remoteCalls = 0;
  const remote = async () => { remoteCalls++; return { name: 'remote' }; };
  const parse = value => { if (typeof value?.name !== 'string') throw new Error('invalid data'); return value.name; };
  let snapshotCalls = 0;
  global.fetch = async (url, options) => {
    snapshotCalls++;
    assert.match(url.href, /\/data\/characters\/new%20slug\.json$/);
    assert.equal(options.cache, 'no-cache');
    return { ok: true, json: async () => ({ name: 'local' }) };
  };
  assert.equal(await readSnapshot('new slug', remote, parse), 'remote');
  assert.equal(remoteCalls, 1);
  assert.equal(snapshotCalls, 0, 'successful API does not request the static snapshot');
  for (const unavailable of [
    async () => { throw new Error('offline'); },
    async () => ({}),
    () => { throw new Error('synchronous failure'); },
  ]) assert.equal(await readSnapshot('new slug', unavailable, parse), 'local');
  assert.equal(snapshotCalls, 3);
  const realSetTimeout = global.setTimeout;
  const realClearTimeout = global.clearTimeout;
  let timerCleared = false;
  global.setTimeout = callback => realSetTimeout(callback, 1);
  global.clearTimeout = timer => { timerCleared = true; realClearTimeout(timer); };
  assert.equal(await readSnapshot('new slug', () => new Promise(() => {}), parse), 'local');
  assert.equal(timerCleared, true);
  global.setTimeout = realSetTimeout;
  global.clearTimeout = realClearTimeout;
  for (const fetch of [
    async () => ({ ok: false }),
    async () => { throw new Error('offline'); },
    async () => ({ ok: true, json: async () => { throw new Error('invalid JSON'); } }),
  ]) {
    global.fetch = fetch;
    await assert.rejects(readSnapshot('new slug', async () => { throw new Error('API unavailable'); }, parse));
  }
  global.fetch = async () => ({ok: true, json: async () => ({})});
  await assert.rejects(readSnapshot('new slug', async () => { throw new Error('API unavailable'); }, parse), /API unavailable/);
  global.fetch = async () => { throw new Error('snapshot must not load'); };
  assert.equal(await readSnapshot('new slug', remote, parse), 'remote');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        subprocess.run(["node", "-", str(ROOT / "assets/character-snapshot.js")], input=program, text=True, check=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
