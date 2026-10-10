"""同価格の補充完了を、反転・突破・切上げの三つの入口へ変換する。"""

from __future__ import annotations

from collections import deque
import math
import numpy as np


FAMILIES = [('R1', '吸収を示唆する補充の後の反転'),
            ('R2', '補充が止まった価格帯の突破'), ('R3', '補充される価格の移動に追従')]


def methods() -> list[dict]:
    """機能: 結果を参照せず、三入口と二回数・二幅の12条件を列挙する。

    引数: なし。返り値: 固定条件一覧(list[dict])。
    """
    return [dict(id=f'{family}_C{count}_{width}', family=family, count=count,
                 width=width, fraction=fraction, name=f'{name}／補充{count}回／{label}',
                 entry_name=name, width_name=label, primary=count == 2 and width == 'W05')
            for family, name in FAMILIES for count in (2, 3)
            for width, fraction, label in [('W05', .0005, '始値の0.05%'), ('W10', .001, '始値の0.10%')]]


def flow_windows(frame: dict, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    """機能: 現在行までの代理買い・売り出来高を時間窓で集計する。

    引数: frame(dict)、seconds(float)。返り値: 買い・売り数量の同長配列(tuple)。
    同時刻の後続行を含めず、品質リセット以前の数量も含めない。
    """
    times = frame['time_s']
    assert np.all(np.diff(times) >= 0)
    left = np.searchsorted(times, times - seconds, side='left')
    reset = np.maximum.accumulate(np.where(frame['reset'], np.arange(len(times)), 0))
    left = np.maximum(left, reset)
    output = []
    for key in ('exec_buy_qty', 'exec_sell_qty'):
        cumulative = np.r_[0., np.cumsum(frame[key])]
        output.append(cumulative[1:] - cumulative[left])
    return tuple(output)


def candidates(frame: dict, events: np.ndarray, count: int, tick: float,
               start: float) -> dict[str, np.ndarray]:
    """機能: 補充の観測と後続の気配変化を原本順で追い、三入口を作る。

    引数: frame(dict)、events(構造化ndarray)、count(int)、tick/start(float)。
    返り値: 類型ごとの行番号・売買方向・構造逆指値・壁価格(ndarray)を持つ辞書。
    同価格の独立した回復周期のみ合算し、判定行より先は参照しない。
    """
    buy30, sell30 = flow_windows(frame, 30.)
    buy10, sell10 = flow_windows(frame, 10.)
    history, arms, anchors = {1: {}, -1: {}}, {}, {}
    output = {family: [] for family, _ in FAMILIES}
    pointer = 0
    old_far = None
    for i in range(len(frame['seq'])):
        now, seq = float(frame['time_s'][i]), int(frame['seq'][i])
        bid, ask, mid = float(frame['bid'][i]), float(frame['ask'][i]), float(frame['mid'][i])
        far = float(frame['bid_far'][i]), float(frame['ask_far'][i])
        if frame['reset'][i] or not frame['valid'][i]:
            history, arms, anchors = {1: {}, -1: {}}, {}, {}
            old_far = None
        if not frame['valid'][i]:
            while pointer < len(events) and events[pointer]['i'] <= i:
                pointer += 1
            continue
        if far != old_far:
            for side in (1, -1):
                for price in list(history[side]):
                    if (side == 1 and price < far[0]) or (side == -1 and price > far[1]):
                        del history[side][price]
            old_far = far
        for key, arm in list(arms.items()):
            side, price = arm['side'], arm['price']
            unknown = (side == 1 and price < far[0]) or (side == -1 and price > far[1])
            if now - arm['time'] > 120. or seq - arm['seq'] > 2000 or unknown:
                del arms[key]
        for side, anchor in list(anchors.items()):
            price = anchor['price']
            unknown = (side == 1 and price < far[0]) or (side == -1 and price > far[1])
            if now - anchor['time'] > 120. or seq - anchor['seq'] > 2000 or unknown:
                del anchors[side]
        found = {family: [] for family, _ in FAMILIES}
        while pointer < len(events) and events[pointer]['i'] == i:
            event = events[pointer]
            pointer += 1
            side, price = int(event['side']), float(event['price'])
            values = history[side].setdefault(price, deque())
            while values and (now - values[0][0] > 120. or seq - values[0][1] > 2000):
                values.popleft()
            previous_count = len(values)
            values.append((now, seq))
            for arm in arms.values():
                if arm['side'] == side and arm['price'] == price:
                    arm['last_refill'] = now
            best_price = bid if side == 1 else ask
            if not (previous_count < count <= len(values) and price == best_price):
                continue
            wall = dict(side=side, price=price, mid=mid, bid=bid, ask=ask,
                        time=now, seq=seq, last_refill=now, crossed=None)
            pressure = (sell30[i], buy30[i]) if side == 1 else (buy30[i], sell30[i])
            if pressure[0] > 0 and pressure[0] >= pressure[1]:
                arms[('R1', side)] = wall.copy()
                arms[('R2', side)] = wall.copy()
            previous = anchors.get(side)
            if previous is not None:
                moved = side * (price - previous['price']) >= tick - 1e-9
                opposite_moved = (ask - previous['ask'] if side == 1 else previous['bid'] - bid) >= tick - 1e-9
                if moved and opposite_moved:
                    found['R3'].append((side, price - side * tick, price))
            if previous is None or price != previous['price']:
                anchors[side] = wall.copy()
        # ----------------------------------------
        # 反転は支えた側、突破は支えが失われた側の反対へ入る。
        for key, arm in list(arms.items()):
            family, wall_side = key
            price = arm['price']
            if family == 'R1':
                broken = bid < price if wall_side == 1 else ask > price
                if broken:
                    del arms[key]
                    continue
                shifted = (bid - price if wall_side == 1 else price - ask) >= tick - 1e-9
                shifted = shifted and wall_side * (mid - arm['mid']) >= tick - 1e-9
                flow = buy10[i] >= sell10[i] if wall_side == 1 else sell10[i] >= buy10[i]
                if shifted and flow and buy10[i] + sell10[i] > 0:
                    found[family].append((wall_side, price - wall_side * tick, price))
                    del arms[key]
            else:
                crossed = ask > price and bid >= price if wall_side == -1 else bid < price and ask <= price
                if not crossed:
                    arm['crossed'] = None
                elif arm['crossed'] is None:
                    arm['crossed'] = now
                elif now - arm['crossed'] >= 2. and now - arm['last_refill'] >= 3.:
                    side = -wall_side
                    found[family].append((side, price - side * tick, price))
                    del arms[key]
        if now < start + 120.:
            continue
        for family, values in found.items():
            directions = {value[0] for value in values}
            if len(directions) == 1:
                side = values[0][0]
                selected = max(values, key=lambda v: side * v[1])
                if side * (mid - selected[1]) > 0:
                    output[family].append((i, *selected))
    return {family: np.asarray(rows, float).reshape(-1, 4) for family, rows in output.items()}


def decisions(rows: np.ndarray, fraction: float, opening: float, tick: float) -> np.ndarray:
    """機能: 壁由来の入口に、判断時点で既知の始値割合幅を付ける。

    引数: rows(ndarray)、fraction/opening/tick(float)。
    返り値: 行番号・方向・固定幅・構造逆指値・壁価格の5列(ndarray)。
    """
    width = max(2. * tick, math.ceil(opening * fraction / tick - 1e-10) * tick)
    return np.column_stack((rows[:, :2], np.full(len(rows), width), rows[:, 2:]))
