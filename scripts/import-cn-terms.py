#!/usr/bin/env python3
"""Import exact UI and classification translations from the supplied workbook."""

from __future__ import annotations

import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ROOT = Path(__file__).resolve().parents[1]

TERM_GROUPS = {
    "Role 定位": "roles",
    "Element 元素": "elements",
    "Weapon 武器": "weapons",
    "Armor 防具": "armor",
    "Light/Shadow 光影": "lightShadow",
    "Personality 个性标签": "personalities",
    "Tier 排名标签": "tiers",
    "角色形态缩写": "forms",
    "Teams 队伍分类/标签": "teams",
}


def workbook_rows(path: Path, wanted_sheet: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(item.itertext()) for item in root.findall(f"{{{MAIN_NS}}}si")]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {item.get("Id"): item.get("Target", "") for item in relationships}
        sheet_path = None
        for sheet in workbook.findall(f"{{{MAIN_NS}}}sheets/{{{MAIN_NS}}}sheet"):
            if sheet.get("name") == wanted_sheet:
                target = rel_map.get(sheet.get(f"{{{DOC_REL_NS}}}id"), "")
                target = target.lstrip("/")
                sheet_path = target if target.startswith("xl/") else posixpath.join("xl", target)
                break
        if sheet_path is None or sheet_path not in names:
            raise ValueError(f"Workbook is missing worksheet {wanted_sheet!r}")

        sheet = ET.fromstring(archive.read(sheet_path))
        rows: list[dict[str, str]] = []
        for row in sheet.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
            values: dict[str, str] = {}
            for cell in row.findall(f"{{{MAIN_NS}}}c"):
                match = re.match(r"[A-Z]+", cell.get("r", ""))
                if match is None:
                    continue
                value = cell.find(f"{{{MAIN_NS}}}v")
                text = "" if value is None or value.text is None else value.text
                if cell.get("t") == "s" and text:
                    text = shared[int(text)]
                elif cell.get("t") == "inlineStr":
                    inline = cell.find(f"{{{MAIN_NS}}}is")
                    text = "" if inline is None else "".join(inline.itertext())
                values[match.group(0)] = text.strip()
            rows.append(values)
        return rows


def find_header(rows: list[dict[str, str]], english_header: str, chinese_header: str) -> int:
    for index, row in enumerate(rows):
        if row.get("B") == english_header and chinese_header in row.values():
            return index
    raise ValueError(f"Could not find workbook header {english_header!r}")


def add_mapping(target: dict[str, str], english: str, chinese: str, context: str) -> None:
    if not english or not chinese:
        return
    previous = target.get(english)
    if previous is not None and previous != chinese:
        raise ValueError(f"Conflicting translations for {english!r}: {previous!r} vs {chinese!r} ({context})")
    target[english] = chinese


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/import-cn-terms.py /path/to/translated-workbook.xlsx", file=sys.stderr)
        return 2

    try:
        source = Path(sys.argv[1]).expanduser().resolve()
        ui_rows = workbook_rows(source, "页面文案")
        term_rows = workbook_rows(source, "筛选与分类")

        ui_header = find_header(ui_rows, "英文原文", "精确中文译文")
        ui: dict[str, str] = {}
        skipped_ui = 0
        for row in ui_rows[ui_header + 1 :]:
            english, chinese = row.get("B", "").strip(), row.get("D", "").strip()
            if not english:
                continue
            if not chinese:
                skipped_ui += 1
                continue
            add_mapping(ui, english, chinese, "页面文案")

        term_header = find_header(term_rows, "英文显示值", "精确中文译文")
        terms = {name: {} for name in TERM_GROUPS.values()}
        skipped_terms = 0
        for row in term_rows[term_header + 1 :]:
            english, chinese = row.get("B", "").strip(), row.get("E", "").strip()
            if not english:
                continue
            if not chinese:
                skipped_terms += 1
                continue
            category = row.get("A", "").strip()
            group = TERM_GROUPS.get(category)
            if group is None:
                raise ValueError(f"Unrecognized translated term category: {category!r} ({english!r})")
            add_mapping(terms[group], english, chinese, category)

        terms = {name: values for name, values in terms.items() if values}
        out_dir = ROOT / "data"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "cn-ui.json").write_text(json.dumps(ui, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out_dir / "cn-terms.json").write_text(json.dumps(terms, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        print(f"[OK] imported {len(ui)} fixed UI strings; skipped {skipped_ui} blank translations")
        print(f"[OK] imported {sum(len(values) for values in terms.values())} terms in {len(terms)} categories; skipped {skipped_terms} blank translations")
        for name, values in terms.items():
            print(f"[OK] {name}: {len(values)}")
        return 0
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

