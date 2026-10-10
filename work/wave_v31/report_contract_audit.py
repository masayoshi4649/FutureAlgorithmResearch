"""全420条件の表示金額・枚数と、選択UIを別経路で検算する。"""

from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査/00026_方向情報の鮮度と保有継続'


def number(text: str) -> float:
    """機能: 表示済みの円額・枚数を数値へ変換する。

    引数: text (str)。返り値: 数値 (float)。
    """
    return float(text.replace(',', '').replace('+', ''))


def main() -> None:
    """機能: 全13区間・2週の840表と表示フィルタを独立に確認する。

    引数: なし。返り値: なし (None)。売買再生・採否変更は行わない。
    """
    path = OUT / '方向情報の鮮度と保有継続.html'
    source = path.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    sections = soup.select('details.method')
    assert len(sections) == 420 and len({s['id'] for s in sections}) == 420
    cache, count, wave_count = {}, 0, 0
    waves = json.loads((HERE / 'episode_audit.json').read_text(encoding='utf-8'))
    wave_by_id = {}
    for row in waves['結果']:
        wave_by_id.setdefault(row['method'], []).append(row)
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
    for section in sections:
        identifier = section['id']
        signal = identifier.split('__')[0]
        if signal not in cache:
            cache[signal] = {v['id']: v['rows'] for v in json.loads(gzip.decompress((HERE / 'sessions' / (signal + '.json.gz')).read_bytes()))}
        rows = cache[signal][identifier]
        tables = section.find_all('table')
        assert len(tables) >= 2
        for symbol, table in zip(('TOPIX', 'NK225'), tables[:2]):
            part = sorted([r for r in rows if r['symbol'] == symbol], key=lambda r: r['session'])
            groups = [part, [r for r in part if r['session'][:10] < '2026-09-28'], [r for r in part if r['session'][:10] >= '2026-09-28']]
            expected = [{k: sum(r[k] for r in group) for k in fields} for group in groups] + part
            printed = table.select('tbody tr')
            assert len(expected) == len(printed) == 16
            for line, row in zip(printed, expected):
                values = [number(c.get_text(strip=True)) for c in line.find_all('td')[1:]]
                target = [row[k] * (-1 if k == 'gross_loss_yen' else 1) for k in fields]
                target.append(row['profit_units'] - row['loss_units'])
                assert values == target, (identifier, symbol)
                count += 1
        # ----------------------------------------
        # 指定波は決済損益と混ぜず、境界時価差と保有分の表示を検算する。
        wave_table = section.select_one('details.wave table')
        assert wave_table is not None
        expected = sorted(wave_by_id[identifier], key=lambda r: (r['wave'], r['symbol']))
        printed = wave_table.select('tbody tr')
        assert len(expected) == len(printed) == 8
        for line, row in zip(printed, expected):
            cells = [c.get_text(strip=True) for c in line.find_all('td')]
            assert cells[:2] == [row['波名'], row['symbol']]
            assert cells[2:4] == [f"{row['正方向ネット保有分']:.1f}", f"{row['逆方向ネット保有分']:.1f}"]
            assert cells[4] == ('達成' if row['正方向ネット20分目安達成'] else '未達')
            assert number(cells[5]) == row['時価損益差円']
            wave_count += 1
    # ----------------------------------------
    # 実際の生成HTMLの複製だけへ操作確認を注入する。利用者のブラウザや元HTMLは変更しない。
    probe = '''/** 表示選択の検査。引数なし、返り値なし。 */
(()=>{try{const keys=['signal','manager','variant'],options=keys.map(k=>Array.from(document.getElementById(k+'-filter').options).map(o=>o.value));let n=0;for(const s of options[0])for(const m of options[1])for(const v of options[2]){const values=[s,m,v];keys.forEach((k,i)=>document.getElementById(k+'-filter').value=values[i]);document.getElementById('signal-filter').dispatchEvent(new Event('change'));const expected=(s?1:12)*(m?1:7)*(v?1:5),actual=document.querySelectorAll('.method:not([hidden])').length;if(actual!==expected)throw Error('選択件数の不一致');n++;}document.body.dataset.probe=JSON.stringify({成功:true,操作数:n});}catch(error){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(error)});}})();'''
    copy = HERE / '表示操作の検査.html'
    copy.write_text(source.replace('</body>', '<script>' + probe + '</script></body>'), encoding='utf-8')
    command = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new', '--disable-gpu',
               '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-sync',
               '--disable-component-update', '--disable-features=MediaRouter,OptimizationHints',
               '--user-data-dir=' + str(HERE / 'browser_report_contract'), '--virtual-time-budget=2000',
               '--dump-dom', copy.as_uri()]
    result = subprocess.run(command, capture_output=True, timeout=50, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0
    dom = BeautifulSoup(result.stdout.decode('utf-8', errors='replace'), 'html.parser')
    tested = json.loads(dom.body['data-probe'])
    assert tested['成功'] and tested['操作数'] == 13 * 8 * 6
    broken = []
    for link in soup.select('a[href]'):
        href = link['href']
        if not href.startswith(('http:', 'https:', '#')) and not (path.parent / href).exists():
            broken.append(href)
    assert not broken, broken
    report = {'手法数': 420, '全セッションと週の表数': 840, '表の行数': count, '全指定波行数': wave_count,
              '金額と枚数の全表示一致': True, '波の全表示一致': True, '全リンク有効': True, '表示操作': tested,
              'HTML_SHA256': sha256(path.read_bytes()).hexdigest()}
    (HERE / 'report_contract_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
