"""表示された全週・全セッションの数値と、手法選択の実動作を検査する。"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import re
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査/00025_相手不一致と保有撤回の分離'


def number(text: str) -> float:
    """機能: 表の金額・枚数表記を独立して数値へ戻す。

    引数: text (str)。返り値: 数値 (float)。
    """
    return float(text.replace(',', '').replace('+', ''))


def browser_probe(path: Path, javascript: str, label: str) -> dict:
    """機能: 検査用複製へ確認操作を注入し、独立ブラウザで実行する。

    引数: path (Path)、javascript/label (str)。返り値: 実行済み結果 (dict)。
    """
    original = path.read_text(encoding='utf-8')
    modified = original.replace('</body>', '<script>' + javascript + '</script></body>')
    destination = HERE / ('操作検査_' + label + '.html')
    destination.write_text(modified, encoding='utf-8')
    command = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new', '--disable-gpu',
               '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
               '--disable-component-update', '--disable-sync', '--disable-features=MediaRouter,OptimizationHints',
               '--window-size=1440,1100', '--virtual-time-budget=2000',
               '--user-data-dir=' + str(HERE / ('browser_contract_' + label)), '--dump-dom', destination.as_uri()]
    process = subprocess.run(command, capture_output=True, timeout=50, creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 0
    soup = BeautifulSoup(process.stdout.decode('utf-8', errors='replace'), 'html.parser')
    result = json.loads(soup.body['data-probe'])
    assert result['成功'], result
    return result


def main() -> None:
    """機能: 84手法の168表、週別合算、全図解とフィルタ操作を確認する。

    引数: なし。返り値: なし (None)。採否や売買規則は変更しない。
    """
    path = OUT / '相手不一致と保有撤回.html'
    soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
    methods = soup.select('details.method')
    assert len(methods) == 84 and len({m['id'] for m in methods}) == 84
    checked = []
    episode = json.loads((HERE / 'episode_audit.json').read_text(encoding='utf-8'))
    wave_checked = 0
    keys = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
    for section in methods:
        identifier = section['id']
        records = json.loads(gzip.decompress((HERE / 'sessions' / (identifier.split('__')[0] + '.json.gz')).read_bytes()))
        source = next(r['rows'] for r in records if r['id'] == identifier)
        tables = section.find_all('table')
        assert len(tables) in (2, 3)
        for symbol, table in zip(('TOPIX', 'NK225'), tables[:2]):
            rows = sorted([r for r in source if r['symbol'] == symbol], key=lambda r: r['session'])
            groups = [rows, [r for r in rows if r['session'][:10] < '2026-09-28'], [r for r in rows if r['session'][:10] >= '2026-09-28']]
            expected = [{k: sum(r[k] for r in group) for k in keys} for group in groups] + rows
            shown = table.select('tbody tr')
            assert len(shown) == len(expected) == 16
            for line, raw in zip(shown, expected):
                values = [number(c.get_text(strip=True)) for c in line.find_all('td')[1:]]
                wanted = [raw[k] * (-1 if k == 'gross_loss_yen' else 1) for k in keys]
                wanted += [raw['profit_units'] - raw['loss_units']]
                assert values == wanted, (identifier, symbol, values, wanted)
            checked.append({'手法': identifier, '銘柄': symbol, '確認行': 16})
        if len(tables) == 3:
            waves = sorted([r for r in episode['結果'] if r['method'] == identifier], key=lambda r: (r['wave'], r['symbol']))
            lines = tables[2].select('tbody tr')
            assert len(lines) == len(waves) == 8
            for line, wave in zip(lines, waves):
                cells = [cell.get_text(strip=True) for cell in line.find_all('td')]
                assert cells[:2] == [wave['波名'], wave['symbol']]
                assert [number(c) for c in cells[2:]] == [round(wave['正方向ネット保有分'], 1), round(wave['逆方向ネット保有分'], 1), wave['時価損益差円']]
                wave_checked += 1
    chart = BeautifulSoup((OUT / '５分足と売買.html').read_text(encoding='utf-8'), 'html.parser')
    data = json.loads(chart.find(id='chart-data').string)
    assert len(data['methods']) == 84 and len(data['trades']) == len(data['states']) == 2184
    for key, trades in data['trades'].items():
        mult = 1000 if key.endswith('|TOPIX') else 10
        for row in trades:
            assert abs(row[2] * row[3] * (row[5] - row[4]) * mult - row[6]) < .001
    report_probe = '''/** 検査用の表示選択。引数なし、返り値なし。 */
(()=>{try{const s=document.getElementById('signal-filter'),m=document.getElementById('manager-filter');let checks=0;for(const sid of ['',...Array.from(s.options).map(o=>o.value).filter(Boolean)]){for(const mid of ['',...Array.from(m.options).map(o=>o.value).filter(Boolean)]){s.value=sid;m.value=mid;s.dispatchEvent(new Event('change'));const expected=(sid?1:12)*(mid?1:7),actual=document.querySelectorAll('.method:not([hidden])').length;if(actual!==expected)throw Error('選択件数不一致');checks++;}}document.body.dataset.probe=JSON.stringify({成功:true,操作数:checks});}catch(error){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(error)});}})();'''
    chart_probe = '''/** 検査用の図解切替。引数なし、返り値なし。 */
(()=>{try{const data=JSON.parse(document.getElementById('chart-data').textContent),m=document.getElementById('method'),s=document.getElementById('symbol'),t=document.getElementById('session');let checks=0;for(let i=0;i<7;i++){m.value='H019__L00'+i;for(const symbol of ['TOPIX','NK225']){s.value=symbol;for(const session of ['2026-09-24_Night','2026-09-29_Day']){t.value=session;m.dispatchEvent(new Event('change'));const expected=data.trades[m.value+'|'+t.value+'|'+s.value].length;if(!document.getElementById('chart-summary').textContent.includes('決済 '+expected+'件'))throw Error('図解件数不一致');checks++;}}}document.body.dataset.probe=JSON.stringify({成功:true,操作数:checks});}catch(error){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(error)});}})();'''
    results = {'表数': len(checked), '表の行数': len(checked) * 16, '指定波表示数': wave_checked, '全図解': 2184,
               '表の数値一致': True, '図解の価格枚数から損益一致': True,
               '表示選択': browser_probe(path, report_probe, '報告'),
               '図解選択': browser_probe(OUT / '５分足と売買.html', chart_probe, '図解')}
    (HERE / 'report_contract_audit.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
