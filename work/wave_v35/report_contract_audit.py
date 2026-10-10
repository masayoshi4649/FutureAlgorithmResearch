"""報告の全金額・返済枚数・表示操作を元台帳から独立照合する。"""

from hashlib import sha256
import gzip
import json
from pathlib import Path
import subprocess

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / 'アルゴリズム調査/00030_板と両市場による条件付き追跡短縮'
TITLE = '板と両市場による条件付き追跡短縮'


def read(path: Path) -> object:
    """機能: 圧縮又は通常のJSONを読む。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def check_tables(section: object, rows: list[dict], identifier: str, later: list[str]) -> int:
    """機能: 17区間×2銘柄の表示金額・枚数を別に足し直す。

    引数: section (BeautifulSoup要素)、rows (list[dict])、identifier (str)、later (list[str])。
    返り値: 照合した行数 (int)。
    """
    fields = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
    tables = section.select('table')
    assert len(tables) == 2
    count = 0
    for symbol, table in zip(('TOPIX', 'NK225'), tables, strict=True):
        assert table['data-id'] == identifier and table['data-symbol'] == symbol
        own = sorted([r for r in rows if r['symbol'] == symbol], key=lambda r: r['session'])
        groups = [own, [r for r in own if r['session'] in later], [r for r in own if r['session'] < '2026-09-28'],
            [r for r in own if r['session'] >= '2026-09-28']]
        expected = [{f: sum(r[f] for r in group) for f in fields} for group in groups] + own
        printed = table.select('tbody tr')
        assert len(printed) == len(expected) == 17
        for line, row in zip(printed, expected, strict=True):
            values = [float(cell.get_text(strip=True).replace(',', '').replace('+', '')) for cell in line.select('td')[1:]]
            targets = [row[f] * (-1 if f == 'gross_loss_yen' else 1) for f in fields]
            targets.append(row['profit_units'] - row['loss_units'])
            assert values == targets, (identifier, symbol)
            count += 1
    return count


def main() -> None:
    """機能: 固定840・時系列運用・主比較・全39フィルタ操作・リンクを照合する。

    引数: なし。返り値: なし (None)。売買再生はしない。
    """
    path = OUT / '全条件損益.html'
    source = path.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    fixed = read(HERE / '探索条件の固定.json')
    verdict = read(HERE / '独立判定.json')
    sections = soup.select('details.method')
    assert len(sections) == 840 and {s['id'] for s in sections} == {r['id'] for r in fixed['conditions']}
    count = 0
    for section in sections:
        rows = read(HERE / 'sessions' / (section['id'] + '.json.gz'))
        count += check_tables(section, rows, section['id'], fixed['共通評価7セッション'])
    policy = verdict['H019運用policy']
    operated = policy['セッション']
    chosen = verdict['選択']['selected_exit_mode_id']
    expected_operated = []
    for part, mode in ((fixed['選択用6セッション'], 'A0'), (fixed['共通評価7セッション'], chosen)):
        expected_operated += [r for r in read(HERE / 'sessions' / f'H019__{mode}__V000.json.gz') if r['session'] in part]
    assert sorted(operated, key=lambda r: (r['session'], r['symbol'])) == sorted(expected_operated, key=lambda r: (r['session'], r['symbol']))
    policy_count = check_tables(soup.select_one('#policy'), operated, 'POLICY', fixed['共通評価7セッション'])
    main_path = OUT / (TITLE + '.html')
    summary = BeautifulSoup(main_path.read_text(encoding='utf-8'), 'html.parser')
    for period in ('all_symbols', 'symbols'):
        targets = []
        for symbol in ('TOPIX', 'NK225'):
            for mode, label in (('A0', '固定幅 A0'), ('MIN', '常時短縮 MIN'), ('POLICY', '自動選択 ' + chosen)):
                item = policy['全13と後7'] if mode == 'POLICY' else read(HERE / 'summaries' / f'H019__{mode}__V000.json')
                r = item[period][symbol]
                targets.append([symbol, label, f"{r['gross_profit_yen']:+,.0f}", f"{-r['gross_loss_yen']:+,.0f}",
                    f"{r['net_yen']:+,.0f}", f"{r['drawdown_yen']:,.0f}",
                    '—' if r['money_ratio'] is None else f"{r['money_ratio']:,.2f}",
                    '—' if r['average_unit_payoff'] is None else f"{r['average_unit_payoff']:,.2f}",
                    f"{r['profit_units']}/{r['loss_units']}/{r['zero_units']}"])
        printed = [[c.get_text(strip=True) for c in line.select('td')] for line in summary.select('#main-' + period + ' tbody tr')]
        assert printed == targets
    clock_targets = []
    for symbol in ('TOPIX', 'NK225'):
        for variant, scale in (('C080', '0.8倍'), ('C120', '1.2倍')):
            baseline = read(HERE / 'summaries' / f'H019__A0__{variant}.json')['symbols'][symbol]['net_yen']
            selected = read(HERE / 'summaries' / f'H019__{chosen}__{variant}.json')['symbols'][symbol]['net_yen']
            clock_targets.append([symbol, scale, f'{baseline:+,.0f}', f'{selected:+,.0f}', f'{selected-baseline:+,.0f}'])
    assert [[c.get_text(strip=True) for c in line.select('td')] for line in summary.select('#clock-comparison tbody tr')] == clock_targets
    input_audit = read(HERE / 'input_causality_before_pnl.json')
    findings = read(HERE / '同じ新規の退出差.json')
    activity_targets = []
    for row in findings['機序別作動量']:
        mode = row['方式']
        nonzero = sum(r['非中立行数'] for r in input_audit['悪化']['rows'] if r['id'] == mode)
        assert nonzero == row['両銘柄全原本の非中立行数']
        counts = []
        for symbol in ('TOPIX', 'NK225'):
            result = read(HERE / 'summaries' / f'H019__{mode}__V000.json')
            counts.append(result['all_symbols'][symbol]['control']['changed_repayments'])
        activity_targets.append([mode, row['名称'], str(nonzero), *map(str, counts)])
    assert [[c.get_text(strip=True) for c in line.select('td')] for line in summary.select('#mechanism-activity tbody tr')] == activity_targets
    for document in (soup, summary):
        for link in document.select('a[href]'):
            destination = link['href']
            if not destination.startswith(('http:', 'https:', '#')):
                assert (OUT / destination).exists(), destination
    # ----------------------------------------
    # 利用者のブラウザと別領域で全表示操作を行う。
    probe = '''/**
 * 全表示操作を検査する。
 * 引数: なし。返り値: なし。
 */
(()=>{try{const keys=['signal','role'],opts=keys.map(k=>Array.from(document.getElementById(k+'-filter').options).map(o=>o.value));let n=0;const all=Array.from(document.querySelectorAll('.method'));for(const signal of opts[0])for(const role of opts[1]){document.getElementById('signal-filter').value=signal;document.getElementById('role-filter').value=role;document.getElementById('signal-filter').dispatchEvent(new Event('change'));const expected=all.filter(e=>(!signal||e.dataset.signal===signal)&&(!role||e.dataset.role===role)).length;if(document.querySelectorAll('.method:not([hidden])').length!==expected)throw Error('件数不一致');if(document.querySelector('#policy').hidden)throw Error('運用成績が隠れた');n++}document.body.dataset.probe=JSON.stringify({成功:true,操作数:n})}catch(e){document.body.dataset.probe=JSON.stringify({成功:false,エラー:String(e)})}})();'''
    copy = HERE / '表示操作の検査.html'
    copy.write_text(source.replace('</body>', '<script>' + probe + '</script></body>'), encoding='utf-8')
    command = ['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new', '--disable-gpu',
        '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-sync',
        '--disable-component-update', '--disable-features=MediaRouter,OptimizationHints',
        '--user-data-dir=' + str(HERE / 'browser_report_contract'), '--virtual-time-budget=3000', '--dump-dom', copy.as_uri()]
    result = subprocess.run(command, capture_output=True, timeout=55, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0
    dom = BeautifulSoup(result.stdout.decode('utf-8', errors='replace'), 'html.parser')
    tested = json.loads(dom.body['data-probe'])
    assert tested['成功'] and tested['操作数'] == 39
    output = {'全方式数': 840, '全損益行': count, '運用損益行': policy_count, '主比較12行一致': True,
        '全金額と枚数一致': True, '入口時計比較4行一致': True, '機序別作動12行一致': True,
        '表示操作': tested, '全リンク有効': True,
        'HTML_SHA256': {p.name: sha256(p.read_bytes()).hexdigest() for p in (path, main_path)}}
    (HERE / 'report_contract_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
