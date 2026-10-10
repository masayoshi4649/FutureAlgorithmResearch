"""M3比較HTMLの１枚基準値・明細・除外診断を元集計と独立に照合する。"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shutil
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

WORK = Path(__file__).resolve().parent
OUT = WORK.parents[1] / 'アルゴリズム調査' / '00014_M3逆A00の変数と安定性'
PAGE = OUT / 'M3逆A00の変数と安定性.html'
SYMBOLS = ['TOPIX', 'NK225']


def read(name: str):
    """作業内のJSONを読む。

    引数: name (str) はファイル名。返り値: JSON値 (dict | list)。
    """
    return json.loads((WORK / name).read_text(encoding='utf-8'))


def bases(node) -> list[float]:
    """金額と枚数のHTML基準値を表示順で取り出す。

    引数: node (bs4.Tag) は照合範囲。返り値: 固定１枚時の値 (list[float])。
    """
    return [float(item['data-base']) for item in node.select('[data-base]')]


def compare(actual: list[float], expected: list[float]) -> int:
    """表示と原集計の数値列を照合する。

    引数: actual/expected (list[float])。返り値: 照合件数 (int)。
    """
    assert len(actual) == len(expected), (actual, expected)
    for left, right in zip(actual, expected):
        assert abs(left - right) < .000001, (left, right)
    return len(expected)


def pnl_row(row: dict) -> list[float]:
    """元集計から損益表に対応する６値を返す。

    引数: row (dict) は元集計。返り値: 金額・累計枚数 (list[float])。
    """
    return [row['gross_profit_yen'], row['profit_units'], -row['gross_loss_yen'], row['loss_units'], row['net_yen'], row['unit_balance']]


def main() -> None:
    """表示候補・思想・近傍・追加診断の値とリンクを確認する。

    引数: なし。返り値: なし。検査結果を保存する。
    """
    records = {row['id']: row for row in read('週比較.json')}
    selection = read('選択結果.json')
    cells = defaultdict(list)
    for row in read('セッション比較.json'):
        cells[(row['method_id'], row['symbol'])].append(row)
    for rows in cells.values():
        rows.sort(key=lambda row: row['session'])
    soup = BeautifulSoup(PAGE.read_text(encoding='utf-8'), 'html.parser')
    assert soup.html['lang'] == 'ja' and soup.select_one('meta[charset]')['charset'] == 'utf-8'
    assert len(soup.select('.chapter')) == len(selection['displayed'])
    assert len(soup.select('.variant')) == len(selection['displayed']) * 2
    checks = table_rows = 0
    for identifier in selection['displayed']:
        chapter = soup.find(id=identifier)
        assert chapter is not None
        for symbol in SYMBOLS:
            node = chapter.select_one(f'[data-variant-symbol="{symbol}"]')
            week = records[identifier]['weeks'][symbol]
            tables = node.select('table.pnl')
            assert len(tables) == 2
            actual_rows = tables[0].select('tbody tr') + tables[1].select('tbody tr')
            expected_rows = [week] + cells[(identifier, symbol)]
            assert len(actual_rows) == len(expected_rows) == 11
            for actual, expected in zip(actual_rows, expected_rows):
                checks += compare(bases(actual), pnl_row(expected))
                assert '累計返済' in actual.get_text() and '累計枚数差' in actual.get_text()
                table_rows += 1
            checks += compare(bases(node.select_one('.result-line')), [week['net_yen']])
            checks += compare(bases(node.select_one('.stats')), [week['drawdown_yen']])
            assert f'{week["money_ratio"]:.2f}倍' in node.select_one('.stats').get_text()
            assert f'{week["unit_payoff"]:.2f}倍' in node.select_one('.stats').get_text()
            checks += compare(bases(node.select_one('table.exclusions')), [week['drop_best_session_net'], week['best_trade_yen'], week['drop_best_trade_net']])
            checks += compare(bases(node.select_one('.contribution')), [week[key] for key in ['first_half_net', 'second_half_net', 'day_net', 'night_net', 'drop_top3_trades_net', 'worst_trade_yen']])
    main, base = records[selection['primary']], records[selection['baseline']]
    for symbol in SYMBOLS:
        checks += compare(bases(soup.select_one(f'[data-overview="{symbol}"]')), [base['weeks'][symbol]['net_yen'], main['weeks'][symbol]['net_yen'], main['weeks'][symbol]['net_yen'] - base['weeks'][symbol]['net_yen']])

    # ----------------------------------------
    neighbor_rows = soup.select('[data-neighbor]')
    assert [row['data-neighbor'] for row in neighbor_rows] == main['neighbor']['ids']
    for row in neighbor_rows:
        record = records[row['data-neighbor']]
        checks += compare(bases(row), [record['weeks'][symbol]['drop_best_session_net'] for symbol in SYMBOLS])
        columns = row.select('td')
        for index, symbol in enumerate(SYMBOLS):
            assert columns[1 + index * 2].get_text() == f'{record["weeks"][symbol]["money_ratio"]:.2f}倍'
            assert f'除外後PF {record["weeks"][symbol]["drop_best_session_pf"]:.2f}' in columns[2 + index * 2].get_text()
            checks += 2
    diagnostics = {row['id']: row for row in read('追加近傍診断.json')}
    diagnostic_summary = read('追加近傍診断の要約.json')
    holding_rows = soup.select('[data-holding]')
    assert [row['data-holding'] for row in holding_rows] == diagnostic_summary['holding_only']
    for row in holding_rows:
        record = diagnostics[row['data-holding']]
        assert f'{record["config"]["timeout_min"]:g}分' in row.select('td')[0].get_text()
        checks += compare(bases(row), [record['weeks'][symbol][key] for symbol in SYMBOLS for key in ['net_yen', 'drop_best_session_net']])
    for row in soup.select('[data-control]'):
        record = records[row['data-control']]
        assert record['config']['entry_atr'] == .25 and record['config']['stop_atr'] == 1 and record['config']['main_trail'] == 2
        checks += compare(bases(row), [value for symbol in SYMBOLS for value in [record['weeks'][symbol]['net_yen'], record['weeks'][symbol]['net_yen'] - base['weeks'][symbol]['net_yen']]])

    # ----------------------------------------
    ids = {item['id'] for item in soup.select('[id]')}
    links = 0
    for link in soup.select('a[href]'):
        href = link['href']
        if href.startswith('#'):
            assert href[1:] in ids
        elif not urlparse(href).scheme:
            assert (PAGE.parent / unquote(href.split('#')[0])).exists(), href
        links += 1
    text = soup.get_text()
    assert '最大利益の１セッションを除外' in text and '最大利益の１取引を除外' in text
    assert '利益上位３取引' in text and '売買経路は再計算しません' in text
    assert '300分' in text and '420分' in text
    assert '360分は保有上限' in text
    assert '両銘柄の上向きを確認したら売りを待ち' in text
    assert '904条件＋追加135条件' in text
    assert len(soup.select('.family')) == len({row['family'] for row in records.values()})
    for symbol, cap in [('TOPIX', 10), ('NK225', 20)]:
        select = soup.select_one(f'[data-scale-for="{symbol}"]')
        assert [int(item['value']) for item in select.select('option')] == list(range(1, cap + 1))
    result = {'合格': True, '表示条件': len(selection['displayed']), '思想別章': len(soup.select('.family')),
              '週区間集計行': table_rows, '元集計との数値照合': checks, 'リンク確認': links,
              '近傍行': len(neighbor_rows), '追加保有時間診断行': len(holding_rows),
              '確認': '固定１枚の原集計とHTML基準値、セッション/取引除外の区別、対照設定・近傍・追加診断、全リンク'}
    (WORK / '表示静的検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for name in ['check_report.py', '表示静的検査.json']:
        shutil.copy2(WORK / name, OUT / '資料' / name)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
