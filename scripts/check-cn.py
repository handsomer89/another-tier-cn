#!/usr/bin/env python3
"""Check the localized mirror for missing or broken name patches."""

from __future__ import annotations

import json
import re
import runpy
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
        character_changes = runpy.run_path(str(ROOT / "scripts/refresh-rankings.py"))["character_changes"]
        snapshot_dir = ROOT / "data/characters"
        for group in ("paid", "free"):
            cards = json.loads((snapshot_dir / f"{group}.json").read_text(encoding="utf-8"))
            for card in cards:
                detail = json.loads((snapshot_dir / f"{card['slug']}.json").read_text(encoding="utf-8"))
                differences = character_changes(card, detail)
                if differences:
                    raise ValueError(f"Ranking/detail mismatch for {card['slug']}: {', '.join(differences)}")
        manifest = json.loads((ROOT / "site.webmanifest").read_text(encoding="utf-8"))
        for icon in manifest["icons"]:
            if not (ROOT / icon["src"].removeprefix("/another-tier-cn/")).is_file():
                raise ValueError(f"Missing manifest icon: {icon['src']}")
        images = runpy.run_path(str(ROOT / "scripts/download-images.py"))
        for url in images["image_urls"]():
            if not images["image_path"](url).is_file():
                raise ValueError(f"Missing image backup: {url}")
        collection = runpy.run_path(str(ROOT / "scripts/generate-collection.py"))
        expected_catalog, collection_diagnostics = collection["build_catalog"](*collection["load_inputs"]())
        collection["validate_catalog"](
            json.loads((ROOT / "data/collection.json").read_text(encoding="utf-8")), expected_catalog)
        collection_image_count = collection["validate_images"](expected_catalog)
        for diagnostic in collection_diagnostics:
            print("[WARN] " + diagnostic, file=sys.stderr)
        collection_page = ROOT / "collection/index.html"
        if not collection_page.is_file():
            raise ValueError("Missing independent collection page: collection/index.html")
        runpy.run_path(str(ROOT / "scripts/patch-collection-navigation.py"))["apply_navigation"](ROOT, check=True)
        runpy.run_path(str(ROOT / "scripts/version-collection-assets.py"))["apply_versions"](ROOT, check=True)

        names = json.loads((ROOT / "data" / "cn-names.json").read_text(encoding="utf-8"))
        generated = (ROOT / "assets" / "cn-names.js").read_text(encoding="utf-8")
        if "export const cnNames" not in generated:
            raise ValueError("Generated browser mapping is missing")

        ui = json.loads((ROOT / "data" / "cn-ui.json").read_text(encoding="utf-8"))
        terms = json.loads((ROOT / "data" / "cn-terms.json").read_text(encoding="utf-8"))
        if len(ui) != 52 or sum(len(group) for group in terms.values()) != 153:
            raise ValueError("Workbook copy mappings or site-specific UI overrides are incomplete; expected 52 UI strings and 153 terms")
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

        pages = sorted(path for path in ROOT.rglob("*.html") if not path.is_relative_to(ROOT / "dist"))
        remaining: dict[str, int] = {}
        detail_pages = 0
        for path in pages:
            page = path.read_text(encoding="utf-8")
            if path == collection_page:
                # This page deliberately has no original app hydration/loader;
                # validate its independent module and public-path contract.
                for asset in ("collection.js", "collection.css", "collection-data.js", "collection-export.js", "collection-filter.js", "collection-catalog.js"):
                    if not (ROOT / "assets" / asset).is_file():
                        raise ValueError(f"Missing collection module: {asset}")
                for asset in ("collection.js", "collection.css"):
                    if f'/another-tier-cn/assets/{asset}' not in page:
                        raise ValueError(f"Missing base-prefixed collection asset: {asset}")
                if not re.search(r'<script\b(?=[^>]*\btype=[\"\']module[\"\'])(?=[^>]*\bsrc=[\"\']/another-tier-cn/assets/collection\.js\?v=[0-9a-f]{12}[\"\'])', page):
                    raise ValueError("Collection page must load its independent ES module")
                if ('window.$_TSR' in page or 'state:$R[' in page
                        or any('/assets/index-' in script for script in re.findall(r'<script\b.*?</script>', page, re.S))):
                    raise ValueError("Collection page unexpectedly loads original application hydration")
            if path.relative_to(ROOT).as_posix() in {"index.html", "free/index.html", "no-sa/index.html", "collection/index.html"} and '/another-tier-cn/collection/' not in page:
                raise ValueError(f"Collection navigation is missing: {path.relative_to(ROOT)}")
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
            if "Another 评级" in page or "maximum-scale=1" in page:
                raise ValueError(f"Outdated title or viewport: {path.relative_to(ROOT)}")
            for label, translated in terms["tiers"].items():
                if label != translated and re.search(r"<h[23]\b[^>]*>\s*" + re.escape(label) + r"\s*</h[23]>", page):
                    raise ValueError(f"Untranslated tier heading {label}: {path.relative_to(ROOT)}")
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

        print("[OK] Ranking/detail snapshots agree; manifest icons and image backups exist")
        print(f"[OK] Collection: {len(expected_catalog['characters'])} unique forms in unified tier order, "
              f"{collection_image_count} image backups; independent page and navigation verified")
        print(f"[OK] {sum(map(len, verified.values()))} verified mappings match site data and visible detail fields")
        print(f"[OK] {len(names)} name mappings, {len(ui)} UI strings, {sum(len(group) for group in terms.values())} terms")
        print(f"[OK] {detail_pages} character pages and {len(pages)} rendered pages, browser display/search/copy patches verified")
        return 0
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
