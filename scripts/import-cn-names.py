#!/usr/bin/env python3
"""Import exact character display names from the supplied workbook."""

from __future__ import annotations

import collections
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


def workbook_texts(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(item.itertext()) for item in root.findall(f"{{{MAIN_NS}}}si")]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find(f"{{{MAIN_NS}}}sheets/{{{MAIN_NS}}}sheet")
        if first_sheet is None:
            raise ValueError("Workbook has no worksheets")
        relationship_id = first_sheet.get(f"{{{DOC_REL_NS}}}id")

        rels_path = "xl/_rels/workbook.xml.rels"
        relationships = ET.fromstring(archive.read(rels_path))
        target = None
        for rel in relationships.findall(f"{{{PKG_REL_NS}}}Relationship"):
            if rel.get("Id") == relationship_id:
                target = rel.get("Target")
                break
        if not target:
            raise ValueError("Could not resolve the first worksheet")
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        sheet = ET.fromstring(archive.read(sheet_path))

        rows: list[list[str]] = []
        for row in sheet.findall(f".//{{{MAIN_NS}}}row"):
            values: dict[str, str] = {}
            for cell in row.findall(f"{{{MAIN_NS}}}c"):
                ref = cell.get("r", "")
                column = re.match(r"[A-Z]+", ref)
                if not column:
                    continue
                kind = cell.get("t", "")
                if kind == "inlineStr":
                    value = "".join(cell.find(f"{{{MAIN_NS}}}is").itertext()) if cell.find(f"{{{MAIN_NS}}}is") is not None else ""
                else:
                    node = cell.find(f"{{{MAIN_NS}}}v")
                    value = node.text if node is not None and node.text is not None else ""
                    if kind == "s" and value:
                        value = shared[int(value)]
                values[column.group(0)] = value
            rows.append([values.get("A", ""), values.get("C", "")])
        return rows


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/import-cn-names.py <character-workbook.xlsx>", file=sys.stderr)
        return 2

    workbook_path = Path(sys.argv[1])
    if not workbook_path.is_file():
        print(f"[ERROR] Workbook not found: {workbook_path}", file=sys.stderr)
        return 2

    rows = workbook_texts(workbook_path)
    if not rows or not (rows[0][0].strip().lower().startswith("character") and rows[0][1].strip() == "中文名称"):
        print("[ERROR] Expected English names in column A and Chinese names in column C.", file=sys.stderr)
        return 1

    names: dict[str, str] = {}
    skipped_blank_cn = 0
    duplicate_cn: dict[str, list[str]] = collections.defaultdict(list)
    errors: list[str] = []

    for row_number, (english, chinese) in enumerate(rows[1:], start=2):
        english = english.strip()
        chinese = chinese.strip()
        if not english and not chinese:
            continue
        if not english and chinese:
            errors.append(f"row {row_number}: Chinese name is present but the English name is blank")
            continue
        if not chinese:
            skipped_blank_cn += 1
            continue
        if english in names and names[english] != chinese:
            errors.append(f"row {row_number}: {english!r} maps to both {names[english]!r} and {chinese!r}")
            continue
        if english in names:
            errors.append(f"row {row_number}: duplicate English name {english!r}")
            continue
        names[english] = chinese
        duplicate_cn[chinese].append(english)

    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    repeated_chinese = {value: keys for value, keys in duplicate_cn.items() if len(keys) > 1}
    output = Path(__file__).resolve().parents[1] / "data" / "cn-names.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(names, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[OK] {len(names)} exact character mappings written to {output.relative_to(Path(__file__).resolve().parents[1])}")
    print(f"[INFO] Skipped {skipped_blank_cn} rows with a blank Chinese name")
    if repeated_chinese:
        for chinese, english_names in repeated_chinese.items():
            print(f"[WARN] Reused Chinese name {chinese!r}: {', '.join(english_names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
