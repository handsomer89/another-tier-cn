#!/usr/bin/env python3
"""Apply workbook-backed UI and structured-term translations to the mirror."""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path


UI_IMPORT = 'import{cnUi,translateUi}from"./cn-ui.js";'
TERMS_IMPORT = 'import{cnTerms}from"./cn-terms.js";'
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW_TAGS = {"script", "style", "noscript"}
VISIBLE_TAGS = {"a", "button", "dd", "dt", "h1", "h2", "h3", "h4", "li", "p", "span", "title"}
DETAIL_TERM_GROUPS = {
    "Tier": "tiers",
    "Weapon": "weapons",
    "Armor": "armor",
    "Element": "elements",
    "Light/Shadow": "lightShadow",
    "Roles": "roles",
    "Personalities": "personalities",
}


def load_object(path: Path, label: str) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{path.relative_to(path.parents[1])} must contain a non-empty object")
    for key, translation in value.items():
        if not isinstance(key, str) or not isinstance(translation, str) or not key.strip() or not translation.strip():
            raise ValueError(f"Invalid {label} mapping: {key!r} -> {translation!r}")
        if key != key.strip() or translation != translation.strip():
            raise ValueError(f"{label} mappings must be trimmed: {key!r} -> {translation!r}")
    return value


def load_copy_data(root: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    ui = load_object(root / "data" / "cn-ui.json", "UI")
    terms_path = root / "data" / "cn-terms.json"
    terms = json.loads(terms_path.read_text(encoding="utf-8"))
    if not isinstance(terms, dict) or not terms:
        raise ValueError("data/cn-terms.json must contain a non-empty object")
    for group, values in terms.items():
        if not isinstance(values, dict):
            raise ValueError(f"cn-terms.json category {group!r} must contain an object")
        for key, translation in values.items():
            if not isinstance(key, str) or not isinstance(translation, str) or not key.strip() or not translation.strip():
                raise ValueError(f"Invalid {group} mapping: {key!r} -> {translation!r}")
            if key != key.strip() or translation != translation.strip():
                raise ValueError(f"{group} mappings must be trimmed: {key!r} -> {translation!r}")
    return ui, terms


def replace_count(source: str, old: str, new: str, expected: int, label: str) -> str:
    old_count = source.count(old)
    new_count = source.count(new)
    if new_count == expected and source.replace(new, "").count(old) == 0:
        return source
    if old_count != expected or new_count:
        raise ValueError(f"{label}: expected {expected} patch anchors, found old={old_count}, new={new_count}")
    return source.replace(old, new)


def insert_import(source: str, statement: str, label: str) -> str:
    count = source.count(statement)
    if count == 1:
        return source
    if count > 1:
        raise ValueError(f"{label}: duplicate localization import {statement!r}")
    return statement + source


def locate_asset(paths: list[Path], root: Path, label: str, anchors: tuple[str, ...]) -> Path:
    matches = [path for path in paths if all(anchor in path.read_text(encoding="utf-8") for anchor in anchors)]
    if len(matches) != 1:
        names = ", ".join(str(path.relative_to(root)) for path in matches) or "none"
        raise ValueError(f"{label}: expected one matching bundle, found {len(matches)} ({names})")
    return matches[0]


def patch_bundle(path: Path, label: str, replacements: list[tuple[str, str, int]], imports: tuple[str, ...]) -> None:
    source = path.read_text(encoding="utf-8")
    legacy_empty = 'children:`cnUi["No characters match your filters"]??`No characters match your filters``'
    fixed_empty = 'children:cnUi["No characters match your filters"]??`No characters match your filters`'
    legacy_count = source.count(legacy_empty)
    if legacy_count > 1:
        raise ValueError(f"{label}: found multiple malformed no-character empty-state expressions")
    if legacy_count:
        source = source.replace(legacy_empty, fixed_empty, 1)
    for old, new, expected in replacements:
        source = replace_count(source, old, new, expected, label)
    for statement in imports:
        source = insert_import(source, statement, label)
    path.write_text(source, encoding="utf-8")
    print(f"[OK] {label}: {path.name}")


class HtmlCopyRewriter(HTMLParser):
    def __init__(self, source: str, ui: dict[str, str], terms: dict[str, dict[str, str]]):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.ui = ui
        self.terms = terms
        self.stack: list[str] = []
        self.pending_detail_label = ""
        self.detail_fields: list[str] = []
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.edits: list[tuple[int, int, str]] = []

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

    def rewrite_attrs(self, tag_text: str, attr_name: str, replacements: dict[str, str]) -> str:
        pattern = re.compile(rf"(\b{re.escape(attr_name)}\s*=\s*)([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)

        def update(match: re.Match[str]) -> str:
            value = html.unescape(match.group(3))
            replacement = replacements.get(value)
            if replacement is None:
                return match.group(0)
            return match.group(1) + match.group(2) + html.escape(replacement, quote=True) + match.group(2)

        return pattern.sub(update, tag_text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_text = self.get_starttag_text() or ""
        start = self.source_offset(self.getpos())
        end = start + self.find_tag_end(tag_text)
        attr_map = {key.lower(): value or "" for key, value in attrs}
        changed = tag_text

        term_replacements = dict(self.ui)
        if self.detail_fields:
            group = DETAIL_TERM_GROUPS.get(self.detail_fields[-1], "")
            for english, chinese in self.terms.get(group, {}).items():
                term_replacements[english] = chinese
                term_replacements.setdefault(english.lower(), chinese)

        if tag == "html" and attr_map.get("lang", "").lower().startswith("en"):
            changed = self.rewrite_attrs(changed, "lang", {attr_map["lang"]: "zh-CN"})
        for attr in ("placeholder", "aria-label", "alt", "title", "content"):
            changed = self.rewrite_attrs(changed, attr, term_replacements)
        if changed != tag_text:
            self.add_edit(start, end, changed)

        if tag == "dd":
            self.detail_fields.append(self.pending_detail_label)
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "dd" and self.detail_fields:
            self.detail_fields.pop()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                break

    def translate_text(self, value: str) -> str:
        replacement = self.ui.get(value)
        field = self.detail_fields[-1] if self.detail_fields else ""
        group = DETAIL_TERM_GROUPS.get(field)
        if group:
            replacement = self.terms.get(group, {}).get(value, replacement)
        elif any(tag in {"h2", "h3"} for tag in self.stack):
            replacement = self.terms.get("teams", {}).get(value, replacement)
        return replacement if replacement is not None else value

    def handle_data(self, data: str) -> None:
        if any(tag in RAW_TAGS for tag in self.stack):
            return
        if "dt" in self.stack:
            label = data.strip()
            if label:
                self.pending_detail_label = label
        if not any(tag in VISIBLE_TAGS for tag in self.stack):
            return

        value = data.strip()
        if not value:
            return
        replacement = self.translate_text(value)
        if "title" in self.stack and replacement == value:
            for english, chinese in sorted(self.ui.items(), key=lambda item: len(item[0]), reverse=True):
                replacement = re.sub(rf"(?<![A-Za-z0-9]){re.escape(english)}(?![A-Za-z0-9])", chinese, replacement)
        if replacement != value:
            start = self.source_offset(self.getpos())
            left = len(data) - len(data.lstrip())
            right = len(data.rstrip())
            self.add_edit(start + left, start + right, replacement)

    def finish(self) -> str:
        output = self.source
        for start, end, replacement in sorted(self.edits, reverse=True):
            output = output[:start] + replacement + output[end:]
        return output


def localize_html(path: Path, root: Path, ui: dict[str, str], terms: dict[str, dict[str, str]]) -> bool:
    source = path.read_text(encoding="utf-8")
    parser = HtmlCopyRewriter(source, ui, terms)
    parser.feed(source)
    parser.close()
    result = parser.finish()
    if result == source:
        return False
    path.write_text(result, encoding="utf-8")
    return True


def generate_browser_maps(root: Path, ui: dict[str, str], terms: dict[str, dict[str, str]]) -> None:
    assets_dir = root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    ui_source = "// Generated from data/cn-ui.json by scripts/import-cn-terms.py.\n"
    ui_source += "export const cnUi = Object.freeze(" + json.dumps(ui, ensure_ascii=False, separators=(",", ":")) + ");\n"
    ui_source += "export function translateUi(value){if(typeof value!==\"string\")return value;if(Object.prototype.hasOwnProperty.call(cnUi,value))return cnUi[value];const patterns=[[/^Variation (.+)$/ ,\"Variation {n}\"],[/^Choose (.+)$/ ,\"Choose {n}\"],[/(^|\\s)(\\d+) core$/ ,\"{n} core\"],[/^This variation fills (\\d+) of 4 frontline slots\\.$/ ,\"This variation fills {n} of 4 frontline slots.\"]];for(const[pattern,key]of patterns){const match=pattern.exec(value);if(match&&cnUi[key])return cnUi[key].replace(\"{n}\",match[2]??match[1]);}return value;}\n"
    (assets_dir / "cn-ui.js").write_text(ui_source, encoding="utf-8")

    terms_source = "// Generated from data/cn-terms.json by scripts/import-cn-terms.py.\n"
    terms_source += "export const cnTerms = Object.freeze(" + json.dumps(terms, ensure_ascii=False, separators=(",", ":")) + ");\n"
    terms_source += "export const translateTerm = (group, value) => cnTerms[group]?.[value] ?? value;\n"
    (assets_dir / "cn-terms.js").write_text(terms_source, encoding="utf-8")


def localize_copy(root: Path) -> int:
    ui, terms = load_copy_data(root)
    assets = sorted((root / "assets").glob("*.js"))
    if not assets:
        raise ValueError("No assets/*.js bundles found")
    generate_browser_maps(root, ui, terms)

    tier = locate_asset(assets, root, "tier filter copy", ("filterPersonalitiesMatch:f", "classTomes.some", "function Ft(e)"))
    detail = locate_asset(assets, root, "character detail copy", ("r.commentary", "function R(e)", "r.otherVersions"))
    search = locate_asset(assets, root, "search controls", ("Filter by name or tome", "Clear All", "function T(e)"))
    site = locate_asset(assets, root, "site navigation and footer", ("u/Natural_Pleasant’s Tier List", "Made by", "Tier list and roles credit to"))
    paid_toggle = locate_asset(assets, root, "paid/free navigation", ("label:`Paid SA`", "label:`Paid No SA`", "label:`Free`"))
    teams = locate_asset(assets, root, "teams page", ("No teams match these filters. Try another character or clear your filters.", "selectionGroups", "placeholder:`Filter by character`"))
    team_helper = locate_asset(assets, root, "team labels and validation", ("Add at least one selection group.", "This variation fills ${r} of 4 frontline slots.", "Choose ${e.pickCount}"))
    seo = locate_asset(assets, root, "default SEO copy", ("Another Tier - Tier List for Another Eden", "Rating characters in their viability against endgame Hidden Bosses, and Challenge Mode difficulties."))
    team_route = locate_asset(assets, root, "teams page title", ("Another Tier", "noindex"))
    error_page = locate_asset(assets, root, "error page copy", ("Page not found", "Back to home", "Home"))

    patch_bundle(tier, "tier list filters and rank labels", [
        ("children:`Tier List`", "children:cnUi[\"Tier List\"]??`Tier List`", 1),
        ("name:`Weapon`", "name:cnUi[\"Weapon\"]??`Weapon`", 1),
        ("name:`Role`", "name:cnUi[\"Role\"]??`Role`", 1),
        ("name:`Personality`", "name:cnUi[\"Personality\"]??`Personality`", 1),
        ("name:`Element`", "name:cnUi[\"Element\"]??`Element`", 1),
        ("function kt(e){return{value:e,label:e}}", "function kt(e){return{value:e,label:cnTerms.personalities[e]??e}}", 1),
        ("function At(e){let[t,n]=e;return{value:t,label:n}}", "function At(e){let[t,n]=e;return{value:t,label:cnTerms.roles[n]??n}}", 1),
        ("alt:u[e]", "alt:cnTerms.weapons[u[e]]??u[e]", 1),
        ("}),u[e]]", "}),cnTerms.weapons[u[e]]??u[e]]", 1),
        ("alt:s[e]", "alt:cnTerms.elements[s[e]]??s[e]", 1),
        ("}),s[e]]", "}),cnTerms.elements[s[e]]??s[e]]", 1),
        ("children:[i,b]", "children:[cnTerms.tiers[i]??i,b]", 1),
        ('children:`No characters match your filters`', 'children:cnUi["No characters match your filters"]??`No characters match your filters`', 1),
    ], (UI_IMPORT, TERMS_IMPORT))

    patch_bundle(detail, "character details and shared terms", [
        ("name:`Tier`", "name:cnUi[\"Tier\"]??`Tier`", 1),
        ("name:`Weapon`", "name:cnUi[\"Weapon\"]??`Weapon`", 1),
        ("name:`Armor`", "name:cnUi[\"Armor\"]??`Armor`", 1),
        ("name:`Element`", "name:cnUi[\"Element\"]??`Element`", 1),
        ("name:`Light/Shadow`", "name:cnUi[\"Light/Shadow\"]??`Light/Shadow`", 1),
        ("name:`Roles`", "name:cnUi[\"Roles\"]??`Roles`", 1),
        ("name:`Paid/Free`", "name:cnUi[\"Paid/Free\"]??`Paid/Free`", 1),
        ("name:`Personalities`", "name:cnUi[\"Personalities\"]??`Personalities`", 1),
        ("name:`Style Change Tome`", "name:cnUi[\"Style Change Tome\"]??`Style Change Tome`", 1),
        ("name:`Class Tome`", "name:cnUi[\"Class Tome\"]??`Class Tome`", 1),
        ("function V(e){return e?[(0,A.jsx)(`li`,{children:e},e)]:[]}", "function V(e){return e?[(0,A.jsx)(`li`,{children:cnTerms.personalities[e]??e},e)]:[]}", 1),
        ("function H(e){return(0,A.jsx)(`li`,{children:e},e)}", "function H(e){let t=typeof e===`string`?e:e.name??e;return(0,A.jsx)(`li`,{children:cnTerms.roles[t]??t},e)}", 1),
        ("function U(e){return(0,A.jsxs)(`li`,{className:`flex items-center gap-1`,children:[(0,A.jsx)(`img`,{alt:`${e} element`,src:`${v}/dpr_2.0/c_lfill,h_24,w_24/q_auto:low/f_auto/v1/${h(e)}`,width:24,height:24}),a[e]]},e)}", "function U(e){let t=a[e],n=cnTerms.elements[t]??t;return(0,A.jsxs)(`li`,{className:`flex items-center gap-1`,children:[(0,A.jsx)(`img`,{alt:n,src:`${v}/dpr_2.0/c_lfill,h_24,w_24/q_auto:low/f_auto/v1/${h(e)}`,width:24,height:24}),n]},e)}", 1),
        ("alt:r.weapon", "alt:cnTerms.weapons[m[r.weapon]]??m[r.weapon]", 1),
        ("}),m[r.weapon]]", "}),cnTerms.weapons[m[r.weapon]]??m[r.weapon]]", 1),
        ("alt:r.armor", "alt:cnTerms.armor[g[r.armor]]??g[r.armor]", 1),
        ("}),g[r.armor]]", "}),cnTerms.armor[g[r.armor]]??g[r.armor]]", 1),
        ("alt:r.lightShadow", "alt:cnTerms.lightShadow[u[r.lightShadow]]??u[r.lightShadow]", 1),
        ("}),u[r.lightShadow]]", "}),cnTerms.lightShadow[u[r.lightShadow]]??u[r.lightShadow]]", 1),
        ("description:r.paid?`Paid`:`Free`", "description:translateUi(r.paid?`Paid`:`Free`)", 1),
        ("children:r.tierSA", "children:cnTerms.tiers[r.tierSA]??r.tierSA", 2),
        ("children:r.tierBase", "children:cnTerms.tiers[r.tierBase]??r.tierBase", 1),
        ("className:`text-xs font-medium text-gray-500 uppercase dark:text-gray-400`,children:e.name", "className:`text-xs font-medium text-gray-500 uppercase dark:text-gray-400`,children:cnUi[e.name]??e.name", 1),
        ("alt:`Hard`", "alt:cnUi[\"Hard\"]??`Hard`", 1),
        ("title:`Hard`", "title:cnUi[\"Hard\"]??`Hard`", 1),
        ("alt:`Very Hard`", "alt:cnUi[\"Very Hard\"]??`Very Hard`", 1),
        ("title:`Very Hard`", "title:cnUi[\"Very Hard\"]??`Very Hard`", 1),
        ("children:`Home`", "children:cnUi[\"Home\"]??`Home`", 1),
        ("children:`Character not found`", "children:cnUi[\"Character not found\"]??`Character not found`", 1),
        ("children:`Other Versions`", "children:cnUi[\"Other Versions\"]??`Other Versions`", 1),
        ("children:[`Wiki `,M]", "children:[cnUi[\"Wiki\"]??`Wiki `,M]", 1),
        ("children:`(a.k.a.)`", "children:cnUi[\"(a.k.a.)\"]??`(a.k.a.)`", 1),
        ("`N/A`", "cnUi[\"N/A\"]??`N/A`", 5),
    ], (UI_IMPORT, TERMS_IMPORT))

    patch_bundle(search, "search labels and placeholders", [
        ("children:[S,`Clear All`]", "children:[S,cnUi[\"Clear All\"]??`Clear All`]", 1),
        ("o=a===void 0?`Filter by name or tome`:a", "o=translateUi(a===void 0?`Filter by name or tome`:a)", 1),
    ], (UI_IMPORT,))

    patch_bundle(site, "navigation and footer copy", [
        ("children:`Tier List`", "children:cnUi[\"Tier List\"]??`Tier List`", 1),
        ("children:`Teams`", "children:cnUi[\"Teams\"]??`Teams`", 1),
        ("children:[`Made by`,` `,", "children:[cnUi[\"Made by\"]??`Made by`,` `,", 1),
        ("children:[`Tier list and roles credit to`,", "children:[cnUi[\"Tier list and roles credit to\"]??`Tier list and roles credit to`,", 1),
        ("children:` and Roles for Another Eden`", "children:` ${cnUi[\"and Roles for Another Eden\"]??\"and Roles for Another Eden\"}`", 1),
    ], (UI_IMPORT,))

    patch_bundle(paid_toggle, "paid and free navigation", [
        ("label:`Paid SA`", "label:cnUi[\"Paid SA\"]??`Paid SA`", 1),
        ("label:`Paid No SA`", "label:cnUi[\"Paid No SA\"]??`Paid No SA`", 1),
        ("label:`Free`", "label:cnUi[\"Free\"]??`Free`", 1),
    ], (UI_IMPORT,))

    patch_bundle(teams, "team page copy and categories", [
        ("children:`Teams`", "children:cnUi[\"Teams\"]??`Teams`", 1),
        ("var h=`CHOOSE`.split(``)", "var h=Array.from(translateUi(`CHOOSE`))", 1),
        ("children:e.name}),e.teams.map", "children:cnTerms.teams[e.name]??e.name}),e.teams.map", 1),
        ("t.name||`Variation ${n+1}`", "translateUi(t.name||`Variation ${n+1}`)", 1),
        ("`No teams match these filters. Try another character or clear your filters.`", "translateUi(`No teams match these filters. Try another character or clear your filters.`)", 1),
        ("`No teams have been added yet.`", "translateUi(`No teams have been added yet.`)", 1),
    ], (UI_IMPORT, TERMS_IMPORT))

    patch_bundle(team_helper, "team selection descriptions", [
        ("return`Add at least one selection group.`", "return translateUi(`Add at least one selection group.`)", 1),
        ("`This variation fills ${r} of 4 frontline slots.`", "translateUi(`This variation fills ${r} of 4 frontline slots.`)", 1),
        ("function b(e){return e.map(e=>e.kind===`core`?`${e.characterIds.length} core`:`Choose ${e.pickCount}`).join(` · `)}", "function b(e){return e.map(e=>e.kind===`core`?translateUi(`${e.characterIds.length} core`):translateUi(`Choose ${e.pickCount}`)).join(` · `)}", 1),
    ], (UI_IMPORT,))

    patch_bundle(seo, "default page metadata", [
        ("title:t=`Another Tier - Tier List for Another Eden`", "title:t=cnUi[\"Another Tier - Tier List for Another Eden\"]??`Another Tier - Tier List for Another Eden`", 1),
        ("description:n=`Rating characters in their viability against endgame Hidden Bosses, and Challenge Mode difficulties.`", "description:n=cnUi[\"Rating characters in their viability against endgame Hidden Bosses, and Challenge Mode difficulties.\"]??`Rating characters in their viability against endgame Hidden Bosses, and Challenge Mode difficulties.`", 1),
    ], (UI_IMPORT,))

    patch_bundle(team_route, "teams page metadata", [
        ("title:`Teams · Another Tier`", "title:`${cnUi[\"Teams\"]??\"Teams\"} · Another Tier`", 1),
    ], (UI_IMPORT,))

    patch_bundle(error_page, "error page copy", [
        ("children:`Try Again`", "children:cnUi[\"Try Again\"]??`Try Again`", 1),
        ("children:`Go Back`", "children:cnUi[\"Go Back\"]??`Go Back`", 1),
        ("children:`Page not found`", "children:cnUi[\"Page not found\"]??`Page not found`", 1),
        ("children:`Back to home`", "children:cnUi[\"Back to home\"]??`Back to home`", 1),
        ("children:`Home`", "children:cnUi[\"Home\"]??`Home`", 1),
    ], (UI_IMPORT,))

    pages = sorted(root.rglob("*.html"))
    if not pages:
        raise ValueError("No HTML pages found")
    changed = sum(localize_html(path, root, ui, terms) for path in pages)
    print(f"[OK] localized fixed copy and structured terms in {changed}/{len(pages)} HTML pages")
    print(f"[OK] {len(ui)} UI strings and {sum(len(group) for group in terms.values())} exact term mappings loaded")
    return changed


def apply_copy_localization(root: Path) -> int:
    return localize_copy(root)

