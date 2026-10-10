"""全条件の表示金額と枚数を、表示器とは別に元セッションから集計する。"""

import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査/00029_仮想建玉による再エントリー制御'


def read(path: Path) -> object:
    """機能: 保存JSONの圧縮を解いて読み込む。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def numeric(value: str) -> float:
    """機能: 日本語表の符号付き数値を比較用へ変換する。

    引数: value (str)。返り値: 数値 (float)。
    """
    return float(value.replace(',', '').replace('+', ''))


def main() -> None:
    """機能: 全6528損益行・主比較・39表示操作・リンクを照合する。

    引数: なし。返り値: なし (None)。売買再生は行わない。
    """
    path = OUT / '全条件損益.html'
    source = path.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    fixed = read(HERE / '探索条件の固定.json')
    sections = soup.select('details.method')
    assert len(sections) == 192 and {s['id'] for s in sections} == {r['id'] for r in fixed['conditions']}
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
    count = 0
    for section in sections:
        rows = read(HERE / 'sessions' / (section['id'] + '.json.gz'))
        tables = section.select('table')
        assert len(tables) == 2
        for symbol, table in zip(('TOPIX', 'NK225'), tables):
            assert table['data-id'] == section['id'] and table['data-symbol'] == symbol
            own = sorted([r for r in rows if r['symbol'] == symbol], key=lambda r: r['session'])
            groups = [own, [r for r in own if r['session'] in fixed['共通評価7セッション']],
                      [r for r in own if r['session'] < '2026-09-28'], [r for r in own if r['session'] >= '2026-09-28']]
            expected = [{field: sum(row[field] for row in group) for field in fields} for group in groups] + own
            printed = table.select('tbody tr')
            assert len(printed) == len(expected) == 17
            for line, row in zip(printed, expected):
                values = [numeric(cell.get_text(strip=True)) for cell in line.select('td')[1:]]
                targets = [row[f] * (-1 if f == 'gross_loss_yen' else 1) for f in fields]
                targets += [row['profit_units'] - row['loss_units']]
                assert values == targets, (section['id'], symbol)
                count += 1
    # ----------------------------------------
    # 主比較表は別資料を照合し、表示用丸めだけを許容する。
    main_path = OUT / '仮想建玉による再エントリー制御.html'
    summary = BeautifulSoup(main_path.read_text(encoding='utf-8'), 'html.parser')
    for period in ('all_symbols', 'symbols'):
        targets = []
        for symbol in ('TOPIX', 'NK225'):
            for mode, gate in (('A0', 'NORMAL'), ('AT', 'NORMAL'), ('AT', 'SHADOW')):
                item = read(HERE / 'summaries' / ('H019__' + mode + '__' + gate + '__V000.json'))
                r = item[period][symbol]
                name = ('固定幅' if mode == 'A0' else '更新幅') + ('＋再新規制御' if gate == 'SHADOW' else '＋通常新規')
                targets.append([symbol, name,
                    f"{r['gross_profit_yen']:+,.0f}", f"{-r['gross_loss_yen']:+,.0f}", f"{r['net_yen']:+,.0f}",
                    f"{r['drawdown_yen']:,.0f}", f"{r['money_ratio']:,.2f}", f"{r['average_unit_payoff']:,.2f}",
                    f"{r['profit_units']}/{r['loss_units']}/{r['zero_units']}"])
        printed = [[c.get_text(strip=True) for c in line.select('td')] for line in summary.select('#main-' + period + ' tbody tr')]
        assert printed == targets
    for document in (soup, summary):
        for link in document.select('a[href]'):
            destination = link['href']
            if not destination.startswith(('http:', 'https:', '#')):
                assert (OUT / destination).exists(), destination
    probe = '''/** 表示全組合せの検査。引数なし、返り値なし。 */
(()=>{try{const keys=['signal','role'],opts=keys.map(k=>Array.from(document.getElementById(k+'-filter').options).map(o=>o.value));let n=0;const all=Array.from(document.querySelectorAll('.method'));for(const signal of opts[0])for(const role of opts[1]){document.getElementById('signal-filter').value=signal;document.getElementById('role-filter').value=role;document.getElementById('signal-filter').dispatchEvent(new Event('change'));const expected=all.filter(e=>(!signal||e.dataset.signal===signal)&&(!role||e.dataset.role===role)).length;if(document.querySelectorAll('.method:not([hidden])').length!==expected)throw Error('件数不一致');n++}document.body.dataset.probe=JSON.stringify({成功:true,操作数:n})}catch(e){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(e)})}})();'''
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
    assert tested['成功'] and tested['操作数'] == 39
    output = {'全方式数': 192, '全損益表': 384, '全損益行': count, '主比較12行一致': True,
              '全金額と枚数一致': True, '表示操作': tested, '全リンク有効': True,
              'HTML_SHA256': {p.name: sha256(p.read_bytes()).hexdigest() for p in (path, main_path)}}
    (HERE / 'report_contract_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
