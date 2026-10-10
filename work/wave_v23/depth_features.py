"""同価格の板数量変化と反復補充を、既存の解放済みブロックへ追加する。"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
COLUMNS = ['dflow_near', 'dflow_far', 'pressure_near', 'pressure_far', 'refill_bid', 'refill_ask']


def snapshot(raw: dict) -> tuple | None:
    """機能: 上位 10 段を読み、交差・ロック・最良数量不正の板を除外する。

    引数: raw (dict)。返り値: 最良価格と同価格数量辞書の組 (tuple|None)。
    """
    sides = []
    for side in ('Buy', 'Sell'):
        levels = []
        for index in range(1, 11):
            row = raw.get(f'{side}{index}') or {}
            try:
                price, qty = float(row.get('Price') or 0.), float(row.get('Qty') or 0.)
            except (TypeError, ValueError):
                price, qty = 0., 0.
            if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty < 0:
                price, qty = 0., 0.
            levels.append((price, qty))
        if levels[0][0] <= 0 or levels[0][1] <= 0:
            return None
        sides.append((levels[0][0], {price: qty for price, qty in levels if price > 0}))
    if sides[0][0] >= sides[1][0]:
        return None
    return sides[0][0], sides[1][0], sides[0][1], sides[1][1]


def consume_refill(history: dict, price: float, delta: float, stamp: float) -> float:
    """機能: 直近 30 秒の同価格減少残高を超えない数量だけ補充として数える。

    引数: history (dict[float, deque])、price/delta/stamp (float)。
    返り値: 今回の観測で対応付けられた非負補充数量 (float)。
    数量減少が約定か取消か、同じ発注者かは判別しない。
    """
    events = history.setdefault(price, deque())
    while events and events[0][0] < stamp - 30.:
        events.popleft()
    if delta < 0:
        events.append([stamp, -delta])
        return 0.
    amount, refill = delta, 0.
    while events and amount > 0:
        use = min(amount, events[0][1])
        amount -= use
        refill += use
        events[0][1] -= use
        if events[0][1] <= 0:
            events.popleft()
    return refill


def extract(path: Path, symbol: str, session: str, frame: pd.DataFrame,
            max_rows: int | None = None) -> tuple[pd.DataFrame, dict]:
    """機能: 原本順に計算し、既存特徴と完全同一の解放行へ 6 列を追加する。

    引数: path (Path)、symbol/session (str)、frame (DataFrame)、max_rows (int|None)。
    返り値: 列追加した表と監査要約 (tuple[DataFrame, dict])。
    未解放の末尾は既存表にも含まれず、途中切断も解放行以前だけを返す。
    """
    result = frame.copy() if max_rows is None else frame.loc[frame.seq < max_rows].copy()
    count = len(result)
    if count == 0:
        return result.assign(**{name: np.array([], dtype=float) for name in COLUMNS}), dict(特徴行数=0)
    first = result.source_first_seq.to_numpy(dtype=np.int64)
    last = result.source_last_seq.to_numpy(dtype=np.int64)
    release = result.seq.to_numpy(dtype=np.int64)
    assert np.all(last < release) and np.all(first <= last)
    sums = np.zeros((count, 8))
    valid_count = np.zeros(count, dtype=np.int64)
    tick = .5 if symbol == 'TOPIX' else 10.
    day_text, kind = session.rsplit('_', 1)
    day = datetime.fromisoformat(day_text).replace(tzinfo=timezone(timedelta(hours=9)))
    start = day + (timedelta(hours=8, minutes=45) if kind == 'Day' else timedelta(hours=17))
    end = day + (timedelta(hours=15, minutes=40) if kind == 'Day' else timedelta(days=1, hours=5, minutes=55))
    start_s, end_s = start.timestamp(), end.timestamp()
    previous, histories, weights = None, ({}, {}), {}
    previous_stamp, current_s, index, read_count, excluded = None, 0., 0, 0, 0
    for seq, line in enumerate(path.open('rb')):
        if max_rows is not None and seq >= max_rows:
            break
        if seq > int(last[-1]):
            break
        read_count += 1
        raw = json.loads(line)
        stamp = raw.get('CurrentPriceTime')
        if not stamp:
            previous, histories = None, ({}, {})
            continue
        if stamp != previous_stamp:
            new_s = datetime.fromisoformat(stamp).timestamp()
            assert new_s >= current_s
            current_s, previous_stamp = new_s, stamp
            for history in histories:
                for price in list(history):
                    events = history[price]
                    while events and events[0][0] < current_s - 30.:
                        events.popleft()
                    if not events:
                        del history[price]
        if not start_s <= current_s < end_s:
            previous, histories = None, ({}, {})
            continue
        current = snapshot(raw)
        if current is None:
            previous, histories = None, ({}, {})
            excluded += 1
            continue
        while index < count and seq > last[index]:
            index += 1
        active = index < count and first[index] <= seq <= last[index]
        weighted = np.zeros((2, 2))
        flow = np.zeros((2, 2))
        refills = [0., 0.]
        for side in range(2):
            best, book = current[side], current[side + 2]
            previous_book = previous[side + 2] if previous is not None else {}
            for price, qty in book.items():
                distance = max(0., (best - price if side == 0 else price - best) / tick)
                if distance not in weights:
                    weights[distance] = (math.exp(-distance / 2.), math.exp(-distance / 8.))
                near, far = weights[distance]
                weighted[side, 0] += near * qty
                weighted[side, 1] += far * qty
                # 共通して見える価格だけを差分にする。板外へ消えた注文を取消にしない。
                if price in previous_book:
                    delta = qty - previous_book[price]
                    if delta:
                        sign = 1. if side == 0 else -1.
                        flow[0, 0] += sign * near * delta
                        flow[0, 1] += sign * far * delta
                        flow[1, 0] += near * abs(delta)
                        flow[1, 1] += far * abs(delta)
                        refills[side] += consume_refill(histories[side], price, delta, current_s)
        if active:
            valid_count[index] += 1
            sums[index, :4] += flow.reshape(-1)
            for scale in range(2):
                denominator = weighted[0, scale] + weighted[1, scale]
                sums[index, 4 + scale] += (weighted[0, scale] - weighted[1, scale]) / denominator if denominator else 0.
            sums[index, 6:] += refills
        previous = current
    np.testing.assert_array_equal(valid_count, result.valid_event_count.to_numpy(dtype=int))
    data = np.zeros((count, 6))
    for scale in range(2):
        np.divide(sums[:, scale], sums[:, 2 + scale], out=data[:, scale], where=sums[:, 2 + scale] > 0)
        data[:, 2 + scale] = sums[:, 4 + scale] / valid_count
    data[:, 4:] = sums[:, 6:]
    assert np.isfinite(data).all() and (np.abs(data[:, :4]) <= 1. + 1e-12).all()
    result[COLUMNS] = data
    audit = dict(セッション=session, 銘柄=symbol, 読取行数=read_count, 特徴行数=count,
                 有効行数一致=True, 特徴解放行一致=True, 不正板行数=excluded,
                 元特徴最終参照行が解放行より前=True,
                 買い補充合計=float(data[:, 4].sum()), 売り補充合計=float(data[:, 5].sum()))
    return result, audit


def main() -> None:
    """機能: 全既知原本の追加特徴を作り、途中切断の不変性と計算定義を保存する。

    引数: なし。返り値: なし (None)。旧特徴、価格原本、過去成果は変更しない。
    """
    features = pickle.loads((OUT / 'features.pkl').read_bytes())
    records, output = [], {}
    for (session, symbol), frame in features.items():
        start = time.monotonic()
        path = ROOT / 'book' / symbol / f'{session}.jsonl'
        result, audit = extract(path, symbol, session, frame)
        output[(session, symbol)] = result
        audit['処理秒'] = round(time.monotonic() - start, 2)
        records.append(audit)
        print(f'{session} {symbol}: {len(result)} 行・{audit["処理秒"]} 秒', flush=True)
    checks = []
    for key in [('2026-09-21_Day', 'TOPIX'), ('2026-09-29_Day', 'NK225')]:
        frame = features[key]
        for fraction in (.25, .6):
            cutoff = int(frame.seq.iloc[int(len(frame) * fraction)])
            part, _ = extract(ROOT / 'book' / key[1] / f'{key[0]}.jsonl', key[1], key[0], frame, cutoff)
            expected = output[key].loc[output[key].seq < cutoff]
            np.testing.assert_array_equal(part[COLUMNS].to_numpy(), expected[COLUMNS].to_numpy())
            checks.append(dict(セッション=key[0], 銘柄=key[1], 切断行=cutoff, 一致行数=len(part)))
    # 同価格の補充は直前減少を超えない。30 秒を超えた減少や新出価格では数えない。
    history = {}
    assert consume_refill(history, 100., -7., 0.) == 0.
    assert consume_refill(history, 100., 4., 10.) == 4.
    assert consume_refill(history, 100., 8., 20.) == 3.
    assert consume_refill(history, 100., -5., 21.) == 0.
    assert consume_refill(history, 100., 10., 52.) == 0.
    assert consume_refill(history, 101., 10., 52.) == 0.
    (OUT / 'features_depth.pkl').write_bytes(pickle.dumps(output, pickle.HIGHEST_PROTOCOL))
    report = dict(合格=True, 原本と既存特徴不変=True, 現在API取得数=0, 列=COLUMNS,
                  距離定義='各側の現在最良気配からの呼値数。近傍 exp(-距離/2)、遠方 exp(-距離/8)。',
                  dflow定義='上位10段に前後共通の価格だけ数量差分。買い増加・売り減少が正。同一原本時刻ブロック内の重み付き符号和/絶対和。',
                  pressure定義='各有効板の距離重み付き買い数量と売り数量の差/和を、原本時刻ブロック内で平均。',
                  refill定義='同価格の前後共通板の数量増加と、直近30秒の未対応減少を小さい数量から対応付ける。ブロック内合計。',
                  限界='板減少は取消と約定を識別できず、補充は同一発注者や隠れ注文を証明しない。受信時刻がなくCurrentPriceTime近似。',
                  途中切断比較=checks, 補充数量上限検査=True, 原本別=records)
    (OUT / '追加板特徴監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
