#!/usr/bin/env python3
"""Refresh rankings and changed character details, including hydration data.

Requires Python 3 and Node.js. Existing localized bundles and page chrome stay intact.
"""

import argparse
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {"index.html": "/", "free/index.html": "/free", "no-sa/index.html": "/no-sa"}
DATA = re.compile(r"(state:\$R\[\d+\]=\{data:)(.*?)(,dataUpdateCount:1,dataUpdatedAt:)(\d+)", re.S)
LOADER = re.compile(r"(l:\$R\[\d+\]=)(\{.*?\})(,ssr:)", re.S)
BASE = "/another-tier-cn"


class TierSection(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.offsets = [0] + [m.end() for m in re.finditer("\n", source)]
        self.depth = 0
        self.spans = []

    def source_offset(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag == "section":
            if self.depth:
                self.depth += 1
            elif dict(attrs).get("class") == "peer":
                self.start = self.source_offset()
                self.depth = 1

    def handle_endtag(self, tag):
        if tag == "section" and self.depth:
            self.depth -= 1
            if not self.depth:
                end = self.source.index(">", self.source_offset()) + 1
                self.spans.append((self.start, end))


def tier_span(source):
    parser = TierSection(source)
    parser.feed(source)
    if len(parser.spans) != 1:
        raise ValueError("Expected exactly one rendered tier list")
    return parser.spans[0]


def extract_data(source):
    matches = list(DATA.finditer(source))
    if len(matches) != 1:
        raise ValueError("Expected exactly one hydrated character query")
    match = matches[0]
    return match, evaluate(match[2])


def evaluate(expression):
    # Evaluate only a captured data expression, in an isolated context with a timeout.
    program = r"""
const fs = require('node:fs'), vm = require('node:vm');
const data = vm.runInNewContext('(' + fs.readFileSync(0, 'utf8') + ')', {$R: []}, {timeout: 5000});
console.log(JSON.stringify(data, (_, value) => {
  if (Object.prototype.toString.call(value) === '[object Map]') return {map: [...value]};
  if (Object.prototype.toString.call(value) === '[object Set]') return {set: [...value]};
  return value;
}));
"""
    result = subprocess.run(["node", "-e", program], input=expression, text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def js_value(value):
    if isinstance(value, dict):
        if list(value) == ["map"]:
            return "new Map(" + js_value(value["map"]) + ")"
        if list(value) == ["set"]:
            return "new Set(" + js_value(value["set"]) + ")"
        return "{" + ",".join(json.dumps(k) + ":" + js_value(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(map(js_value, value)) + "]"
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def refresh(original, upstream):
    old_match, old_data = extract_data(original)
    new_match, new_data = extract_data(upstream)
    if not new_data.get("characterMap", {}).get("map"):
        raise ValueError("Upstream character data is empty")
    start, end = tier_span(upstream)
    section = upstream[start:end]
    cards = re.findall(r'<article\b.*?href="/c/([^"?]+)"', section, re.S)
    expected = [slug for _, slugs in new_data["tierMap"]["map"] for slug in slugs["set"]]
    if cards != expected or len(cards) != len(set(cards)):
        raise ValueError("Rendered cards do not match embedded tier data")
    section = section.replace('href="/c/', 'href="/another-tier-cn/c/')
    replacement = old_match[1] + js_value(new_data) + old_match[3] + new_match[4]
    result = original[:old_match.start()] + replacement + original[old_match.end():]
    start, end = tier_span(result)
    result = result[:start] + section + result[end:]
    # The router's successful loader timestamp should agree with the refreshed query.
    result = result.replace('u:' + old_match[4], 'u:' + new_match[4])
    return result, old_data, new_data, new_match[4]


def character_changes(card, detail):
    """Compare ranking fields, ignoring representation and ordering differences."""
    def normalize(key, value):
        if key in ("roles", "classTomes") and isinstance(value, list):
            value = [item["name"] if isinstance(item, dict) else item for item in value]
        return sorted(value) if isinstance(value, list) else value

    return [key for key, value in card.items()
            if normalize(key, value) != normalize(key, detail.get(key))]


def main_span(source):
    matches = list(re.finditer(r"<main\b[^>]*>.*?</main>", source, re.S))
    if len(matches) != 1:
        raise ValueError("Expected exactly one character main element")
    return matches[0]


def refresh_character(original, upstream, card):
    """Keep the local app shell and asset manifest while updating character content."""
    old_match, old_data = extract_data(original)
    new_match, new_data = extract_data(upstream)
    if new_data.get("slug") != card["slug"] or character_changes(card, new_data):
        raise ValueError(f"Character detail disagrees with rankings: {card['slug']}")
    old_loader, new_loader = LOADER.search(original), LOADER.search(upstream)
    if not old_loader or not new_loader:
        raise ValueError("Expected character loader metadata")
    loader = evaluate(new_loader[2])
    result = original[:old_loader.start(2)] + js_value(loader) + original[old_loader.end(2):]
    # Recalculate the data span after replacing loader metadata.
    old_match, _ = extract_data(result)
    replacement = old_match[1] + js_value(new_data) + old_match[3] + new_match[4]
    result = result[:old_match.start()] + replacement + result[old_match.end():]
    start, end = main_span(result).span()
    body = main_span(upstream)[0]
    body = re.sub(r'(href|src)="(/(?!/))', rf'\1="{BASE}\2', body)
    result = result[:start] + body + result[end:]
    result = re.sub(r'\bu:\d+(?=,s:"success")', 'u:' + new_match[4], result)
    result = re.sub(r'\bdehydratedAt:\d+', 'dehydratedAt:' + new_match[4], result)

    # A new character uses an existing detail page as its compatible local shell.
    old_slug, slug = old_data["slug"], new_data["slug"]
    result = result.replace('\\u0000' + old_slug + '\\u0000', '\\u0000' + slug + '\\u0000')
    result = re.sub(r'(queryKey:\$R\[\d+\]=)\["character","[^"]+"\]',
                    lambda match: match[1] + js_value(["character", slug]), result)
    old_hash = json.dumps(json.dumps(["character", old_slug], separators=(",", ":")))
    new_hash = json.dumps(json.dumps(["character", slug], separators=(",", ":")))
    result = result.replace('queryHash:' + old_hash, 'queryHash:' + new_hash)

    # Copy only character-specific head tags; keep local bundles, CSS and entrypoints.
    result = re.sub(r'<title>.*?</title>', lambda _: re.search(r'<title>.*?</title>', upstream)[0], result, count=1)
    for name in ("og:title", "twitter:title", "description", "og:description", "twitter:description",
                 "og:url", "twitter:url", "og:image", "twitter:image"):
        pattern = rf'<meta name="{re.escape(name)}"[^>]*>'
        tag = re.search(pattern, upstream)
        if tag:
            result = re.sub(pattern, lambda _: tag[0], result, count=1)
    pattern = r'<link rel="canonical"[^>]*>'
    canonical = re.search(pattern, upstream)
    if canonical:
        result = re.sub(pattern, lambda _: canonical[0], result, count=1)
    image_preload = r'<link\b(?=[^>]*\bas="image")[^>]*>'
    result = re.sub(image_preload, '', result)
    images = ''.join(re.findall(image_preload, upstream))
    result = result.replace('</head>', images + '</head>', 1)
    return result


def fetch_source(route, source_dir):
    if source_dir:
        filename = "index.html" if route == "/" else route[1:] + ".html"
        if route.startswith("/c/"):
            filename = route[1:] + "/index.html"
        return (source_dir / filename).read_text(encoding="utf-8")
    request = Request("https://anothertier.com" + route, headers={"User-Agent": "Another-Tier-CN snapshot refresh"})
    with urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8")


def prepare_outputs(source_dir=None):
    outputs = []
    characters = {}
    for path, route in ROUTES.items():
        upstream = fetch_source(route, source_dir)
        original = (ROOT / path).read_text(encoding="utf-8")
        result, old, new, timestamp = refresh(original, upstream)
        outputs.append((path, result))
        for slug, card in new["characterMap"]["map"]:
            if slug in characters and characters[slug] != card:
                raise ValueError(f"Rankings disagree on character data: {slug}")
            characters[slug] = card
        print(f"[OK] {path}: {len(new['characterMap']['map'])} characters; dataUpdatedAt={timestamp}")
    template = next((ROOT / "c").glob("*/index.html")).read_text(encoding="utf-8")
    refreshed = 0
    for slug, card in characters.items():
        path = f"c/{slug}/index.html"
        existing = ROOT / path
        original = existing.read_text(encoding="utf-8") if existing.exists() else template
        changes = character_changes(card, extract_data(original)[1]) if existing.exists() else ["new"]
        if not changes:
            continue
        upstream = fetch_source("/c/" + slug, source_dir)
        outputs.append((path, refresh_character(original, upstream, card)))
        refreshed += 1
        print(f"[OK] {path}: refreshed ({', '.join(changes)})")
    print(f"[OK] character details: refreshed {refreshed}; unchanged {len(characters) - refreshed}")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Use cached index.html, free.html, no-sa.html and c/<slug>/index.html")
    args = parser.parse_args()
    outputs = prepare_outputs(args.source_dir)
    # Validate every source before writing any output.
    for path, result in outputs:
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result, encoding="utf-8")
    for script in ("localize-cn.py", "optimize-mirror.py", "generate-character-snapshots.py", "download-images.py", "check-cn.py"):
        subprocess.run(["python3", str(ROOT / "scripts" / script)], check=True)


if __name__ == "__main__":
    main()
