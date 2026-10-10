"""全報告金額・返済枚数と表示条件を、sessionsから独立に再集計する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
import subprocess

from bs4 import BeautifulSoup

import band_design as design


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00031_出来高通過と気配維持からの方向判定'
TITLE = '出来高通過と気配維持からの方向判定'
FIELDS = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
LABELS = {'Q034': '気配維持と出来高', 'Q007': '価格だけ', 'Q016': '価格と全出来高', 'H019': '旧中期方向'}


def read(path: Path) -> object:
    """機能: 報告生成器を使わず保存JSONを読む。

    引数: path (Path)。返り値: JSON内容 (object)。
    """
    payload = path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix == '.gz' else payload)


def digest(path: Path) -> str:
    """機能: 読取資料の内容を固定する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを有限値だけで保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def sessions_checked(rows: list[dict], identifier: str, names: list[str]) -> None:
    """機能: 元26区間の欠落・重複・非有限・銘柄混合を拒否する。

    引数: rows (list[dict])、identifier (str)、names (list[str])。返り値: なし (None)。
    """
    assert len(rows) == 26 and len(names) == len(set(names)) == 13
    assert {(row['session'], row['symbol']) for row in rows} == {
        (name, symbol) for name in names for symbol in ('TOPIX', 'NK225')}
    for row in rows:
        assert row['id'] == identifier
        for field in (*FIELDS, 'drawdown_yen', 'min_equity_yen', 'max_equity_yen'):
            assert isinstance(row[field], (int, float)) and not isinstance(row[field], bool)
            assert math.isfinite(row[field])
        assert abs(row['gross_profit_yen'] - row['gross_loss_yen'] - row['net_yen']) <= 1e-6
        assert row['gross_profit_yen'] >= 0 and row['gross_loss_yen'] >= 0 and row['drawdown_yen'] >= 0
        assert row['min_equity_yen'] <= row['max_equity_yen']
        for field in ('profit_units', 'loss_units', 'zero_units'):
            assert row[field] >= 0 and row[field] == int(row[field])


def aggregate(rows: list[dict]) -> dict:
    """機能: 同銘柄の金額・枚数と、区間境界を跨ぐ最大下落を独立合算する。

    引数: rows (list[dict])。返り値: 表に必要な独立指標 (dict)。
    区間内DDは既監査値、区間を跨ぐDDは過去山と当区間最小時価から計算する。
    """
    assert rows and len({row['symbol'] for row in rows}) == 1
    ordered = sorted(rows, key=lambda row: row['session'])
    output = {field: math.fsum(row[field] for row in ordered) for field in FIELDS}
    cash = peak = decline = 0.
    for row in ordered:
        decline = max(decline, row['drawdown_yen'], peak - (cash + row['min_equity_yen']))
        peak = max(peak, cash + row['max_equity_yen'])
        cash += row['net_yen']
    output['drawdown_yen'] = decline
    output['money_ratio'] = output['gross_profit_yen'] / output['gross_loss_yen'] if output['gross_loss_yen'] > 1e-8 else None
    output['average_unit_payoff'] = ((output['gross_profit_yen'] / output['profit_units']) /
        (output['gross_loss_yen'] / output['loss_units'])) if output['profit_units'] and output['loss_units'] and output['gross_loss_yen'] > 1e-8 else None
    return output


def money_expected(rows: list[dict], names: list[str], symbol: str) -> list[list]:
    """機能: 全13・後7・2週・全13区間の17行を別式で作る。

    引数: rows (list[dict])、names (list[str])、symbol (str)。返り値: ラベルと数値 (list[list])。
    """
    own = sorted((row for row in rows if row['symbol'] == symbol), key=lambda row: row['session'])
    assert [row['session'] for row in own] == names
    groups = [('全13', own), ('共通後半7', [row for row in own if row['session'] in names[6:]]),
        ('9/21開始週', [row for row in own if row['session'] < '2026-09-28']),
        ('9/28開始週・途中', [row for row in own if row['session'] >= '2026-09-28'])]
    groups += [(row['session'], [row]) for row in own]
    output = []
    for label, group in groups:
        item = aggregate(group)
        values = [item[field] * (-1 if field == 'gross_loss_yen' else 1) for field in FIELDS]
        values.append(item['profit_units'] - item['loss_units'])
        output.append([label, *values])
    return output


def numeric(text: str, expected: float | None, digits: int) -> None:
    """機能: 表示丸め後の数値を検算し、欠測記号とゼロの混同も拒否する。

    引数: text (str)、expected (float|None)、digits (int)。返り値: なし (None)。
    """
    if expected is None:
        assert text == '—', (text, expected)
        return
    assert text != '—'
    actual = float(text.replace(',', ''))
    assert math.isfinite(actual) and actual == float(f'{expected:.{digits}f}'), (text, expected, digits)


def check_money(table, expected: list[list]) -> int:
    """機能: 表ラベル・金額・数量差を全行照合する。

    引数: table (BeautifulSoup要素)、expected (list[list])。返り値: 検査行数 (int)。
    """
    printed = table.select('tbody tr')
    assert len(printed) == len(expected) == 17
    for line, wanted in zip(printed, expected):
        cells = [cell.get_text(strip=True) for cell in line.find_all('td')]
        assert len(cells) == len(wanted) == 8 and cells[0] == wanted[0]
        for text, value in zip(cells[1:], wanted[1:]):
            numeric(text, value, 0)
    return len(printed)


def filter_contract(soup, specs: list[dict]) -> dict:
    """機能: 実HTMLの区分属性と実JavaScriptを、最小DOMで全364選択操作検査する。

    引数: soup (BeautifulSoup)、specs (list[dict])。返り値: 操作記録 (dict)。
    実ブラウザの見た目・リンク・CSS表示は別render担当の検査とする。
    """
    sections = soup.select('details.method')
    by_id = {row['id']: row for row in specs}
    assert len(sections) == len(by_id) == 429 and len({row['id'] for row in sections}) == 429
    assert {row['id'] for row in sections} == set(by_id)
    elements = []
    for section in sections:
        spec = by_id[section['id']]
        role = 'supplementary' if spec.get('supplementary') else 'primary' if spec['primary'] else 'diagnostic'
        assert section['data-signal'] == spec['signal_id'] and section['data-role'] == role
        elements.append(dict(id=section['id'], dataset=dict(signal=spec['signal_id'], role=role), hidden=False))
    options = {}
    for key in ('signal', 'role'):
        select = soup.select_one('#' + key + '-filter')
        assert select is not None
        values = [item['value'] for item in select.find_all('option')]
        assert len(values) == len(set(values))
        selected = [item['value'] for item in select.find_all('option') if item.has_attr('selected')]
        assert len(selected) == 1
        options[key] = dict(values=values, selected=selected[0])
    assert set(options['signal']['values']) == {spec['signal_id'] for spec in specs}
    assert len(options['signal']['values']) == 91 and options['signal']['selected'] == 'Q034'
    assert options['role']['values'] == ['primary', 'diagnostic', 'supplementary', '']
    assert options['role']['selected'] == 'primary'
    scripts = [tag.get_text() for tag in soup.find_all('script') if tag.get_text().strip()]
    assert len(scripts) == 1
    payload = json.dumps(dict(elements=elements, options=options), ensure_ascii=False)
    before = '''const p=PAYLOAD;const methods=p.elements;const count={textContent:''};const selects={};
for(const k of ['signal','role'])selects[k]={value:p.options[k].selected,callback:null,addEventListener(type,fn){if(type!=='change')throw Error('イベント型');this.callback=fn;}};
global.document={querySelectorAll(s){if(s==='.method')return methods;if(s==='select')return Object.values(selects);throw Error('未対応DOM '+s);},getElementById(id){if(id==='visible-count')return count;const k=id.replace('-filter','');if(!(k in selects))throw Error('未対応ID');return selects[k];}};
'''.replace('PAYLOAD', payload)
    after = '''
const results=[];for(const signal of p.options.signal.values)for(const role of p.options.role.values){selects.signal.value=signal;selects.role.value=role;selects.role.callback({type:'change'});const want=methods.filter(e=>e.dataset.signal===signal&&(!role||e.dataset.role===role));const got=methods.filter(e=>!e.hidden);if(JSON.stringify(got.map(e=>e.id))!==JSON.stringify(want.map(e=>e.id)))throw Error('表示集合');if(count.textContent!==want.length+'条件を表示')throw Error('件数表示');results.push({signal,role,count:got.length});}process.stdout.write(JSON.stringify({成功:true,操作数:results.length,操作:results}));
'''
    completed = subprocess.run(['node', '-'], input=before + scripts[0] + after,
        text=True, encoding='utf-8', capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['成功'] and result['操作数'] == 364
    for row in result['操作']:
        expected = 1 if row['role'] == 'primary' else 3 if row['role'] == 'diagnostic' else (
            65 if row['signal'] == 'Q034' else 0) if row['role'] == 'supplementary' else (69 if row['signal'] == 'Q034' else 4)
        assert row['count'] == expected
    return result


def synthetic() -> dict:
    """機能: 合算・境界DD・表示丸めと破損拒否を新損益なしで検査する。

    引数: なし。返り値: 人工検査結果 (dict)。
    """
    names = ['2026-09-' + f'{day:02d}' + '_Day' for day in range(17, 30)]
    rows = [dict(id='人工', session=name, symbol=symbol, gross_profit_yen=10., gross_loss_yen=4.,
        net_yen=6., profit_units=2, loss_units=1, zero_units=1, drawdown_yen=3., min_equity_yen=-2., max_equity_yen=8.)
        for name in names for symbol in ('TOPIX', 'NK225')]
    sessions_checked(rows, '人工', names)
    assert aggregate([row for row in rows if row['symbol'] == 'TOPIX'])['drawdown_yen'] == 4.
    assert aggregate([row for row in rows if row['symbol'] == 'TOPIX'])['net_yen'] == 78.
    expected = money_expected(rows, names, 'TOPIX')
    html = '<table><tbody>' + ''.join('<tr>' + ''.join('<td>' + str(value) + '</td>' for value in row) + '</tr>' for row in expected) + '</tbody></table>'
    assert check_money(BeautifulSoup(html, 'html.parser').table, expected) == 17
    refused = 0
    for mode in ('不足', '重複', '非有限', '枚数端数', '銘柄混入', '金額破損', 'ラベル破損', '欠測を零表示'):
        try:
            bad = deepcopy(rows)
            if mode == '不足': bad.pop()
            elif mode == '重複': bad[-1] = deepcopy(bad[0])
            elif mode == '非有限': bad[0]['gross_profit_yen'] = float('nan')
            elif mode == '枚数端数': bad[0]['profit_units'] = .5
            elif mode == '銘柄混入': bad[0]['symbol'] = '混合'
            if mode in ('金額破損', 'ラベル破損'):
                changed = BeautifulSoup(html, 'html.parser')
                changed.select('tbody tr td')[1 if mode == '金額破損' else 0].string = '999'
                check_money(changed.table, expected)
            elif mode == '欠測を零表示': numeric('0', None, 2)
            else: sessions_checked(bad, '人工', names)
        except (AssertionError, ValueError):
            refused += 1
    assert refused == 8
    return dict(全人工合格=True, 正常表行数=17, 区間跨ぎDD別式=True, 破損拒否数=refused,
        新損益読取=False, 売買再生=False, API取得数=0)


def prepare() -> dict:
    """機能: 対象と独立式を実結果の前に固定する。

    引数: なし。返り値: 固定規則 (dict)。
    """
    test = synthetic()
    save(HERE/'report_contract_selftest.json', test)
    files = [Path(__file__), HERE/'band_design.py', HERE/'report_contract_selftest.json']
    value = dict(主条件数=364, 補助条件数=65, 全表行数=429*2*17, 主比較行数=4*2*2,
        全表示操作数=91*4, 金額枚数源='主とsupplementaryのsessionsをIDごとに区別',
        DD計算='区間内DDと過去山から現在区間最小時価への下落の最大値',
        外観リンク検査=False, 新損益読取=False, 売買再生=False,
        SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in files})
    path = HERE/'report_contract_fixed.json'
    if path.exists(): assert read(path) == value
    else: save(path, value)
    return value


def audit() -> dict:
    """機能: 全429方式と主比較16行を、報告用集計を流用せず検算する。

    引数: なし。返り値: 表示内容監査 (dict)。注文再生や条件再選抜は行わない。
    """
    protocol = prepare()
    files = [OUT/'全条件損益.html', OUT/(TITLE+'.html'), HERE/'report_band.py',
        HERE/'探索条件の固定.json', ROOT/'work/wave_v23/inputs.pkl']
    before = {path.relative_to(ROOT).as_posix(): digest(path) for path in files}
    inputs = pickle.loads(files[-1].read_bytes())
    names = sorted({key[0] for key in inputs})
    assert len(inputs) == 26 and len(names) == 13
    fixed = read(HERE/'探索条件の固定.json')
    assert fixed['全セッション'] == names
    specs = design.conditions() + design.supplementary_conditions()
    source = (OUT/'全条件損益.html').read_text(encoding='utf-8')
    soup = BeautifulSoup(source, 'html.parser')
    filtering = filter_contract(soup, specs)
    sections = {section['id']: section for section in soup.select('details.method')}
    table_count = line_count = 0
    saved_rows = {}
    for spec in specs:
        path = HERE/('supplementary' if spec.get('supplementary') else '')/'sessions'/(spec['id']+'.json.gz')
        before[path.relative_to(ROOT).as_posix()] = digest(path)
        rows = read(path)
        sessions_checked(rows, spec['id'], names)
        saved_rows[spec['id']] = rows
        tables = sections[spec['id']].find_all('table')
        assert len(tables) == 2
        assert {table['data-symbol'] for table in tables} == {'TOPIX', 'NK225'}
        for table in tables:
            assert table['data-id'] == spec['id']
            line_count += check_money(table, money_expected(rows, names, table['data-symbol']))
            table_count += 1
    main = BeautifulSoup((OUT/(TITLE+'.html')).read_text(encoding='utf-8'), 'html.parser')
    main_count = 0
    for period, selection in [('all_symbols', names), ('symbols', names[6:])]:
        table = main.select_one('#main-' + period)
        assert table is not None
        lines = table.select('tbody tr')
        assert len(lines) == 8
        for line, (symbol, identifier) in zip(lines, [(s, i) for s in ('TOPIX', 'NK225') for i in LABELS]):
            cells = [cell.get_text(strip=True) for cell in line.find_all('td')]
            assert len(cells) == 9 and cells[:2] == [symbol, LABELS[identifier]]
            item = aggregate([row for row in saved_rows[identifier+'__V000'] if row['symbol'] == symbol and row['session'] in selection])
            for position, field, sign, digits in [(2, 'gross_profit_yen', 1, 0), (3, 'gross_loss_yen', -1, 0),
                (4, 'net_yen', 1, 0), (5, 'drawdown_yen', 1, 0), (6, 'money_ratio', 1, 2), (7, 'average_unit_payoff', 1, 2)]:
                numeric(cells[position], item[field] * sign if item[field] is not None else None, digits)
            assert cells[8] == '/'.join(str(int(item[field])) for field in ('profit_units', 'loss_units', 'zero_units'))
            main_count += 1
    assert line_count == 14586 and table_count == 858 and main_count == 16
    assert before == {path: digest(ROOT/path) for path in before}
    return dict(全報告照合合格=True, 全条件数=429, 主条件数=364, 補助条件数=65,
        全金額枚数表数=table_count, 全金額枚数行数=line_count, 主比較行数=main_count,
        表示操作=filtering, 合成検査=read(HERE/'report_contract_selftest.json'), 規則=protocol,
        参照SHA256=before, 入力HTML前後不変=True, 新売買再生=False, API取得数=0,
        現在保存物使用=False, 外観リンクは別検査=True)


def main() -> None:
    """機能: 事前固定又はHTML生成後の照合だけを実行する。

    引数: --prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare()
        print('報告照合規則・人工8破損拒否を新損益前に固定', flush=True)
        return
    value = audit()
    save(HERE/'report_contract_audit.json', value)
    print({key: value[key] for key in ('全報告照合合格', '全金額枚数行数', '主比較行数')}, flush=True)


if __name__ == '__main__':
    main()
