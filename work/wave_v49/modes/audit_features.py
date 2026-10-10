"""追従・反復・板特徴の未来独立性と上下対称性を全保存セッションで確認する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

import features as signals

HERE = Path(__file__).resolve().parent
ROOT = signals.ROOT


def compare(left: dict, right: dict, count: int | None = None) -> None:
    """機能: 信号と支持抵抗を同じ行範囲で照合する。

    引数: left/right(dict)、count(int|None)。返り値: なし(None)。
    """
    assert set(left) == set(right) == set(signals.FIELDS)
    for name in signals.FIELDS:
        a, b = left[name][:count], right[name][:count]
        if name in ('book_score', 'support20', 'resistance20', 'center20'):
            np.testing.assert_allclose(a, b, atol=1e-9, rtol=0, equal_nan=True, err_msg=name)
        else:
            np.testing.assert_array_equal(a, b, err_msg=name)


def cut(inputs: dict, frames: dict, counts: dict) -> tuple[dict, dict]:
    """機能: 原本行を途中で切り、未公開の同秒板も取り除く。

    引数: inputs/frames/counts(dict)。返り値: 切断済み入力と板(tuple[dict,dict])。
    """
    out, board = {}, {}
    for key, ready in inputs.items():
        count = counts[key]
        out[key] = {name: value[:count].copy() if isinstance(value, np.ndarray) and len(value) == len(ready['seq']) else value
                    for name, value in ready.items()}
        board[key] = frames[key].loc[frames[key].seq <= out[key]['seq'][-1]].copy()
    return out, board


def altered(inputs: dict, frames: dict, cutoff: float | None) -> tuple[dict, dict, Path, dict]:
    """機能: 未来改変又は上下反射を新作業のコピーだけへ加える。

    引数: inputs/frames(dict)、cutoff(float|None)。返り値: 入力・板・足根・反射中心(tuple)。
    """
    output, boards, centers = {}, {}, {}
    label = 'reflection' if cutoff is None else 'future'
    root = HERE / 'audit_candles' / label
    for key, ready in inputs.items():
        row = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in ready.items()}
        frame = frames[key].copy()
        candles = pd.read_csv(ROOT / 'candle_1min' / key[1] / (key[0] + '.csv'))
        release = pd.to_datetime(candles.time).dt.as_unit('ns').astype('int64').to_numpy(float) / 1e9 + 120
        if cutoff is None:
            center = float(2 * np.ceil(np.max(ready['last']) / ready['tick']) * ready['tick'])
            centers[key] = center
            row['last'] = center - row['last']
            for name in ('ofi_signed', 'dflow_near', 'dflow_far', 'pressure_near', 'pressure_far'):
                frame[name] = -frame[name]
            for a, b in (('refill_bid', 'refill_ask'), ('trade_pos', 'trade_neg')):
                frame[a], frame[b] = frame[b].copy(), frame[a].copy()
            high, low = candles.high.copy(), candles.low.copy()
            candles['high'], candles['low'] = center - low, center - high
            for name in ('open', 'close'):
                candles[name] = center - candles[name]
        else:
            mask = row['time_s'] >= cutoff
            row['last'][mask] = row['last'][mask] * 1.3 + 17 * ready['tick']
            row['atr'][mask] *= 2.3
            mask = frame.time_s >= cutoff
            for name in ('ofi_signed', 'dflow_near', 'dflow_far', 'pressure_near', 'pressure_far'):
                frame.loc[mask, name] = -frame.loc[mask, name]
            for a, b in (('refill_bid', 'refill_ask'), ('trade_pos', 'trade_neg')):
                av, bv = frame.loc[mask, a].copy(), frame.loc[mask, b].copy()
                frame.loc[mask, a], frame.loc[mask, b] = bv, av
            for name in ('open', 'high', 'low', 'close'):
                candles[name] = candles[name].astype(float)
                candles.loc[release >= cutoff, name] = candles.loc[release >= cutoff, name] * 1.3 + 17 * ready['tick']
        destination = root / 'candle_1min' / key[1] / (key[0] + '.csv')
        destination.parent.mkdir(parents=True, exist_ok=True)
        candles.to_csv(destination, index=False, encoding='utf8')
        output[key], boards[key] = row, frame
    return output, boards, root, centers


def synthetic() -> dict:
    """機能: 同秒公開順・継続確認境界・即中立化を人工例で確認する。

    引数: なし。返り値: 確認結果(dict)。
    """
    actual = signals.window_sum(np.array([10., 10., 11.]), np.array([1., 2., 3.]), 30)
    np.testing.assert_array_equal(actual, [1, 3, 6])
    actual = signals.asof(np.array([11, 13]), np.array([3., 7.]), np.array([10, 11, 12, 13]), 0)
    np.testing.assert_array_equal(actual, [0, 3, 3, 7])
    actual = signals.confirmed(np.array([0., 59., 60., 61., 62., 121., 122., 200., 260.]),
                               np.array([1, 1, 1, 0, -1, -1, -1, 2, 2], np.int8))
    np.testing.assert_array_equal(actual, [0, 0, 1, 0, 0, 0, -1, 0, 2])
    return dict(同秒窓先取りなし=True, 同秒公開seq以前参照なし=True, 確認60秒と中立解除=True)


def main() -> None:
    """機能: 32市場で切断・未来変更・反射・同秒途中を確認して記録する。

    引数: なし。返り値: なし(None)。売買結果は読まない。
    """
    signals.freeze()
    artificial = synthetic()
    inputs, frames = signals.load_inputs()
    records, coverage = [], []
    for session in sorted({key[0] for key in inputs}):
        keys = [(session, symbol) for symbol in ('TOPIX', 'NK225')]
        own, board = {key: inputs[key] for key in keys}, {key: frames[key] for key in keys}
        base = signals.build(own, board)
        start, end = max(r['start'] for r in own.values()), min(r['time_s'][-1] for r in own.values())
        cutoff = start + (end - start) * .37
        counts = {key: int(np.searchsorted(r['time_s'], cutoff, side='left')) for key, r in own.items()}
        ci, cf = cut(own, board, counts)
        partial = signals.build(ci, cf)
        future_time = start + (end - start) * .73
        fi, ff, fr, _ = altered(own, board, future_time)
        future = signals.build(fi, ff, fr)
        mi, mf, mr, centers = altered(own, board, None)
        reflected = signals.build(mi, mf, mr)
        for key in keys:
            ready = own[key]
            compare(base[key], partial[key], counts[key])
            count = int(np.searchsorted(ready['time_s'], future_time, side='left'))
            compare(base[key], future[key], count)
            expected = {name: values.copy() for name, values in base[key].items()}
            for name in ('trend', 'range_side', 'book_score', 'absorb_side'):
                expected[name] *= -1
            expected['support20'] = centers[key] - base[key]['resistance20']
            expected['resistance20'] = centers[key] - base[key]['support20']
            expected['center20'] = centers[key] - base[key]['center20']
            compare(expected, reflected[key])
            duplicate = np.flatnonzero(np.diff(ready['time_s']) == 0) + 1
            assert len(duplicate)
            count = int(duplicate[np.argmin(np.abs(duplicate - int(len(ready['time_s']) * .61)))])
            same_counts = {selected: count if selected == key else len(own[selected]['seq']) for selected in keys}
            si, sf = cut(own, board, same_counts)
            same_time = signals.build(si, sf)
            compare(base[key], same_time[key], count)
            records.append(dict(session=key[0], symbol=key[1], 全行=len(ready['seq']),
                                先頭切断一致=True, 未来改変一致=True, 上下反射一致=True, 同秒途中切断一致=True))
            coverage.append(dict(session=key[0], symbol=key[1],
                mode原本行数={str(mode): int(np.sum(base[key]['mode'] == mode)) for mode in (0, 1, 2)},
                有効板行数=int(np.sum(base[key]['book_valid'])),
                反復入口行数=int(np.sum(base[key]['range_side'] != 0)),
                吸収入口行数=int(np.sum(base[key]['absorb_side'] != 0))))
        print(session + ' の切断・未来・反射・同秒検査が一致', flush=True)
    result = dict(全合格=True, 売買損益参照=False, API取得数=0, 対象入力数=len(records), 人工検査=artificial,
                  確認=records, 情報被覆=coverage,
                  実装SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__), HERE / 'features.py', HERE / '特徴定義.json')})
    signals.save(HERE / '特徴監査.json', result)
    print('全32市場の特徴監査に合格しました。', flush=True)


if __name__ == '__main__':
    main()
