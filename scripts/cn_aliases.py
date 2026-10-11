"""Localize verified AC aliases in visible copy and browser search."""

import json

from cn_localization import HtmlCopyRewriter, load_object, locate_asset, patch_bundle


class AliasHtml(HtmlCopyRewriter):
    def __init__(self, source, aliases):
        super().__init__(source, {}, {})
        self.aliases = aliases

    def translate_text(self, value):
        # AC aliases occupy the h2 immediately beneath the character name.
        if "h2" in self.stack:
            return self.aliases.get(value, value)
        return value


def apply_aliases(root):
    aliases = load_object(root / "data/cn-aliases.json", "AC alias")
    runtime = "// Generated from data/cn-aliases.json by scripts/localize-cn.py.\n"
    runtime += "export const cnAliases=Object.freeze(" + json.dumps(aliases, ensure_ascii=False, separators=(",", ":")) + ");\n"
    runtime += 'export function translateAlias(value){return cnAliases[value]??value??"";}\n'
    (root / "assets/cn-aliases.js").write_text(runtime, encoding="utf-8")

    assets = list((root / "assets").glob("*.js"))
    detail = locate_asset(assets, root, "AC alias detail", ("r.commentary", "r.alterName", "r.otherVersions"))
    tier = locate_asset(assets, root, "AC alias search", ("filterPersonalitiesMatch:f", "classTomes.some", "function It(e)"))
    imported = 'import{translateAlias}from"./cn-aliases.js";'
    patch_bundle(detail, "Chinese AC detail aliases", [
        ("children:r.alterName", "children:translateAlias(r.alterName)", 1),
    ], (imported,))
    patch_bundle(tier, "Chinese AC alias search", [
        ("It(t.alterName).includes(n)", "It(t.alterName??``).includes(n)||It(translateAlias(t.alterName)).includes(n)", 1),
    ], (imported,))

    changed = 0
    for path in (root / "c").glob("*-ac*/index.html"):
        source = path.read_text(encoding="utf-8")
        parser = AliasHtml(source, aliases)
        parser.feed(source)
        parser.close()
        result = parser.finish()
        if result != source:
            path.write_text(result, encoding="utf-8")
            changed += 1
    print(f"[OK] {len(aliases)} verified AC aliases; updated {changed} character pages")
