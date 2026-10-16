#!/usr/bin/env python3
"""Build the independent collection catalog from ranking maps and public snapshots.

The source pages and snapshots are read-only. A failed build keeps the previous
catalog intact. Run --check after image downloads to validate the deployed files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIERS = ("New", "Best", "SSS", "SS", "S", "A", "B", "C", "D", "E", "F", "Niche", "Slave")
SOURCES = (("paid", "index.html"), ("free", "free/index.html"))
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CDN = "https://res.cloudinary.com/ryanditjia/image/upload/"
PORTRAIT = CDN + "dpr_2.0/c_lfill,h_80,w_80/q_auto:low/f_auto/v1/another-eden/characters/{slug}/portrait"
SA = CDN + "dpr_2.0/c_limit,h_24,w_24/{effect}q_auto:low/f_auto/v1/another-eden/sa"


def content_version(characters):
    payload = json.dumps(characters, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_catalog(snapshots, tier_maps):
    """Return a deterministic catalog and maintenance diagnostics without writes."""
    diagnostics = []
    records = {}
    source_records = {}
    candidates = []
    for source_index, (source, _) in enumerate(SOURCES):
        cards = snapshots[source]
        if not isinstance(cards, list) or not cards:
            raise ValueError(f"Empty or invalid {source} character snapshot")
        by_slug = {}
        for card in cards:
            if not isinstance(card, dict) or not SLUG.fullmatch(str(card.get("slug", ""))):
                raise ValueError(f"Invalid character record in {source}")
            slug = card["slug"]
            if not isinstance(card.get("canSA"), bool):
                raise ValueError(f"Invalid canSA value for {slug}")
            if "order" in card or "source" in card:
                raise ValueError(f"Reserved collection fields in source character: {slug}")
            if slug in by_slug:
                diagnostics.append(f"Duplicate {source} snapshot slug: {slug}; keeping its first record")
                if by_slug[slug] != card:
                    diagnostics.append(f"Conflicting {source} duplicate fields for {slug}; retaining first record")
                continue
            by_slug[slug] = card
            if slug in records and records[slug] != card:
                diagnostics.append(f"Paid/free fields disagree for {slug}; retaining the first sorted occurrence")
            records[slug] = card
        source_records[source] = by_slug

        ranked = set()
        for tier_index, (tier, slugs) in enumerate(tier_maps[source]):
            if not isinstance(tier, str) or not isinstance(slugs, list):
                raise ValueError(f"Invalid tier map in {source}")
            known = tier in TIERS
            if not known:
                diagnostics.append(f"Unknown {source} tier {tier!r}; placed after known tiers, update TIERS")
            for position, slug in enumerate(slugs):
                if slug not in by_slug:
                    raise ValueError(f"Ranked {source} slug is absent from its snapshot: {slug}")
                if slug in ranked:
                    diagnostics.append(f"Duplicate {source} ranking slug: {slug}; keeping its earliest unified position")
                ranked.add(slug)
                priority = TIERS.index(tier) if known else len(TIERS)
                key = (priority, source_index, tier_index if not known else 0, position, slug)
                candidates.append((key, slug, source))
        for slug in sorted(by_slug.keys() - ranked):
            diagnostics.append(f"Unranked {source} slug: {slug}; placed after ranked characters")
            candidates.append(((len(TIERS) + 1, source_index, 0, 0, slug), slug, source))

    characters = []
    seen = set()
    for _, slug, source in sorted(candidates):
        if slug in seen:
            diagnostics.append(f"Duplicate unified slug: {slug}; retaining its first sorted occurrence")
            continue
        seen.add(slug)
        characters.append({**source_records[source][slug], "order": len(characters), "source": source})
    if seen != records.keys():
        raise ValueError("Collection coverage differs from the paid/free snapshot union")
    return {"catalogVersion": content_version(characters), "characters": characters}, diagnostics


def load_inputs(root=ROOT):
    extract_data = runpy.run_path(str(ROOT / "scripts/refresh-rankings.py"))["extract_data"]
    snapshots, tier_maps = {}, {}
    for source, page in SOURCES:
        cards = json.loads((root / f"data/characters/{source}.json").read_text(encoding="utf-8"))
        _, hydrated = extract_data((root / page).read_text(encoding="utf-8"))
        # These should come from the same successful refresh; never publish stale fields.
        if cards != [card for _, card in hydrated["characterMap"]["map"]]:
            raise ValueError(f"{source} snapshot differs from ranking page; regenerate public snapshots first")
        snapshots[source] = cards
        tier_maps[source] = [(tier, slugs["set"]) for tier, slugs in hydrated["tierMap"]["map"]]
    return snapshots, tier_maps


def validate_catalog(catalog, expected):
    if not isinstance(catalog, dict) or set(catalog) != {"catalogVersion", "characters"}:
        raise ValueError("Invalid collection catalog structure")
    characters = catalog["characters"]
    if not isinstance(characters, list) or any(not isinstance(card, dict) for card in characters):
        raise ValueError("Invalid collection character list")
    slugs = [card.get("slug") for card in characters]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Duplicate slugs in collection catalog")
    if [card.get("order") for card in characters] != list(range(len(characters))):
        raise ValueError("Collection order indexes are not contiguous")
    if catalog["catalogVersion"] != content_version(characters):
        raise ValueError("Collection catalogVersion does not match its content")
    if catalog != expected:
        raise ValueError("Collection catalog differs from current ranking order or snapshot union; regenerate it")


def validate_images(catalog, root=ROOT):
    images = runpy.run_path(str(ROOT / "scripts/download-images.py"))
    # Keep the browser/export image choices covered even though dynamic cards are
    # not discoverable by the downloader's HTML parser.
    urls = {PORTRAIT.format(slug=card["slug"]) for card in catalog["characters"]}
    if any(card["canSA"] for card in catalog["characters"]):
        urls.update(SA.format(effect=effect) for effect in ("", "e_grayscale/"))
    for card in catalog["characters"]:
        for group, values, size in (
            ("elements", card.get("elements") or [], 18),
            ("light-shadow", [card.get("lightShadow")], 16),
            ("weapons", [card.get("weapon")], 18),
            ("armors", [card.get("armor")], 18),
        ):
            for value in values:
                if value:
                    urls.add(CDN + f"dpr_2.0/c_lfill,h_{size},w_{size}/q_auto:low/f_auto/v1/another-eden/{group}/{value}")
    paths = [root / images["image_path"](url).relative_to(ROOT) for url in sorted(urls)]
    if len(set(paths)) != len(paths):
        raise ValueError("Collection image backup paths collide")
    missing = [str(path.relative_to(root)) for path in paths if not path.is_file()]
    if missing:
        raise ValueError("Missing collection image backups: " + ", ".join(missing[:10])
                         + (f" (and {len(missing) - 10} more)" if len(missing) > 10 else ""))
    return len(paths)


def write_catalog(catalog, expected, destination):
    """Validate serialized output before atomically replacing the last good file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                                         prefix=".collection-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(catalog, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        validate_catalog(json.loads(temporary.read_text(encoding="utf-8")), expected)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate the existing catalog without changing it")
    parser.add_argument("--check-images", action="store_true", help="Also require same-origin portrait and SA backups")
    args = parser.parse_args()
    try:
        catalog, diagnostics = build_catalog(*load_inputs())
        for diagnostic in diagnostics:
            print("[WARN] " + diagnostic, file=sys.stderr)
        destination = ROOT / "data/collection.json"
        count = validate_images(catalog) if args.check_images else None
        if args.check:
            validate_catalog(json.loads(destination.read_text(encoding="utf-8")), catalog)
        elif not destination.is_file() or destination.read_text(encoding="utf-8") != json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n":
            write_catalog(catalog, catalog, destination)
        print(f"[OK] Collection: {len(catalog['characters'])} unique forms, {catalog['catalogVersion']}"
              + (f", {count} image backups" if count is not None else ""))
    except Exception as error:
        print(f"[ERROR] Collection catalog unchanged: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
