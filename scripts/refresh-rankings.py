#!/usr/bin/env python3
"""Refresh rendered tier lists and their matching hydration data from upstream.

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
    # Evaluate only the captured data expression, in an isolated context with a timeout.
    program = r"""
const fs = require('node:fs'), vm = require('node:vm');
const data = vm.runInNewContext('(' + fs.readFileSync(0, 'utf8') + ')', {$R: []}, {timeout: 5000});
console.log(JSON.stringify(data, (_, value) => {
  if (Object.prototype.toString.call(value) === '[object Map]') return {map: [...value]};
  if (Object.prototype.toString.call(value) === '[object Set]') return {set: [...value]};
  return value;
}));
"""
    result = subprocess.run(["node", "-e", program], input=match[2], text=True, capture_output=True, check=True)
    return match, json.loads(result.stdout)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Use previously fetched index.html, free.html and no-sa.html")
    args = parser.parse_args()
    outputs = []
    for path, route in ROUTES.items():
        if args.source_dir:
            filename = "index.html" if route == "/" else route[1:] + ".html"
            upstream = (args.source_dir / filename).read_text()
        else:
            request = Request("https://anothertier.com" + route, headers={"User-Agent": "Another-Tier-CN snapshot refresh"})
            with urlopen(request, timeout=45) as response:
                upstream = response.read().decode("utf-8")
        original = (ROOT / path).read_text()
        result, old, new, timestamp = refresh(original, upstream)
        outputs.append((path, result))
        print(f"[OK] {path}: {len(new['characterMap']['map'])} characters; dataUpdatedAt={timestamp}")
    # Validate every source before writing any output.
    for path, result in outputs:
        (ROOT / path).write_text(result)
    subprocess.run(["python3", str(ROOT / "scripts/localize-cn.py")], check=True)
    subprocess.run(["python3", str(ROOT / "scripts/check-cn.py")], check=True)


if __name__ == "__main__":
    main()
