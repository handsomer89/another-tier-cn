#!/usr/bin/env python3
"""Trim source-site analytics and admin loading from the public static mirror.

Run after localization or a mirror refresh. Original admin bundles stay on disk
because localization also patches their shared UI code.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SDK = "module-Cgfs6_u8.js"


def write_changed(path: Path, source: str) -> None:
    if path.read_text(encoding="utf-8") != source:
        path.write_text(source, encoding="utf-8")


def optimize_assets() -> None:
    # The entry used the Mutation class from an admin route chunk. Keep the
    # shared class while cutting the route import and its static dependencies.
    admin = (ASSETS / "admin.characters._slug-jCSjMq9H.js").read_text(encoding="utf-8")
    mutation = admin[admin.index("var l=class"):admin.index("var d=n(`/admin/characters/$slug`)")]
    (ASSETS / "query-mutation.js").write_text(
        'import{I as i,L as a,z as o}from"./character-BWOG_BU2.js";'
        + mutation + 'export{l as n};\n', encoding="utf-8"
    )

    path = ASSETS / "index-Dn3mCF7k.js"
    source = path.read_text(encoding="utf-8")
    source = source.replace('import{r as me,t as he}', 'import{t as he}')
    source = source.replace('import{n as Le,t as Re}from"./admin.characters._slug-jCSjMq9H.js";',
                            'import{n as Le}from"./query-mutation.js";')
    for name, binding in [("login-CyYE1qSR.js", "Ve"), ("admin-oClykytE.js", "He"),
                          ("admin.teams-B-atVWsq.js", "We"), ("admin.characters-_e0dkfda.js", "Ge"),
                          ("admin.characters.index-EaCGXR4M.js", "Je")]:
        source = source.replace(f'import{{t as {binding}}}from"./{name}";', "")
    if "var Yo=te(`/admin/`)" in source:
        start = source.index("var Yo=te(`/admin/`)")
        end = source.index(";function ps()", start)
        source = source[:start] + (
            'var Qo=Ue.update({id:`/_site`,getParentRoute:()=>qo}),'
            'ns=Ke.update({id:`/{-$type}`,path:`/{-$type}`,getParentRoute:()=>Qo}),'
            'rs=qe.update({id:`/teams`,path:`/teams`,getParentRoute:()=>Qo}),'
            'os={SiteTeamsRoute:rs,SiteChar123TypeChar125Route:ns,'
            'SiteCSlugIndexRoute:Ye.update({id:`/c/$slug/`,path:`/c/$slug/`,getParentRoute:()=>Qo})},'
            'ss=Qo._addFileChildren(os),us={SiteRoute:ss},ds=qo._addFileChildren(us)'
        ) + source[end:]
    start = source.index("function ms(e)", source.index("function ps(){let e=new Ha"))
    end = source.index("async function hs()", start)
    source = source[:start] + 'function ms(e){return Ua.useEffect(installImageFallback,[]),e.children}' + source[end:]
    image_import = 'import{installImageFallback}from"./image-fallback.js";'
    if image_import not in source:
        source = image_import + source
    source = source.replace(", maximum-scale=1", "")
    for name in ["favicon-96x96.png", "favicon.svg", "favicon.ico", "apple-touch-icon.png", "site.webmanifest"]:
        source = source.replace(f'href:`/{name}`', f'href:`/another-tier-cn/{name}`')
    write_changed(path, source)

    # Auth and event hooks remain compatible, without importing or initializing
    # the original site's 173 KB analytics SDK.
    path = ASSETS / "auth-context-COmTV8lL.js"
    source = path.read_text(encoding="utf-8")
    source = source.replace(f'import{{t as o}}from"./{SDK}";', "")
    start, end = source.index("var u=r()"), source.index("var w=e()")
    source = (source[:start] + 'var u=r(),d=a(i());function _(e){return e.children}'
              'function y(){return null}' + source[end:])
    write_changed(path, source)
    write_changed(ASSETS / "posthog-CY_6dI6O.js",
                  '// Analytics are disabled for this public mirror.\n'
                  'function t(){}export{t as a,t as i,t as n,t as r,t};\n')

    # Vite's runtime preloader also lists transitive imports. Preserve indices
    # and remove the SDK after mapping, so dynamic imports cannot download it.
    for name in ["_-_type_-sCbOOeVf.js", "c._slug.index-CnDIcEok.js", "teams-BxreHm35.js"]:
        path = ASSETS / name
        source = path.read_text(encoding="utf-8")
        source = source.replace('=>i.map(i=>d[i]);',
                                f'=>i.map(i=>d[i]).filter(p=>!p.endsWith("/{SDK}"));')
        write_changed(path, source)

    # The original Vite build used /. Runtime preloads must use the same base
    # as the mirrored entry and its relative dynamic imports.
    path = ASSETS / "preload-helper-BXtnOz6r.js"
    source = path.read_text(encoding="utf-8")
    source = source.replace('eg=function(e){return`/`+e}',
                            'eg=function(e){return`/another-tier-cn/`+e}')
    write_changed(path, source)

    for path in ASSETS.glob("*.css"):
        source = path.read_text(encoding="utf-8")
        source = re.sub(r"@font-face\{([^}]+)\}",
                        lambda m: m[0] if "font-display:" in m[1]
                        else "@font-face{font-display:swap;" + m[1] + "}", source)
        write_changed(path, source)


def optimize_html() -> None:
    # Public pages never use admin/login. Their files are deliberately retained.
    removed = 0
    pattern = re.compile(r'<link\b(?=[^>]*\brel="modulepreload")(?=[^>]*\bhref="[^"]*/assets/(?:admin[^"/]*|login-[^"/]*|module-Cgfs6_u8)\.js")[^>]*?/?>')
    unwanted = re.compile(r"/assets/(?:admin|login-|module-Cgfs6_u8)")
    # TanStack serializes a second preload list into its hydration manifest.
    # Filter these arrays too, retaining $R assignments and their reference IDs.
    def trim_manifest(match: re.Match[str]) -> str:
        preloads = json.loads(match[2])
        return match[1] + json.dumps([p for p in preloads if not unwanted.search(p)], separators=(",", ":"))

    for path in ROOT.rglob("*.html"):
        if path.is_relative_to(ROOT / "dist"):
            continue
        source = path.read_text(encoding="utf-8")
        source, count = pattern.subn("", source)
        removed += count
        source = re.sub(r'(preloads:(?:\$R\[\d+\]=)?)(\[[^\]]*\])', trim_manifest, source)
        # A Cloudflare challenge captured from the source site cannot run on
        # this mirror. Remove only that challenge script, not application code.
        source = re.sub(r"<script\b[^>]*>.*?</script>",
                        lambda m: "" if "__CF$cv$params" in m[0]
                        and "challenge-platform/scripts/jsd/main.js" in m[0] else m[0],
                        source, flags=re.DOTALL)
        write_changed(path, source.replace(", maximum-scale=1", ""))
    print(f"Removed {removed} admin/login/analytics modulepreloads; viewport zoom enabled.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-only", action="store_true", help="Leave HTML for the final generation step")
    args = parser.parse_args()
    optimize_assets()
    if not args.assets_only:
        optimize_html()
    navigation_args = ["--assets-only"] if args.assets_only else []
    subprocess.run([sys.executable, str(ROOT / "scripts" / "patch-collection-navigation.py"), *navigation_args], check=True)
    print("Public entry excludes admin/login routes; source-site analytics disabled; fonts use swap.")


if __name__ == "__main__":
    main()
