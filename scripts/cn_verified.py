"""Apply only source-verified national-server names, preserving English source data."""
import csv
import html
import json
import re
from cn_localization import HtmlCopyRewriter, patch_bundle, locate_asset


def read_rows(root, filename):
    with (root / 'reports' / filename).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def verified_data(root):
    groups = {'materials': {}, 'dungeons': {}, 'personalities': {}}
    for filename in ('未汉化名称清单.csv', '其他英文名称待核对.csv'):
        for row in read_rows(root, filename):
            if row['核对状态'] != '国服资料已核对':
                continue
            english, chinese = row['英文原文'], row['中文译名（国服原文）']
            if not chinese or not row['来源链接']:
                raise ValueError(f'Missing verified translation or source: {english}')
            group = 'personalities' if row['类别'] == '个性' else 'dungeons' if row['类别'] == '副本/掉落地点' else 'materials'
            if english in groups[group] and groups[group][english] != chinese:
                raise ValueError(f'Conflicting verified translation: {english}')
            groups[group][english] = chinese
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


def pending_markdown(root):
    rows = read_rows(root, '待核实国服译名.csv')
    output = ['# 待核实国服译名', '', '核对日期：2026-10-07。共 25 项：24 项书籍材料，1 项网站分类用语。', '',
              '仅纳入网站角色名已为中文的角色。下列条目尚未取得中国国服完整原文，或资料存在用字冲突；候选译名不作为网站译文，网站保留英文。角色名仍为英文的条目不在本表翻译范围内。', '',
              '| ID | 类别 | 英文原文 | 国服关联角色 | 核对状态 | 候选译名 / 待核实原因 | 参考来源 |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for row in rows:
        links = '<br>'.join(f'[来源 {i}]({url})' for i, url in enumerate(row['来源链接'].splitlines(), 1) if url)
        values = [row['条目ID'], row['类别'], row['英文原文'], row['国服关联角色（按网站）'], row['核对状态'], row['候选译名/差异说明'], links or '暂无可确认原文的来源']
        output.append('| ' + ' | '.join(value.replace('|', '\\|').replace('\n', '<br>') for value in values) + ' |')
    output += ['', '完整检索记录及页面定位见 [待核实国服译名.csv](待核实国服译名.csv)；已核对的原文与证据见 [未汉化名称清单.md](未汉化名称清单.md) 和 [其他英文名称待核对.csv](其他英文名称待核对.csv)。', '']
    (root / 'reports/待核实国服译名.md').write_text('\n'.join(output), encoding='utf-8')
