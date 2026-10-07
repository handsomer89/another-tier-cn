"""Apply only source-verified national-server names, preserving English source data."""
import html
import json
import re
from cn_localization import HtmlCopyRewriter, patch_bundle, locate_asset


def verified_data(root):
    groups = json.loads((root / 'data/cn-verified.json').read_text(encoding='utf-8'))
    expected = {'materials', 'dungeons', 'personalities'}
    if not isinstance(groups, dict) or set(groups) != expected:
        raise ValueError('data/cn-verified.json has an invalid group structure')
    for group, entries in groups.items():
        if not isinstance(entries, dict) or any(
            not isinstance(source, str) or not source.strip()
            or not isinstance(translation, str) or not translation.strip()
            for source, translation in entries.items()
        ):
            raise ValueError(f'data/cn-verified.json has invalid {group} mappings')
    return groups


class VerifiedHtml(HtmlCopyRewriter):
    def __init__(self, source, groups):
        super().__init__(source, {}, {})
        heading = re.search(r'<h1\b[^>]*>(.*?)</h1>', source, re.S)
        self.eligible = bool(heading and re.search(r'[\u3400-\u9fff]', html.unescape(re.sub('<[^>]+>', '', heading[1]))))
        self.groups = groups

    def translate_text(self, value):
        if not self.eligible or not self.detail_fields:
            return value
        field = self.detail_fields[-1]
        if field in ('Class Tome', 'Style Change Tome', '职业书', '异节/改典/典录'):
            return self.groups['materials'].get(value, self.groups['dungeons'].get(value, value))
        if field in ('Personalities', '个性'):
            return self.groups['personalities'].get(value, value)
        return value


def apply_verified(root):
    groups = verified_data(root)
    (root / 'data/cn-verified.json').write_text(json.dumps(groups, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    runtime = 'import{cnNames}from"./cn-names.js";\n'
    runtime += 'export const cnVerified=' + json.dumps(groups, ensure_ascii=False, separators=(',', ':')) + ';\n'
    runtime += 'export function translateVerified(group,value,character){if(typeof value!=="string")return value;if(character!==undefined&&!/[\\u3400-\\u9fff]/u.test(cnNames[character]??character))return value;return cnVerified[group]?.[value]??value;}\n'
    (root / 'assets/cn-verified.js').write_text(runtime, encoding='utf-8')
    assets = list((root / 'assets').glob('*.js'))
    detail = locate_asset(assets, root, 'verified detail', ('r.commentary', 'function R(e)', 'r.otherVersions'))
    tier = locate_asset(assets, root, 'verified search', ('filterPersonalitiesMatch:f', 'classTomes.some', 'function Ft(e)'))
    imported = 'import{translateVerified}from"./cn-verified.js";'
    patch_bundle(detail, 'verified materials and personalities', [
        ('description:r.styleChangeTome', 'description:translateVerified("materials",r.styleChangeTome,r.name)', 1),
        ('r.classTomes.map(z)', 'r.classTomes.map(t=>z(t,r.name))', 1),
        ('function z(e){', 'function z(e,character){', 1),
        ('children:[e.name,e.dropsFrom.length', 'children:[translateVerified("materials",e.name,character),e.dropsFrom.length', 1),
        ('P(e.dropsFrom).map(B)', 'P(e.dropsFrom).map(t=>B(t,character))', 1),
        ('function B(e){', 'function B(e,character){', 1),
        ('children:[e.name,(0,A.jsxs)(`div`', 'children:[translateVerified("dungeons",e.name,character),(0,A.jsxs)(`div`', 1),
        ('r.personalities?.flatMap(V)', 'r.personalities?.flatMap(t=>V(t,r.name))', 1),
        ('function V(e){', 'function V(e,character){', 1),
        ('children:cnTerms.personalities[e]??e', 'children:cnTerms.personalities[e]??translateVerified("personalities",e,character)', 1),
    ], (imported,))
    patch_bundle(tier, 'verified Chinese tome search', [
        ('It(t.styleChangeTome).includes(n)', 'It(t.styleChangeTome).includes(n)||It(translateVerified("materials",t.styleChangeTome,t.name)).includes(n)', 1),
        ('t.classTomes.some(e=>It(e).includes(n))', 't.classTomes.some(e=>It(e).includes(n)||It(translateVerified("materials",e,t.name)).includes(n))', 1),
        ('label:cnTerms.personalities[e]??e', 'label:cnTerms.personalities[e]??translateVerified("personalities",e)', 1),
    ], (imported,))
    changed = 0
    for path in (root / 'c').rglob('*.html'):
        source = path.read_text(encoding='utf-8')
        parser = VerifiedHtml(source, groups)
        parser.feed(source)
        parser.close()
        result = parser.finish()
        if result != source:
            path.write_text(result, encoding='utf-8')
            changed += 1
    print(f'[OK] {sum(map(len, groups.values()))} verified mappings; updated {changed} character pages')
