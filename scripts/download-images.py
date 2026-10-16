#!/usr/bin/env python3
"""Download missing CDN image variants for the mirror's on-error fallback."""

import argparse
import concurrent.futures
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CDN = "https://res.cloudinary.com/ryanditjia/image/upload/"


def image_path(url):
    # Keep this naming rule in sync with assets/image-fallback.js.
    return ROOT / "mirror-images" / (re.sub(r"[^a-zA-Z0-9/._-]", "_", url[len(CDN):]) + ".webp")


class Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        src = dict(attrs).get("src", "")
        if tag == "img" and src.startswith(CDN):
            self.urls.add(src)


def image_urls():
    parser = Images()
    for page in ROOT.rglob("*.html"):
        if not page.is_relative_to(ROOT / "dist"):
            parser.feed(page.read_text(encoding="utf-8"))
    # Collection cards are created in the browser, so their portraits and icons
    # may never occur in static HTML (for example, a newly introduced element).
    catalog = ROOT / "data/collection.json"
    if catalog.is_file():
        parser.urls.update(collection_image_urls(json.loads(catalog.read_text(encoding="utf-8"))))
    return sorted(parser.urls)


def collection_image_urls(catalog):
    """Include exactly the variants used by collection cards and PNG exports."""
    urls = set()
    for card in catalog["characters"]:
        urls.add(CDN + "dpr_2.0/c_lfill,h_80,w_80/q_auto:low/f_auto/v1/another-eden/characters/"
                 + card["slug"] + "/portrait")
        if card["canSA"]:
            urls.update(CDN + "dpr_2.0/c_limit,h_24,w_24/" + effect + "q_auto:low/f_auto/v1/another-eden/sa"
                        for effect in ("", "e_grayscale/"))
        for group, values, size in (
            ("elements", card.get("elements") or [], 18),
            ("light-shadow", [card.get("lightShadow")], 16),
            ("weapons", [card.get("weapon")], 18),
            ("armors", [card.get("armor")], 18),
        ):
            urls.update(CDN + f"dpr_2.0/c_lfill,h_{size},w_{size}/q_auto:low/f_auto/v1/another-eden/{group}/{value}"
                        for value in values if value)
    return urls


def download(url, refresh=False):
    target = image_path(url)
    if target.is_file() and not refresh:
        return False
    request = Request(url, headers={"Accept": "image/webp", "User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        data = response.read()
    if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise ValueError(f"Expected WebP image: {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Download existing backups again")
    args = parser.parse_args()
    urls = image_urls()
    if len({image_path(url) for url in urls}) != len(urls):
        raise ValueError("Image backup filenames collide")
    downloaded = 0
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(download, url, args.refresh): url for url in urls}
        for count, job in enumerate(concurrent.futures.as_completed(jobs), 1):
            try:
                downloaded += job.result()
            except Exception as error:
                errors.append(f"{jobs[job]}: {error}")
            if count % 100 == 0:
                print(f"[INFO] Checked {count}/{len(urls)} images", flush=True)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        raise SystemExit(f"{len(errors)} downloads failed; rerun to fetch missing images")
    total = sum(image_path(url).stat().st_size for url in urls)
    print(f"[OK] {len(urls)} image backups, {downloaded} downloaded, {total / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    main()
