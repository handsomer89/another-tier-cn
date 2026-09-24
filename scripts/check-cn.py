#!/usr/bin/env python3
"""Check the localized mirror for missing or broken name patches."""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VisibleNameCheck(HTMLParser):
    def __init__(self, names: dict[str, str]):
        super().__init__(convert_charrefs=False)
        self.names = names
        self.stack: list[str] = []
        self.english_headings: list[str] = []
        self.slugs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag in {"h1", "h3", "h4", "a", "span"} and tag not in self.stack:
            pass
        if tag == "img":
            alt = attr_map.get("alt", "")
            if alt in self.names:
                self.english_headings.append(alt)
        if tag == "a" and attr_map.get("href", "").startswith("/c/"):
            self.slugs.append(attr_map["href"])
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(tag in {"script", "style", "noscript"} for tag in self.stack):
            return
        if any(tag in {"h1", "h3", "h4", "a", "span", "title"} for tag in self.stack):
            value = data.strip()
            if value in self.names:
                self.english_headings.append(value)


def main() -> int:
    try:
        names = json.loads((ROOT / "data" / "cn-names.json").read_text(encoding="utf-8"))
        generated = (ROOT / "assets" / "cn-names.js").read_text(encoding="utf-8")
        if "export const cnNames" not in generated:
            raise ValueError("Generated browser mapping is missing")

        assets = list((ROOT / "assets").glob("*.js"))
        required_patterns = {
            "card display and search": "cnNames[",
            "Chinese name search": "It(cnNames[t.name]??t.name).includes(n)",
            "character detail title": "children:cnNames[r.name]??r.name",
        }
        combined = "\n".join(path.read_text(encoding="utf-8") for path in assets)
        for label, pattern in required_patterns.items():
            if pattern not in combined:
                raise ValueError(f"Missing required patch: {label}")

        pages = sorted(ROOT.rglob("*.html"))
        remaining: dict[str, int] = {}
        for path in pages:
            parser = VisibleNameCheck(names)
            parser.feed(path.read_text(encoding="utf-8"))
            parser.close()
            for english in parser.english_headings:
                remaining[english] = remaining.get(english, 0) + 1
        if remaining:
            preview = ", ".join(f"{name} ({count})" for name, count in list(remaining.items())[:20])
            raise ValueError(f"English names remain in visible HTML text or alt attributes: {preview}")

        print(f"[OK] {len(names)} mappings, {len(pages)} HTML pages, browser display/search patches verified")
        return 0
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
