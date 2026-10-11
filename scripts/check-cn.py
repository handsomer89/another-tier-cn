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

        ui = json.loads((ROOT / "data" / "cn-ui.json").read_text(encoding="utf-8"))
        terms = json.loads((ROOT / "data" / "cn-terms.json").read_text(encoding="utf-8"))
        if len(ui) != 52 or sum(len(group) for group in terms.values()) != 152:
            raise ValueError("Workbook copy mappings or site-specific UI overrides are incomplete; expected 52 UI strings and 152 terms")
        from cn_aliases import AliasHtml
        aliases = json.loads((ROOT / "data/cn-aliases.json").read_text(encoding="utf-8"))
        alias_runtime = (ROOT / "assets/cn-aliases.js").read_text(encoding="utf-8")
        if "export const cnAliases=Object.freeze(" + json.dumps(aliases, ensure_ascii=False, separators=(",", ":")) + ");" not in alias_runtime:
            raise ValueError("AC alias browser mappings are out of date")
        expected_ui = {
            "Paid SA": "梦见·星导", "Paid No SA": "梦见·无星导",
            "Match all?": "匹配全部？", "AND": "且（全部满足）", "OR": "或（满足任一）",
        }
        if any(ui.get(key) != value for key, value in expected_ui.items()):
            raise ValueError("Navigation or match-mode translations are missing")
        from cn_verified import VerifiedHtml, verified_data
        verified = json.loads((ROOT / "data/cn-verified.json").read_text(encoding="utf-8"))
        if verified != verified_data(ROOT):
            raise ValueError("Verified translations differ from data/cn-verified.json")
        verified_runtime = (ROOT / "assets/cn-verified.js").read_text(encoding="utf-8")
        serialized = json.dumps(verified, ensure_ascii=False, separators=(",", ":"))
        if "export const cnVerified=" + serialized + ";" not in verified_runtime:
            raise ValueError("Verified browser mappings are out of date")
        if ui.get("Paid") != "梦见":
            raise ValueError("Site-specific Paid translation is missing")

        ui_runtime = (ROOT / "assets" / "cn-ui.js").read_text(encoding="utf-8")
        terms_runtime = (ROOT / "assets" / "cn-terms.js").read_text(encoding="utf-8")
        if "export const cnUi" not in ui_runtime or "export function translateUi" not in ui_runtime:
            raise ValueError("Generated UI runtime mapping is missing")
        if "export const cnTerms" not in terms_runtime:
            raise ValueError("Generated term runtime mapping is missing")

        assets = list((ROOT / "assets").glob("*.js"))
        required_patterns = {
            "card display and search": "cnNames[",
            "Chinese name search": "It(cnNames[t.name]??t.name).includes(n)",
            "Chinese alias search": "It(translateAlias(t.alterName)).includes(n)",
            "Chinese detail alias": "children:translateAlias(r.alterName)",
            "localized match-mode toggle": "label:translateUi(`Match all?`)",
            "localized match-mode description": "?translateUi(`AND`):translateUi(`OR`)",
            "tier navigation after static directory redirect": r'[`/`,`/free`,`/no-sa`].includes(t.pathname.replace(/\/+$/,``)||`/`)',
            "character detail title": "children:cnNames[r.name]??r.name",
            "localized tier filter personalities": 'label:cnTerms.personalities[e]??translateVerified("personalities",e)',
            "localized detail personalities": 'children:cnTerms.personalities[e]??translateVerified("personalities",e,character)',
            "localized detail roles": "cnTerms.roles[t]??t",
            "localized detail weapons": "cnTerms.weapons[m[r.weapon]]??m[r.weapon]",
            "localized detail tiers": "cnTerms.tiers[r.tierSA]??r.tierSA",
            "localized team categories": "cnTerms.teams[e.name]??e.name",
            "localized no-character empty state": 'children:cnUi["No characters match your filters"]??`No characters match your filters`',
        }
        combined = "\n".join(path.read_text(encoding="utf-8") for path in assets)
        malformed_empty_state = 'children:`cnUi["No characters match your filters"]??`No characters match your filters``'
        if malformed_empty_state in combined:
            raise ValueError("Malformed no-character empty-state expression remains")
        for label, pattern in required_patterns.items():
            if pattern not in combined:
                raise ValueError(f"Missing required patch: {label}")

        pages = sorted(ROOT.rglob("*.html"))
        remaining: dict[str, int] = {}
        detail_pages = 0
        for path in pages:
            page = path.read_text(encoding="utf-8")
            if path.relative_to(ROOT).parts[:1] == ("c",):
                detail_pages += 1
                if "-ac" in path.parent.name:
                    alias_parser = AliasHtml(page, aliases)
                    alias_parser.feed(page)
                    alias_parser.close()
                    if alias_parser.edits:
                        raise ValueError(f"AC alias is not localized: {path.relative_to(ROOT)}")
                verified_parser = VerifiedHtml(page, verified)
                verified_parser.feed(page)
                verified_parser.close()
                if verified_parser.edits:
                    raise ValueError(f"Verified translations missing in visible detail fields: {path.relative_to(ROOT)}")
                if "定位" not in page or "个性" not in page:
                    raise ValueError(f"Character detail copy is not localized: {path.relative_to(ROOT)}")
            if '<html lang="zh-CN"' not in page:
                raise ValueError(f"HTML language is not set to zh-CN: {path.relative_to(ROOT)}")
            if "梦见·星导觉醒" in page or "梦见·非星导觉醒" in page:
                raise ValueError(f"Outdated navigation copy: {path.relative_to(ROOT)}")
            parser = VisibleNameCheck(names)
            parser.feed(page)
            parser.close()
            for english in parser.english_headings:
                remaining[english] = remaining.get(english, 0) + 1
        if remaining:
            preview = ", ".join(f"{name} ({count})" for name, count in list(remaining.items())[:20])
            raise ValueError(f"English names remain in visible HTML text or alt attributes: {preview}")

        print(f"[OK] {sum(map(len, verified.values()))} verified mappings match site data and visible detail fields")
        print(f"[OK] {len(names)} name mappings, {len(ui)} UI strings, {sum(len(group) for group in terms.values())} terms")
        print(f"[OK] {detail_pages} character pages and {len(pages)} rendered pages, browser display/search/copy patches verified")
        return 0
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
