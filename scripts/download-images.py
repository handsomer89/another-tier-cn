#!/usr/bin/env python3
"""Download missing CDN image variants for the mirror's on-error fallback."""

import argparse
import concurrent.futures
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
    return sorted(parser.urls)


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
