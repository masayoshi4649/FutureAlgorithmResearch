"""同時保有上限・枚数配分・累計返済を示すHTMLの全表示値とリンクを照合する。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
SEARCH = WORK / 'allocation'
OUT = ROOT / 'アルゴリズム調査' / '00013_共通上位４手法のスケールダウン'
PAGE = OUT / '共通上位４手法のスケールダウン.html'


def number(text: str) -> int:
    """表示の円額・枚数を整数へ直して照合する。

    引数: text (str) はカンマ・単位付き表示。返り値: 整数 (int)。
    """
    cleaned = re.sub(r'累計返済 |累計枚数差 |候補 |参考 |最大 |,|円|枚|約', '', text)
    return int(cleaned)


def check_row(row, expected: dict) -> int:
    """利益・損失・収支の金額と累計返済枚数６値を照合する。

    引数: row (bs4.Tag) はHTML行、expected (dict) は原集計。返り値: 照合数 (int)。
    """
    actual = [[number(value) for value in cell.stripped_strings] for cell in row.select('td')[1:]]
    values = [[expected['gross_profit_yen'], expected['profit_units']],
              [-expected['gross_loss_yen'], expected['loss_units']],
              [expected['net_yen'], expected['unit_balance']]]
    assert actual == values, (actual, values)
    assert '累計返済' in row.get_text() and '累計枚数差' in row.get_text()
    return 6


def check_allocation(section, expected: dict) -> tuple[int, int]:
    """１配分の週・10区間・指標・同時保有を照合する。

    引数: section (bs4.Tag) は配分表示、expected (dict) は確定値。
    返り値: 数値照合数と集計行数 (tuple[int, int])。
    """
    week, config = expected['week'], expected['config']
    assert number(section.select_one('.result-line strong').get_text()) == week['net_yen']
    rule = section.select_one('.allocation-rule').get_text()
    assert f'初回{config["initial_qty"]}枚' in rule
    assert (f'追加{config["add_qty"]}枚' if config['add_qty'] else '追加なし') in rule
    position = section.select_one('.position-limit').get_text()
    assert f'買い {week["max_long"]}枚' in position and f'売り {week["max_short"]}枚' in position
    assert week['max_long'] <= config['position_cap'] and week['max_short'] <= config['position_cap']
    tables = section.select('table')
    assert len(tables) == 2
    weekly = tables[0].select('tbody tr')
    sessions = tables[1].select('tbody tr')
    assert len(weekly) == 1 and len(sessions) == 10
    checks = check_row(weekly[0], week)
    for row, record in zip(sessions, expected['sessions']):
        checks += check_row(row, record)
    stats = section.select('.stats b')
    assert [tag.get_text() for tag in stats[:2]] == [f'{week[key]:.2f}倍' for key in ['money_ratio', 'unit_payoff']]
    assert number(stats[2].get_text()) == week['drawdown_yen']
    return checks + 8, 11


def main() -> None:
    """主表示・週収支最大・感度注記・全リンクを静的に確認する。

    引数: なし。返り値: なし。確認結果をJSONへ保存する。
    """
    data = json.loads((SEARCH / 'allocation_report_data.json').read_text(encoding='utf-8'))
    source = PAGE.read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    assert soup.html['lang'] == 'ja' and soup.select_one('meta[charset]')['charset'] == 'utf-8'
    assert len(soup.select('.chapter')) == 4 and len(soup.select('.variant')) == 8
    assert not soup.select('script, iframe, img')
    assert 'color-scheme: dark' in source and '@media (max-width: 640px)' in source
    assert not re.search(r'__[A-Z]+__', source)
    checks = rows = allocations = 0
    for method in data['methods']:
        chapter = soup.find('article', id=method['id'])
        assert method['name'] in chapter.h2.get_text()
        assert method['entry'] in chapter.get_text() and method['exit'] in chapter.get_text()
        for symbol, variant in method['variants'].items():
            section = chapter.select_one(f'[data-symbol="{symbol}"]')
            cap = 10 if symbol == 'TOPIX' else 20
            assert f'同時保有上限：買い {cap}枚 ／ 売り {cap}枚' in section.get_text()
            same = all(variant['selected']['config'][key] == variant['max_net']['config'][key] for key in ['initial_qty', 'add_qty', 'position_cap'])
            for key in ['selected', 'max_net']:
                choice = section.select_one(f'[data-choice="{key}"]')
                if key == 'max_net' and same:
                    assert section.select_one('[data-same-allocation="true"]')
                    continue
                assert choice is not None
                count, row_count = check_allocation(choice, variant[key])
                checks += count
                rows += row_count
                allocations += 1

    # ----------------------------------------
    summary_rows = soup.select('#weekly-overview tbody tr')
    assert len(summary_rows) == 4
    for method, row in zip(data['methods'], summary_rows):
        assert method['id'] in row.get_text()
        for index, symbol in enumerate(['TOPIX', 'NK225'], 1):
            for key in ['selected', 'max_net']:
                displayed = row.select('td')[index].select_one(f'[data-summary="{key}"]').get_text()
                assert number(displayed) == method['variants'][symbol][key]['week']['net_yen']
                checks += 1
    neighbors = json.loads((SEARCH / '全配分の週合計.json').read_text(encoding='utf-8'))
    sensitivity = soup.select_one('.sensitivity').get_text()
    for record in neighbors:
        if record['method_id'] == 'M3_逆_A03' and record['symbol'] == 'NK225' and record['initial_qty'] == 1 and record['add_qty'] in [15, 16, 17]:
            assert f'追加{record["add_qty"]}枚：{round(record["net_yen"]):+,}円' in sensitivity
            checks += 1
    topix_rows = soup.select('.topix-neighbors tbody tr')
    expected_topix = sorted([row for row in neighbors if row['method_id'] == 'M3_逆_A03' and row['symbol'] == 'TOPIX' and (row['initial_qty'], row['add_qty']) in {(6, 3), (7, 2), (7, 3), (8, 2)}], key=lambda row: (row['initial_qty'], row['add_qty']))
    assert len(topix_rows) == len(expected_topix) == 4
    for row, record in zip(topix_rows, expected_topix):
        assert row.select('td')[0].get_text() == f'初回{record["initial_qty"]}枚・追加{record["add_qty"]}枚'
        assert number(row.select('td')[1].get_text()) == record['net_yen']
        checks += 3
    ids = {item['id'] for item in soup.select('[id]')}
    links = 0
    for anchor in soup.select('a[href]'):
        href = anchor['href']
        if href.startswith('#'):
            assert href[1:] in ids, href
        elif not urlparse(href).scheme:
            assert (PAGE.parent / unquote(href.split('#')[0])).exists(), href
        links += 1
    assert '同時保有は１枚、累計返済は20枚' in source
    assert '１枚が最適という意味ではなく' in source
    assert '1 → 17 → 20枚' in source and '最後は残り枠の3枚' in source
    assert '7 → 10枚' in source
    assert '同じ既読１週間' in source and '１枚差に敏感' in source
    assert '実画面は未確認' in source
    result = {'合格': True, '手法章': 4, '銘柄版': 8, '表示配分数': allocations,
              '集計表示行': rows, '表示数値照合': checks, 'リンク照合': links,
              '検査': '同時保有上限・初回・追加・実績最大、週と全セッションの金額・累計返済枚数、損益比・最大下落、候補と最大収支、隣接配分感度、構造・リンク',
              'ブラウザー実画面': '既存のURLポリシー拒否を再試行せず未確認'}
    (WORK / '表示静的検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for filename in ['check_scale_report.py', '表示静的検査.json']:
        shutil.copy2(WORK / filename, OUT / '資料' / filename)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
