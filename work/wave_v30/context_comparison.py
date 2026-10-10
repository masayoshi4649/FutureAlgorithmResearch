"""全84条件のC/S撤回を、最初の注文分岐と連続中立の原因から診断する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import pickle
import socket
import sys
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
V27, V28, OLD = (HERE.parent / name for name in ('wave_v27', 'wave_v28', 'wave_v23'))
import episode_audit as episode
sys.path.insert(0, str(HERE))
import context_split_runner as runner

SYMBOLS = ('TOPIX', 'NK225')
MODES = (('反転', 'L001', 'L002'), ('中立', 'L003', 'L004'), ('併用', 'L005', 'L006'))
CAUSES = ('準備20分不足', 'ATR無効', '自己中立', '相手不一致又は相手方向なし', '中立ではない')


def freeze() -> dict:
    """機能: 実装と参照仕様の指紋を新しい結果を読む前に固定する。

    引数: なし。返り値: 固定記録 (dict)。既存の比較規則は変更しない。
    """
    paths = [Path(__file__), HERE / 'context_comparison_fixed.json', HERE / '探索条件の固定.json',
             HERE / '管理設計の固定.json', HERE / 'context_split_runner.py', HERE / 'episode_audit.py',
             V28 / 'engine_context.py', OLD / 'managers.py', OLD / 'research.py', OLD / 'inputs.pkl']
    hashes = {str(p.relative_to(HERE.parent)): runner.digest(p) for p in paths}
    path = HERE / 'context_comparison_implementation.json'
    if path.exists():
        record = runner.read(path)
        assert record['SHA256'] == hashes, '固定後の実装変更'
        return record
    record = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
              '比較仕様は損益未読で先行固定': True,
              '実装固定前の受領情報': '親から全84完了数とS-C/S-B0中央値の要約を受領。比較規則は変更していない。',
              'SHA256': hashes}
    runner.save(path, record)
    return record


def arrays(path: Path) -> dict:
    """機能: 保存された方向をセッション・銘柄の辞書として読む。

    引数: path (Path)。返り値: 原本行配列の辞書 (dict)。
    """
    assert 'live' not in path.parts
    with np.load(path) as archive:
        return {tuple(k.split('|')): archive[k] for k in archive.files}


def causes(ready: dict, combined: np.ndarray, own: np.ndarray) -> np.ndarray:
    """機能: Cが0になる原因を、判別可能な範囲で相互排他的に分類する。

    引数: ready (dict)、combined/own (ndarray[int8])。返り値: 原因番号 (ndarray[int8])。
    相手の不一致と方向未提供は保存contextだけでは分離せず統合表示する。
    """
    assert np.all((combined == 0) | (combined == own))
    assert np.all(combined[own == 0] == 0)
    result = np.full(len(own), 4, dtype=np.int8)
    result[(combined == 0) & (own != 0)] = 3
    result[own == 0] = 2
    result[~np.isfinite(ready['atr']) | (ready['atr'] <= 0)] = 1
    result[ready['time_s'] < ready['start'] + 1200] = 0
    return result


def segments(ready: dict, codes: np.ndarray, begin: int, end: int, cutoff: float | None = None) -> list[dict]:
    """機能: 原因が変わる境界ごとに連続区間を分解し、経過秒を保存する。

    引数: ready (dict)、codes (ndarray)、begin/end (int)、cutoff (float|None)。
    返り値: 原因別連続区間 (list[dict])。endは排他的、同値時刻は0秒。
    """
    times = ready['time_s']
    terminal = float(times[end]) if end < len(times) else float(times[-1])
    if cutoff is not None:
        terminal = min(terminal, float(cutoff))
    cuts = np.r_[begin, begin + 1 + np.flatnonzero(codes[begin + 1:end] != codes[begin:end - 1]), end]
    output = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        start = float(times[a])
        finish = min(float(times[b]) if b < len(times) else float(times[-1]), terminal)
        if start > terminal:
            break
        output.append({'原因': CAUSES[int(codes[a])], '開始行': int(a), '終了行未満': int(b),
                       '開始seq': int(ready['seq'][a]), '開始': episode.stamp(start),
                       '終了': episode.stamp(max(start, finish)), '秒': max(0., finish - start)})
    return output


def neutral_runs(ready: dict, context: np.ndarray, codes: np.ndarray, result: dict) -> list[dict]:
    """機能: 保有中の連続0時計を原因交代でも切らず再構成する。

    引数: ready/result (dict)、context/codes (ndarray)。返り値: 連続中立と判断時原因内訳 (list[dict])。
    返済後は時計を解除する。注文器内部値を直接観測した記録ではない。
    """
    curve, times = result['curve'], ready['time_s']
    active = (curve[:, 2] + curve[:, 3] > 0) & (context == 0)
    starts = np.flatnonzero(active & ~np.r_[False, active[:-1]])
    ends = np.flatnonzero(active & ~np.r_[active[1:], False]) + 1
    output = []
    neutral_orders = result['orders'][result['orders'][:, 6] == 10]
    for begin, end in zip(starts, ends):
        pieces = segments(ready, codes, int(begin), int(end))
        selected = neutral_orders[(neutral_orders[:, 1] >= begin) & (neutral_orders[:, 1] < end)]
        decisions = []
        for order in selected:
            source = int(order[1])
            age = float(times[source] - times[begin])
            assert age >= 600. - 1e-8, '10分より前の中立返済'
            decisions.append({'判断行': source, '約定行': int(order[0]), '時計秒': age,
                              '判断までの原因区間': segments(ready, codes, int(begin), source + 1, float(times[source]))})
        output.append({'開始行': int(begin), '終了行未満': int(end), '開始': episode.stamp(times[begin]),
                       '秒': sum(p['秒'] for p in pieces), '原因交代数': max(0, len(pieces) - 1),
                       '原因区間': pieces, '中立返済判断': decisions})
    return output


def order_record(order: np.ndarray | None, ready: dict, combined: np.ndarray, own: np.ndarray) -> dict | None:
    """機能: 分岐時の一注文を、元判断行と二つの管理方向つきで表示する。

    引数: order (ndarray|None)、ready (dict)、combined/own (ndarray)。返り値: 注文記録 (dict|None)。
    """
    if order is None:
        return None
    fill, source = int(order[0]), int(order[1])
    assert source < fill
    return {'約定行': fill, '約定seq': int(ready['seq'][fill]), '約定時刻': episode.stamp(ready['time_s'][fill]),
            '判断行': source, '判断時刻': episode.stamp(ready['time_s'][source]), '判断C': int(combined[source]),
            '判断S': int(own[source]), '方向': int(order[3]), '枚数': int(order[4]), '価格': float(order[5]),
            '理由': int(order[6]), '新規': bool(order[7])}


def neutral_clock(ready: dict, context: np.ndarray, codes: np.ndarray, curve: np.ndarray, row: int) -> dict:
    """機能: 共通状態から分岐する直前の中立時計を原本行で再構成する。

    引数: ready (dict)、context/codes/curve (ndarray)、row (int)。返り値: 時計と原因区間 (dict)。
    内部変数の直接読取りではなく、保有と連続0からの再構成である。
    """
    if row < 0 or context[row] != 0 or curve[row, 2] + curve[row, 3] <= 0:
        return {'作動中': False, '時計秒': 0., '原因区間': []}
    start = row
    while start > 0 and context[start - 1] == 0 and curve[start - 1, 2] + curve[start - 1, 3] > 0:
        start -= 1
    return {'作動中': True, '開始行': start, '時計秒': float(ready['time_s'][row] - ready['time_s'][start]),
            '原因区間': segments(ready, codes, start, row + 1, float(ready['time_s'][row]))}


def first_divergence(ready: dict, combined: np.ndarray, own: np.ndarray, left: dict, right: dict) -> dict:
    """機能: 共通注文prefixの後で最初に違う原本行を特定する。

    引数: ready/left/right (dict)、combined/own (ndarray)。返り値: 最初の分岐と共通保有 (dict)。
    後続の組番号や異なる時点の玉を対応させない。
    """
    a, b = left['orders'], right['orders']
    shared = min(len(a), len(b))
    differences = np.flatnonzero(np.any(a[:shared] != b[:shared], axis=1))
    prefix = int(differences[0]) if len(differences) else shared
    if prefix == len(a) == len(b):
        return {'注文台帳同一': True, '共通注文数': prefix, '金銭経路同一': bool(np.array_equal(left['curve'][:, :7], right['curve'][:, :7]))}
    next_a = a[prefix] if prefix < len(a) else None
    next_b = b[prefix] if prefix < len(b) else None
    row = min(int(order[0]) for order in (next_a, next_b) if order is not None)
    np.testing.assert_array_equal(left['curve'][:row, :7], right['curve'][:row, :7])
    prior = left['curve'][row - 1] if row else np.zeros(8)
    codes = causes(ready, combined, own)
    return {'注文台帳同一': False, '共通注文数': prefix, '最初の分岐行': row, '最初の分岐seq': int(ready['seq'][row]),
            '時刻': episode.stamp(ready['time_s'][row]), '分岐直前まで現金保有時価同一': True,
            '直前共通状態': {'買い枚数': float(prior[2]), '売り枚数': float(prior[3]), '現金': float(prior[5]),
                            'ネット枚数': float(prior[6]), '時価': float(prior[0])},
            '同じ分岐行のC注文': order_record(next_a if next_a is not None and next_a[0] == row else None, ready, combined, own),
            '同じ分岐行のS注文': order_record(next_b if next_b is not None and next_b[0] == row else None, ready, combined, own),
            '分岐直前のC中立時計': neutral_clock(ready, combined, codes, left['curve'], row - 1),
            '分岐直前のS中立時計': neutral_clock(ready, own, codes, right['curve'], row - 1),
            '解釈': '注文履歴と固定機構からの原因説明。非共通となった後のcampaign番号は対応させない。'}


def accounting(ready: dict, result: dict, config: dict) -> None:
    """機能: 約定注文だけから全原本行の現金・両保有・時価・DDを独立に再構成する。

    引数: ready/result/config (dict)。返り値: なし (None)。上限・先取り・場末の残玉も検算する。
    """
    n = len(ready['last'])
    orders, curve = result['orders'], result['curve']
    cash, long, short = np.zeros(n), np.zeros(n), np.zeros(n)
    for order in orders:
        row, source, side, qty, price, opening = int(order[0]), int(order[1]), int(order[3]), order[4], order[5], bool(order[7])
        assert 0 <= source < row
        cash[row] -= side * qty * price
        if opening:
            (long if side == 1 else short)[row] += qty
        else:
            (short if side == 1 else long)[row] -= qty
    cash, long, short = (np.cumsum(value) for value in (cash, long, short))
    equity = cash + (long - short) * ready['last']
    high = np.maximum.accumulate(np.maximum(equity, 0))
    dd = np.maximum.accumulate(high - equity)
    np.testing.assert_allclose(curve[:, [0, 2, 3, 4, 5, 6]], np.column_stack((equity, long, short, dd, cash, long - short)), atol=1e-6, rtol=0)
    assert min(long.min(), short.min()) >= 0 and max(long.max(), short.max()) <= config['audit_cap']
    assert long[-1] == short[-1] == 0
    trades = result['trades']
    np.testing.assert_allclose(trades[:, 10], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]), atol=1e-6, rtol=0)
    np.testing.assert_allclose(trades[:, 10].sum(), cash[-1], atol=1e-6, rtol=0)
    assert trades[:, 3].sum() == orders[orders[:, 7] == 0, 4].sum()
    closing = int(np.searchsorted(ready['time_s'], ready['limit'], side='left'))
    if closing + 1 < n:
        assert np.all(long[closing + 1:] == 0) and np.all(short[closing + 1:] == 0)


def activity(ready: dict, result: dict) -> dict:
    """機能: 保有時間・枚数時間と撤回後の新規までの空白を数える。

    引数: ready/result (dict)。返り値: 機会と参加量の記録 (dict)。
    """
    times, curve, orders = ready['time_s'], result['curve'], result['orders']
    weights = np.maximum(0., np.diff(times)) / 60
    opens = orders[orders[:, 7] == 1]
    withdrawals = orders[np.isin(orders[:, 6], [10, 13])]
    gaps = []
    for order in withdrawals:
        later = opens[opens[:, 0] > order[0]]
        gaps.append({'返済行': int(order[0]), '次新規行': int(later[0, 0]) if len(later) else None,
                     '空白分': float((times[int(later[0, 0])] - times[int(order[0])]) / 60) if len(later) else None})
    return {'買い枚数分': float(np.sum(weights * curve[:-1, 2])), '売り枚数分': float(np.sum(weights * curve[:-1, 3])),
            '保有分': float(np.sum(weights * (curve[:-1, 2] + curve[:-1, 3] > 0))), '新規数': len(opens),
            '撤回返済数': len(withdrawals), '撤回後の再新規': gaps}


def process_signal(spec: dict, fixed: dict, inputs: dict) -> dict:
    """機能: 同一入口の7管理を全26入力で再生し、分岐と原因を一度に記録する。

    引数: spec/fixed/inputs (dict)。返り値: 全管理集計と全C/S分岐 (dict)。
    """
    signal_id = spec['id']
    state = arrays(HERE / 'directions' / f'{signal_id}.npz')
    combined = arrays(HERE / 'contexts' / f'{signal_id}.npz')
    own = arrays(HERE / 'contexts_own' / f'{signal_id}.npz')
    original = arrays(V27 / 'directions' / f'{signal_id}.npz')
    c_original = arrays(V28 / 'contexts' / f'{signal_id}.npz')
    own_id = fixed['own_signals'][signal_id]['id']
    s_original = arrays(V28 / 'contexts' / f'{own_id}.npz')
    rows_by_id = {manager['id']: [] for manager in fixed['managers']}
    fingerprints = {manager['id']: {symbol: {field: hashlib.sha256() for field in ('orders', 'trades', 'money')}
                                    for symbol in SYMBOLS} for manager in fixed['managers']}
    saved = {item['id']: {(r['session'], r['symbol']): r for r in item['rows']}
             for item in runner.read(HERE / 'sessions' / f'{signal_id}.json.gz')}
    all_rows, comparisons, exposures = [], [], []
    for key, ready in inputs.items():
        assert np.all(np.isfinite(ready['last'])) and np.all(ready['last'] > 0)
        for actual, expected in ((state[key], original[key]), (combined[key], c_original[key]), (own[key], s_original[key])):
            np.testing.assert_array_equal(actual, expected)
        codes = causes(ready, combined[key], own[key])
        exposures.append({'session': key[0], 'symbol': key[1], '原因区間': segments(ready, codes, 0, len(codes))})
        results = {}
        for manager in fixed['managers']:
            identifier = signal_id + '__' + manager['id']
            config = runner.managers.make_config(manager, key[1], ready)
            context = None if manager['context_source'] == 'entry' else (combined[key] if manager['context_source'] == 'main' else own[key])
            result = runner.engine.run(ready, state[key], config, True, context=context)
            accounting(ready, result, config)
            for field, array in [('orders', result['orders']), ('trades', result['trades']), ('money', result['curve'][:, :7])]:
                fingerprints[manager['id']][key[1]][field].update(str(key).encode())
                fingerprints[manager['id']][key[1]][field].update(array.tobytes())
            row = runner.research.summarize(result, config, key[1], key[0], identifier)
            row['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
            assert row == saved[identifier][key], identifier + ':保存集計不一致'
            rows_by_id[manager['id']].append(row)
            runs = neutral_runs(ready, state[key] if context is None else context, codes, result) if context is not None else []
            all_rows.append({'id': identifier, 'session': key[0], 'symbol': key[1], **activity(ready, result),
                             '連続中立': runs, '保存損益': row, '観測行数': len(ready['last']), '独立会計一致': True})
            results[manager['id']] = result
        for mode, c_id, s_id in MODES:
            record = first_divergence(ready, combined[key], own[key], results[c_id], results[s_id])
            comparisons.append({'signal': signal_id, 'mode': mode, 'session': key[0], 'symbol': key[1], **record})
        print(signal_id, key[0], key[1], '7管理の会計・中立・分岐一致', flush=True)
    totals = {manager_id: runner.diagnostics(rows) for manager_id, rows in rows_by_id.items()}
    saved_totals = {row['manager_id']: row['symbols'] for row in runner.read(HERE / 'summaries' / f'{signal_id}.json')['candidates']}
    assert totals == saved_totals, '全期間集計の不一致'
    hashes = {manager_id: {symbol: {field: value.hexdigest() for field, value in hashes.items()}
                           for symbol, hashes in by_symbol.items()} for manager_id, by_symbol in fingerprints.items()}
    return {'signal': spec, '全管理の集計': totals, '全区間の参加と中立': all_rows,
            '最初のCS分岐': comparisons, '保有に無関係なcontext原因': exposures, '銘柄別の全13区間指紋': hashes}


def summarize(values: list[dict]) -> dict:
    """機能: 12入口を等重みでS-C/S-B0/C-B0の期間差へ整理する。

    引数: values (list[dict]) は全入口の診断。返り値: 216対応差とモード別集計 (dict)。
    """
    pairs = []
    for value in values:
        signal = value['signal']
        for mode, c_id, s_id in MODES:
            for comparison, added, baseline in [('S-C', s_id, c_id), ('S-B0', s_id, 'L000'), ('C-B0', c_id, 'L000')]:
                for symbol in SYMBOLS:
                    own, ref = value['全管理の集計'][added][symbol], value['全管理の集計'][baseline][symbol]
                    a_hash = value['銘柄別の全13区間指紋'][added][symbol]
                    b_hash = value['銘柄別の全13区間指紋'][baseline][symbol]
                    activities = {}
                    for field in ('買い枚数分', '売り枚数分', '保有分', '新規数', '撤回返済数'):
                        a_total = sum(row[field] for row in value['全区間の参加と中立'] if row['symbol'] == symbol and row['id'].endswith('__' + added))
                        b_total = sum(row[field] for row in value['全区間の参加と中立'] if row['symbol'] == symbol and row['id'].endswith('__' + baseline))
                        activities[field + '差'] = a_total - b_total
                    pairs.append({'signal': signal['id'], 'main_kind': signal['params']['main_kind'],
                                  'philosophy': 'EMA' if signal['params']['main_kind'].startswith('ema') else signal['params']['main_kind'],
                                  'mode': mode, 'comparison': comparison, 'symbol': symbol,
                                  '収支差円': own['net_yen'] - ref['net_yen'], 'DD差円': own['drawdown_yen'] - ref['drawdown_yen'],
                                  '注文台帳完全一致': a_hash['orders'] == b_hash['orders'],
                                  '返済台帳完全一致': a_hash['trades'] == b_hash['trades'],
                                  '金銭経路完全一致': a_hash['money'] == b_hash['money'],
                                  **activities, '比較側': own, '基準側': ref})
    groups = []
    for mode, _, _ in MODES:
        for comparison in ('S-C', 'S-B0', 'C-B0'):
            for symbol in SYMBOLS:
                rows = [r for r in pairs if r['mode'] == mode and r['comparison'] == comparison and r['symbol'] == symbol]
                assert len(rows) == 12
                n, d = np.array([r['収支差円'] for r in rows]), np.array([r['DD差円'] for r in rows])
                groups.append({'mode': mode, 'comparison': comparison, 'symbol': symbol, '入口数': len(rows),
                               '収支差中央値円': float(np.median(n)), 'DD差中央値円': float(np.median(d)),
                               '収支改善率': float(np.mean(n > .01)), '収支悪化率': float(np.mean(n < -.01)),
                               'DD改善率': float(np.mean(d < -.01)), 'DD悪化率': float(np.mean(d > .01)),
                               '両改善率': float(np.mean((n > .01) & (d < -.01))),
                               '収支同値率': float(np.mean(np.abs(n) <= .01)), 'DD同値率': float(np.mean(np.abs(d) <= .01)),
                               '全13区間注文台帳同一率': float(np.mean([r['注文台帳完全一致'] for r in rows])),
                               '全13区間返済台帳同一率': float(np.mean([r['返済台帳完全一致'] for r in rows]))})
    strata = []
    for key in ('main_kind', 'philosophy'):
        for name in sorted({row[key] for row in pairs}):
            for group in groups:
                selected = [row for row in pairs if row[key] == name and all(row[field] == group[field] for field in ('mode', 'comparison', 'symbol'))]
                strata.append({'区分': key, '名称': name, **{field: group[field] for field in ('mode', 'comparison', 'symbol')},
                               '入口数': len(selected), '収支差平均円': float(np.mean([row['収支差円'] for row in selected])),
                               'DD差平均円': float(np.mean([row['DD差円'] for row in selected])),
                               '両改善率': float(np.mean([row['収支差円'] > .01 and row['DD差円'] < -.01 for row in selected]))})
    equal_families = []
    for group in groups:
        selected = [row for row in strata if row['区分'] == 'philosophy' and all(row[field] == group[field] for field in ('mode', 'comparison', 'symbol'))]
        assert len(selected) == 5
        equal_families.append({**{field: group[field] for field in ('mode', 'comparison', 'symbol')},
                               '思想数': 5, '思想内平均収支差の中央値円': float(np.median([row['収支差平均円'] for row in selected])),
                               '思想内平均DD差の中央値円': float(np.median([row['DD差平均円'] for row in selected]))})
    return {'対応差': pairs, '全12入口の等重み集計': groups, '6主方向と5思想の層別': strata,
            'EMAを統合した5思想の等重み': equal_families}


def main() -> None:
    """機能: 固定後に全84条件の原因診断を実行し、現在データを遮断する。

    引数: --prepare (bool)。返り値: なし (None)。全条件を残し順位選抜しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = episode.reject_network
    socket.create_connection = episode.reject_network
    urllib.request.OpenerDirector.open = episode.reject_network
    implementation = freeze()
    if args.prepare:
        print('全84の原因・対応比較実装を固定。先行固定の比較規則を維持。', flush=True)
        return
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    fixed = runner.read(HERE / '探索条件の固定.json')
    assert len(fixed['signals']) == 12 and len(fixed['managers']) == 7 and len(inputs) == 26
    directory = HERE / 'context_causes'
    directory.mkdir(exist_ok=True)
    values = []
    for spec in fixed['signals']:
        value = process_signal(spec, fixed, inputs)
        runner.save(directory / (spec['id'] + '.json.gz'), value)
        values.append(value)
    result = summarize(values)
    result.update(固定仕様=runner.read(HERE / 'context_comparison_fixed.json'), 実装固定=implementation,
                  全入力数=sum(len(v['全区間の参加と中立']) for v in values),
                  全観測行数=sum(r['観測行数'] for v in values for r in v['全区間の参加と中立']),
                  CS分岐比較数=sum(len(v['最初のCS分岐']) for v in values), API取得=0, 現在保存物使用=False)
    assert result['全入力数'] == 2184 and len(result['対応差']) == 216
    assert freeze() == implementation
    runner.save(HERE / 'context_comparison.json', result)
    lines = ['# 相手不一致と保有撤回の全対応診断', '', '全84条件。主比較S-Cに加えS-B0/C-B0を全て表示。正の収支差・負のDD差が改善。未知性能ではない。', '',
             '|撤回|差|銘柄|収支差中央値|DD差中央値|収支改善率|DD改善率|', '|---|---|---|---:|---:|---:|---:|']
    for row in result['全12入口の等重み集計']:
        lines.append(f"|{row['mode']}|{row['comparison']}|{row['symbol']}|{row['収支差中央値円']:+,.0f}|{row['DD差中央値円']:+,.0f}|{row['収支改善率']:.1%}|{row['DD改善率']:.1%}|")
    lines += ['', '中立原因は連続0全区間の交代を保存。最初の注文分岐だけを共通状態から説明し、後続組番号は対応させない。全原因明細は context_causes/ に保存した。']
    (HERE / 'context_comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
