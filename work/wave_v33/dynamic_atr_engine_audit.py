"""追跡幅更新の合成境界と旧固定T全26入力の台帳互換だけを監査する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine_dynamic_atr as engine
sys.path.insert(0, str(HERE.parent / 'wave_v28'))
import engine_context as previous
sys.path.insert(0, str(HERE.parent / 'wave_v23'))
import managers

A = {name: index for index, name in enumerate(engine.ATR_COLUMNS)}


def deny(*args: object, **kwargs: object) -> None:
    """機能: 外部通信を常に拒否する。

    引数: args/kwargs (object)。返り値: なし (None)。常に例外。
    """
    raise AssertionError('追跡ATR監査の外部通信は禁止です')


def config(symbol: str, ready: dict) -> dict:
    """機能: 既に固定されたL000=D273設定だけを使用する。

    引数: symbol (str)、ready (dict)。返り値: 注文設定 (dict)。
    """
    fixed = json.loads((HERE.parent / 'wave_v30/探索条件の固定.json').read_text(encoding='utf-8'))
    return managers.make_config(next(row for row in fixed['managers'] if row['id'] == 'L000'), symbol, ready)


def fixture(prices: list[float], atr: list[float] | None = None, trail: list[float] | None = None) -> tuple:
    """機能: 場末判断と次行返済を付けたTOPIX用の因果合成入力を作る。

    引数: prices (list[float])、atr/trail (list[float]|None)。返り値: ready、方向、config、追跡ATR (tuple)。
    """
    count = len(prices)
    initial = [4.] * count if atr is None else atr
    tracking = initial if trail is None else trail
    ready = {'time_s': np.r_[np.arange(count), 10000., 10001.],
             'last': np.array(prices + [prices[-1]] * 2, dtype=float),
             'atr': np.array(initial + [initial[-1]] * 2, dtype=float),
             'start': -1200., 'limit': 10000., 'us_open': np.inf, 'tick': 1., 'seq': np.arange(count + 2)}
    state = np.ones(count + 2, dtype=np.int8)
    return ready, state, config('TOPIX', ready), np.array(tracking + [tracking[-1]] * 2, dtype=float)


def same_old(actual: dict, expected: dict) -> None:
    """機能: 旧5結果を全要素厳密比較する。

    引数: actual/expected (dict)。返り値: なし (None)。
    """
    for field in ('trades', 'cycles', 'curve', 'orders', 'stats'):
        np.testing.assert_array_equal(actual[field], expected[field], err_msg=field)


def account(ready: dict, result: dict, cfg: dict) -> None:
    """機能: 全注文から現金と買売保有を再構成して全行時価・上限・場末を確認する。

    引数: ready/result/cfg (dict)。返り値: なし (None)。
    """
    n = len(ready['last'])
    moves = np.zeros((n, 3))
    for order in result['orders']:
        row, source = int(order[0]), int(order[1])
        side, qty, fill, opening = order[3], order[4], order[5], bool(order[7])
        assert 0 <= source < row < n and qty >= 1 and qty == int(qty)
        moves[row, 0] -= side * qty * fill
        position_side = side if opening else -side
        moves[row, 1 if position_side == 1 else 2] += qty if opening else -qty
    cash, long, short = np.cumsum(moves, axis=0).T
    equity = cash + (long - short) * ready['last']
    np.testing.assert_allclose(result['curve'][:, [0, 2, 3, 5, 6]],
                               np.column_stack((equity, long, short, cash, long - short)), atol=1e-7, rtol=0)
    assert np.all((long >= 0) & (short >= 0) & (long <= cfg['audit_cap']) & (short <= cfg['audit_cap']))
    assert long[-1] == short[-1] == 0
    closing_row = np.searchsorted(ready['time_s'], ready['limit'], side='left') + 1
    assert not (long[closing_row:] + short[closing_row:]).any()
    trades = result['trades']
    np.testing.assert_allclose(trades[:, 10], trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]), atol=1e-7, rtol=0)
    np.testing.assert_allclose(trades[:, 10].sum(), cash[-1], atol=1e-7, rtol=0)
    for cycle in result['cycles']:
        first, last, a0 = int(cycle[1]), int(cycle[2]), cycle[5]
        trace = result['atr_curve'][first:last]
        np.testing.assert_array_equal(trace[:, A['initial_atr']], np.full(last - first, a0))
        np.testing.assert_array_equal(trace[:, A['initial_risk']], np.full(last - first, cycle[4]))
        np.testing.assert_allclose(cycle[4], cfg['initial_qty'] * cfg['stop_atr'] * a0, atol=1e-9)
        active = trace[np.isfinite(trace[:, A['trail_level']]), A['trail_level']]
        if len(active) > 1:
            assert np.all(np.diff(active) * cycle[8] >= -1e-9)


def synthetic() -> list[dict]:
    """機能: ATRの拡縮・次行発効・左右反射・部分返済を合成相場で検査する。

    引数: なし。返り値: 検査記録 (list[dict])。実際の新損益条件は試さない。
    """
    checks = []
    r, s, cfg, at = fixture([100., 101., 110., 110., 110., 109.], trail=[4., 4., 4., 2., 10., 10.])
    result = engine.run(r, s, cfg, True, width_mode=1, trail_atr=at)
    trace = result['atr_curve']
    np.testing.assert_array_equal(trace[2:5, A['trail_level']], [98., 104., 104.])
    np.testing.assert_array_equal(trace[2:5, A['stop_level']], [89., 89., 89.])
    assert result['trades'][0, 5] == 109 and result['trades'][0, 3] == 2
    account(r, result, cfg)
    checks.append({'検査': 'ATR縮小で追跡線を締め、拡大しても既設線を緩めず、部分後も初期組リスクを維持', '一致': True})
    fixed = engine.run(r, s, cfg, True, width_mode=0, trail_atr=at)
    same_old(fixed, previous.run(r, s, cfg, True))
    altered = engine.run(r, s, cfg, True, width_mode=0, trail_atr=np.full(len(s), np.nan))
    same_old(altered, fixed)
    checks.append({'検査': '固定モードは追跡ATR列の値・欠測に関係なく旧5結果と完全一致', '一致': True})

    # ----------------------------------------
    r, s, cfg, at = fixture([100., 101., 106., 106., 107., 107.], trail=[4., 4., 2., 2., 2., 2.])
    result = engine.run(r, s, cfg, True, width_mode=1, trail_atr=at)
    assert not result['atr_curve'][1:4, A['trail_active']].any()
    assert result['atr_curve'][4, A['trail_active']] == 1
    assert result['atr_curve'][4, A['trail_level']] == 101
    account(r, result, cfg)
    checks.append({'検査': 'ATRが縮小しても1.5A0前は追跡を始動しない', '一致': True})
    r, s, cfg, at = fixture([100., 101., 120., 110., 110.], trail=[4., 4., 4., 2., 2.])
    result = engine.run(r, s, cfg, True, width_mode=1, trail_atr=at)
    assert result['atr_curve'][2, A['trail_level']] == 108
    assert result['atr_curve'][3, A['trail_level']] == 114
    assert not np.any(result['orders'][:, 0] == 3)
    final = result['trades'][-1]
    assert final[7] == 4 and final[5] == 110 and final[9] == 2
    account(r, result, cfg)
    checks.append({'検査': '価格据置きでもATR縮小で既通過の追跡線を新設したら当該行で返済せず次行観測値で返済', '一致': True})
    r, s, cfg, at = fixture([100., 101., 120., 109.], trail=[4., 4., 2., 20.])
    result = engine.run(r, s, cfg, True, width_mode=1, trail_atr=at)
    assert result['trades'][-1, 7] == 3 and result['trades'][-1, 5] == 114
    account(r, result, cfg)
    checks.append({'検査': '到達行でATRが拡大しても前行までの追跡条件を先に執行する', '一致': True})

    # ----------------------------------------
    r, s, cfg, at = fixture([100., 101., 102., 103., 104., 105., 106., 107.], trail=[np.nan, np.nan, 3., np.nan, np.inf, -1., 0., .5])
    result = engine.run(r, s, cfg, True, width_mode=1, trail_atr=at)
    np.testing.assert_array_equal(result['atr_curve'][1:8, A['current_atr']], [4., 3., 3., 3., 3., 3., 2.])
    account(r, result, cfg)
    checks.append({'検査': '初回欠測はA0、以後NaN/無限大/非正値は直前有効ATR、2呼値下限', '一致': True})
    r, s, cfg, at = fixture([100., 100., 101., 110.], atr=[4., 20., 30., 40.])
    result = engine.run(r, s, cfg, True, width_mode=1)
    assert result['orders'][0, 5] == 101 and result['cycles'][0, 5] == 4
    assert result['atr_curve'][2, A['current_atr']] == 30 and result['atr_curve'][2, A['initial_risk']] == 20
    assert result['trades'][0, 5] == 109
    account(r, result, cfg)
    checks.append({'検査': '準備から約定までATRが変わっても入口・初期予算・部分利確は準備時A0を維持', '一致': True})

    # ----------------------------------------
    r, s, cfg, at = fixture([100., 102., 120., 110., 110.], trail=[4., 4., 4., 2., 2.])
    for mode in (0, 1):
        for observed in (False, True):
            result = engine.run(r, s, cfg, True, width_mode=mode, observed_fill=observed, trail_atr=at)
            reflected = dict(r, last=300. - r['last'])
            mirror = engine.run(reflected, -s, cfg, True, width_mode=mode, observed_fill=observed, trail_atr=at)
            np.testing.assert_array_equal(result['trades'][:, [0, 1, 3, 6, 7, 8, 9, 10]], mirror['trades'][:, [0, 1, 3, 6, 7, 8, 9, 10]])
            np.testing.assert_allclose(result['orders'][:, 5] + mirror['orders'][:, 5], 300., atol=1e-9)
            account(r, result, cfg)
            account(reflected, mirror, cfg)
            if observed:
                np.testing.assert_array_equal(result['orders'][:, 5], r['last'][result['orders'][:, 0].astype(int)])
    checks.append({'検査': '固定/現在と指定/観測の4組合せで売買反射・全玉会計が対称、観測モデルは全約定で現在p', '一致': True})
    r, s, cfg, at = fixture([100., 101., 110., 110., 110., 100.], trail=[4., 4., 4., 2., 10., 10.])
    full = engine.run(r, s, cfg, True, width_mode=1, trail_atr=at)
    cutoff = 4
    limited = {key: value[:cutoff].copy() if isinstance(value, np.ndarray) else value for key, value in r.items()}
    short = engine.run(limited, s[:cutoff], cfg, True, width_mode=1, trail_atr=at[:cutoff])
    for field in ('curve', 'atr_curve'):
        np.testing.assert_array_equal(short[field], full[field][:cutoff])
    future = deepcopy(r)
    future['last'][cutoff:] = 5000
    future['atr'][cutoff:] = 90
    changed = at.copy();changed[cutoff:] = .1
    directions = s.copy();directions[cutoff:] = -1
    result = engine.run(future, directions, cfg, True, width_mode=1, trail_atr=changed)
    for field in ('curve', 'atr_curve'):
        np.testing.assert_array_equal(result[field][:cutoff], full[field][:cutoff])
    np.testing.assert_array_equal(result['orders'][result['orders'][:, 0] < cutoff], full['orders'][full['orders'][:, 0] < cutoff])
    checks.append({'検査': '未来価格・入口ATR・追跡ATR・方向の除去と改変でも過去注文と両曲線不変', '一致': True})
    compact = engine.run(r, s, cfg, False, width_mode=1, trail_atr=at)
    for field in ('trades', 'cycles', 'orders', 'stats'):
        np.testing.assert_array_equal(compact[field], full[field])
    checks.append({'検査': '詳細有無で取引・組・注文・集計は不変', '一致': True})
    for override in ({'width_mode': 2}, {'width_mode': True}, {'trail_atr': at[:-1]}, {'trail_atr': at.astype(int)},
                     {'trail_atr': at[:, None]}, {'config': dict(cfg, split_target=1)}, {'config': dict(cfg, main_trail=2)}):
        options = dict(config=cfg, width_mode=0, trail_atr=at)
        options.update(override)
        try:
            engine.run(r, s, **options)
        except ValueError:
            pass
        else:
            raise AssertionError('非対応設定を受け入れた')
    checks.append({'検査': 'ATR列の型/長さ/次元、幅モードと共通D273以外を拒否', '一致': True})
    return checks


def old_fixed() -> int:
    """機能: 既知H019固定の26入力を旧v28と厳密比較し、旧保存V000集計にも照合する。

    引数: なし。返り値: 一致入力数 (int)。新モードの相場成績は実行しない。
    """
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    old_settings = json.loads((HERE.parent / 'wave_v31/探索条件の固定.json').read_text(encoding='utf-8'))
    old_manager = next(row for row in old_settings['managers'] if row['id'] == 'L000')
    saved = json.loads(gzip.decompress((HERE.parent / 'wave_v31/sessions/H019.json.gz').read_bytes()))
    saved_rows = next(row['rows'] for row in saved if row['id'] == 'H019__L000__V000')
    reference = {(row['session'], row['symbol']): row for row in saved_rows}
    count = 0
    with np.load(HERE.parent / 'wave_v27/directions/H019.npz') as archive:
        for key, ready in inputs.items():
            state = archive['|'.join(key)]
            cfg = config(key[1], ready)
            assert cfg == managers.make_config(old_manager, key[1], ready)
            current = engine.run(ready, state, cfg, True, width_mode=0)
            same_old(current, previous.run(ready, state, cfg, True))
            account(ready, current, cfg)
            profits = current['trades'][:, 10] * cfg['point_value']
            np.testing.assert_allclose([profits.sum(), profits[profits > 1e-6].sum(), -profits[profits < -1e-6].sum(), current['stats'][1] * cfg['point_value']],
                                       [reference[key][name] for name in ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'drawdown_yen')], atol=1e-6, rtol=0)
            count += 1
    assert count == 26
    return count


def main() -> None:
    """機能: 合成と旧固定互換を検査し、実装指紋と件数だけを保存する。

    引数: --synthetic-only (bool)。返り値: なし (None)。新格子・現在セッションは実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--synthetic-only', action='store_true')
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    urllib.request.OpenerDirector.open = deny
    paths = [HERE.parent / name for name in ('wave_v28/engine_context.py', 'wave_v23/inputs.pkl', 'wave_v27/directions/H019.npz',
                                            'wave_v31/探索条件の固定.json', 'wave_v31/sessions/H019.json.gz')]
    fingerprints = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    checks = synthetic()
    count = 0 if args.synthetic_only else old_fixed()
    assert fingerprints == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    record = {'全合格': count == 26, '合成全合格': True, '合成件数': len(checks), '合成検査': checks,
              '旧固定H019完全一致入力数': count, '旧5結果完全一致': count == 26,
              '新しい動的ATRの実相場再生': False, '現在保存物使用': False, 'API取得数': 0,
              '原本不変': True, '原本SHA256': fingerprints,
              'engine_SHA256': hashlib.sha256((HERE / 'engine_dynamic_atr.py').read_bytes()).hexdigest(),
              'ATR_COLUMNS': engine.ATR_COLUMNS}
    (HERE / 'dynamic_atr_engine_audit.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('合成', len(checks), '件、旧固定H019', count, '入力完全一致。新相場格子実行なし。', flush=True)


if __name__ == '__main__':
    main()
