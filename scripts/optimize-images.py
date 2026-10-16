#!/usr/bin/env python3
"""Generate content versions and apply snapshot-first image URLs before loading."""

import argparse
import hashlib
import json
import re
from html import escape, unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CDN = 'https://res.cloudinary.com/ryanditjia/image/upload/'
BASE = '/another-tier-cn/mirror-images/'
RUNTIMES = {
    'section-heading-y4o2THRi.js': 'b',
    '_-_type_-DkE39AzC.js': 'Q',
    'c._slug.index-BladTgt_.js': 'A',
    'stellar-awakening-icon-Cb239FB7.js': 'a',
}


def apply_images(root=ROOT, *, check=False, assets_only=False):
    pending = {}
    versions = {p.relative_to(root / 'mirror-images').as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()[:12]
                for p in sorted((root / 'mirror-images').rglob('*.webp'))}
    manifest = 'export const imageVersions = Object.freeze(' + json.dumps(versions, separators=(',', ':')) + ');\n'

    def put(path, result):
        if not path.is_file() or path.read_text(encoding='utf-8') != result:
            pending[path] = result

    put(root / 'assets/image-manifest.js', manifest)
    for name, binding in RUNTIMES.items():
        path = root / 'assets' / name
        source = path.read_text(encoding='utf-8')
        original, patched = f'{binding}=e()', f'{binding}=mirrorImageRuntime(e())'
        if patched not in source:
            if source.count(original) != 1:
                raise ValueError(f'Image JSX runtime changed: {name}')
            source = source.replace(original, patched)
        if 'import{mirrorImageRuntime}from' not in source:
            source = 'import{mirrorImageRuntime}from"./image-fallback.js";' + source
        put(path, source)

    if not assets_only:
        def rewrite_tag(match):
            tag = match[0]
            attribute = 'src' if tag.startswith('<img') else 'href'
            if attribute == 'href' and not re.search(r'\bas="image"', tag):
                return tag
            source = re.search(rf'(?<![\w-]){attribute}="([^"]*)"', tag)
            original = re.search(r'\bdata-original-src="([^"]*)"', tag)
            if not source:
                return tag
            url = unescape(original[1] if original else source[1])
            if not url.startswith(CDN):
                return tag
            file = re.sub(r'[^a-zA-Z0-9/._-]', '_', url[len(CDN):]) + '.webp'
            if file not in versions:
                return tag
            tag = tag[:source.start(1)] + BASE + file + '?v=' + versions[file] + tag[source.end(1):]
            if not original:
                tag = tag.replace(' ' + attribute + '=', ' data-original-src="' + escape(url, quote=True) + '" ' + attribute + '=', 1)
            return tag

        for path in root.rglob('*.html'):
            if not path.is_relative_to(root / 'dist'):
                put(path, re.sub(r'<(?:img|link)\b[^>]*>', rewrite_tag, path.read_text(encoding='utf-8')))

    if check and pending:
        raise ValueError('Image snapshots are stale; run python3 scripts/optimize-images.py: '
                         + ', '.join(str(p.relative_to(root)) for p in list(pending)[:5]))
    for path, source in pending.items():
        path.write_text(source, encoding='utf-8')
    print(f'[OK] snapshot-first images: {len(versions)} content versions, {len(pending)} files updated')
    return len(pending)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--assets-only', action='store_true')
    args = parser.parse_args()
    apply_images(check=args.check, assets_only=args.assets_only)
