"""条件付き追跡全840と選択後補助を、独立全玉会計と因果性で監査する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
from pathlib import Path
import pickle
import socket
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import conditional_audit_helpers as helper
import conditional_inputs as inputs_api
import engine_conditional as ENGINE

legacy = helper.legacy
previous = legacy.previous
read, save, digest = legacy.read, legacy.save, legacy.digest
compare, exact = legacy.compare, legacy.exact
MANAGERS = legacy.MANAGERS
INPUTS, FIXED = {}, {}
DESTINATION = ''
SESSION_FIELDS = (legacy.SESSION_FIELDS - {'gate'}) | {'control', 'exit_pairs', 'completed_at', 'complete'}
PERIOD_FIELDS = (legacy.PERIOD_FIELDS - {'gate'}) | {'control'}


def initialize(destination: str = '') -> None:
    """機能: 固定原本と監査済み入力だけを読み、通信経路を拒否する。

    引数: destination (str) は空又はsupplementary。返り値: なし (None)。
    """
    global INPUTS, FIXED, DESTINATION
    socket.socket.connect = legacy.reject_network
    socket.create_connection = legacy.reject_network
    urllib.request.OpenerDirector.open = legacy.reject_network
    INPUTS = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    FIXED = read(HERE / '探索条件の固定.json')
    inputs_api.initialize(INPUTS)
    assert len(INPUTS) == 26 and len(FIXED['conditions']) == 840
    assert destination in ('', 'supplementary')
    DESTINATION = destination


def columns(spec: dict, key: tuple) -> tuple:
    """機能: 固定された入口・悪化方向・根拠行を銘柄区間別に読む。

    引数: spec (dict)、key (tuple[str,str])。返り値: 3配列 (tuple[ndarray,...])。
    """
    entry = inputs_api.entry(spec['signal_id'], spec['entry_clock_scale'], key)
    direction, source = inputs_api.deterioration(spec['condition_id'], key, spec['random_seed'])
    if spec.get('reverse_deterioration', False):
        direction = -direction
    return entry, direction, source


def fingerprint(result: dict) -> dict:
    """機能: 新しい詳細状態を含む全10配列の形・全内容を指紋化する。

    引数: result (dict)。返り値: 全配列の指紋 (dict)。
    """
    return {name: dict(shape=list(result[name].shape), SHA256=hashlib.sha256(result[name].tobytes()).hexdigest())
            for name in helper.FIELDS}


def ledger_equal(result: dict, saved: dict) -> None:
    """機能: 保存実体の全注文・返済・準備・短縮イベントと全配列SHAを照合する。

    引数: result/saved (dict)。返り値: なし (None)。
    """
    for field, width in (('trades', 11), ('orders', 8), ('cycles', 10), ('prepare_events', 7),
                         ('entry_preparations', 4), ('trail_events', 15)):
        exact(result[field], np.asarray(saved[field], float).reshape(-1, width), '保存実体/' + field)
    exact(result['stats'], np.asarray(saved['stats'], float), '保存実体/stats')
    compare(fingerprint(result), saved['result_fingerprints'], '保存全10指紋')


def totals(rows: list[dict], series: dict, sessions: list[str]) -> dict:
    """機能: 主集計の関数を使わず、独立全行曲線から期間全数値を求める。

    引数: rows (list[dict])、series (dict)、sessions (list[str])。返り値: 両銘柄集計 (dict)。
    """
    members = [r for r in rows if r['session'] in sessions]
    curves = {k: v for k, v in series.items() if k[0] in sessions}
    result = {}
    for symbol in previous.MULT:
        selected = [r for r in members if r['symbol'] == symbol]
        value = previous.period_values(members, curves, symbol)
        value.update({f: sum(r[f] for r in selected) for f in legacy.PARTICIPATION})
        value['retracement'] = legacy.retracement_totals([t for r in selected for t in r['retracements']])
        value['control'] = {f: sum(r['control'][f] for r in selected) for f in helper.CONTROL_FIELDS}
        result[symbol] = {f: value[f] for f in PERIOD_FIELDS}
    return result


def evaluate(spec: dict) -> dict:
    """機能: 一条件の全26入力と前6/後7/結合保存を、会計・価格線・未来で検査する。

    引数: spec (dict)。返り値: 詳細を除いた条件監査値 (dict)。収支で対象を絞らない。
    """
    identifier, destination = spec['id'], HERE / DESTINATION
    paths = [destination / phase / folder / (identifier + suffix)
        for phase in ('training', 'evaluation', '')
        for folder, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))]
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    data = {phase: {folder: read(destination / phase / folder / (identifier + suffix))
        for folder, suffix in (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))}
        for phase in ('training', 'evaluation', '')}
    for folder in ('sessions', 'ledgers'):
        compare(data['training'][folder] + data['evaluation'][folder], data[''][folder], '前後結合/' + folder)
    saved_rows, saved_ledgers, summary = (data[''][name] for name in ('sessions', 'ledgers', 'summaries'))
    targets = {(r['session'], r['symbol']): r for r in saved_rows}
    ledgers = {(r['session'], r['symbol']): r for r in saved_ledgers}
    assert len(saved_rows) == len(saved_ledgers) == len(targets) == len(ledgers) == 26
    assert set(targets) == set(ledgers) == set(INPUTS)
    assert summary['spec'] == spec and summary['id'] == identifier
    assert summary['全新規一致'] is True and summary['全返済が影以前'] is True
    assert summary['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
    rows, series, hasher = [], {}, hashlib.sha256()
    # ----------------------------------------
    # 前段と後段を結合した保存順に、同じ原本を独立して再生・再計算する。
    for stored in saved_ledgers:
        key = (stored['session'], stored['symbol']); ready = INPUTS[key]
        entry, direction, source = columns(spec, key)
        config = MANAGERS.make_config(FIXED['manager'], key[1], ready)
        result = helper.replay(ready, entry, direction, source, config, spec)
        row, reconstructed = previous.session_values(ready, result, config, identifier)
        _, shadow_series = previous.session_values(ready, result['shadow'], config, identifier + '/影')
        row.update(legacy.participation(ready, result))
        row['retracements'] = legacy.retracements(ready, result, reconstructed, config)
        structure = helper.line_structure(ready, direction, source, config, spec, result)
        row['control'], row['exit_pairs'] = helper.control_metrics(ready, config, result, reconstructed, shadow_series, direction, structure)
        row['completed_at'] = float(ready['time_s'][-1])
        row['complete'] = bool(reconstructed['long'][-1] == reconstructed['short'][-1] == 0
            and len(result['cycles']) == len(result['entry_preparations']))
        assert row['complete'] and ready['time_s'][-1] > ready['limit']
        links = legacy.connection.preparation_links(ready, entry, config, result, True)
        if spec['width_mode'] == 0:
            legacy.connection.same_results(result, result['shadow'], helper.FIELDS)
            old = legacy.ENGINE.run(ready, entry, config, detail=True, width_mode=0,
                observed_fill=spec['observed_fill'])
            legacy.connection.same_results(result, old, (*legacy.connection.OLD_FIELDS, *legacy.connection.EXTRA_FIELDS))
        assert set(targets[key]) == SESSION_FIELDS
        compare({name: row[name] for name in SESSION_FIELDS}, targets[key], '独立全session値')
        assert stored['config'] == config
        ledger_equal(result, stored); ledger_equal(result['shadow'], stored['shadow'])
        for name, value in (('prepare_allow_SHA256', result['allow']), ('deterioration_SHA256', direction),
                            ('deterioration_source_SHA256', source), ('curve_SHA256', result['curve'])):
            assert hashlib.sha256(value.tobytes()).hexdigest() == stored[name], name
        hasher.update(str(key).encode('utf-8')); hasher.update(result['trades'].tobytes())
        assert len(result['orders']) == len(np.unique(result['orders'][:, 0])), '一行一約定'
        helper.future_checks(ready, entry, direction, source, config, spec, result)
        helper.reflection(ready, entry, direction, source, config, spec, result)
        row.update(prefix検査合格=True, 未来改変合格=True, 買売反射合格=True, 全台帳配列一致=True,
            全時価曲線SHA一致=True, ATR全保有行検算=True, 短縮線独立検算=True, 返却独立検算=True,
            影会計一致=True, 全新規一致=True, 全退出影以前=True, 準備起点検査=links)
        rows.append(row); series[key] = reconstructed['equity']
    assert hasher.hexdigest() == summary['ledger_hash']
    periods = {}
    for name, session_names in (('all_symbols', FIXED['全セッション']),
        ('symbols', FIXED['共通評価7セッション']), ('training_symbols', FIXED['選択用6セッション'])):
        periods[name] = totals(rows, series, session_names)
        compare(periods[name], summary[name], '独立全期間/' + name)
    for phase, session_names, expected_n in (('training', FIXED['選択用6セッション'], 12),
        ('evaluation', FIXED['共通評価7セッション'], 14)):
        group = data[phase]
        expected_keys = {key for key in INPUTS if key[0] in session_names}
        for folder in ('sessions', 'ledgers'):
            assert len(group[folder]) == expected_n
            assert {(r['session'], r['symbol']) for r in group[folder]} == expected_keys
        assert group['summaries']['id'] == identifier and group['summaries']['spec'] == spec
        assert group['summaries']['phase'] == phase
        assert group['summaries']['探索固定SHA256'] == digest(HERE / '探索条件の固定.json')
        compare(totals(rows, series, session_names), group['summaries']['symbols'], '独立段階集計/' + phase)
    assert before == {name: digest(ROOT / name) for name in before}
    output = dict(id=identifier, 全入力数=26, 原本行会計数=sum(r['検算した観測行数'] for r in rows),
        prefix検査数=26, 未来価格ATR入口悪化根拠改変数=26, 買売反射数=26,
        全保存数値一致=True, 全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True,
        短縮線独立検算=True, 返却独立検算=True, 影会計一致=True, 準備接続検査=True,
        全新規一致=True, 全退出影以前=True, 全段階接続一致=True,
        固定A0旧版同値=spec['width_mode'] == 0, 台帳SHA256=hasher.hexdigest(),
        sessions=rows, 保存資料SHA256=before, **periods)
    save(destination / 'accounting_details' / (identifier + '.json.gz'), output)
    return {k: v for k, v in output.items() if k not in ('sessions', '保存資料SHA256')}


def self_test() -> dict:
    """機能: 人工相場で線再構成・悪化解除・反射・未来影再生成と不正証拠拒否を確認する。

    引数: なし。返り値: 合成検査結果 (dict)。新しい実相場損益は計算しない。
    """
    prices = np.tile(np.array([100., 96., 98., 104., 111., 118., 120., 110., 103., 90., 94., 99.]), 20)
    n = len(prices) + 2
    ready = dict(time_s=np.r_[np.floor(np.arange(n - 2) / 2.) * 10., 1300., 1301.], seq=np.arange(n),
        last=np.r_[prices, prices[-1], prices[-1]], atr=np.full(n, 4.), tick=1., start=-1200.,
        limit=1300., us_open=np.inf, symbol='TOPIX', session='合成Day')
    entry = np.where(np.arange(n) % 51 < 25, 1, -1).astype(np.int8)
    direction = np.where(np.arange(n) % 3 == 0, 0, -entry).astype(np.int8)
    source = np.where(direction != 0, np.maximum(np.arange(n) - 1, 0), -1).astype(np.int64)
    tracking = np.resize(np.array([np.nan, 1., 2., 8., np.inf, -1., 4.]), n)
    manager = read(HERE / '探索条件の固定.json')['manager']
    config = MANAGERS.make_config(manager, 'TOPIX', ready)
    advances, count = 0, 0
    for mode in (0, 1, 2):
        for observed in (False, True):
            spec = dict(width_mode=mode, observed_fill=observed)
            result = helper.replay(ready, entry, direction, source, config, spec, tracking)
            _, series = previous.session_values(ready, result, config, '合成')
            _, shadow_series = previous.session_values(ready, result['shadow'], config, '合成影')
            structure = helper.line_structure(ready, direction, source, config, spec, result, tracking)
            metrics, _ = helper.control_metrics(ready, config, result, series, shadow_series, direction, structure)
            legacy.connection.preparation_links(ready, entry, config, result, True)
            legacy.retracements(ready, result, series, config)
            helper.future_checks(ready, entry, direction, source, config, spec, result, tracking)
            helper.reflection(ready, entry, direction, source, config, spec, result, tracking)
            advances += metrics['conditional_advance_events']; count += 1
            other = helper.replay(ready, entry, -direction, source, config, spec, np.full(n, 50000.))
            legacy.connection.same_results(result['shadow'], other['shadow'], helper.FIELDS)
            exact(result['allow'], other['allow'], '追跡ATRと悪化を変えても影不変')
    assert advances > 0, '追加短縮を実際に発生させる'
    # ----------------------------------------
    # 人工的な証拠破壊が独立検算へ実際に引っかかることを確認する。
    spec = dict(width_mode=2, observed_fill=False)
    result = helper.replay(ready, entry, direction, source, config, spec, tracking)
    rejects = 0
    for field, column in (('conditional_curve', 8), ('conditional_curve', 17), ('trail_events', 6)):
        corrupted = dict(result); corrupted[field] = result[field].copy()
        rows = np.flatnonzero(np.isfinite(corrupted[field][:, column]))
        target = rows[len(rows) // 2]; corrupted[field][target, column] += 100.
        try:
            helper.line_structure(ready, direction, source, config, spec, corrupted, tracking)
        except AssertionError:
            rejects += 1
    assert rejects == 3
    altered_entry = entry.copy(); altered_entry[n // 2:] = 0
    changed = helper.replay(ready, altered_entry, direction, source, config, spec, tracking)
    exact(result['allow'][:n // 2], changed['allow'][:n // 2], '影未来再生成prefix')
    assert not np.array_equal(result['allow'][n // 2:], changed['allow'][n // 2:]), '未来影mask流用を拒否'
    for bad in (np.full(n, n, np.int64), np.full(n, -1, np.int64)):
        try:
            helper.replay(ready, entry, np.ones(n, np.int8), bad, config, spec)
        except ValueError:
            rejects += 1
    assert rejects == 5
    artificial = [dict(retracement_r=r, retracement_yen=r * 100., positive_peak=positive, holding_minutes=1.)
        for r, positive in ((1., False), (2., True), (4., True), (5., True))]
    totals_value = legacy.retracement_totals(artificial)
    assert totals_value['all']['mean_yen'] == totals_value['all']['median_yen'] == 300.
    assert totals_value['positive_peak']['median_yen'] == 400.
    assert legacy.retracement_totals([])['all']['mean_yen'] is None
    return dict(合成合格=True, 合成組合せ数=count, 不正拒否数=rejects, 条件追加進行数=advances,
        全玉会計=True, 全新規影一致=True, 全退出影以前=True, 固定候補毎行更新=True,
        悪化解除後も床維持=True, ATR欠測下限保持=True, 未来影再生成=True, 旧未来mask流用拒否=True,
        同時刻原本順=True, 上下反射=True, 円平均中央値_空集合=True, 新損益読取=False, API取得数=0)


def freeze() -> dict:
    """機能: 全840と結果依存しない補助全分岐の監査対象・計算コードを固定する。

    引数: なし。返り値: 固定記録 (dict)。既存内容が異なれば停止する。
    """
    fixed = read(HERE / '探索条件の固定.json')
    paths = [Path(__file__), HERE / 'conditional_audit_helpers.py', HERE / 'engine_conditional.py',
        HERE / 'conditional_inputs.py', HERE / 'conditional_input_fixed.json', HERE / 'input_causality_before_pnl.json',
        HERE / 'supplementary_design_fixed.json', HERE.parent / 'wave_v34/accounting_audit.py',
        HERE.parent / 'wave_v34/scheduler_audit_helpers.py', HERE.parent / 'wave_v33/accounting_audit_v2.py',
        HERE.parent / 'wave_v30/all_accounting_audit.py', HERE.parent / 'wave_v29/selected_accounting_audit.py']
    value = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 対象条件数=840,
        対象条件ID=[s['id'] for s in fixed['conditions']], 一条件入力数=26,
        対象='全12入口×14方式×5変形。補助は事前固定768分岐から選択済Bに対応する64だけ、別集計。',
        会計='影と実の全原本行を注文現金・在庫・元建値返済から再構成。上限・次行約定・場内完結。',
        作用='準備と全新規の属性・時刻が影と完全一致。全組返済が影以前。全玉数量・金額差を対応照合。',
        価格線='A0と公開At、固定3A0候補、悪化条件時min追加候補、単調線、全短縮イベントと証拠行を別計算。',
        全保存値='前6/後7/結合の全session・ledger・全10配列SHA・全期間値、control17項目、exit_pairs、返却額の円/R平均中央値。',
        因果='全入力37%切断、73%以後価格/入口ATR/追跡ATR/入口/悪化/根拠行変更、上下反射。影maskは毎回再生成。',
        互換='固定A0全60条件は同じ時計・約定設定の旧v34全8配列と一致。新固定影と全10配列同値。',
        件数='主840×26、補助適用時64×26。原本行数は各入力配列長の実合計から求める。',
        制限='成績で対象選別・ルール変更なし。未知収益性・金銭損失上限を保証しない。原本旧版は読取専用、現在API/保存ライブ不使用。',
        参照SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in paths},
        探索固定SHA256=digest(HERE / '探索条件の固定.json'))
    path = HERE / 'accounting_fixed.json'
    if path.exists():
        old = read(path)
        assert {k: v for k, v in value.items() if k != '固定日時'} == {k: v for k, v in old.items() if k != '固定日時'}
        return old
    save(path, value)
    return value


def main() -> None:
    """機能: 結果前合成固定、又は主840/補助64の独立会計を全件実行する。

    引数: --prepare/--synthetic-only/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true'); parser.add_argument('--synthetic-only', action='store_true')
    parser.add_argument('--supplementary', action='store_true'); parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    synthetic = self_test(); save(HERE / 'accounting_selftest.json', synthetic)
    if args.synthetic_only:
        print('人工相場の全玉・価格線・影再生成検査を通過。新損益読取なし。', flush=True); return
    protocol = freeze()
    if args.prepare:
        print('全840及び該当補助64の監査を固定。新損益読取なし。', flush=True); return
    destination = 'supplementary' if args.supplementary else ''
    initialize(destination)
    assert read(HERE / '主再生の完了.json')['全条件数'] == 840
    specs = FIXED['conditions']
    if args.supplementary:
        selection = read(HERE / '選択固定.json')['選択']['selected_exit_mode_id']
        specs = read(HERE / 'supplementary_design_fixed.json')['全分岐'][selection]
        completed = read(HERE / '補助乱数診断.json')
        assert completed['条件数'] == len(specs) and completed['条件IDs'] == [s['id'] for s in specs]
    started = time.perf_counter()
    before = {name: digest(ROOT / name) for name in FIXED['SHA256']}
    assert before == FIXED['SHA256']
    structure = read(HERE / 'input_causality_before_pnl.json')
    assert structure['構造監査合格'] and structure['全監査完了']
    originals = legacy.original_hashes(); assert originals == structure['原本78SHA256']
    output = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize, initargs=(destination,)) as pool:
        futures = {pool.submit(evaluate, spec): spec['id'] for spec in specs}
        for future in as_completed(futures):
            output.append(future.result())
            print(f'{len(output)}/{len(specs)} {futures[future]} 全玉・影・条件線・未来一致', flush=True)
    assert len(output) == len({r['id'] for r in output}) == len(specs)
    assert {r['id'] for r in output} == {s['id'] for s in specs}
    raw_count = sum(len(r['last']) for r in INPUTS.values())
    assert sum(r['原本行会計数'] for r in output) == raw_count * len(specs)
    assert sum(r['固定A0旧版同値'] for r in output) == (0 if args.supplementary else 60)
    assert before == {name: digest(ROOT / name) for name in before}
    assert originals == legacy.original_hashes() and freeze() == protocol
    count = len(specs) * len(INPUTS)
    result = dict(全監査合格=True, 対象条件数=len(specs), 全入力数=count, 一条件原本行数=raw_count,
        全原本行会計数=raw_count * len(specs), prefix検査数=count, 未来価格ATR入口悪化根拠改変数=count, 買売反射数=count,
        全保存数値一致=True, 全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True,
        短縮線独立検算=True, 返却独立検算=True, 影会計一致=True, 準備接続検査=True,
        全新規一致=True, 全退出影以前=True, 全段階接続一致=True, 固定A0旧版同値条件数=sum(r['固定A0旧版同値'] for r in output),
        監査規則=protocol, 合成検査=synthetic, 条件=sorted(output, key=lambda r: r['id']),
        詳細=(destination + '/' if destination else '') + 'accounting_details/{id}.json.gz',
        参照SHA256=before, 原本78SHA256=originals, 探索固定SHA256=digest(HERE / '探索条件の固定.json'),
        API取得数=0, 現在保存物使用=False, 成績による対象選別=False, 規則変更=False,
        補助診断=args.supplementary, 実行秒=time.perf_counter() - started)
    save(HERE / destination / 'accounting_audit.json', result)
    (HERE / destination / 'accounting_audit.md').write_text(
        f'# 条件付き追跡の独立監査\n\n全{len(specs)}条件×26入力の注文会計・全新規の影との一致・全返済が影以前・原本行別の保護線・返却額・三段階保存値が一致。'
        '全件で37%切断・73%未来改変・上下反射を検査し、その都度影を再生成した。原本78と固定実装の前後SHAは不変。API・保存ライブ使用なし。'
        '\n\n機械的実装と会計の確認であり、未知期間の利益を保証するものではない。\n', encoding='utf-8')
    print({k: result[k] for k in ('全監査合格', '対象条件数', '全入力数', '全原本行会計数', '実行秒')}, flush=True)


if __name__ == '__main__':
    main()
