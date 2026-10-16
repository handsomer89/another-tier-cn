#!/usr/bin/env python3
"""Version the collection's module graph and stylesheet to avoid stale exports."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORT = re.compile(r'''(\bfrom\s*["'])(\./[^"'?]+\.js)(?:\?v=[0-9a-f]+)?(["'])''')


def content_version(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def apply_versions(root: Path, *, check: bool = False) -> int:
    pending = {}
    versions = {}
    visiting = set()

    def visit(path: Path) -> str:
        path = path.resolve()
        if path in visiting:
            raise ValueError(f"Circular collection module import: {path.name}")
        if path in versions:
            return versions[path]
        visiting.add(path)
        source = path.read_text(encoding="utf-8")

        def version_import(match: re.Match[str]) -> str:
            version = visit(path.parent / match[2])
            return f"{match[1]}{match[2]}?v={version}{match[3]}"

        result = IMPORT.sub(version_import, source)
        visiting.remove(path)
        versions[path] = content_version(result)
        if result != source:
            pending[path] = result
        return versions[path]

    entry_version = visit(root / "assets/collection.js")
    css_version = content_version((root / "assets/collection.css").read_text(encoding="utf-8"))
    page = root / "collection/index.html"
    source = page.read_text(encoding="utf-8")
    result = source
    for name, version in [("collection.js", entry_version), ("collection.css", css_version)]:
        pattern = re.compile(rf'''(/another-tier-cn/assets/{re.escape(name)})(?:\?v=[0-9a-f]+)?(?=["'])''')
        result, count = pattern.subn(lambda match: f"{match[1]}?v={version}", result)
        if count != 1:
            raise ValueError(f"Expected one collection asset URL in HTML: {name}")
    if result != source:
        pending[page] = result
    if check and pending:
        raise ValueError("Collection asset versions are stale; run python3 scripts/version-collection-assets.py")
    for path, result in pending.items():
        path.write_text(result, encoding="utf-8")
    print(f"[OK] collection asset versions: {len(versions)} modules checked, {len(pending)} files updated")
    return len(pending)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check content versions without changing files")
    args = parser.parse_args()
    try:
        apply_versions(ROOT, check=args.check)
        return 0
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
