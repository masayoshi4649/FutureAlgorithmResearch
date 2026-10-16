"""公開採点を変えず、率差の単位と実施済み反証の案内だけを訂正する。"""

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
ARCHIVE = HERE / 'report_archive/revision3'
OUT = HERE / 'report_check/revision4'
MD_NAME = '事後に残った予兆候補S03.md'
MANIFEST = HERE / '四十四条件と全三十七場の公開射影.json'
REVIEW = '../../work/topix10pt_20261016/s03_review/S03の仮説と六割の信頼性を敵対的に確認.md'


def main() -> None:
    """
    機能: revision3を保全し、率差表記と参考反証の実施状況だけを修正する。
    引数: なし。根の2点の表示訂正に限定。
    返り値: None。数値・selection・実測sourceを変えず、元市場・結果・射影を再読しない。
    """
    report.check(not ARCHIVE.exists() and not OUT.exists(), '自動修正再実行を禁止')
    ARCHIVE.mkdir(parents=True)
    OUT.mkdir(parents=True)
    old = {}
    archived = []
    for path in [report.PUBLIC / name for name in (report.HTML_NAME, report.JSON_NAME, 'README.md', MD_NAME)] + [MANIFEST]:
        data = path.read_bytes()
        (ARCHIVE / path.name).write_bytes(data)
        old[path.name] = data
        archived.append(dict(original=path.relative_to(ROOT).as_posix(), path=(ARCHIVE / path.name).relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(data).hexdigest()))
    html = old[report.HTML_NAME].decode('utf-8')
    original_data = re.findall(r'<script id="report-data" type="application/json">(.*?)</script>', html, flags=re.S)
    report.check(len(original_data) == 1, '旧埋込データの一意')
    html, changes = re.subn(r'(<td>)([+-]\d+(?:\.\d+)?)pt(</td>)', r'\g<1>\g<2>％ポイント\g<3>', html)
    report.check(changes == 5, '正式3とS03/T01の率差5セルだけ')
    html = html.replace('<th>良い方との差</th>', '<th>良い方との差（率）</th>')
    old_note = '大きく当たった場を除く確認は未実施で、場への依存を要確認です。'
    new_note = '1場ずつ除く参考確認も行いましたが、小標本・場依存は残ります。'
    report.check(html.count(old_note) == 1, '未実施文の一意')
    html = html.replace(old_note, new_note + ' <a href="' + REVIEW + '">1場除外・場bootstrapの反証</a>。')
    current_data = re.findall(r'<script id="report-data" type="application/json">(.*?)</script>', html, flags=re.S)
    report.check(current_data == original_data, '埋込採点とselectionの同bytes')
    markdown = old[MD_NAME].decode('utf-8')
    report.check(markdown.count(old_note) == 1, 'MD未実施文の一意')
    markdown = markdown.replace(old_note, new_note + ' [1場除外・場bootstrapの反証](' + REVIEW + ')。')
    texts = {report.HTML_NAME: html, MD_NAME: markdown}
    for name, text in texts.items():
        data = text.encode('utf-8')
        (OUT / name).write_bytes(data)
        (report.PUBLIC / name).write_bytes(data)
    report.check((report.PUBLIC / report.JSON_NAME).read_bytes() == old[report.JSON_NAME], '公開採点JSONの同bytes')
    outputs = []
    for name in (report.HTML_NAME, report.JSON_NAME, 'README.md', MD_NAME):
        data = texts[name].encode('utf-8') if name in texts else old[name]
        outputs.append(dict(path=(report.PUBLIC / name).relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(data).hexdigest()))
    manifest = json.loads(old[MANIFEST.name].decode('utf-8'))
    manifest.update(revision=4, outputs=outputs, 前revision同bytes保全=archived,
        表記修正='率差5セルを％ポイントと明示。1場除外の参考確認済み文と反証MDリンクを追加。全採点/正式選択不変。',
        final_labels_source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        元結果再読=0, 元小射影再読=0)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    proof = dict(全合格=True, 率差セル修正=changes, 公開採点同bytes=True, 埋込採点同bytes=True,
        原市場=0, 原結果再読=0, 元小射影再読=0, 金融=0, API=0,
        outputs=outputs, 前revision同bytes保全=archived, source_SHA256=manifest['source_SHA256'],
        final_labels_source_SHA256=manifest['final_labels_source_SHA256'])
    (OUT / '率差単位と反証実施状況だけの訂正証跡.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, revision=4, 率差5セル=changes, 公開採点同bytes=True, 埋込採点同bytes=True, 原結果再読=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
