"""確定した採点値を変えず、事後候補S03と全期間の弱さを冒頭へ示す。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report

ROOT = HERE.parents[1]
ARCHIVE = HERE / 'report_archive/revision2'
OUT = HERE / 'report_check/revision3'
MD_NAME = '事後に残った予兆候補S03.md'
MANIFEST = HERE / '四十四条件と全三十七場の公開射影.json'


def main() -> None:
    """
    機能: revision2を同bytes保全し、S03の位置・具体3手順・全期間留保だけを変更する。
    引数: なし。根の明示したUI修正に固定。
    返り値: None。原結果・元射影・原入力・金融を読まず、公開採点の再選択をしない。
    """
    report.check(not OUT.exists() and not ARCHIVE.exists(), '自動修正再実行を禁止')
    OUT.mkdir(parents=True)
    ARCHIVE.mkdir(parents=True)
    old = {}
    archived = []
    for path in [report.PUBLIC / name for name in (report.HTML_NAME, report.JSON_NAME, 'README.md', MD_NAME)] + [MANIFEST, HERE / 'append_s03.py']:
        data = path.read_bytes()
        (ARCHIVE / path.name).write_bytes(data)
        old[path.name] = data
        archived.append(dict(original=path.relative_to(ROOT).as_posix(), path=(ARCHIVE / path.name).relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(data).hexdigest()))
    public = json.loads(old[report.JSON_NAME].decode('utf-8'))
    unchanged = deepcopy(public)
    summaries = {row['id']: row for row in public['summaries']}
    summary = summaries['S03']
    recent = summary['periods']['別枠10']['risks'][2]['全体']
    full = summary['periods']['全37']['risks'][2]['全体']
    train = summary['periods']['学習']['risks'][2]['全体']
    night = next(row for row in public['rows'] if row['id'] == 'S03' and row['session'] == '2026-10-14_Night')['risks'][2]
    caution = ('別枠10場の順10／逆10は' + report.cell_text(recent) + 'ですが、全37場では' + report.cell_text(full) +
               '、学習内21場では' + report.percentage(train['全候補順先率']) + 'です。全期間で安定した予兆とは言えません。')
    concentration = ('別枠の順先' + str(recent['順先']) + '件には、2026-10-14ナイトの' + str(night['順先']) + '/' + str(night['n']) +
                     'が含まれます。大きく当たった場を除く確認は未実施で、場への依存を要確認です。')
    steps = [
        '直前5分の高安幅が、直前20分の高安幅の半分以下に狭まっている。',
        'EMA2・3・4・5・6・8が新しく同方向へ並び、短期EMA帯の幅も拡大する。',
        '閉じた足を公開した時点の現在Lastが、前5分の高値より上（買い）又は安値より下（売り）にある。'
    ]
    steps_html = '<ol id="posthoc-steps">' + ''.join('<li>' + value + '</li>' for value in steps) + '</ol>'
    original_html = old[report.HTML_NAME].decode('utf-8')
    pattern = r'<section class="panel" id="posthoc-s03">.*?</section>'
    found = re.findall(pattern, original_html, flags=re.S)
    report.check(len(found) == 1, '既追補章の一意')
    body = found[0]
    body = body.replace('<h2>事後に残った予兆候補：S03</h2>', '<h2>探索で残った候補 S03</h2>')
    intro = '<p>短い時間の値幅が狭まった後、短期移動平均が揃い始め、現在値が過去の帯を抜ける場面を拾う手法です。</p>'
    report.check(body.count(intro) == 1, '要点段落の位置')
    body = body.replace(intro, steps_html)
    width = re.findall(r'<div class="scroll"><table id="posthoc-width-table">.*?</table></div>', body, flags=re.S)
    report.check(len(width) == 1, '三幅表の一意')
    body = body.replace(width[0], '')
    body = body.replace(steps_html, steps_html + width[0] + '<p class="notice" id="posthoc-full-caution">' + caution +
        '</p><p class="note">' + concentration + ' 全44条件を見た後に注目した最近10場の仮説で、未知の市場での再現は確認していません。</p>')
    comparison = re.findall(r'<div class="scroll"><table id="posthoc-comparison-table">.*?</table></div>', body, flags=re.S)
    report.check(len(comparison) == 1, 'T01比較の一意')
    body = body.replace(comparison[0], '<details><summary>S03とT01の固定方向比較（事後所見）</summary>' + comparison[0] + '</details>')
    html = original_html.replace(found[0], '')
    report.check(html.count('</h1>') == 1, 'タイトルの一意')
    html = html.replace('</h1>', '</h1>' + body)
    previous_default = 'const selected=D.displayed.length?D.displayed[0].id:D.specifications[0].id;'
    report.check(html.count(previous_default) == 1, 'ビュー初期値の一意')
    html = html.replace(previous_default, "const selected='S03';")
    public['view_initial_id'] = 'S03'
    public['view_note'] = '全37場の初期表示だけS03。正式selectionと候補3件は不変更。'
    payload = json.dumps(public, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    html = re.sub(r'(<script id="report-data" type="application/json">).*?(</script>)',
                  lambda match: match.group(1) + payload + match.group(2), html, count=1, flags=re.S)
    report.check(public['selection'] == unchanged['selection'] and public['displayed'] == unchanged['displayed'], '正式選択不変')
    report.check(public['rows'] == unchanged['rows'] and public['summaries'] == unchanged['summaries'], '全数値不変')
    primary_pattern = r'<table id="primary-table">.*?</table>'
    report.check(re.findall(primary_pattern, original_html, flags=re.S) == re.findall(primary_pattern, html, flags=re.S), '正式3主表の同bytes')
    markdown = old[MD_NAME].decode('utf-8')
    paragraph = '\n\n' + caution + '\n\n' + concentration + '\n\n簡単な3手順：\n\n' + '\n'.join(f'{i + 1}. {value}' for i, value in enumerate(steps))
    point = markdown.index('\n\n具体的な入口：')
    markdown = markdown[:point] + paragraph + markdown[point:]
    readme = old['README.md'].decode('utf-8') + '\nHTMLの冒頭は事後所見S03です。全37場の初期表示もS03ですが、選択6場で決めた正式3候補のID・数値は変更していません。\n'
    texts = {report.HTML_NAME: html, report.JSON_NAME: json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
             'README.md': readme, MD_NAME: markdown}
    outputs = []
    for name, text in texts.items():
        data = text.encode('utf-8')
        (OUT / name).write_bytes(data)
        (report.PUBLIC / name).write_bytes(data)
        outputs.append(dict(path=(report.PUBLIC / name).relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(data).hexdigest()))
    manifest = json.loads(old[MANIFEST.name].decode('utf-8'))
    manifest.update(revision=3, outputs=outputs, 前revision同bytes保全=archived,
        UI修正='事後S03の冒頭配置・具体3手順・全期間低率と場依存を近接表示。全37初期ビューだけS03。正式選択/全数値不変。',
        UI_source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 元結果再読=0, 元小射影再読=0)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    proof = dict(全合格=True, 原結果再読=0, 元小射影再読=0, 原入力=0, 金融=0, API=0,
        正式選択不変=True, 全数値不変=True, 正式主表同bytes=True, 冒頭S03=True, 初期ビュー='S03',
        outputs=outputs, 前revision同bytes保全=archived, source_SHA256=public['source_SHA256'],
        UI_source_SHA256=manifest['UI_source_SHA256'])
    (OUT / 'S03冒頭配置と正式選択全数値不変の証跡.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 正式選択不変=True, 全数値不変=True, revision=3, 元結果再読=0, 元小射影再読=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
