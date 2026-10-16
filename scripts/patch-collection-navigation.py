#!/usr/bin/env python3
"""Keep the independent collection link in the ranking SSR and client navigation.

Only the known ranking toggle bundle and three ranking headers are patched.
Unexpected bundle/header shapes fail before any file is written.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HREF = "/another-tier-cn/collection/"
LINK_CLASS = (
    "flex items-center gap-1.5 rounded-[calc(var(--radius-lg)-1px)] pl-2 pr-2.5 py-1.5 "
    "text-xs font-medium transition-colors border border-transparent "
    "text-gray-600 hover:text-gray-900 whitespace-nowrap "
    "dark:text-gray-300 dark:hover:text-gray-100 "
    "outline-none focus-visible:ring-2 focus-visible:ring-gray-400 "
    "focus-visible:ring-offset-1 dark:focus-visible:ring-gray-500"
)
LINK_HTML = f'<a href="{HREF}" class="{LINK_CLASS}" data-collection-navigation="true">图鉴</a>'
CLIENT_OLD = "r=n.map(l),t[0]=n,t[1]=r"
CLIENT_NEW = (
    'r=[...n.map(l),(0,s.jsx)(`a`,{href:`' + HREF + '`,className:`' + LINK_CLASS
    + '`,"data-collection-navigation":"true",children:`图鉴`},`collection`)],t[0]=n,t[1]=r'
)
ROUTES = ("index.html", "no-sa/index.html", "free/index.html")


def patch_client(source: str, label: str) -> str:
    # These anchors identify the original toggle implementation, independently
    # of the filename hash and of the Chinese display-copy imports.
    for anchor in ("function l(e){let{label:t,to:r,search:a,params:o,Icon:c,prefix:l}=e;", "links:[u,p,h]"):
        if source.count(anchor) != 1:
            raise ValueError(f"{label}: expected one known ranking-toggle anchor: {anchor}")
    old, new = source.count(CLIENT_OLD), source.count(CLIENT_NEW)
    if old == 0 and new == 1 and source.count(HREF) == 1:
        return source
    if old != 1 or new != 0 or HREF in source:
        raise ValueError(f"{label}: unexpected collection patch state (old={old}, new={new})")
    return source.replace(CLIENT_OLD, CLIENT_NEW, 1)


def patch_html(source: str, label: str) -> str:
    headers = list(re.finditer(r"<header\b[^>]*>.*?</header>", source, re.DOTALL))
    if len(headers) != 1:
        raise ValueError(f"{label}: expected exactly one header, found {len(headers)}")
    header = headers[0]
    anchors = list(re.finditer(
        r'<a\b(?=[^>]*\bhref="/another-tier-cn/free/?(?:\?[^"<>]*)?")[^>]*>[^<]*</a>',
        header[0],
    ))
    if len(anchors) != 1:
        raise ValueError(f"{label}: expected one Free navigation anchor, found {len(anchors)}")
    anchor = anchors[0]
    if re.sub(r"<[^>]+>", "", anchor[0]).strip() not in {"Free", "配布"}:
        raise ValueError(f"{label}: unexpected Free navigation label")
    end = header.start() + anchor.end()
    if source.count(LINK_HTML) == 1 and source[end:end + len(LINK_HTML)] == LINK_HTML:
        if source.count(HREF) != 1:
            raise ValueError(f"{label}: duplicate collection navigation")
        return source
    if HREF in source or "data-collection-navigation" in source:
        raise ValueError(f"{label}: collection link differs from the known adjacent native link")
    return source[:end] + LINK_HTML + source[end:]


def apply_navigation(root: Path, *, assets_only: bool = False, check: bool = False) -> int:
    bundles = sorted((root / "assets").glob("tier-list-paid-free-toggle-*.js"))
    if len(bundles) != 1:
        raise ValueError(f"Expected one ranking-toggle bundle, found {len(bundles)}")
    files = [(bundles[0], patch_client)]
    if not assets_only:
        files.extend((root / route, patch_html) for route in ROUTES)
    pending = []
    for path, patch in files:
        source = path.read_text(encoding="utf-8")
        result = patch(source, str(path.relative_to(root)))
        if check and result != source:
            raise ValueError(f"{path.relative_to(root)}: collection navigation patch is missing")
        if result != source:
            pending.append((path, result))
    for path, result in pending:
        path.write_text(result, encoding="utf-8")
    print(f"[OK] collection native navigation: {len(files)} files checked, {len(pending)} changed")
    return len(pending)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-only", action="store_true", help="Leave ranking HTML for the final generation step")
    parser.add_argument("--check", action="store_true", help="Verify navigation without writing files")
    args = parser.parse_args()
    try:
        apply_navigation(ROOT, assets_only=args.assets_only, check=args.check)
        return 0
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
