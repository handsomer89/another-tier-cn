#!/usr/bin/env python3
"""Export public API-shaped JSON from the mirrored pages' raw hydration data.

Run after refreshing the HTML. The browser reads these same-origin snapshots first
so public navigation stays consistent with the static pages during API outages.
"""

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
extract_data = runpy.run_path(str(ROOT / "scripts/refresh-rankings.py"))["extract_data"]


def main():
    snapshots = {}
    for filename, page in (("paid", "index.html"), ("free", "free/index.html")):
        _, data = extract_data((ROOT / page).read_text())
        snapshots[filename] = [character for _, character in data["characterMap"]["map"]]

    for page in sorted((ROOT / "c").glob("*/index.html")):
        _, character = extract_data(page.read_text())
        if character["slug"] != page.parent.name:
            raise ValueError(f"Character slug disagrees with page path: {page}")
        snapshots[character["slug"]] = character

    listed = {character["slug"] for group in ("paid", "free") for character in snapshots[group]}
    missing = listed - (snapshots.keys() - {"paid", "free"})
    if missing:
        raise ValueError(f"Missing character pages: {', '.join(sorted(missing))}")

    destination = ROOT / "data/characters"
    destination.mkdir(parents=True, exist_ok=True)
    for filename, data in snapshots.items():
        (destination / f"{filename}.json").write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
    print(f"[OK] Public snapshots: {len(snapshots['paid'])} paid, {len(snapshots['free'])} free, "
          f"{len(snapshots) - 2} character details")


if __name__ == "__main__":
    main()
