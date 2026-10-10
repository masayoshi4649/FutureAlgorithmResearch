"""全420条件の指定波と参加時間を、同じ再生台帳から選別せず計測する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
V30, V28, OLD = (HERE.parent / item for item in ('wave_v30', 'wave_v28', 'wave_v23'))
sys.path.insert(0, str(HERE))
import episode_participation_design as design
import lag_runner as runner

specification = importlib.util.spec_from_file_location('v31_fixed_wave_metrics', V30 / 'episode_audit.py')
metrics = importlib.util.module_from_spec(specification)
sys.modules[specification.name] = metrics
specification.loader.exec_module(metrics)
INPUTS, FIXED = {}, {}
VARIANTS = ('V000', 'V030', 'V060', 'W030', 'W060')
PAIRS = (('V030', 'V000'), ('W030', 'V000'), ('V030', 'W030'),
         ('V060', 'V000'), ('W060', 'V000'), ('V060', 'W060'))
PARTICIPATION_FIELDS = ('観測分', '買い枚数分', '売り枚数分', '買い保有分', '売り保有分', '保有分', '無建玉分',
                        '初回新規待ち分', '返済後再開待ち分', '最終返済後待ち分', '新規注文数', '新規枚数', '返済枚数',
                        'long_unit_minutes', 'short_unit_minutes', 'opening_orders')


def deny_network() -> None:
    """機能: 親・子処理とも外部通信を禁止する。

    引数: なし。返り値: なし (None)。
    """
    socket.socket.connect = metrics.reject_network
    socket.create_connection = metrics.reject_network
    urllib.request.OpenerDirector.open = metrics.reject_network


def catalog(fixed: dict) -> list[dict]:
    """機能: 損益を参照せず全420の三部IDと実仕様を作る。

    引数: fixed (dict) は探索固定。返り値: 全手法仕様 (list[dict])。
    """
    variants = {row['id']: row for row in fixed['variants']}
    assert set(variants) == set(VARIANTS)
    result = [{'id': signal['id'] + '__' + manager['id'] + '__' + variant,
               'name': signal['name'] + '／' + manager['name'] + '／' + variants[variant]['name'],
               'signal': signal, 'manager': manager, 'variant': variants[variant]}
              for signal in fixed['signals'] for manager in fixed['managers'] for variant in VARIANTS]
    assert sorted(row['id'] for row in result) == sorted(design.freeze()['規則']['全対象'])
    return result


def freeze() -> dict:
    """機能: 全対象と計測実装、参照元の指紋を結果の読取り前に固定する。

    引数: なし。返り値: 固定記録 (dict)。旧ファイルは変更しない。
    """
    rules = design.freeze()
    fixed = runner.read(HERE / '探索条件の固定.json')
    paths = [Path(__file__), HERE / 'episode_participation_fixed.json', HERE / 'episode_participation_design.py',
             HERE / '探索条件の固定.json', HERE / 'lag_runner.py', V30 / 'episode_audit.py',
             V28 / 'engine_context.py', OLD / 'managers.py', OLD / 'research.py', OLD / 'inputs.pkl']
    hashes = {p.relative_to(HERE.parent).as_posix(): runner.digest(p) for p in paths}
    for relative, expected in fixed['SHA256'].items():
        assert runner.digest(HERE.parent / relative) == expected
    record = {'規則': rules['規則'], '対象仕様': catalog(fixed), '参照コードSHA256': hashes,
              '主探索固定SHA256': runner.digest(HERE / '探索条件の固定.json')}
    path = HERE / 'episode_audit_fixed.json'
    if path.exists():
        old = runner.read(path)
        assert {k: v for k, v in old.items() if k != '固定日時'} == record
        return old
    record['固定日時'] = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    runner.save(path, record)
    return record


def worker_init() -> None:
    """機能: 無通信の子処理に固定入力と仕様だけを読む。

    引数: なし。返り値: なし (None)。
    """
    global INPUTS, FIXED
    deny_network()
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FIXED = runner.read(HERE / '探索条件の固定.json')
    assert len(INPUTS) == 26


def arrays(folder: str, signal_id: str, variant: str) -> dict:
    """機能: 変形済み方向をそのまま読み、時間や足を作り直さない。

    引数: folder/signal_id/variant (str)。返り値: 原本行方向の辞書 (dict)。
    """
    with np.load(HERE / folder / f'{signal_id}__{variant}.npz') as archive:
        result = {key: archive['|'.join(key)] for key in INPUTS}
    for key, value in result.items():
        assert value.dtype == np.int8 and len(value) == len(INPUTS[key]['last']) and np.isin(value, [-1, 0, 1]).all()
    if variant == 'V000':
        with np.load(V30 / folder / f'{signal_id}.npz') as original:
            for key in INPUTS:
                np.testing.assert_array_equal(result[key], original['|'.join(key)])
    return result


def account(ready: dict, result: dict, config: dict) -> None:
    """機能: 注文から現金・両在庫・全行時価・DDを再構築する。

    引数: ready/result/config (dict)。返り値: なし (None)。返済価格損益・上限・場末・前行判断も確認する。
    """
    n = len(ready['last'])
    cash, long, short = np.zeros(n), np.zeros(n), np.zeros(n)
    for row, source, _, side, qty, price, _, opening in result['orders']:
        assert 0 <= source < row < n and qty > 0 and qty == int(qty)
        index = int(row)
        cash[index] -= side * qty * price
        if opening:
            (long if side == 1 else short)[index] += qty
        else:
            (short if side == 1 else long)[index] -= qty
    cash, long, short = (np.cumsum(value) for value in (cash, long, short))
    equity = cash + (long - short) * ready['last']
    dd = np.maximum.accumulate(np.maximum.accumulate(np.maximum(equity, 0.)) - equity)
    expected = np.column_stack((equity, long, short, dd, cash, long - short))
    np.testing.assert_allclose(result['curve'][:, [0, 2, 3, 4, 5, 6]], expected, atol=1e-6, rtol=0)
    assert np.all((long >= 0) & (short >= 0) & (long <= config['audit_cap']) & (short <= config['audit_cap']))
    assert long[-1] == short[-1] == 0
    close_row = int(np.searchsorted(ready['time_s'], ready['limit'], side='left')) + 1
    assert not (long[close_row:] + short[close_row:]).any()
    trades = result['trades']
    np.testing.assert_allclose(trades[:, 10], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]), atol=1e-6, rtol=0)
    np.testing.assert_allclose(trades[:, 10].sum(), cash[-1], atol=1e-6, rtol=0)
    assert trades[:, 3].sum() == result['orders'][result['orders'][:, 7] == 0, 4].sum()


def participation(ready: dict, result: dict, state: np.ndarray, main: np.ndarray, own: np.ndarray) -> dict:
    """機能: 保有量・方向状態と三種類の無建玉時間を原本行で測る。

    引数: ready/result (dict)、state/main/own (ndarray)。返り値: 参加時間と枚数 (dict)。
    最終観測以降を延長せず、同時刻行の積分は0とする。
    """
    times, curve, orders = ready['time_s'], result['curve'], result['orders']
    start, end = max(float(ready['start']), float(times[0])), min(float(ready['limit']), float(times[-1]))
    held = curve[:, 2] + curve[:, 3] > 0
    measure = lambda values: metrics.integrate(times, values, start, end)
    active_orders = orders[(times[orders[:, 0].astype(int)] >= start) & (times[orders[:, 0].astype(int)] <= end)]
    flat = ~held
    begins = np.flatnonzero(flat & ~np.r_[False, flat[:-1]])
    ends = np.flatnonzero(flat & ~np.r_[flat[1:], False]) + 1
    gaps = []
    initial = terminal = middle = 0.
    for a, b in zip(begins, ends):
        low = max(start, float(times[a]))
        high = min(end, float(times[b]) if b < len(times) else float(times[-1]))
        if high <= low:
            continue
        minutes = (high - low) / 60
        label = '初回新規待ち' if not held[:a].any() else ('最終返済後待ち' if not held[b:].any() else '返済後再開待ち')
        if label == '初回新規待ち':
            initial += minutes
        elif label == '最終返済後待ち':
            terminal += minutes
        else:
            middle += minutes
        gaps.append({'区分': label, '開始': metrics.stamp(low), '終了': metrics.stamp(high), '分': minutes})
    flat_minutes = measure(flat)
    np.testing.assert_allclose(initial + middle + terminal, flat_minutes, atol=1e-8)
    duration = (end - start) / 60
    np.testing.assert_allclose(measure(held) + flat_minutes, duration, atol=1e-8)
    directional = {name: {label: measure(value == side) for side, label in ((1, '買い分'), (-1, '売り分'), (0, '中立分'))}
                   for name, value in (('入口', state), ('両市場C', main), ('自己S', own))}
    for value in directional.values():
        np.testing.assert_allclose(sum(value.values()), duration, atol=1e-8)
    opening_orders = orders[orders[:, 7] == 1]
    raw_long = metrics.integrate(times, curve[:, 2], float(times[0]), float(times[-1]))
    raw_short = metrics.integrate(times, curve[:, 3], float(times[0]), float(times[-1]))
    return {'観測分': duration, '買い枚数分': measure(curve[:, 2]), '売り枚数分': measure(curve[:, 3]),
            '買い保有分': measure(curve[:, 2] > 0), '売り保有分': measure(curve[:, 3] > 0),
            '保有分': measure(held), '無建玉分': flat_minutes, '初回新規待ち分': initial,
            '返済後再開待ち分': middle, '最終返済後待ち分': terminal, '無建玉区間': gaps,
            '新規注文数': int(np.sum(active_orders[:, 7] == 1)),
            '新規枚数': float(active_orders[active_orders[:, 7] == 1, 4].sum()),
            '返済枚数': float(orders[orders[:, 7] == 0, 4].sum()),
            'long_unit_minutes': raw_long, 'short_unit_minutes': raw_short, 'opening_orders': len(opening_orders),
            'first_entry_min': None if len(opening_orders) == 0 else float((times[int(opening_orders[0, 0])] - ready['start']) / 60.),
            '場末後等の区間外買い枚数分': raw_long - measure(curve[:, 2]),
            '場末後等の区間外売り枚数分': raw_short - measure(curve[:, 3]),
            '方向の時間': directional, '観測行数': len(times)}


def process_signal(signal: dict) -> dict:
    """機能: 一入口35条件を全26区間で再生し波・参加・図用台帳を作る。

    引数: signal (dict)。返り値: 一入口の全計測 (dict)。勝率や収益で対象を減らさない。
    """
    signal_id = signal['id']
    items = [row for row in catalog(FIXED) if row['signal']['id'] == signal_id]
    expected = {row['id']: {(r['session'], r['symbol']): r for r in row['rows']}
                for row in runner.read(HERE / 'sessions' / f'{signal_id}.json.gz')}
    previous = {row['id']: {(r['session'], r['symbol']): r for r in row['rows']}
                for row in runner.read(V30 / 'sessions' / f'{signal_id}.json.gz')}
    rows, wave_rows, ledgers, chart, source_hashes = [], [], [], [], {}
    waves = list(metrics.EPISODES)
    variant_arrays = {}
    for variant in VARIANTS:
        variant_arrays[variant] = [arrays(folder, signal_id, variant) for folder in ('directions', 'contexts', 'contexts_own')]
        for folder in ('directions', 'contexts', 'contexts_own'):
            path = HERE / folder / f'{signal_id}__{variant}.npz'
            source_hashes[path.relative_to(HERE).as_posix()] = runner.digest(path)
    for variant, other in (('V030', 'W030'), ('V060', 'W060')):
        for key in INPUTS:
            a, b = variant_arrays[variant][0][key], variant_arrays[other][0][key]
            # 開放境界では現在entryが0の場合もあるため、W初回非0とV初回非0の一致は要求しない。
            gate = int(np.flatnonzero(a != 0)[0]) if np.any(a != 0) else len(a)
            current = variant_arrays['V000']
            for j in range(3):
                np.testing.assert_array_equal(variant_arrays[other][j][key][:gate], np.zeros(gate, dtype=np.int8))
                np.testing.assert_array_equal(variant_arrays[other][j][key][gate:], current[j][key][gate:])
    for method in items:
        variant, manager = method['variant']['id'], method['manager']
        entry, combined, own = variant_arrays[variant]
        for key, ready in INPUTS.items():
            config = runner.managers.make_config(manager, key[1], ready)
            state, main, self_direction = entry[key], combined[key], own[key]
            context = {'entry': None, 'main': main, 'own': self_direction}[manager['context_source']]
            result = runner.engine.run(ready, state, config, detail=True, context=context)
            account(ready, result, config)
            observed = participation(ready, result, state, main, self_direction)
            actual = runner.research.summarize(result, config, key[1], key[0], method['id'])
            actual['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
            expected_row = expected[method['id']][key]
            new_fields = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders', 'first_entry_min')
            assert actual == {k: v for k, v in expected_row.items() if k not in new_fields}, method['id'] + ':探索集計不一致'
            for field in new_fields:
                if expected_row[field] is None:
                    assert observed[field] is None
                else:
                    np.testing.assert_allclose(observed[field], expected_row[field], atol=1e-7, rtol=0, err_msg=field)
            if variant == 'V000':
                older = dict(previous[signal_id + '__' + manager['id']][key])
                assert {k: v for k, v in actual.items() if k != 'id'} == {k: v for k, v in older.items() if k != 'id'}, 'V000旧集計差'
            rows.append({'id': method['id'], 'signal_id': signal_id, 'manager_id': manager['id'], 'variant_id': variant,
                         'session': key[0], 'symbol': key[1], **observed, '損益': actual})
            orders = metrics.order_records(ready, state, result, runner.engine.REASONS, context)
            if key[0] in {wave['session'] for wave in waves}:
                ledgers.append({'method': method['id'], 'session': key[0], 'symbol': key[1], '全約定': orders})
                for wave in waves:
                    if wave['session'] == key[0]:
                        wave_rows.append(metrics.episode_metrics(method, wave, ready, state, result, orders, config['point_value'], context))
            if signal_id == 'H019':
                changes = np.flatnonzero(np.r_[True, (state[1:] != state[:-1]) | (main[1:] != main[:-1]) | (self_direction[1:] != self_direction[:-1])])
                trade_rows = metrics.trade_records(ready, result, config['point_value'])
                chart.append({'method': method['id'], 'session': key[0], 'symbol': key[1], '全返済': trade_rows,
                              '状態': [[float(ready['time_s'][i]), int(state[i]), int(main[i]), int(self_direction[i])] for i in changes],
                              '損益': actual})
        print(method['id'], '26入力の波・参加・会計一致', flush=True)
    boundary_check = metrics.accounting_checks(wave_rows, ledgers)
    assert len(rows) == 910 and len(wave_rows) == 280
    for relative, expected_hash in source_hashes.items():
        assert runner.digest(HERE / relative) == expected_hash
    return {'signal': signal, '手法': items, '参加': rows, '波': wave_rows,
            '境界独立検算': boundary_check, '図示用': chart, '保存方向SHA256': source_hashes,
            '計測固定SHA256': runner.digest(HERE / 'episode_audit_fixed.json')}


def aggregate_participation(values: list[dict]) -> dict:
    """機能: セッション・週・全期間の参加量と対照差を同銘柄内でまとめる。

    引数: values (list[dict])。返り値: 全行・全対照と等重み集計 (dict)。
    """
    sessions = [row for value in values for row in value['参加']]
    methods = [method for value in values for method in value['手法']]
    periods, weeks = [], []
    for method in methods:
        for symbol in ('TOPIX', 'NK225'):
            rows = [row for row in sessions if row['id'] == method['id'] and row['symbol'] == symbol]
            assert len(rows) == 13
            groups = [('全期間', rows)]
            labels = sorted({datetime.fromisoformat(row['session'][:10]).isocalendar()[:2] for row in rows})
            for year, week in labels:
                groups.append((f'{year}-W{week:02d}', [row for row in rows if datetime.fromisoformat(row['session'][:10]).isocalendar()[:2] == (year, week)]))
            for name, members in groups:
                record = {'id': method['id'], 'symbol': symbol, '区間': name, 'セッション数': len(members),
                          **{field: sum(row[field] for row in members) for field in PARTICIPATION_FIELDS},
                          '方向の時間': {source: {label: sum(row['方向の時間'][source][label] for row in members) for label in ('買い分', '売り分', '中立分')} for source in ('入口', '両市場C', '自己S')},
                          '損益': runner.research.aggregate([row['損益'] for row in members])}
                (periods if name == '全期間' else weeks).append(record)
    index = {(row['id'], row['symbol']): row for row in periods}
    differences = []
    for signal in values:
        spec = signal['signal']
        for manager in range(7):
            for newer, baseline in PAIRS:
                for symbol in ('TOPIX', 'NK225'):
                    a = index[(f"{spec['id']}__L{manager:03d}__{newer}", symbol)]
                    b = index[(f"{spec['id']}__L{manager:03d}__{baseline}", symbol)]
                    differences.append({'signal': spec['id'], 'manager': f'L{manager:03d}', 'comparison': newer + '-' + baseline,
                                        'symbol': symbol, 'main_kind': spec['params']['main_kind'],
                                        'philosophy': 'EMA' if spec['params']['main_kind'].startswith('ema') else spec['params']['main_kind'],
                                        **{field + '差': a[field] - b[field] for field in PARTICIPATION_FIELDS},
                                        '収支差円': a['損益']['net_yen'] - b['損益']['net_yen'],
                                        'DD差円': a['損益']['drawdown_yen'] - b['損益']['drawdown_yen']})
    groups = []
    for manager in range(7):
        for a, b in PAIRS:
            for symbol in ('TOPIX', 'NK225'):
                selected = [r for r in differences if r['manager'] == f'L{manager:03d}' and r['comparison'] == a + '-' + b and r['symbol'] == symbol]
                assert len(selected) == 12
                fields = [field + '差' for field in PARTICIPATION_FIELDS] + ['収支差円', 'DD差円']
                family_means = {family: {field: float(np.mean([r[field] for r in selected if r['philosophy'] == family])) for field in fields} for family in sorted({r['philosophy'] for r in selected})}
                assert len(family_means) == 5
                groups.append({'manager': f'L{manager:03d}', 'comparison': a + '-' + b, 'symbol': symbol,
                               '全12入口の中央値': {field: float(np.median([r[field] for r in selected])) for field in fields},
                               '5思想の内部平均': family_means,
                               '5思想等重みの中央値': {field: float(np.median([row[field] for row in family_means.values()])) for field in fields}})
    assert len(sessions) == 10920 and len(differences) == 1008
    return {'セッション': sessions, '週別': weeks, '全期間': periods, '対照差': differences, '等重み集計': groups}


def main() -> None:
    """機能: 全420の一度の再生から指定波・参加対照・図の材料を保存する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。保存済み一入口は指紋照合して再利用する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    deny_network()
    frozen = freeze()
    if args.prepare:
        print('全420の波3360・参加10920・図示H019全35を固定', flush=True)
        return
    fixed = runner.read(HERE / '探索条件の固定.json')
    selected = catalog(fixed)
    for signal in fixed['signals']:
        summary = runner.read(HERE / 'summaries' / (signal['id'] + '.json'))
        assert {c['id'] for c in summary['candidates']} == {m['id'] for m in selected if m['signal']['id'] == signal['id']}
    destination = HERE / 'episode_participation_details'
    destination.mkdir(exist_ok=True)
    values, pending = [], []
    for signal in fixed['signals']:
        path = destination / (signal['id'] + '.json.gz')
        if path.exists():
            value = runner.read(path)
            assert value['計測固定SHA256'] == runner.digest(HERE / 'episode_audit_fixed.json')
            for relative, expected in value['保存方向SHA256'].items():
                assert runner.digest(HERE / relative) == expected
            values.append(value)
        else:
            pending.append(signal)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=worker_init) as pool:
        futures = [pool.submit(process_signal, signal) for signal in pending]
        for future in as_completed(futures):
            value = future.result()
            runner.save(destination / (value['signal']['id'] + '.json.gz'), value)
            values.append(value)
    values.sort(key=lambda row: row['signal']['id'])
    rows = [row for value in values for row in value['波']]
    summaries = [{'method': method['id'], '対象区間数': 8,
                  '目安達成区間数': sum(row['正方向ネット20分目安達成'] for row in rows if row['method'] == method['id']),
                  '正方向保有0区間': [{'wave': row['wave'], 'symbol': row['symbol']} for row in rows if row['method'] == method['id'] and row['正方向ネット保有分'] == 0]} for method in selected]
    assert len(rows) == 3360 and len(summaries) == 420
    assert freeze() == frozen
    runner.save(HERE / 'episode_audit.json', {'固定仕様': frozen, '手法': selected, '結果': rows, '方法別要約': summaries,
                 '境界損益の独立検算': {'全約定からの独立会計一致': True, '比較境界数': sum(v['境界独立検算']['比較境界数'] for v in values)},
                 '全入力数': 10920, '全行独立会計数': sum(row['観測行数'] for value in values for row in value['参加']),
                 '計測固定SHA256': runner.digest(HERE / 'episode_audit_fixed.json'), 'API取得数': 0, 'ルール変更': False,
                 '現在保存物使用': False, '参照コード不変': True, '参照コードSHA256': frozen['参照コードSHA256']})
    participation_result = aggregate_participation(values)
    participation_result.update(固定仕様=frozen, API取得数=0, 現在保存物使用=False)
    runner.save(HERE / 'participation.json', participation_result)
    lines = ['# 方向の鮮度と参加時間', '', '全420条件を選別せず再生。Vは方向遅延、Wは開始待ちだけ。V-WとV000との差を別々に読む。遅延最良を採用しない。', '',
             '|変形|全条件|8波すべて20分達成|', '|---|---:|---:|']
    for variant in VARIANTS:
        subset = [row for row in summaries if row['method'].endswith('__' + variant)]
        lines.append(f"|{variant}|{len(subset)}|{sum(r['目安達成区間数'] == 8 for r in subset)}|")
    lines += ['', '参加の全セッション・週・全期間と1,008対応差は participation.json。数値は同銘柄内の差であり、銘柄の円収支を合算しない。',
              '無建玉時間を初回待ち・返済後再開待ち・最終返済後待ちに分離。方向信号の時間と建玉時間は別に測る。',
              '図示は結果前にH019全35条件へ固定。全26入力の全返済を同じ再生台帳から描画する。', '']
    (HERE / 'episode_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    print('全420の波・参加対照を保存。API 0。', flush=True)


if __name__ == '__main__':
    main()
