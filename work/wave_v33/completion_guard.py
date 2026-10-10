"""主96・独立会計・全波・H019図を欠落なく結び、採否と検証完了を分ける。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import pickle
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import numpy as np
import assessment
import atr_runner as runner
import design
import run_verified

HERE, ROOT = design.HERE, design.ROOT


def close(actual, expected, label: str) -> None:
    """機能: 構造と全値を照合し、小さな演算順差だけ許容する。

    引数: actual/expected (object)、label (str)。返り値: なし (None)。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), label + '項目集合不一致'
        for name, value in expected.items():
            close(actual[name], value, label + '/' + str(name))
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), label + '件数不一致'
        for i, value in enumerate(expected):
            close(actual[i], value, label + '/' + str(i))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert math.isfinite(actual) and math.isfinite(expected)
        assert math.isclose(actual, expected, abs_tol=1e-6, rel_tol=1e-10), label + '数値不一致'
    else:
        assert actual == expected, label + '値不一致'


def subset(actual: dict, expected: dict, label: str) -> None:
    """機能: 必須項目を全て要求し、追加監査項目は残して比較する。

    引数: actual/expected (dict)、label (str)。返り値: なし (None)。
    """
    assert set(expected) <= set(actual), label + '必須項目欠落'
    for name, value in expected.items():
        close(actual[name], value, label + '/' + name)


def unique(rows: list, fields: tuple) -> dict:
    """機能: 全明細を一意の複合キーにし、重複を拒否する。

    引数: rows (list[dict])、fields (tuple[str])。返り値: 索引 (dict)。
    """
    result = {tuple(r[k] for k in fields): r for r in rows}
    assert len(result) == len(rows), '重複資料'
    return result


def accounting_record(record: dict, summary: dict, rows: list, inputs: dict) -> None:
    """機能: 独立会計一条件26入力の必須保存項目と検査数を照合する。

    引数: record/summary/inputs (dict)、rows (list[dict])。返り値: なし (None)。
    """
    assert record['id'] == summary['id'] and record['全入力数'] == len(inputs)
    assert record['原本行会計数'] == sum(len(r['last']) for r in inputs.values())
    assert record['台帳SHA256'] == summary['ledger_hash']
    for name in ('prefix検査数', '未来価格入口ATR追跡ATR方向改変数', '買売反射数'):
        assert record[name] == len(inputs)
    for name in ('全保存数値一致', '全台帳配列一致', '全時価曲線SHA一致', 'ATR全保有行検算', '返却独立検算'):
        assert record[name] is True
    index = unique(record['sessions'], ('session', 'symbol'))
    assert set(index) == set(inputs)
    for row in rows:
        key = row['session'], row['symbol']
        saved = index[key]
        subset(saved, row, '独立会計全保存値')
        assert saved['検算した観測行数'] == len(inputs[key]['last'])
        for name in ('prefix検査合格', '未来改変合格', '買売反射合格', '全台帳配列一致',
                     '全時価曲線SHA一致', 'ATR全保有行検算', '返却独立検算'):
            assert saved[name] is True
    for period in ('all_symbols', 'symbols'):
        close(record[period], summary[period], '独立期間会計')


def verify_ledger(records: list, rows: list, summary: dict, inputs: dict, fixed: dict) -> dict:
    """機能: 全約定の金額・枚数・組ピーク悪化と指紋を全26で照合する。

    引数: records/rows (list[dict])、summary/inputs/fixed (dict)。返り値: 件数 (dict)。
    """
    ledgers, sessions = unique(records, ('session', 'symbol')), unique(rows, ('session', 'symbol'))
    assert set(ledgers) == set(sessions) == set(inputs)
    hasher = hashlib.sha256()
    trade_count = order_count = 0
    for key, ready in inputs.items():
        record, row = ledgers[key], sessions[key]
        config = runner.managers.make_config(fixed['manager'], key[1], ready)
        assert record['config'] == config
        trades = np.asarray(record['trades'], float).reshape(-1, 11)
        orders = np.asarray(record['orders'], float).reshape(-1, 8)
        cycles = np.asarray(record['cycles'], float).reshape(-1, 10)
        stats = np.asarray(record['stats'], float)
        assert all(np.isfinite(v).all() for v in (trades, orders, cycles, stats))
        hasher.update(str(key).encode()); hasher.update(trades.tobytes())
        multiplier = config['point_value']
        pnl = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * multiplier
        close(float(pnl[pnl > 1e-6].sum()), row['gross_profit_yen'], '全利益')
        close(float(-pnl[pnl < -1e-6].sum()), row['gross_loss_yen'], '全損失')
        close(float(pnl.sum()), row['net_yen'], '全返済収支')
        for mask, field in ((pnl > 1e-6, 'profit_units'), (pnl < -1e-6, 'loss_units'), (np.abs(pnl) <= 1e-6, 'zero_units')):
            close(float(trades[mask, 3].sum()), row[field], '決済枚数')
        assert int(stats[9]) == 0 and max(stats[2], stats[3]) <= config['audit_cap']
        assert np.all(orders[:, 0] > orders[:, 1]) and len(np.unique(orders[:, 0])) == len(orders)
        close(float(trades[:, 3].sum()), row['closed_units'], '全決済枚数')
        close(float(cycles[:, 3].sum()) * multiplier, row['net_yen'], '全組収支')
        close(float(stats[0]) * multiplier, row['net_yen'], '口座収支')
        assert len(cycles) == row['cycles'] == row['opening_orders'] == len(row['retracements'])
        assert row['closed_units'] == config['initial_qty'] * len(cycles)
        for raw, metric in zip(cycles, row['retracements']):
            assert [metric['campaign'], metric['entry_row'], metric['exit_row']] == list(map(int, raw[:3]))
            close(metric['risk_yen'], float(raw[4]) * multiplier, '初回R固定')
            close(metric['final_yen'], float(raw[3]) * multiplier, '組最終損益')
            assert metric['risk_yen'] > 0 and metric['peak_yen'] >= 0
            close(metric['retracement_yen'], max(0., metric['peak_yen'] - metric['final_yen']), '組悪化差額')
            close(metric['retracement_r'], metric['retracement_yen'] / metric['risk_yen'], '組悪化R')
            assert metric['positive_peak'] == (metric['peak_yen'] > 1e-8 * multiplier)
            close(metric['holding_minutes'], float((ready['time_s'][int(raw[2])] - ready['time_s'][int(raw[1])]) / 60), '組保有時間')
        trade_count += len(trades)
        order_count += len(orders)
    assert hasher.hexdigest() == summary['ledger_hash']
    return {'返済脚数': trade_count, '全注文数': order_count}


def wave_records(main: dict, independent: list[dict]) -> None:
    """機能: 全96の8波の一意集合と、独立注文会計による時間・境界差を照合する。

    引数: main (dict[id,list])、independent (list[dict])。返り値: なし (None)。
    """
    rows = [r for group in main.values() for r in group]
    expected = {(name, wave['id'], symbol) for name in main for wave in design.waves() for symbol in assessment.SYMBOLS}
    source = unique(rows, ('method', 'wave', 'symbol'))
    audit = unique(independent, ('method', 'wave', 'symbol'))
    assert len(rows) == len(independent) == 768 and set(source) == set(audit) == expected
    fields = ('正方向ネット保有分', '逆方向ネット保有分', 'ネット中立分', '正方向脚保有分', '逆方向脚保有分',
              '正方向枚数分', '逆方向枚数分', '両建て保有分', '時価損益差円', '実現損益差円', '含み損益差円')
    boundary_fields = ('参照行', 'seq', 'last', '買い枚数', '売り枚数', 'ネット枚数', '時価損益円', '実現損益円', '含み損益円')
    for key, row in audit.items():
        original = source[key]
        assert row['保存値一致'] is True and row['session'] == original['session']
        for name in fields:
            close(row[name], original[name], '波の注文独立検算')
        for name in ('開始境界', '終了境界'):
            assert set(row[name]) == set(boundary_fields)
            for field in boundary_fields:
                close(row[name][field], original[name][field], '波の時価境界')


def verify_waves(waves: dict, load, check) -> dict:
    """機能: 全波監査の固定対象と実体指紋を照合する。

    引数: waves (dict)、load/check (callable)。返り値: 波件数 (dict)。
    """
    planned = load(HERE / 'chart_wave_fixed.json')
    fixed = load(HERE / 'wave_order_fixed.json')
    audit = load(HERE / 'wave_order_audit.json')
    assert planned['全条件'] == design.catalog() and planned['全指定波'] == design.waves()
    assert fixed['対象'] == [s['id'] for s in design.catalog()]
    for value in (planned, audit):
        assert value['全条件数'] == 96 and value['全指定波数'] == 768 and value['比較境界数'] == 1536
    assert audit['全合格'] is True and audit['API取得数'] == 0 and audit['現在保存物使用'] is False and audit['注文器再生'] is False
    for name in ('注文独立会計一致', '保有時間枚数分一致', '区間内全注文一致'):
        assert audit[name] is True
    check(HERE / 'wave_order_fixed.json', audit['固定SHA256'])
    for group in (planned['参照SHA256'], fixed['SHA256']):
        for name, expected in group.items():
            check(ROOT / name, expected)
    expected_names = {str(Path(folder) / (name + '.json.gz')) for name in waves for folder in ('ledgers', 'waves')}
    assert set(audit['保存資料SHA256']) == expected_names
    for name, expected in audit['保存資料SHA256'].items():
        check(HERE / name, expected)
    wave_records(waves, audit['結果'])
    return {'全指定波数': 768, '境界数': 1536, '全注文からの時価と保有時間一致': True}


class ChartData(HTMLParser):
    """機能: HTMLの図JSONとリンクを抽出する。

    引数: feedへHTML (str)。返り値: data/links属性 (str/list)。
    """

    def __init__(self) -> None:
        """機能: 抽出状態を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__()
        self.active, self.data, self.links, self.ids = False, '', [], set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """機能: 図JSON開始・リンク・重複IDを確認する。

        引数: tag (str)、attrs (list)。返り値: なし (None)。
        """
        value = dict(attrs)
        if value.get('id'):
            assert value['id'] not in self.ids
            self.ids.add(value['id'])
        if tag == 'script' and value.get('id') == 'chart-data':
            self.active = True
        if tag == 'a' and value.get('href'):
            self.links.append(value['href'])

    def handle_endtag(self, tag: str) -> None:
        """機能: JSON収集を終了する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag == 'script':
            self.active = False

    def handle_data(self, text: str) -> None:
        """機能: JSON内容を蓄積する。

        引数: text (str)。返り値: なし (None)。
        """
        if self.active:
            self.data += text


def verify_charts(details: dict, load, check) -> dict:
    """機能: 固定2方式52図を台帳・原本asof・HTMLの間で照合する。

    引数: details (dict)、load/check (callable)。返り値: 全図検査数 (dict)。
    """
    fixed = load(HERE / 'chart_fixed.json')
    audit = load(HERE / 'chart_audit.json')
    html_audit = load(HERE / 'chart_data_audit.json')
    plots = load(HERE / 'chart_details.json.gz')
    ids = ['H019__A0__V000', 'H019__AT__V000']
    assert fixed['手法'] == plots['対象'] == ids and fixed['全図示数'] == audit['全図示数'] == html_audit['全図示数'] == 52
    for name in ('全収支一致', '全返済一致', '全台帳一致', '全原本asof一致'):
        assert audit[name] is True
    assert html_audit['全返済一致'] is True and html_audit['原本asof列一致'] is True
    for name in ('全新規一致', 'ATR価格線の別式計算一致', 'ローカルリンク全有効'):
        assert html_audit[name] is True
    for value in (audit, html_audit):
        assert value['API取得数'] == 0 and value['現在保存物使用'] is False
    for value in (audit, plots):
        check(HERE / 'chart_fixed.json', value['固定SHA256'])
    check(HERE / 'chart_fixed.json', html_audit['固定SHA256'])
    for name, expected in fixed['SHA256'].items():
        check(ROOT / name, expected)
    for name, expected in audit['台帳元SHA256'].items():
        check(HERE / name, expected)
    check(HERE / 'chart_data_audit.py')
    path = ROOT / 'アルゴリズム調査/00028_保有中ATRによる追跡幅更新/５分足と売買.html'
    check(path, html_audit['HTML_SHA256'])
    parser = ChartData(); parser.feed(path.read_text(encoding='utf-8'))
    payload = json.loads(parser.data)
    assert payload['trace_columns'] == fixed['TRACE_COLUMNS']
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    expected = {(name, *key) for name in ids for key in inputs}
    records = unique(plots['図'], ('method', 'session', 'symbol'))
    checked = unique(audit['保存済み収支との比較'], ('id', 'session', 'symbol'))
    assert set(records) == set(checked) == expected
    assert set(payload['trades']) == set(payload['tracking']) == {'|'.join(key) for key in expected}
    trades = orders = samples = 0
    source_rows = {name: unique(details[name], ('session', 'symbol')) for name in ids}
    for key, row in records.items():
        ready = inputs[key[1], key[2]]
        saved = payload['trades']['|'.join(key)]
        close(payload['tracking']['|'.join(key)], row['asof'], 'HTML原本指標列')
        assert len(saved) == len(row['全返済']) == checked[key]['返済件数'] and checked[key]['保存値一致'] is True
        for actual, target in zip(saved, row['全返済']):
            times = [datetime.fromisoformat(target[name]).timestamp() for name in ('新規時刻', '返済時刻')]
            close(actual[:7], times + [target['direction'], target['枚数'], target['新規価格'], target['返済価格'], target['損益円']], 'HTML返済')
            assert actual[7] == runner.engine.REASONS[target['返済理由番号']]
            assert actual[9:] == [target['新規行'], target['返済行']]
        for point in row['asof']:
            time, reference = point[:2]
            wanted = int(np.searchsorted(ready['time_s'], time, side='right') - 1)
            assert reference == wanted
            if reference < 0 or point[3] == 0:
                assert all(value is None for value in point[4:])
        main = source_rows[key[0]][key[1], key[2]]
        close(sum(r[6] for r in saved), main['net_yen'], '図台帳収支')
        close(checked[key]['収支円'], main['net_yen'], '図監査収支')
        close(checked[key]['新規件数'], main['opening_orders'], '図新規数')
        trades += len(saved)
        orders += checked[key]['新規件数']
        samples += len(row['asof'])
    assert trades == html_audit['全返済件数'] and orders == html_audit['全新規件数'] and samples == html_audit['原本asof標本数']
    for href in parser.links:
        assert not href.startswith(('http:', 'https:'))
        target = href.split('#', 1)[0]
        assert not target or (path.parent / target).exists()
    return {'全図示数': 52, '全返済脚数': trades, '全新規件数': orders, '原本asof標本数': samples, '原本asofと全返済とHTML一致': True}


def collect() -> dict:
    """機能: 全96の資料集合と全監査・判定を結合し、前後指紋を確認する。

    引数: なし。返り値: 完備監査 (dict)。売買再生はしない。
    """
    prior = run_verified.verify_sources()
    hashes = dict(prior['SHA256'])

    def check(path: Path, expected: str | None = None) -> str:
        """機能: 参照ファイルの指紋を記録し、期待値と改変を照合する。

        引数: path (Path)、expected (str|None)。返り値: SHA256 (str)。
        """
        path = path.resolve(); name = path.relative_to(ROOT).as_posix()
        actual = design.digest(path)
        assert expected is None or actual == expected, '指紋不一致: ' + name
        assert name not in hashes or hashes[name] == actual, '読取り途中の改変: ' + name
        hashes[name] = actual
        return actual

    def load(path: Path):
        """機能: 指紋を固定し保存JSONを読む。

        引数: path (Path)。返り値: JSON内容 (object)。
        """
        check(path)
        return runner.read(path)

    fixed = load(HERE / '探索条件の固定.json')
    evidence = load(HERE / '主再生の起動証跡.json')['実行'][-1]
    assert evidence['完了'] is True and evidence['実行可能'] is True
    check(HERE / 'run_verified.py', evidence['ガード実装SHA256'])
    check(HERE / 'run_verified_fixed.json', evidence['ガード固定SHA256'])
    startup_fixed = load(HERE / 'run_verified_fixed.json')
    check(HERE / 'run_verified_test.py', startup_fixed['拒否検査実装SHA256'])
    check(HERE / 'run_verified_test.json', startup_fixed['拒否検査SHA256'])
    assert load(HERE / 'run_verified_test.json')['全検査合格'] is True
    check(HERE / '探索条件の固定.json', evidence['探索固定SHA256'])
    check(HERE / '主再生の完了.json', evidence['主再生の完了SHA256'])
    complete = load(HERE / '主再生の完了.json')
    assert complete['全条件数'] == 96 and complete['全入力数'] == 2496 and complete['全波数'] == 768
    assert complete['旧固定12一致'] is True and complete['API取得数'] == 0 and complete['現在保存物使用'] is False
    check(HERE / '探索条件の固定.json', complete['探索固定SHA256'])
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    specs = {s['id']: s for s in design.catalog()}
    summaries = load(HERE / '全条件の期間集計.json.gz')
    index = unique(summaries, ('id',))
    assert len(summaries) == 96 and set(index) == {(name,) for name in specs}
    for folder, suffix in (('sessions', '.json.gz'), ('summaries', '.json'), ('ledgers', '.json.gz'), ('waves', '.json.gz'), ('accounting_details', '.json.gz')):
        assert {p.name for p in (HERE / folder).glob('*' + suffix)} == {name + suffix for name in specs}, folder + '欠落/余分な結果'
    accounting = load(HERE / 'accounting_audit.json')
    assert accounting['全監査合格'] is True and accounting['対象条件数'] == 96 and accounting['全入力数'] == 2496
    revision = load(HERE / 'accounting_revision.json')
    assert revision['終了コード'] == 1 and revision['API取得数'] == 0
    for name in ('売買コード変更', '成績変更', '対象変更', '採否基準変更'):
        assert revision[name] is False
    check(HERE / 'accounting_audit.py', revision['旧監査SHA256'])
    check(HERE / 'accounting_fixed.json', revision['旧監査規則SHA256'])
    check(HERE / 'accounting_audit_v2.py', revision['新監査SHA256'])
    assert accounting['監査規則'] == load(HERE / 'accounting_fixed_v2.json')
    assert accounting['合成検査'] == load(HERE / 'accounting_selftest_v2.json')
    assert accounting['合成検査']['合成合格'] is True and accounting['合成検査']['合成組合せ数'] == 4
    assert accounting['監査規則']['対象条件ID'] == [s['id'] for s in design.catalog()]
    for group in ('参照SHA256', '事前入力監査参照SHA256', '原本78SHA256'):
        for name, expected in accounting[group].items():
            check(ROOT / name, expected)
    causal = load(HERE / 'input_causality_before_pnl.json')
    assert accounting['参照SHA256'] == fixed['SHA256'] and accounting['事前入力監査参照SHA256'] == causal['参照SHA256']
    assert accounting['原本78SHA256'] == causal['原本78SHA256']
    check(HERE / '探索条件の固定.json', accounting['探索固定SHA256'])
    for name, expected in accounting['監査規則']['参照SHA256'].items():
        check(ROOT / name, expected)
    audit_rows = unique(accounting['条件'], ('id',))
    assert set(audit_rows) == set(index)
    details, waves, ledgers = {}, {}, {}
    trade_count = order_count = 0
    for identifier, spec in specs.items():
        summary = index[identifier,]
        close(summary, load(HERE / 'summaries' / (identifier + '.json')), '主集計と個別集計')
        assert summary['spec'] == spec
        check(HERE / '探索条件の固定.json', summary['探索固定SHA256'])
        rows = details[identifier] = load(HERE / 'sessions' / (identifier + '.json.gz'))
        records = ledgers[identifier] = load(HERE / 'ledgers' / (identifier + '.json.gz'))
        waves[identifier] = load(HERE / 'waves' / (identifier + '.json.gz'))
        assert len(waves[identifier]) == 8 and all(r['method'] == identifier for r in waves[identifier])
        assert len(rows) == 26 and all(r['id'] == identifier for r in rows)
        counts = verify_ledger(records, rows, summary, inputs, fixed)
        trade_count += counts['返済脚数']; order_count += counts['全注文数']
        for period, sessions in (('all_symbols', fixed['全セッション']), ('symbols', fixed['共通評価7セッション'])):
            close(summary[period], runner.periods(rows, sessions), '全期間再集計')
        assert summary['wave_passes'] == sum(r['正方向ネット20分目安達成'] for r in waves[identifier])
        recorded = load(HERE / 'accounting_details' / (identifier + '.json.gz'))
        accounting_record(recorded, summary, rows, inputs)
        close(audit_rows[identifier,], {k: v for k, v in recorded.items() if k not in ('sessions', '保存資料SHA256')}, '会計要約と明細')
        for name, expected in recorded['保存資料SHA256'].items():
            check(ROOT / name, expected)
        is_old = spec['atr_mode'] == 'initial' and spec['variant_id'] in ('V000', 'L300')
        assert summary['旧固定再現'] == recorded['旧固定一致'] == recorded['固定方式の追跡ATR不使用一致'] == is_old
    for signal in design.SIGNAL_IDS:
        initial, lagged = signal + '__A0__V000', signal + '__A0__L300'
        close(ledgers[initial], ledgers[lagged], 'A0で追跡ATR変更不使用')
        old = next(r for r in load(HERE.parent / 'wave_v31/summaries' / (signal + '.json'))['candidates'] if r['id'] == signal + '__L000__V000')
        assert index[initial,]['ledger_hash'] == old['ledger_hash'] == index[lagged,]['ledger_hash']
    raw_count = sum(len(r['last']) for r in inputs.values())
    assert accounting['一条件原本行数'] == raw_count and accounting['全原本行会計数'] == raw_count * 96
    for name in ('prefix検査数', '未来価格入口ATR追跡ATR方向改変数', '買売反射数'):
        assert accounting[name] == 2496
    for name in ('全保存数値一致', '全台帳配列一致', '全時価曲線SHA一致', 'ATR全保有行検算', '返却独立検算'):
        assert accounting[name] is True
    assert accounting['旧固定一致条件数'] == accounting['固定方式の追跡ATR不使用一致条件数'] == 24
    assert accounting['API取得数'] == 0 and all(accounting[n] is False for n in ('現在保存物使用', '成績による対象選別', '規則変更'))
    judged = load(HERE / '独立判定.json')
    check(HERE / 'assessment_fixed.json', judged['独立判定固定SHA256'])
    close({k: v for k, v in judged.items() if k != '独立判定固定SHA256'}, assessment.assess(summaries, details, waves), '全96独立判定')
    wave_stats = verify_waves(waves, load, check)
    chart_stats = verify_charts(details, load, check)
    own_fixed = load(HERE / 'completion_guard_fixed.json')
    check(Path(__file__), own_fixed['実装SHA256'])
    check(HERE / 'completion_guard_test.py', own_fixed['検査実装SHA256'])
    tests = load(HERE / 'completion_guard_test.json')
    check(HERE / 'completion_guard_test.json', own_fixed['検査SHA256'])
    assert tests['全検査合格'] is True and tests['採否条件変更'] is False
    for name, expected in hashes.items():
        assert design.digest(ROOT / name) == expected, '完備監査前後の変更: ' + name
    return {'検証完了': True, '全条件数': 96, '全入力数': 2496, '全指定波数': 768, '全図示数': 52,
            '全原本行会計数': raw_count * 96, '全返済脚数': trade_count, '全注文数': order_count,
            '旧固定一致条件数': 24, '入力未来改変/切断/反射数': 2496,
            '全波': wave_stats, '全図': chart_stats, '主採用目安ID': judged['主条件採用目安ID'],
            '会計監査改訂': {'記録': 'accounting_revision.json', '旧監査不変': True, '全96をv2再検算': True, '売買コード変更': False},
            '参照資料SHA256': hashes, 'ガード実装SHA256': own_fixed['実装SHA256'],
            'ガード固定SHA256': design.digest(HERE / 'completion_guard_fixed.json'),
            '採否条件変更': False, 'API取得数': 0, '現在保存物使用': False,
            '意味': '全件の実装・会計・記録・比較の完了。採用目安合格や未知収益保証とは区別。',
            '確認日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()}


def freeze() -> dict:
    """機能: 完備ガードと人工拒否検査を固定する。

    引数: なし。返り値: 固定記録 (dict)。採否条件を変更しない。
    """
    payload = {'実装SHA256': design.digest(Path(__file__)), '検査SHA256': design.digest(HERE / 'completion_guard_test.json'),
               '検査実装SHA256': design.digest(HERE / 'completion_guard_test.py'),
               '全条件数': 96, '全入力数': 2496, '全指定波数': 768, '全図示数': 52, '採否条件変更': False}
    path = HERE / 'completion_guard_fixed.json'
    if path.exists():
        assert runner.read(path) == payload
    else:
        runner.save(path, payload)
    return payload


def main() -> None:
    """機能: 完備ガードを固定し、全資料の照合完了後だけ完了を保存する。

    引数: --prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    freeze()
    if args.prepare:
        print('全96完備ガード固定。採否条件変更なし。')
        return
    result = collect()
    runner.save(HERE / '完備監査.json', result)
    print({k: result[k] for k in ('検証完了', '全条件数', '全入力数', '全指定波数', '全図示数')})


if __name__ == '__main__':
    main()

