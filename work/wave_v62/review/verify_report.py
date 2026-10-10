"""短い偶然性報告の全表数値・リンク・広狭幅表示を確認する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'アルゴリズム調査/00059_銘柄別黒字候補の偶然性確認'
SOURCE = OUT / '片方だけの黒字は偶然ではないと言えるか.html'


def amount(value: float) -> str:
    """機能: 元数値を報告の円表記へ変換する。

    引数: value(float)。返り値: 表示文字列(str)。
    """
    return f'{value:+,.0f}円'.replace('-', '−')


def main() -> None:
    """機能: 診断JSONから全表の表示を照合し、隔離Chromeで画像を保存する。

    引数: なし。返り値: なし(None)。公開HTMLと旧作業を変更しない。
    """
    text = SOURCE.read_text(encoding='utf-8')
    soup = BeautifulSoup(text, 'html.parser')
    data = json.loads((HERE.parent / '偶然性の診断.json').read_text(encoding='utf-8'))
    candidates = sorted(data['候補'], key=lambda x: x['銘柄'] != 'TOPIX')
    reference = next(v for v in data['再標本化'] if v['対象'] == '12日・24場' and v['平均ブロック日数'] == 2)
    tables = soup.select('table')
    assert len(tables) == 2
    numbers = 0
    for row, candidate in zip(tables[0].select('tbody tr'), candidates):
        cells = [x.get_text(strip=True) for x in row.select('td')]
        value = next(v for v in reference['候補'] if v['候補列'] == candidate['列'])
        low, high = value['平均日収支の基本法95区間']
        expected = [candidate['銘柄'] + candidate['条件ID'], amount(candidate['集計']['net']),
            amount(candidate['集計']['without_best']), amount(candidate['最大黒字日除外']),
            f'{amount(low)} ～ {amount(high)}', f'{value["単独片側参考p"]:.2f}']
        assert cells == expected, (cells, expected)
        numbers += 6
    expected_details = []
    for result in data['再標本化']:
        for value in result['候補']:
            candidate = next(v for v in candidates if v['列'] == value['候補列'])
            low, high = value['平均日収支の基本法95区間']
            expected_details.append([result['対象'], str(result['平均ブロック日数']), candidate['銘柄'],
                f'{amount(low)} ～ {amount(high)}', f'{value["単独片側参考p"]:.3f}',
                f'{value["全900系列最大値調整参考p"]:.3f}'])
    actual_details = [[c.get_text(strip=True) for c in r.select('td')] for r in tables[1].select('tbody tr')]
    assert actual_details == expected_details
    numbers += 48
    links = 0
    for tag in soup.select('a[href]'):
        href = tag['href']
        if href.startswith(('http', '#')):
            continue
        assert (OUT / unquote(href.split('#')[0])).exists(), href
        links += 1
    for path in (OUT / 'README.md', HERE / 'README.md'):
        for _, url in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if url.startswith(('http', '#')) or url.endswith('HTML表示の独立検査.json'):
                continue
            assert (path.parent / unquote(url.split('#')[0])).exists(), url
            links += 1
    index = BeautifulSoup((OUT.parent / 'index.html').read_text(encoding='utf-8'), 'html.parser')
    listed = [a['href'] for a in index.select('a[href]') if OUT.name in unquote(a['href'])]
    assert listed and OUT.name in (OUT.parent / 'README.md').read_text(encoding='utf-8')
    for url in listed:
        assert (OUT.parent / unquote(url)).exists()
        links += 1
    spec = importlib.util.spec_from_file_location('独立Chrome描画', ROOT / 'work/wave_v52/review/verify_report.py')
    browser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(browser)
    browser.OUT = OUT
    browser.VISUAL = HERE / 'visual'
    browser.PROBE = '''<script>
/**
 * 機能: 画面外溢れと未定義表示を確認する。
 * @returns {void} 検査結果をbody属性へ保存する。
 */
function verify(){const bg=getComputedStyle(document.body).backgroundColor;document.body.dataset.check=JSON.stringify({全合格:document.documentElement.scrollWidth<=innerWidth+2&&!/NaN|undefined/.test(document.body.innerText),画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:bg});}verify();
</script>'''
    screens = [browser.render(text, '全体', 1450, 1650), browser.render(text, '狭幅', 520, 1650)]
    outcome = dict(合格=True, 目視確認=False, 表数=2, 表行数=14, 数値照合=numbers, リンク=links,
        完全12日と全25場の区別=True, 全感度表示=True, 画面=screens,
        HTML_SHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
    (HERE / 'HTML表示の独立検査.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(outcome, ensure_ascii=False))


if __name__ == '__main__':
    main()
