"""報告HTMLの全損益行と表示選択を、元の区間台帳から別途検算する。"""

from __future__ import annotations

import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査/00027_順張りと反転の機械的選択'


def read(path: Path) -> object:
    """機能: 保存資料を表示側とは別の経路で読み込む。

    引数: path (Path)。返り値: JSON内容 (object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def number(value: str) -> float:
    """機能: HTMLの数値文字列を円額・枚数へ変換する。

    引数: value (str)。返り値: 数値 (float)。
    """
    return float(value.replace(',', '').replace('+', ''))


def main() -> None:
    """機能: 全148方式・5032損益行と21表示操作を照合する。

    引数: なし。返り値: なし (None)。売買再生は行わない。
    """
    path = OUT / '順張りと反転の機械的選択.html'
    source = path.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    fixed = read(HERE / '探索条件の固定.json')
    sections = soup.select('details.method')
    assert {section['id'] for section in sections} == {r['id'] for r in fixed['conditions']}
    assert len(sections) == 148
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
    count, wave_count = 0, 0
    waves = read(HERE / 'episode_audit.json')
    wave_by_id = {}
    for row in waves['結果']:
        wave_by_id.setdefault(row['method'], []).append(row)
    for section in sections:
        rows = read(HERE / 'sessions' / (section['id'] + '.json.gz'))
        tables = section.find_all('table')
        assert len(tables) >= 2
        for symbol, table in zip(('TOPIX', 'NK225'), tables[:2]):
            own = sorted([r for r in rows if r['symbol'] == symbol], key=lambda r: r['session'])
            groups = [[r for r in own if r['session'] in fixed['共通評価7セッション']], own,
                      [r for r in own if r['session'][:10] < '2026-09-28'], [r for r in own if r['session'][:10] >= '2026-09-28']]
            expected = [{field: sum(row[field] for row in group) for field in fields} for group in groups] + own
            printed = table.select('tbody tr')
            assert len(printed) == len(expected) == 17
            for line, row in zip(printed, expected):
                values = [number(cell.get_text(strip=True)) for cell in line.find_all('td')[1:]]
                target = [row[field] * (-1 if field == 'gross_loss_yen' else 1) for field in fields]
                target.append(row['profit_units'] - row['loss_units'])
                assert values == target, (section['id'], symbol)
                count += 1
        wave_table = section.select_one('details.wave table')
        assert wave_table is not None
        expected = sorted(wave_by_id[section['id']], key=lambda r: (r['wave'], r['symbol']))
        lines = wave_table.select('tbody tr')
        assert len(lines) == len(expected) == 8
        for line, row in zip(lines, expected):
            cells = [cell.get_text(strip=True) for cell in line.find_all('td')]
            assert cells[:2] == [row['波名'], row['symbol']]
            assert cells[2:4] == [f"{row['正方向ネット保有分']:.1f}", f"{row['逆方向ネット保有分']:.1f}"]
            assert cells[4] == ('達成' if row['正方向ネット20分目安達成'] else '未達')
            assert number(cells[5]) == row['時価損益差円']
            wave_count += 1
    # ----------------------------------------
    # 独立ブラウザ内の複製へだけ操作検査を注入する。
    probe = '''/** 表示切替の全組合せを検査する。引数なし、返り値なし。 */
(()=>{try{const keys=['role','base'],options=keys.map(k=>Array.from(document.getElementById(k+'-filter').options).map(o=>o.value));let count=0;const all=Array.from(document.querySelectorAll('.method'));for(const role of options[0])for(const base of options[1]){const values=[role,base];keys.forEach((k,i)=>document.getElementById(k+'-filter').value=values[i]);document.getElementById('role-filter').dispatchEvent(new Event('change'));const expected=all.filter(e=>(!role||e.dataset.role===role)&&(!base||e.dataset.base===base)).length;if(document.querySelectorAll('.method:not([hidden])').length!==expected)throw Error('件数不一致');count++;}document.body.dataset.probe=JSON.stringify({成功:true,操作数:count});}catch(e){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(e)});}})();'''
    copy = HERE / '表示操作の検査.html'
    copy.write_text(source.replace('</body>', '<script>' + probe + '</script></body>'), encoding='utf-8')
    command = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new', '--disable-gpu',
               '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-sync',
               '--disable-component-update', '--disable-features=MediaRouter,OptimizationHints',
               '--user-data-dir=' + str(HERE / 'browser_report_contract'), '--virtual-time-budget=2000', '--dump-dom', copy.as_uri()]
    result = subprocess.run(command, capture_output=True, timeout=50, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0
    dom = BeautifulSoup(result.stdout.decode('utf-8', errors='replace'), 'html.parser')
    tested = json.loads(dom.body['data-probe'])
    assert tested['成功'] and tested['操作数'] == 21
    for link in soup.select('a[href]'):
        target = link['href']
        if not target.startswith(('http:', 'https:', '#')):
            assert (OUT / target).exists(), target
    checked = {'全方式数': 148, '全損益表': 296, '全損益行': count, '全指定波行': wave_count,
               '全波表示一致': True, '全金額と枚数一致': True,
               '表示操作': tested, '全リンク有効': True, 'HTML_SHA256': sha256(path.read_bytes()).hexdigest()}
    (HERE / 'report_contract_audit.json').write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(checked, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
