"""公開説明の範囲・算術・表不変更を検査し、専用ブラウザで表示を保存する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00114_公表活動と表示数量の維持後の価格応答'
WORK = HERE.parent
AUDIT = WORK / 'audit_aggregation'
HTML = PUBLIC / '表示数量を観測した後の方向応答.html'
PROOF = HERE / '説明算術と表不変更及び隔離表示の確認.json'


def sha(raw: bytes) -> str:
    """
    機能: 保存対象の同一性を示す指紋を作る。
    引数: raw(bytes)。
    返り値: SHA256の十六進文字列(str)。
    """
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict:
    """
    機能: 既に保存された小検算資料を読む。
    引数: path(Path)。
    返り値: 辞書(dict)。原結果・原入力は対象外。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def cells(text: str) -> list[list[list[str]]]:
    """
    機能: HTMLの全表セルを空白正規化して抽出する。
    引数: text(str)。
    返り値: 表・行・セルの三重リスト(list)。
    """
    soup = BeautifulSoup(text, 'html.parser')
    return [[[cell.get_text(' ', strip=True) for cell in row.find_all(['th', 'td'])]
             for row in table.find_all('tr')] for table in soup.find_all('table')]


def links(path: Path) -> int:
    """
    機能: 公開文書のローカル参照先が実在することを確認する。
    引数: path(Path)。
    返り値: 検査した参照数(int)。外部通信は行わない。
    """
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.html':
        urls = [tag['href'] for tag in BeautifulSoup(text, 'html.parser').select('a[href]')]
    else:
        urls = re.findall(r'\]\(([^)]+)\)', text)
    checked = 0
    for value in urls:
        if value.startswith(('http:', 'https:', '#')):
            continue
        target = path.parent / unquote(value.split('#')[0])
        assert target.exists(), (str(path), value)
        checked += 1
    return checked


def main() -> None:
    """
    機能: 文書補足・初版保全の同値確認・独立算術・暗色広狭表示を一度保存する。
    引数: なし。
    返り値: None。原入力・原結果・金融・APIを読まず、測定sourceを変更しない。
    """
    assert not PROOF.exists(), '完成証跡は上書きしない'
    HERE.mkdir(parents=True, exist_ok=True)
    false_path = HERE / '開始前False.json'
    assert not false_path.exists()
    false_path.write_text(json.dumps(dict(全合格=False, 状態='説明算術と表示確認の開始前',
        原入力=0, 原結果=0, 金融=0, API=0), ensure_ascii=False, indent=2), encoding='utf-8')
    source_before = {name: sha((WORK / name).read_bytes()) for name in
                     ('plan.py', 'run.py', 'engine.py', 'artificial_engine.py', 'artificial_run.py')}
    old = (AUDIT / '公開HTMLの同bytes私有コピー.html').read_bytes()
    assert sha(old) == '3c5680650944928c0780a0c773f52229fe49b869e74fe0039f4120332ceec16e'
    archive = WORK / 'public_archive/表示数量を観測した後の方向応答_初版.html'
    archive.parent.mkdir(exist_ok=True)
    if archive.exists():
        assert archive.read_bytes() == old
    else:
        archive.write_bytes(old)
    current = HTML.read_bytes()
    (HERE / '仕上げ対象HTMLの同bytes私有コピー.html').write_bytes(current)
    assert cells(current.decode('utf-8')) == cells(old.decode('utf-8'))

    # ----------------------------------------
    extra_path = AUDIT / '正の公表差更新回数の一回と複数の補足算術.json'
    extra = read_json(extra_path)
    md = PUBLIC / '結論と未検証の売買.md'
    previous = md.read_text(encoding='utf-8')
    (HERE / '結論と未検証の売買_補足前.md').write_text(previous, encoding='utf-8')
    paragraphs = []
    for symbol, label in (('TOPIX', 'TOPIX'), ('NK225', '日経')):
        one = extra['集計'][symbol]['正増1更新']
        many = extra['集計'][symbol]['正増複数更新']
        for group in (one, many):
            assert group['resolved'] == group['plus'] + group['minus']
            assert abs(group['rate'] - group['plus'] / group['resolved']) < 1e-14
        paragraphs.append(f"{label}は{one['plus']:,}／{one['resolved']:,}＝{one['rate']*100:.2f}% 対 "
                          f"{many['plus']:,}／{many['resolved']:,}＝{many['rate']*100:.2f}%")
    addition = ('\n## 数量だけの効果としないための補足\n\n'
        '数量到達までの正の公表出来高差が1更新の例と、複数更新の例でも率が違う。' +
        '、'.join(paragraphs) + 'だった。更新数は約定回数や方向別枚数ではない。'
        '初期数量、待ち時間、時間帯、方向なども異なり得るため、数量維持の因果効果や反転の原因とは断定しない。'
        'この事後分類を新しい売買閾値として採用した成績も未測定。\n\n'
        '[更新回数の補足算術](../../work/quantity_response_corrected_20261015/audit_aggregation/正の公表差更新回数の一回と複数の補足算術.json)。\n')
    assert '## 数量だけの効果としないための補足' not in previous
    md.write_text(previous.rstrip() + '\n' + addition, encoding='utf-8')
    paths = [HTML, md, PUBLIC / 'README.md']
    link_count = sum(links(path) for path in paths)
    text = current.decode('utf-8')
    assert '支持されませんでした' in text and '最初の活動代理だけでも' in text
    assert '停止時1＋修正版66' in text and '観測0' in text
    assert '売買成績ではありません' in text and '利益・費用回収・真の補充は未測定' in text
    assert len(cells(text)) == 4

    # ----------------------------------------
    spec = importlib.util.spec_from_file_location('数量表示の隔離描画', ROOT / 'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = PUBLIC
    renderer.VISUAL = HERE / 'screens'
    expected = cells(text)
    renderer.PROBE = '''<script>
/**
 * 機能: 表の全セル・暗色・本文幅と未定義値を隔離Chromeで検査する。
 * @param {なし} なし。
 * @returns {object} 検査件数と表示品質。
 */
function verifyQuantityDisplay(){
 const expected=__EXPECTED__;
 const tables=Array.from(document.querySelectorAll('table')).map(t=>Array.from(t.rows).map(r=>Array.from(r.cells).map(c=>c.innerText.replace(/\\s+/g,' ').trim())));
 if(JSON.stringify(tables)!==JSON.stringify(expected))throw Error('表セル不一致');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 const body=getComputedStyle(document.body).backgroundColor;
 if(body!=='rgb(13, 20, 33)')throw Error('暗色背景');
 if(/NaN|Infinity|undefined|__EXPECTED__/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,表数:tables.length,表セル数:tables.flat(2).length,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:body};
}
try{document.body.dataset.check=JSON.stringify(verifyQuantityDisplay());}
catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}
</script>'''.replace('__EXPECTED__', json.dumps(expected, ensure_ascii=False))
    clone = text.replace('<html lang="ja">', '<html lang="ja"><head>', 1)
    clone = clone.replace('</style><main>', '</style></head><body><main>', 1).replace('</main></html>', '</main></body></html>', 1)
    images = [renderer.render(clone, 'PC_1450', 1450, 1100),
              renderer.render(clone, 'モバイル_520', 520, 1000),
              renderer.render(clone, '詳細_1450', 1450, 1100,
                '<script>document.querySelector("details").open=true;document.querySelector("details").scrollIntoView();</script>')]
    assert source_before == {name: sha((WORK / name).read_bytes()) for name in source_before}
    proof = dict(全合格=True, 初版HTML_SHA256=sha(old), 公開HTML_SHA256=sha(current),
        公開文書={str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in paths},
        測定source不変更=source_before, 全表セル不変更=True, 表セル数=sum(len(r) for t in expected for r in t),
        ローカルリンク数=link_count, 画像=images, root画像目視=False,
        補足算術_SHA256=sha(extra_path.read_bytes()), 原入力追加読=0, 原結果追加読=0,
        履歴=dict(初版原入力読=1, 初版観測=0, 修正版原入力読=66, 修正版口座=66, 独立標本増加ではない=True),
        金融=0, API=0, 範囲='既保存小算術による説明・全表不変・ローカル参照・隔離描画のみ。売買/因果/真補充は未検証。')
    PROOF.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全合格=True, 証跡=str(PROOF), SHA256=sha(PROOF.read_bytes()),
                         HTML_SHA256=sha(current), 画像=[row['画像'] for row in images]), ensure_ascii=False))


if __name__ == '__main__':
    main()
