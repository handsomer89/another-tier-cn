#!/usr/bin/env python3
"""Apply the Chinese display-name layer to a refreshed static mirror."""

from __future__ import annotations

import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORT = 'import{cnNames}from"./cn-names.js";'
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
VISIBLE_TAGS = {"a", "h1", "h3", "h4", "span", "title"}
RAW_TAGS = {"script", "style", "noscript"}


def load_names() -> dict[str, str]:
    path = ROOT / "data" / "cn-names.json"
    names = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(names, dict) or not names:
        raise ValueError("data/cn-names.json must contain a non-empty object")
    for english, chinese in names.items():
        if not isinstance(english, str) or not isinstance(chinese, str) or not english.strip() or not chinese.strip():
            raise ValueError(f"Invalid name mapping: {english!r} -> {chinese!r}")
        if english != english.strip() or chinese != chinese.strip():
            raise ValueError(f"Names must be trimmed: {english!r} -> {chinese!r}")
    return names


def insert_import(source: str, label: str) -> str:
    count = source.count(IMPORT)
    if count == 1:
        return source
    if count > 1:
        raise ValueError(f"{label}: duplicate cn-names import")
    return IMPORT + source


def replace_once(source: str, old: str, new: str, label: str) -> str:
    old_count = source.count(old)
    new_count = source.count(new)
    if old_count == 0 and new_count == 1:
        return source
    if old_count != 1 or new_count:
        raise ValueError(f"{label}: expected one patch anchor, found old={old_count}, new={new_count}")
    return source.replace(old, new, 1)


def replace_count(source: str, old: str, new: str, expected: int, label: str) -> str:
    old_count = source.count(old)
    new_count = source.count(new)
    if new_count == expected and source.replace(new, "").count(old) == 0:
        return source
    if old_count != expected or new_count:
        raise ValueError(f"{label}: expected {expected} patch anchors, found old={old_count}, new={new_count}")
    return source.replace(old, new)


def locate_asset(paths: list[Path], label: str, anchors: tuple[str, ...]) -> Path:
    matches = [path for path in paths if all(anchor in path.read_text(encoding="utf-8") for anchor in anchors)]
    if len(matches) != 1:
        names = ", ".join(str(path.relative_to(ROOT)) for path in matches) or "none"
        raise ValueError(f"{label}: expected one matching bundle, found {len(matches)} ({names})")
    return matches[0]


def patch_bundle(path: Path, label: str, replacements: list[tuple[str, str, int]]) -> None:
    source = path.read_text(encoding="utf-8")
    for old, new, expected in replacements:
        source = replace_count(source, old, new, expected, label)
    source = insert_import(source, label)
    path.write_text(source, encoding="utf-8")
    print(f"[OK] {label}: {path.relative_to(ROOT)}")


class NameCollector(HTMLParser):
    def __init__(self, names: dict[str, str]):
        super().__init__(convert_charrefs=False)
        self.names = names
        self.stack: list[str] = []
        self.found: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(tag in RAW_TAGS for tag in self.stack):
            return
        if any(tag in VISIBLE_TAGS for tag in self.stack):
            value = data.strip()
            if value in self.names:
                self.found.add(value)


class HtmlNameRewriter(HTMLParser):
    def __init__(self, source: str, names: dict[str, str], page_names: set[str], is_character_page: bool):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.names = names
        self.page_names = page_names
        self.is_character_page = is_character_page
        self.stack: list[str] = []
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.edits: list[tuple[int, int, str]] = []
        self.deferred_meta: list[tuple[int, int, str]] = []

    def source_offset(self, position: tuple[int, int]) -> int:
        line, column = position
        return self.line_offsets[line - 1] + column

    def add_edit(self, start: int, end: int, replacement: str) -> None:
        if self.source[start:end] != replacement:
            self.edits.append((start, end, replacement))

    @staticmethod
    def find_tag_end(tag_text: str) -> int:
        quote = None
        for index, char in enumerate(tag_text):
            if quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == ">":
                return index + 1
        return len(tag_text)

    def rewrite_attr(self, tag_text: str, attr_name: str, replacements: dict[str, str]) -> str:
        pattern = re.compile(rf"(\b{re.escape(attr_name)}\s*=\s*)([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)

        def update(match: re.Match[str]) -> str:
            value = html.unescape(match.group(3))
            replacement = replacements.get(value)
            if replacement is None:
                return match.group(0)
            return match.group(1) + match.group(2) + html.escape(replacement, quote=True) + match.group(2)

        return pattern.sub(update, tag_text)

    def rewrite_meta(self, tag_text: str) -> str:
        pattern = re.compile(r"(\bcontent\s*=\s*)([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)

        def update(match: re.Match[str]) -> str:
            value = html.unescape(match.group(3))
            for english in sorted(self.page_names, key=len, reverse=True):
                value = re.sub(
                    rf"(?<![A-Za-z0-9]){re.escape(english)}(?![A-Za-z0-9])",
                    self.names[english],
                    value,
                )
            if value == html.unescape(match.group(3)):
                return match.group(0)
            return match.group(1) + match.group(2) + html.escape(value, quote=True) + match.group(2)

        return pattern.sub(update, tag_text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_text = self.get_starttag_text() or ""
        tag_start = self.source_offset(self.getpos())
        tag_end = tag_start + self.find_tag_end(tag_text)
        attr_map = {key.lower(): value or "" for key, value in attrs}

        if tag == "img":
            changed = self.rewrite_attr(tag_text, "alt", self.names)
            if changed != tag_text:
                self.add_edit(tag_start, tag_end, changed)
        elif tag == "meta" and self.is_character_page:
            field = attr_map.get("name", "").lower() or attr_map.get("property", "").lower()
            if field in {"description", "og:title", "og:description", "twitter:title", "twitter:description"}:
                self.deferred_meta.append((tag_start, tag_end, tag_text))

        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_text = self.get_starttag_text() or ""
        tag_start = self.source_offset(self.getpos())
        tag_end = tag_start + self.find_tag_end(tag_text)
        if tag == "img":
            changed = self.rewrite_attr(tag_text, "alt", self.names)
            if changed != tag_text:
                self.add_edit(tag_start, tag_end, changed)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(tag in RAW_TAGS for tag in self.stack):
            return
        if not any(tag in VISIBLE_TAGS for tag in self.stack):
            return

        value = data.strip()
        if not value:
            return
        replacement = self.names.get(value)
        if replacement is None and "title" in self.stack:
            for english in sorted(self.page_names, key=len, reverse=True):
                if value == english or value.startswith(english + " - "):
                    replacement = self.names[english] + value[len(english):]
                    break
        if replacement is not None:
            start = self.source_offset(self.getpos())
            left = len(data) - len(data.lstrip())
            right = len(data.rstrip())
            self.add_edit(start + left, start + right, replacement)

    def finish(self) -> str:
        for start, end, tag_text in self.deferred_meta:
            changed = self.rewrite_meta(tag_text)
            if changed != tag_text:
                self.add_edit(start, end, changed)

        output = self.source
        for start, end, replacement in sorted(self.edits, reverse=True):
            output = output[:start] + replacement + output[end:]
        return output


def localize_html(path: Path, names: dict[str, str]) -> bool:
    source = path.read_text(encoding="utf-8")
    collector = NameCollector(names)
    collector.feed(source)
    collector.close()
    is_character_page = path.relative_to(ROOT).parts[:1] == ("c",)
    parser = HtmlNameRewriter(source, names, collector.found, is_character_page)
    parser.feed(source)
    parser.close()
    result = parser.finish()
    if result != source:
        path.write_text(result, encoding="utf-8")
        return True
    return False


def main() -> int:
    try:
        names = load_names()
        assets = sorted((ROOT / "assets").glob("*.js"))
        if not assets:
            raise ValueError("No assets/*.js bundles found")

        card = locate_asset(assets, "character card", ("function S(e)", "lcpImage:s", "width:80,height:80"))
        tier = locate_asset(assets, "tier list search", ("filterKeyword:o", "classTomes.some", "filterPersonalitiesMatch:f"))
        detail = locate_asset(assets, "character detail", ("Character not found", "Other Versions", "r.commentary"))
        detail_route = locate_asset(assets, "character SEO route", ("Another Eden ${n} tier character.", "catch(t){throw console.error(t),e()}"))
        team_search = locate_asset(assets, "team character search", ("function g(e,t)", "e.name.toLocaleLowerCase().includes(n)", "selectionGroups"))

        generated = "// Generated from data/cn-names.json by scripts/localize-cn.py.\n"
        generated += "export const cnNames = Object.freeze(" + json.dumps(names, ensure_ascii=False, separators=(",", ":")) + ");\n"
        generated += "export const displayCharacterName = (name) => cnNames[name] ?? name;\n"
        (ROOT / "assets" / "cn-names.js").write_text(generated, encoding="utf-8")

        patch_bundle(card, "character card", [
            ("width:80,height:80,alt:d", "width:80,height:80,alt:cnNames[d]??d", 1),
            ("className:`text-sm`,children:d", "className:`text-sm`,children:cnNames[d]??d", 1),
        ])
        patch_bundle(tier, "tier list search", [
            ("It(t.name).includes(n)", "It(t.name).includes(n)||It(cnNames[t.name]??t.name).includes(n)", 1),
        ])
        patch_bundle(detail, "character detail", [
            ("pages:[{name:r.name,linkProps:a,current:!0}]", "pages:[{name:cnNames[r.name]??r.name,linkProps:a,current:!0}]", 1),
            ("className:`text-2xl font-medium text-gray-800 dark:text-gray-100`,children:r.name", "className:`text-2xl font-medium text-gray-800 dark:text-gray-100`,children:cnNames[r.name]??r.name", 1),
            ("alt:n.name", "alt:cnNames[n.name]??n.name", 3),
            ("alt:r,className", "alt:cnNames[r]??r,className", 1),
            ("className:`mt-2 text-center text-lg/tight font-medium`,children:r", "className:`mt-2 text-center text-lg/tight font-medium`,children:cnNames[r]??r", 1),
        ])
        patch_bundle(detail_route, "character SEO route", [
            ("${e.name} - Another Tier", "${cnNames[e.name]??e.name} - Another Tier", 1),
            ("View ${e.name}'s key stats", "View ${cnNames[e.name]??e.name}'s key stats", 1),
        ])
        patch_bundle(team_search, "team character search", [
            ("e.name.toLocaleLowerCase().includes(n)", "(e.name.toLocaleLowerCase().includes(n)||cnNames[e.name]?.toLocaleLowerCase().includes(n))", 1),
        ])

        pages = sorted(ROOT.rglob("*.html"))
        if not pages:
            raise ValueError("No HTML pages found")
        changed = sum(localize_html(path, names) for path in pages)
        print(f"[OK] localized visible names in {changed}/{len(pages)} HTML pages")
        print(f"[OK] {len(names)} exact-name mappings available to the browser")
        from cn_localization import apply_copy_localization

        apply_copy_localization(ROOT)
        return 0
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

