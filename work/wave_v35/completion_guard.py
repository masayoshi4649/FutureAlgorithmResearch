"""全840の初期選択・後期評価・独立監査と補助診断を欠落なく結合する。"""
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
import conditional_design as design
import conditional_assessment as assessment
import conditional_runner as runner
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


def wave_records(main: dict, independent: list[dict]) -> None:
    """機能: 全840の8波の一意集合と、独立注文会計による時間・境界差を照合する。

    引数: main (dict[id,list])、independent (list[dict])。返り値: なし (None)。
    """
    rows = [r for group in main.values() for r in group]
    expected = {(name, wave['id'], symbol) for name in main for wave in design.waves() for symbol in assessment.SYMBOLS}
    source = unique(rows, ('method', 'wave', 'symbol'))
    audit = unique(independent, ('method', 'wave', 'symbol'))
    assert len(rows) == len(independent) == 6720 and set(source) == set(audit) == expected
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

def stage_rows(rows: list, identifier: str, keys: set, inputs: dict) -> dict:
    """機能: 段階ごとの必要区間を厳密に要求し、未完了・未来混入を拒否する。

    引数: rows (list)、identifier (str)、keys (set)、inputs (dict)。返り値: 区間索引 (dict)。
    """
    index = unique(rows, ('session', 'symbol'))
    assert set(index) == keys, '段階の区間不足又は混入'
    import conditional_accounting_audit as independent
    for key, row in index.items():
        assert set(row) == independent.SESSION_FIELDS, '保存session項目集合不一致'
        assert row['id'] == identifier and row['complete'] is True
        close(row['completed_at'], float(inputs[key]['time_s'][-1]), '完了時刻')
        assert row['completed_at'] > inputs[key]['limit']
    return index


def preparation_and_pairs(record: dict, row: dict, ready: dict, spec: dict) -> None:
    """機能: 影と全新規が一致し、全対応組の退出が影より遅くないことを照合する。

    引数: record/row/ready/spec (dict)。返り値: なし (None)。保存配列だけを使用する。
    """
    shapes = {'trades': 11, 'orders': 8, 'cycles': 10, 'prepare_events': 7,
              'entry_preparations': 4, 'trail_events': 15}
    arrays = []
    for source in (record, record['shadow']):
        assert set(source['result_fingerprints']) == set(runner.RESULT_FIELDS)
        values = {}
        for field in runner.STORED_FIELDS:
            raw = source[field]
            value = np.asarray(raw, dtype=float)
            if field in shapes:
                value = value.reshape(-1, shapes[field])
            if field != 'trail_events':
                assert np.isfinite(value).all()
            else:
                assert not np.isinf(value).any()
                allowed = np.zeros(value.shape, bool); allowed[:, [3, 5]] = True
                assert np.all(np.isfinite(value) | allowed), '価格線以外の欠測'
            expected = {'shape': list(value.shape), 'SHA256': hashlib.sha256(value.tobytes()).hexdigest()}
            assert source['result_fingerprints'][field] == expected, '台帳数値指紋不一致'
            values[field] = value
        events, links, orders = values['prepare_events'], values['entry_preparations'], values['orders']
        assert np.array_equal(events[:, 0], np.arange(len(events)))
        assert len(np.unique(events[:, 1])) == len(events) and np.all(np.diff(events[:, 1]) > 0)
        assert np.all(events[:, 1] == events[:, 1].astype(int))
        assert np.all((events[:, 1] >= 0) & (events[:, 1] < len(ready['last'])))
        opens = orders[orders[:, 7] == 1]
        assert len(opens) == len(links) == len(values['cycles'])
        for link, opening in zip(links, opens, strict=True):
            campaign, fill, identity, fresh = map(int, link)
            assert list(link) == [campaign, fill, identity, fresh]
            assert 0 <= identity < len(events)
            event = events[identity]
            assert fresh == event[1] and fresh <= opening[1] < fill == opening[0]
            assert campaign == opening[2] and opening[3] == event[2] and opening[4] == event[6]
        arrays.append(values)
    actual, shadow = arrays
    for field in ('prepare_events', 'entry_preparations'):
        np.testing.assert_array_equal(actual[field], shadow[field])
    np.testing.assert_array_equal(actual['orders'][actual['orders'][:, 7] == 1], shadow['orders'][shadow['orders'][:, 7] == 1])
    allow = np.zeros(len(ready['last']), bool)
    allow[shadow['prepare_events'][:, 1].astype(int)] = True
    assert record['prepare_allow_SHA256'] == hashlib.sha256(allow.tobytes()).hexdigest()
    if spec['width_mode'] == 0:
        assert record['result_fingerprints'] == record['shadow']['result_fingerprints']
    pairs = []
    factor = record['config']['point_value']
    for a, b in zip(actual['cycles'], shadow['cycles'], strict=True):
        assert np.array_equal(a[[0, 1, 4, 5, 8]], b[[0, 1, 4, 5, 8]]) and a[2] <= b[2]
        cid = int(a[0]); left = actual['trades'][actual['trades'][:, 0] == cid, 2:]
        right = shadow['trades'][shadow['trades'][:, 0] == cid, 2:]
        pairs.append({'campaign': cid, 'entry_row': int(a[1]), 'shadow_exit_row': int(b[2]),
            'actual_exit_row': int(a[2]), 'shadow_yen': float(b[3] * factor),
            'actual_yen': float(a[3] * factor), 'difference_yen': float((a[3] - b[3]) * factor),
            'difference_r': float((a[3] - b[3]) / a[4]),
            'changed_repayments': not np.array_equal(left, right)})
    close(row['exit_pairs'], pairs, '全退出対応')
    control = row['control']; assert set(control) == set(runner.CONTROL_FIELDS)
    expected = {'campaigns': len(pairs), 'earlier_exits': sum(p['actual_exit_row'] < p['shadow_exit_row'] for p in pairs),
        'equal_exit_rows': sum(p['actual_exit_row'] == p['shadow_exit_row'] for p in pairs),
        'changed_repayments': sum(p['changed_repayments'] for p in pairs),
        'exit_difference_yen': sum(p['difference_yen'] for p in pairs),
        'exit_difference_r': sum(p['difference_r'] for p in pairs)}
    subset(control, expected, '全退出集計')
    assert control['campaigns'] == row['cycles'] == row['opening_orders']
    for field in runner.CONTROL_FIELDS:
        value = control[field]
        assert math.isfinite(value)
        if field not in ('exit_difference_yen', 'exit_difference_r'):
            assert value >= 0
    assert control['adverse_rows'] <= control['held_rows']
    assert control['contracted_atr_rows'] <= control['shortening_enabled_rows'] <= control['held_rows']
    assert control['stricter_candidate_rows'] <= control['shortening_enabled_rows']
    assert control['conditional_advance_events'] <= control['additional_advance_events']
    events = actual['trail_events']
    assert control['fixed_advance_events'] == np.sum(events[:, 7] == 1)
    assert control['additional_advance_events'] == np.sum(events[:, 7] >= 2)
    assert control['conditional_advance_events'] == np.sum(events[:, 7] == 3)
    assert control['adverse_seconds'] <= control['held_seconds'] + 1e-6
    assert control['shortening_enabled_seconds'] <= control['held_seconds'] + 1e-6


def verify_ledger(records: list, rows: list, summary: dict, inputs: dict, fixed: dict) -> dict:
    """機能: 全約定から金額・決済枚数・全組対応・初回Rを直接再集計する。

    引数: records/rows (list)、summary/inputs/fixed (dict)。返り値: 件数 (dict)。
    """
    ledgers, sessions = unique(records, ('session', 'symbol')), unique(rows, ('session', 'symbol'))
    assert set(ledgers) == set(sessions) == set(inputs)
    hasher = hashlib.sha256(); trades_count = orders_count = 0
    for record in records:
        key = record['session'], record['symbol']; ready, row = inputs[key], sessions[key]
        preparation_and_pairs(record, row, ready, summary['spec'])
        config = runner.managers.make_config(fixed['manager'], key[1], ready)
        assert record['config'] == config
        trades = np.asarray(record['trades'], float).reshape(-1, 11)
        orders = np.asarray(record['orders'], float).reshape(-1, 8)
        cycles = np.asarray(record['cycles'], float).reshape(-1, 10)
        stats = np.asarray(record['stats'], float)
        hasher.update(str(key).encode()); hasher.update(trades.tobytes())
        multiplier = config['point_value']
        pnl = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * multiplier
        close(float(pnl[pnl > 1e-6].sum()), row['gross_profit_yen'], '全利益')
        close(float(-pnl[pnl < -1e-6].sum()), row['gross_loss_yen'], '全損失')
        close(float(pnl.sum()), row['net_yen'], '全収支')
        for mask, field in ((pnl > 1e-6, 'profit_units'), (pnl < -1e-6, 'loss_units'), (np.abs(pnl) <= 1e-6, 'zero_units')):
            close(float(trades[mask, 3].sum()), row[field], '決済枚数')
        assert stats[9] == 0 and max(stats[2], stats[3]) <= config['audit_cap']
        assert np.all(orders[:, 0] > orders[:, 1]) and len(np.unique(orders[:, 0])) == len(orders)
        close(float(trades[:, 3].sum()), row['closed_units'], '決済総数')
        close(float(cycles[:, 3].sum() * multiplier), row['net_yen'], '組収支')
        close(float(stats[0] * multiplier), row['net_yen'], '口座収支')
        assert len(cycles) == row['cycles'] == row['opening_orders'] == len(row['retracements'])
        assert row['closed_units'] == config['initial_qty'] * len(cycles)
        for raw, metric in zip(cycles, row['retracements']):
            assert [metric['campaign'], metric['entry_row'], metric['exit_row']] == list(map(int, raw[:3]))
            close(metric['risk_yen'], float(raw[4]) * multiplier, '初回R')
            close(metric['final_yen'], float(raw[3]) * multiplier, '組損益')
            assert metric['risk_yen'] > 0 and metric['peak_yen'] >= 0
            close(metric['retracement_yen'], max(0., metric['peak_yen'] - metric['final_yen']), '返却円')
            close(metric['retracement_r'], metric['retracement_yen'] / metric['risk_yen'], '返却R')
            assert metric['positive_peak'] == (metric['peak_yen'] > 1e-8 * multiplier)
            close(metric['holding_minutes'], (ready['time_s'][int(raw[2])] - ready['time_s'][int(raw[1])]) / 60, '保有分')
        trades_count += len(trades); orders_count += len(orders)
    assert hasher.hexdigest() == summary['ledger_hash']
    return {'返済脚数': trades_count, '全注文数': orders_count}


def verify_stages(base: Path, spec: dict, inputs: dict, fixed: dict, load) -> tuple:
    """機能: 初期6と後7の保存物が全13へ無改変で結合されたことを確認する。

    引数: base (Path)、spec/inputs/fixed (dict)、load (callable)。返り値: 集計・全明細・台帳・波 (tuple)。
    """
    import conditional_accounting_audit as independent
    name = spec['id']; phases = {}
    for phase, sessions in (('training', fixed['選択用6セッション']), ('evaluation', fixed['共通評価7セッション']), ('', fixed['全セッション'])):
        data = {folder: load(base / phase / folder / (name + ext))
                for folder, ext in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('waves', '.json.gz'), ('summaries', '.json'))}
        expected = {key for key in inputs if key[0] in sessions}
        stage_rows(data['sessions'], name, expected, inputs)
        assert set(unique(data['ledgers'], ('session', 'symbol'))) == expected
        assert data['summaries']['id'] == name and data['summaries']['spec'] == spec
        assert data['summaries']['探索固定SHA256'] == design.digest(HERE / '探索条件の固定.json')
        fields = ('symbols',) if phase else ('all_symbols', 'symbols', 'training_symbols')
        for period in fields:
            assert set(data['summaries'][period]) == set(assessment.SYMBOLS)
            assert all(set(v) == independent.PERIOD_FIELDS for v in data['summaries'][period].values())
        if phase:
            assert data['summaries']['phase'] == phase
            close(data['summaries']['symbols'], runner.periods(data['sessions'], sessions), '段階集計')
        assert len(data['waves']) == (0 if phase == 'evaluation' else 8)
        phases[phase] = data
    for folder in ('sessions', 'ledgers', 'waves'):
        assert phases[''][folder] == phases['training'][folder] + phases['evaluation'][folder], '結合時の内容変更'
    summary, rows = phases['']['summaries'], phases['']['sessions']
    for field, sessions in (('all_symbols', fixed['全セッション']), ('symbols', fixed['共通評価7セッション']), ('training_symbols', fixed['選択用6セッション'])):
        close(summary[field], runner.periods(rows, sessions), '全13と初期6と後7の再集計')
    assert summary['全新規一致'] is True and summary['全返済が影以前'] is True
    assert summary['wave_passes'] == sum(r['正方向ネット20分目安達成'] for r in phases['']['waves'])
    return summary, rows, phases['']['ledgers'], phases['']['waves']


def verify_selection(payload: dict, training: dict, fixed: dict, inputs: dict, check) -> dict:
    """機能: 初期専用168資料だけから選択を再算し、後7開始前の固定へ照合する。

    引数: payload/training/fixed/inputs (dict)、check (callable)。返り値: 固定選択 (dict)。
    """
    assert payload['後7再生前'] is True
    cutoff = min(r['start'] for key, r in inputs.items() if key[0] in fixed['共通評価7セッション'])
    close(payload['cutoff'], cutoff, '選択締切')
    check(HERE / '探索条件の固定.json', payload['探索固定SHA256'])
    check(HERE / 'conditional_assessment.py', payload['選択実装SHA256'])
    expected = {f'work/wave_v35/training/sessions/{s["id"]}.json.gz' for s in design.catalog() if s['variant_id'] == 'V000'}
    assert set(payload['選択用SHA256']) == expected
    for name, sha in payload['選択用SHA256'].items():
        check(ROOT / name, sha)
    selection = assessment.select_training(training, cutoff)
    close(selection, payload['選択'], '選択固定の再判定')
    return selection

ACCOUNT_FLAGS = ('全保存数値一致', '全台帳配列一致', '全時価曲線SHA一致', 'ATR全保有行検算',
    '短縮線独立検算', '返却独立検算', '影会計一致', '準備接続検査', '全新規一致', '全退出影以前', '全段階接続一致')
CHECK_COUNTS = ('prefix検査数', '未来価格ATR入口悪化根拠改変数', '買売反射数')


def versioned_body(record: dict, protocol_sha: str) -> dict:
    """機能: 新版で実行した監査だけを認め、旧版比較用の本体を返す。

    引数: record (dict)、protocol_sha (str)。返り値: 版メタデータを除いた監査本体 (dict)。
    """
    assert record['監査版'] == 2 and record['監査固定SHA256'] == protocol_sha
    assert record['旧版実体同値'] is True or record['旧版実体同値'] is None
    return {k: v for k, v in record.items() if k not in ('監査版', '監査固定SHA256', '旧版実体同値')}


def accounting_record(record: dict, summary: dict, rows: list, inputs: dict) -> None:
    """機能: 独立会計の必須全保存値と26入力の個別検査を確認する。

    引数: record/summary/inputs (dict)、rows (list)。返り値: なし (None)。
    """
    assert record['id'] == summary['id'] and record['全入力数'] == 26
    assert record['原本行会計数'] == sum(len(r['last']) for r in inputs.values())
    assert record['台帳SHA256'] == summary['ledger_hash']
    for field in CHECK_COUNTS:
        assert record[field] == 26
    for field in ACCOUNT_FLAGS:
        assert record[field] is True
    assert record['固定A0旧版同値'] == (summary['spec']['width_mode'] == 0)
    index = unique(record['sessions'], ('session', 'symbol'))
    assert set(index) == set(inputs)
    for row in rows:
        key = row['session'], row['symbol']; saved = index[key]
        subset(saved, row, '全session必須項目')
        assert saved['検算した観測行数'] == len(inputs[key]['last'])
        for field in ('prefix検査合格', '未来改変合格', '買売反射合格', '全台帳配列一致',
                      '全時価曲線SHA一致', 'ATR全保有行検算', '短縮線独立検算', '返却独立検算',
                      '影会計一致', '全新規一致', '全退出影以前'):
            assert saved[field] is True
        links = saved['準備起点検査']
        for field in ('準備独立値一致', '約定起点一致', '影新設対応一致'):
            assert links[field] is True
        assert links['新設数'] == links['影新設数']
        assert links['新規起点数'] == row['opening_orders']
    for period in ('all_symbols', 'symbols', 'training_symbols'):
        close(record[period], summary[period], '独立期間会計')


def audit_header(base: Path, specs: list, inputs: dict, fixed: dict, load, check) -> tuple:
    """機能: 全会計監査の固定資料・対象集合と全件数を検査する。

    引数: base (Path)、specs (list)、inputs/fixed (dict)、load/check (callable)。返り値: 全会計と索引 (tuple)。
    """
    audit = load(base / 'accounting_audit.json'); protocol = load(HERE / 'accounting_fixed_v2.json')
    protocol_sha = check(HERE / 'accounting_fixed_v2.json')
    assert audit['監査版'] == 2 and audit['監査固定SHA256'] == protocol_sha
    assert audit['監査規則'] == protocol
    assert audit['合成検査'] == load(HERE / 'accounting_selftest_v2.json') == load(HERE / 'accounting_selftest.json')
    assert audit['合成検査']['合成合格'] is True and audit['合成検査']['合成組合せ数'] == 6
    assert audit['合成検査']['不正拒否数'] == 5
    assert protocol['対象条件ID'] == [s['id'] for s in design.catalog()]
    check(HERE / '探索条件の固定.json', protocol['探索固定SHA256'])
    for name, value in protocol['参照SHA256'].items():
        check(ROOT / name, value)
    assert audit['全監査合格'] is True and audit['対象条件数'] == len(specs)
    count = len(specs) * len(inputs); raw = sum(len(r['last']) for r in inputs.values())
    assert audit['全入力数'] == count and audit['一条件原本行数'] == raw
    assert audit['全原本行会計数'] == raw * len(specs)
    for name in CHECK_COUNTS:
        assert audit[name] == count
    for name in ACCOUNT_FLAGS:
        assert audit[name] is True
    assert audit['固定A0旧版同値条件数'] == sum(s['width_mode'] == 0 for s in specs)
    assert audit['参照SHA256'] == fixed['SHA256']
    assert audit['原本78SHA256'] == load(HERE / 'input_causality_before_pnl.json')['原本78SHA256']
    for group in ('参照SHA256', '原本78SHA256'):
        for name, sha in audit[group].items():
            check(ROOT / name, sha)
    check(HERE / '探索条件の固定.json', audit['探索固定SHA256'])
    assert audit['API取得数'] == 0
    for name in ('現在保存物使用', '成績による対象選別', '規則変更'):
        assert audit[name] is False
    assert audit['補助診断'] == (base != HERE)
    index = unique(audit['条件'], ('id',))
    assert set(index) == {(s['id'],) for s in specs}
    for record in index.values():
        versioned_body(record, protocol_sha)
    assert audit['旧版実体同値条件数'] == sum(r['旧版実体同値'] is True for r in index.values())
    return audit, index


def exact_files(base: Path, specs: list) -> None:
    """機能: 全三段階のファイル集合を確認し、足りない又は余分な条件を拒否する。

    引数: base (Path)、specs (list)。返り値: なし (None)。
    """
    for phase in ('training', 'evaluation', ''):
        for folder, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('waves', '.json.gz'), ('summaries', '.json')):
            assert {p.name for p in (base / phase / folder).glob('*' + suffix)} == {s['id'] + suffix for s in specs}, '段階実体集合不一致'
    assert {p.name for p in (base / 'accounting_details').glob('*.json.gz')} == {s['id'] + '.json.gz' for s in specs}


def verify_waves(waves: dict, load, check) -> dict:
    """機能: 全840の全指定波を、別注文会計の6720波と照合する。

    引数: waves (dict)、load/check (callable)。返り値: 波件数 (dict)。
    """
    planned = load(HERE / 'chart_wave_fixed.json'); protocol = load(HERE / 'wave_order_fixed.json')
    audit = load(HERE / 'wave_order_audit.json')
    assert planned['全条件'] == design.catalog() and planned['全指定波'] == design.waves()
    assert protocol['対象'] == [s['id'] for s in design.catalog()]
    for value in (planned, audit):
        assert value['全条件数'] == 840 and value['全指定波数'] == 6720 and value['比較境界数'] == 13440
    assert audit['全合格'] is True and audit['API取得数'] == 0
    assert audit['現在保存物使用'] is False and audit['注文器再生'] is False
    for name in ('注文独立会計一致', '保有時間枚数分一致', '区間内全注文一致'):
        assert audit[name] is True
    check(HERE / 'wave_order_fixed.json', audit['固定SHA256'])
    for group in (planned['参照SHA256'], protocol['SHA256']):
        for name, sha in group.items():
            check(ROOT / name, sha)
    expected = {str(Path(folder) / (name + '.json.gz')) for name in waves for folder in ('ledgers', 'waves')}
    assert set(audit['保存資料SHA256']) == expected
    for name, sha in audit['保存資料SHA256'].items():
        check(HERE / name, sha)
    wave_records(waves, audit['結果'])
    return {'全指定波数': 6720, '境界数': 13440, '注文独立会計一致': True}


def chart_views(mode: str, inputs: dict) -> dict:
    """機能: 初期A0と後期選択を図の表示参照へ機械的に割り当てる。

    引数: mode (str)、inputs (dict)。返り値: 表示キーから固有図への対応 (dict)。
    """
    mapping = {}
    for slot in ('A0', 'MIN', 'POLICY', 'SELECTED'):
        for session, symbol in inputs:
            actual = slot if slot in ('A0', 'MIN') else (mode if slot == 'SELECTED' or session in design.SESSIONS[6:] else 'A0')
            mapping[f'{slot}|{session}|{symbol}'] = f'H019__{actual}__V000|{session}|{symbol}'
    assert len(mapping) == 104
    return mapping


def verify_charts(details: dict, selection: dict, inputs: dict, load, check) -> dict:
    """機能: 104表示と52又は78固有図を、約定・状態・図JSONへ結ぶ。

    引数: details/selection/inputs (dict)、load/check (callable)。返り値: 図示件数 (dict)。
    """
    fixed = load(HERE / 'chart_fixed.json'); audit = load(HERE / 'chart_audit.json')
    html_audit = load(HERE / 'chart_data_audit.json'); plots = load(HERE / 'chart_details.json.gz')
    mode = selection['selected_exit_mode_id']; expected = chart_views(mode, inputs)
    count = 78 if mode.startswith('B') else 52
    for value in (audit, html_audit):
        assert value['全図示数'] == 104 and value['固有再生数'] == count
        assert value['API取得数'] == 0 and value['現在保存物使用'] is False
        check(HERE / 'chart_fixed.json', value['固定SHA256'])
    for name in ('全収支一致', '全返済一致', '全台帳一致', '全原本asof一致',
                 '全仮想準備一致', '全実準備一致', '全準備起点一致', '全追跡根拠一致'):
        assert audit[name] is True
    for name in ('表示参照全一致', '全返済一致', '全新規一致', '全仮想準備一致', '全実準備一致',
                 '全準備起点一致', '原本asof列一致', 'ATR価格線の別式計算一致', '全追跡根拠一致', 'ローカルリンク全有効'):
        assert html_audit[name] is True
    assert html_audit['追加売買再生'] is False
    assert audit['選択方式'] == mode and plots['表示参照'] == expected
    for value in (audit, plots):
        check(HERE / '選択固定.json', value['選択固定SHA256'])
        check(HERE / 'chart_fixed.json', value['固定SHA256'])
    for name, sha in fixed['SHA256'].items():
        check(ROOT / name, sha)
    for name, sha in audit['台帳元SHA256'].items():
        check(HERE / name, sha)
    check(HERE / 'chart_data_audit.py')
    path = ROOT / 'アルゴリズム調査/00030_板と両市場による条件付き追跡短縮/５分足と売買.html'
    check(path, html_audit['HTML_SHA256'])
    parser = ChartData(); parser.feed(path.read_text(encoding='utf-8')); payload = json.loads(parser.data)
    assert payload['views'] == expected and payload['selected_mode'] == mode
    assert payload['trace_columns'] == fixed['TRACE_COLUMNS']
    assert payload['preparation_columns'] == fixed['PREPARATION_COLUMNS']
    assert payload['event_columns'] == ['time', *runner.engine.TRAIL_EVENT_COLUMNS]
    plots_index = unique(plots['図'], ('key',)); checked = unique(audit['保存済み収支との比較'], ('key',))
    keys = set(expected.values())
    assert set(payload['cases']) == keys and set(plots_index) == set(checked) == {(k,) for k in keys}
    counts = dict(固有新規件数=0, 固有返済件数=0, 原本asof標本数=0, 固有準備件数=0, 固有追跡進行件数=0)
    ledgers = {}
    for identifier in {k.split('|')[0] for k in keys}:
        ledgers[identifier] = unique(load(HERE / 'ledgers' / (identifier + '.json.gz')), ('session', 'symbol'))
    for key in sorted(keys):
        plot = plots_index[key,]; shown = payload['cases'][key]; verified = checked[key,]
        subset(plot, shown, '図JSON全内容')
        method, session, symbol = key.split('|'); ready = inputs[session, symbol]
        record = ledgers[method][session, symbol]; row = next(r for r in details[method] if r['session'] == session and r['symbol'] == symbol)
        assert plot['全注文'] == record['orders'] and plot['result_fingerprints'] == record['result_fingerprints']
        assert verified['保存値一致'] is True
        trades = np.asarray(record['trades'], float).reshape(-1, 11)
        assert len(shown['trades']) == len(trades) == verified['返済件数']
        for shown_trade, trade in zip(shown['trades'], trades, strict=True):
            begin, end = int(trade[6]), int(trade[7])
            close(shown_trade[:7], [float(ready['time_s'][begin]), float(ready['time_s'][end]), *trade[[2, 3, 4, 5]].tolist(),
                float(trade[2] * trade[3] * (trade[5] - trade[4]) * record['config']['point_value'])], '図の全返済')
            assert shown_trade[7] == runner.engine.REASONS[int(trade[9])] and shown_trade[9:] == [begin, end]
        close(shown['net_yen'], row['net_yen'], '図収支'); close(verified['収支円'], row['net_yen'], '図検算収支')
        close(shown['control'], row['control'], '図作用17項目')
        assert verified['新規件数'] == row['opening_orders']
        assert len(shown['events']) == len(record['trail_events']) == verified['追跡進行件数']
        for event, raw in zip(shown['events'], record['trail_events'], strict=True):
            close(event, [float(ready['time_s'][int(raw[0])]), *raw], '図追跡全根拠')
        assert shown['preparations']['shadow'] == shown['preparations']['actual']
        assert len(shown['preparations']['actual']) == len(record['prepare_events'])
        for sample in shown['tracking']:
            reference = int(np.searchsorted(ready['time_s'], sample[0], side='right') - 1)
            assert sample[1] == reference
            if sample[3] == 0:
                assert sample[4:] == [None] * 8
        counts['固有新規件数'] += row['opening_orders']; counts['固有返済件数'] += len(trades)
        counts['原本asof標本数'] += len(shown['tracking']); counts['固有準備件数'] += len(record['prepare_events'])
        counts['固有追跡進行件数'] += len(record['trail_events'])
    subset(html_audit, counts, '図全件数')
    for href in parser.links:
        assert not href.startswith(('http:', 'https:', '//'))
        target = href.split('#', 1)[0]
        assert not target or (path.parent / target).exists()
    return {'全図示数': 104, '固有図示再生数': count, **counts, '全表示参照と台帳一致': True}

def condition_group(base: Path, specs: list, fixed: dict, inputs: dict, load, check) -> tuple:
    """機能: 一群の全段階・独立会計・台帳を逐次照合し、大きな台帳は保持しない。

    引数: base (Path)、specs (list)、fixed/inputs (dict)、load/check (callable)。返り値: 集計・明細・波・件数 (tuple)。
    """
    exact_files(base, specs)
    _, audit_index = audit_header(base, specs, inputs, fixed, load, check)
    summaries = load(base / '全条件の期間集計.json.gz')
    index = unique(summaries, ('id',)); assert set(index) == {(s['id'],) for s in specs}
    details, waves, totals = {}, {}, {'返済脚数': 0, '全注文数': 0}
    for position, spec in enumerate(specs, 1):
        name = spec['id']; summary, rows, ledgers, wave_rows = verify_stages(base, spec, inputs, fixed, load)
        close(index[name,], summary, '全条件集計との一致')
        counts = verify_ledger(ledgers, rows, summary, inputs, fixed)
        for field in totals:
            totals[field] += counts[field]
        record = load(base / 'accounting_details' / (name + '.json.gz'))
        versioned_body(record, check(HERE / 'accounting_fixed_v2.json'))
        accounting_record(record, summary, rows, inputs)
        close(audit_index[name,], {k: v for k, v in record.items() if k not in ('sessions', '保存資料SHA256')}, '独立監査明細と一覧')
        expected = {(base / phase / folder / (name + suffix)).relative_to(ROOT).as_posix()
            for phase in ('training', 'evaluation', '') for folder, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))}
        assert set(record['保存資料SHA256']) == expected
        for path, sha in record['保存資料SHA256'].items():
            check(ROOT / path, sha)
        assert len(wave_rows) == 8 and all(w['method'] == name for w in wave_rows)
        details[name], waves[name] = rows, wave_rows
        if spec['variant_id'] == 'R000' and spec['exit_mode_id'] in ('A0', 'MIN'):
            original = load(base / 'ledgers' / (spec['base_id'] + '.json.gz'))
            assert ledgers == original, '条件不使用R000が基準と不一致'
        if base != HERE:
            import wave_order_audit as wave_audit
            by_key = unique(ledgers, ('session', 'symbol')); accounts = {}
            for wave in wave_rows:
                key = wave['session'], wave['symbol']
                if key not in accounts:
                    accounts[key] = wave_audit.reconstruct(inputs[key], by_key[key])
                wave_audit.measure(inputs[key], by_key[key], wave, accounts[key])
        if position % 60 == 0:
            print(f'完備照合 {base.name} {position}/{len(specs)}', flush=True)
    return summaries, details, waves, totals


def supplementary_summary(record: dict, specs: list, main_index: dict, extra_index: dict, mode: str) -> None:
    """機能: 全乱数64本と反転1本を全保存値から再集計し、最良差替を認めない。

    引数: record/main_index/extra_index (dict)、specs (list)、mode (str)。返り値: なし (None)。
    """
    assert record['適用'] == bool(specs) and record['条件数'] == len(specs)
    assert record['全入力数'] == len(specs) * 26 and record['全波数'] == len(specs) * 8
    assert record['条件IDs'] == [s['id'] for s in specs]
    assert record['採用変更'] is False and record['正式p値'] is False
    if not specs:
        assert record['集計'] == {} and record['基準seed0 ID'] is None
        return
    assert mode.startswith('B') and len(specs) == 64
    assert {s['random_seed'] for s in specs} == {None, *range(1, 64)}
    assert sum(s['reverse_deterioration'] for s in specs) == 1
    base = main_index[f'H019__{mode}__V000',]
    seed0 = main_index[f'H019__{mode}__R000',]
    assert record['基準seed0 ID'] == seed0['id']
    randoms = [seed0] + [extra_index[s['id'],] for s in specs if s['random_seed'] is not None]
    reversed_value = extra_index[next(s['id'] for s in specs if s['reverse_deterioration']),]
    assert len({s['id'] for s in randoms}) == 64
    expected = {}
    for period in ('all_symbols', 'symbols'):
        expected[period] = {}
        for symbol in assessment.SYMBOLS:
            source = base[period][symbol]; nets = [s[period][symbol]['net_yen'] for s in randoms]
            expected[period][symbol] = {'元条件': source, '乱数64収支中央値円': float(np.median(nets)),
                '乱数64収支最小円': min(nets), '乱数64収支最大円': max(nets),
                '元条件より黒字額が大きい本数': sum(v > source['net_yen'] + 1e-6 for v in nets),
                '元条件と同じ収支本数': sum(abs(v - source['net_yen']) <= 1e-6 for v in nets),
                '反転条件': reversed_value[period][symbol],
                '乱数全64': [{'id': s['id'], '成績': s[period][symbol]} for s in randoms]}
    close(record['集計'], expected, '乱数全64分布')


def verify_amendment(load, check) -> dict:
    """機能: 保存失敗の旧証跡と、保存表現だけ修正後の全初期資料一致を確認する。

    引数: load/check (callable)。返り値: 修正の範囲 (dict)。過去証跡は書き換えない。
    """
    archive = HERE / 'attempt_01'
    initial = load(HERE / '保存形式修正の記録.json'); repeated = load(HERE / '保存形式修正の再検算.json')
    for key, value in initial.items():
        if key not in ('再実行後照合', '全初期840資料バイト一致'):
            close(repeated[key], value, '保存修正記録の不変')
    assert repeated['保存形式のみ修正'] is True and repeated['再実行後照合'] is True
    assert repeated['全初期840資料バイト一致'] is True
    for field in ('売買条件変更', '判定変更', '入力変更', '初回選択', '初回後半再生', '初回結果数値の閲覧'):
        assert repeated[field] is False
    assert repeated['初回前6計算済条件数'] == 840 and repeated['初回完成集計数'] == 0
    assert set(repeated['旧初期840資料SHA256']) == {s['id'] + '.json.gz' for s in design.catalog()}
    check(archive / '探索条件の固定.json', repeated['旧探索固定SHA256'])
    check(HERE / '探索条件の固定.json', repeated['新探索固定SHA256'])
    check(archive / 'conditional_runner.py', repeated['旧実装SHA256'])
    check(HERE / 'conditional_runner.py', repeated['新実装SHA256'])
    old = load(archive / '探索条件の固定.json'); new = load(HERE / '探索条件の固定.json')
    assert {k: v for k, v in old.items() if k not in ('固定日時', 'SHA256')} == {k: v for k, v in new.items() if k not in ('固定日時', 'SHA256')}
    changed = sorted(name for name in old['SHA256'] if old['SHA256'][name] != new['SHA256'][name])
    assert changed == repeated['変更実装'] == ['work/wave_v35/conditional_runner.py', 'work/wave_v35/runner_synthetic_audit.py']
    assert set(old['SHA256']) == set(new['SHA256'])
    for path, sha in repeated['旧初期840資料SHA256'].items():
        check(archive / 'training/sessions' / path, sha); check(HERE / 'training/sessions' / path, sha)
    failed = load(archive / '主再生の起動証跡.json')['実行'][-1]
    assert failed['完了'] is False and failed.get('主再生済', False) is False
    assert failed['探索固定SHA256'] == repeated['旧探索固定SHA256']
    assert not (archive / '選択固定.json').exists()
    assert not list((archive / 'training/summaries').glob('*.json'))
    for name in ('起動前監査.json', 'runner_synthetic_audit.json', 'runner_synthetic_audit.py', 'serialization_amendment.py'):
        path = archive / name if name != 'serialization_amendment.py' else HERE / name
        check(path)
    return {'失敗起動保存': True, '保存表現のみ修正': True, '初期840内容不変': True}


def verify_accounting_revision(load, check) -> dict:
    """機能: 速度改訂の同一検査・全件新版・全旧完了実体の同値を独立に検算する。

    引数: load/check (callable)。返り値: 改訂の接続結果 (dict)。
    採否・売買の変更を認めず、旧未完監査を全完了へ読み替えない。
    """
    plan = load(HERE / 'accounting_revision_plan.json')
    revision = load(HERE / 'accounting_revision.json')
    assert all(revision[name] == value for name, value in plan.items())
    assert revision['改訂完了'] is True and revision['混在なし'] is True
    assert revision['主新版完了条件数'] == 840 and revision['補助新版完了条件数'] == 64
    for field in ('売買条件変更', '入力変更', '成績変更', '採否基準変更', '監査対象変更', '検査閾値変更'):
        assert revision[field] is False
    assert revision['全840を新版で再実施'] is True and revision['旧版全監査完了ではない'] is True
    check(HERE / 'accounting_performance_revision.py', revision['記録実装SHA256'])
    for name, sha in revision['参照SHA256'].items():
        check(ROOT / name, sha)
    stopped = load(HERE / 'accounting_v1_stop.json')
    assert stopped['停止確認'] is True and stopped['旧監査全件完了ではない'] is True
    assert stopped['検査エラーによる停止'] is False

    # ----------------------------------------
    # 旧規則は保存し、新版でも対象・許容誤差・全検査本文を維持する。
    old = load(HERE / 'accounting_fixed.json'); new = load(HERE / 'accounting_fixed_v2.json')
    old_sha = check(HERE / 'accounting_fixed.json', revision['旧監査固定SHA256'])
    new_sha = check(HERE / 'accounting_fixed_v2.json', revision['新監査固定SHA256'])
    assert {k: new[k] for k in old if k not in ('固定日時', '参照SHA256')} == {
        k: v for k, v in old.items() if k not in ('固定日時', '参照SHA256')}
    assert new['監査版'] == 2 and new['全件再実施'] is True and new['旧監査固定SHA256'] == old_sha
    assert all(new[field] is False for field in ('監査対象変更', '検査閾値変更', '売買条件変更'))
    assert all(new['参照SHA256'][k] == v for k, v in old['参照SHA256'].items())
    for name, sha in new['参照SHA256'].items():
        check(ROOT / name, sha)
    for name, sha in revision['旧監査実装SHA256'].items():
        check(HERE / name, sha); check(HERE / 'accounting_v1' / name, sha)
    for name in ('accounting_fixed.json', 'accounting_selftest.json'):
        check(HERE / 'accounting_v1' / name, check(HERE / name))
    assert load(HERE / 'accounting_selftest_v2.json') == load(HERE / 'accounting_selftest.json')
    comparison = load(HERE / 'comparison_equivalence.json')
    assert comparison['全判定一致'] is True and comparison['比較数'] == 1260
    for field in ('NaN位置', '無限大符号', '形状型', '基準側rtol', '低精度旧比較委譲', '空配列とscalar'):
        assert comparison[field] is True
    assert comparison['旧ファイル変更'] is False and comparison['売買条件変更'] is False
    build = load(HERE / 'reconstruction_vectorized_build.json')
    reconstructed = load(HERE / 'reconstruction_vectorized_audit.json')
    assert build['逆置換本文完全一致'] is True and build['全assert同一'] is True and build['assert数'] == 22
    assert build['旧コード変更'] is False and build['売買エンジンへの依存'] is False
    assert reconstructed['全合格'] is True and reconstructed['人工完全一致数'] == 76 and reconstructed['破損同拒否数'] == 14
    for field in ('全集計値完全一致', '全現金保有時価実現列完全一致', '未返済接頭辞検査', '無約定検査', '旧コード不変'):
        assert reconstructed[field] is True
    assert reconstructed['API取得数'] == 0 and reconstructed['現在保存物読取'] is False
    check(HERE / 'accounting_reconstruction_vectorized.py', build['新独立会計SHA256'])
    assert reconstructed['新独立会計SHA256'] == build['新独立会計SHA256']

    # ----------------------------------------
    # 切替前の15件と旧全完了件をそれぞれ実体まで確認し、版混在を拒否する。
    probe = load(HERE / 'performance_probe_equivalence.json')
    check(HERE / 'performance_probe_equivalence.json', revision['既15同値成果SHA256'])
    assert probe['全値同一'] is True and probe['条件数'] == 15 and probe['入力数'] == 390
    assert probe['監査固定SHA256'] == new_sha
    expected_probe = {s['id'] for s in design.catalog()[:15]}
    assert set(probe['対象ID']) == expected_probe and len(probe['対象ID']) == 15
    relocation = revision['旧参照移設対応']
    archived = revision['旧完了実体SHA256']
    assert set(relocation.values()) == set(archived)
    assert len(relocation) == len(set(relocation.values())) == revision['旧完了条件数']
    assert {Path(p).name.removesuffix('.json.gz') for p in archived} == set(revision['旧完了条件IDs'])
    assert len(revision['旧完了条件IDs']) == len(archived)
    assert set(probe['旧版SHA256']) <= set(relocation)
    assert {Path(p).name.removesuffix('.json.gz') for p in probe['新版SHA256']} == expected_probe
    assert {Path(p).name.removesuffix('.json.gz') for p in probe['旧版SHA256']} == expected_probe
    for name, sha in probe['旧版SHA256'].items():
        old_path = ROOT / relocation[name]; check(old_path, sha)
        new_path = HERE / 'performance_probe/accounting_details' / old_path.name
        check(new_path, probe['新版SHA256'][new_path.relative_to(ROOT).as_posix()])
        newer = load(new_path)
        assert newer['旧版実体同値'] is True and versioned_body(newer, new_sha) == load(old_path)
    proof = load(HERE / 'accounting_v1_equivalence.json')
    check(HERE / 'accounting_v1_equivalence.json', revision['全既完了同値成果SHA256'])
    assert proof['全既完了同値'] is True and proof['条件数'] == len(archived) and proof['入力数'] == len(archived) * 26
    rows = unique(proof['条件'], ('id',))
    assert set(rows) == {(name,) for name in revision['旧完了条件IDs']}
    for name, sha in archived.items():
        old_path = ROOT / name; check(old_path, sha)
        old_record = load(old_path); newer_path = HERE / 'accounting_details' / old_path.name
        row = rows[old_record['id'],]
        assert row['全値同一'] is True and row['旧実体'] == name and row['旧SHA256'] == sha
        assert row['新実体'] == newer_path.relative_to(ROOT).as_posix()
        check(newer_path, row['新SHA256'])
        newer = load(newer_path)
        assert newer['旧版実体同値'] is True and versioned_body(newer, new_sha) == old_record
    assert load(HERE / 'accounting_audit.json')['旧版実体同値条件数'] == len(archived)
    assert load(HERE / 'supplementary/accounting_audit.json')['旧版実体同値条件数'] == 0
    return {'監査版': 2, '比較1260同判定': True, '旧15全値同一': True,
        '旧完了全値同一条件数': len(archived), '全件新版再実施': True, '採否変更': False}


def collect() -> dict:
    """機能: 全主条件・初期選択・補助条件と全監査を結び、前後指紋を確認する。

    引数: なし。返り値: 完備結果 (dict)。注文器を再生せず、採否基準は変更しない。
    """
    prior = run_verified.verify_sources(); hashes = dict(prior['SHA256'])
    def check(path: Path, expected: str | None = None) -> str:
        """機能: 読み取る資料の指紋を結合し、途中改変と固定不一致を拒否する。

        引数: path (Path)、expected (str|None)。返り値: SHA256 (str)。
        """
        path = path.resolve(); name = path.relative_to(ROOT).as_posix()
        actual = design.digest(path)
        assert expected is None or actual == expected, '指紋不一致: ' + name
        assert name not in hashes or hashes[name] == actual, '読取り中の変更: ' + name
        hashes[name] = actual
        return actual
    def load(path: Path):
        """機能: 資料の指紋を記録してJSONを読む。

        引数: path (Path)。返り値: 内容 (object)。
        """
        check(path)
        return runner.read(path)
    fixed = load(HERE / '探索条件の固定.json'); specs = design.catalog()
    assert fixed['conditions'] == specs
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    evidence = load(HERE / '主再生の起動証跡.json')['実行'][-1]
    assert evidence['完了'] is True and evidence['実行可能'] is True and evidence['主再生済'] is True
    assert evidence['SHA256'] == prior['SHA256']
    check(HERE / 'run_verified.py', evidence['ガード実装SHA256'])
    check(HERE / 'run_verified_fixed.json', evidence['ガード固定SHA256'])
    startfixed = load(HERE / 'run_verified_fixed.json')
    check(HERE / 'run_verified_test.py', startfixed['拒否検査実装SHA256'])
    check(HERE / 'run_verified_test.json', startfixed['拒否検査SHA256'])
    assert load(HERE / 'run_verified_test.json')['全検査合格'] is True
    check(HERE / '探索条件の固定.json', evidence['探索固定SHA256'])
    check(HERE / '主再生の完了.json', evidence['主再生の完了SHA256'])
    check(HERE / '補助乱数診断.json', evidence['補助診断SHA256'])
    complete = load(HERE / '主再生の完了.json')
    for key, value in {'全条件数': 840, '全入力数': 21840, '全波数': 6720, '前6入力数': 10080, '後7入力数': 11760}.items():
        assert complete[key] == value
    assert complete['API取得数'] == 0 and complete['現在保存物使用'] is False
    check(HERE / '探索条件の固定.json', complete['探索固定SHA256'])
    check(HERE / '選択固定.json', complete['選択固定SHA256'])
    check(HERE / '選択固定.json', evidence['選択固定SHA256'])
    amendment = verify_amendment(load, check)
    accounting_revision = verify_accounting_revision(load, check)
    summaries, details, waves, counts = condition_group(HERE, specs, fixed, inputs, load, check)
    training = {s['id']: load(HERE / 'training/sessions' / (s['id'] + '.json.gz')) for s in specs if s['variant_id'] == 'V000'}
    selection = verify_selection(load(HERE / '選択固定.json'), training, fixed, inputs, check)
    judged = load(HERE / '独立判定.json')
    check(HERE / 'conditional_assessment_fixed.json', judged['独立判定固定SHA256'])
    close({k: v for k, v in judged.items() if k != '独立判定固定SHA256'}, assessment.assess(summaries, details, waves, selection), '全840独立判定')
    import supplementary_diagnostics
    supplement = load(HERE / '補助乱数診断.json')
    for path, field in (('選択固定.json', '選択固定SHA256'), ('探索条件の固定.json', '探索固定SHA256')):
        check(HERE / path, supplement[field])
    extra_specs = supplementary_diagnostics.catalog(selection['selected_exit_mode_id'])
    extra_summaries, extra_counts = [], {'返済脚数': 0, '全注文数': 0}
    if extra_specs:
        extra_summaries, _, _, extra_counts = condition_group(HERE / 'supplementary', extra_specs, fixed, inputs, load, check)
    else:
        for folder in ('sessions', 'ledgers', 'waves', 'summaries', 'accounting_details'):
            assert not list((HERE / 'supplementary' / folder).glob('*.json*'))
    supplementary_summary(supplement, extra_specs, unique(summaries, ('id',)), unique(extra_summaries, ('id',)), selection['selected_exit_mode_id'])
    wave_stats = verify_waves(waves, load, check)
    chart_stats = verify_charts(details, selection, inputs, load, check)
    own = load(HERE / 'completion_guard_fixed.json')
    check(Path(__file__), own['実装SHA256']); check(HERE / 'completion_guard_test.py', own['検査実装SHA256'])
    check(HERE / 'completion_guard_test.json', own['検査SHA256'])
    tests = load(HERE / 'completion_guard_test.json')
    assert tests['全検査合格'] is True and tests['採否条件変更'] is False
    guard_revision = load(HERE / '完備ガード改訂の記録.json')
    assert guard_revision['新実装SHA256'] == own['実装SHA256'] and guard_revision['採否条件変更'] is False
    check(HERE / 'completion_guard_fixed.json', guard_revision['新固定SHA256'])
    preserved = load(HERE / '完備ガード改訂前の保存.json')
    for name, item in preserved['旧資料'].items():
        check(HERE / item['保存先'], item['SHA256'])
    for name, expected in hashes.items():
        assert design.digest(ROOT / name) == expected, '完備監査前後の変更: ' + name
    raw = sum(len(r['last']) for r in inputs.values())
    return {'検証完了': True, '全条件数': 840, '全入力数': 21840, '全指定波数': 6720,
        '全図示数': 104, '固有図示再生数': chart_stats['固有図示再生数'], '全原本行会計数': raw * 840,
        '全返済脚数': counts['返済脚数'], '全注文数': counts['全注文数'], '固定A0旧版同値条件数': 60,
        '初期6のみで選択固定': True, '全新規一致': True, '全退出影以前': True, '全段階保存一致': True,
        '全波': wave_stats, '全図': chart_stats, '保存形式修正': amendment, '独立会計速度改訂': accounting_revision,
        '補助条件数': len(extra_specs), '補助入力数': len(extra_specs) * 26, '補助波数': len(extra_specs) * 8,
        '補助全会計照合': True, '補助全指定波検算': True, '補助返済脚数': extra_counts['返済脚数'],
        '主採用目安ID': judged['主条件採用目安ID'], '参照資料SHA256': hashes,
        'ガード実装SHA256': own['実装SHA256'], 'ガード固定SHA256': design.digest(HERE / 'completion_guard_fixed.json'),
        '採否条件変更': False, 'API取得数': 0, '現在保存物使用': False,
        '確認日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()}


def freeze() -> dict:
    """機能: 完備検査と人工破損拒否を固定する。

    引数: なし。返り値: 固定資料 (dict)。
    """
    value = {'実装SHA256': design.digest(Path(__file__)), '検査実装SHA256': design.digest(HERE / 'completion_guard_test.py'),
        '検査SHA256': design.digest(HERE / 'completion_guard_test.json'), '全主条件数': 840,
        '補助は別集計': True, '採否条件変更': False}
    path = HERE / 'completion_guard_fixed.json'
    if path.exists() and runner.read(path) != value:
        preserved = runner.read(HERE / '完備ガード改訂前の保存.json')
        for name, item in preserved['旧資料'].items():
            assert design.digest(HERE / item['保存先']) == item['SHA256']
        prior = runner.read(HERE / 'completion_guard_fixed_会計高速化対応前.json')
        assert runner.read(path) == prior, '保存した改訂前固定からの一度の接続変更だけを認める'
        runner.save(path, value)
        runner.save(HERE / '完備ガード改訂の記録.json', dict(
            理由='旧会計の全証跡を保存した速度改訂版へ接続。採否・売買・対象・許容誤差は不変。',
            旧実装SHA256=prior['実装SHA256'], 新実装SHA256=value['実装SHA256'],
            旧固定SHA256=design.digest(HERE / 'completion_guard_fixed_会計高速化対応前.json'),
            新固定SHA256=design.digest(path), 採否条件変更=False, 売買条件変更=False,
            対象変更=False, 検査閾値変更=False))
    elif path.exists():
        assert runner.read(path) == value
    else:
        runner.save(path, value)
    return value


def main() -> None:
    """機能: 完備規則を固定し、指定時に全保存資料の照合を実行する。

    引数: --prepare (bool)。返り値: なし (None)。API・売買再生を使わない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args(); freeze()
    if args.prepare:
        print('全840と補助0又は64の完備検査を固定。新損益読取なし。', flush=True)
        return
    result = collect(); runner.save(HERE / '完備監査.json', result)
    print({k: result[k] for k in ('検証完了', '全条件数', '全入力数', '全指定波数', '全図示数', '補助条件数')}, flush=True)


if __name__ == '__main__':
    main()
