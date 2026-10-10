"""二市場特徴・共同状態・再準備pulse・発注写像を人工入力で独立検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
import numba

from dual_fixtures import paired_cases, one_side_future, cut_one_side, swap
from independent_account import save
from sync_oracle import asof_fast


HERE = Path(__file__).resolve().parent
os.environ.setdefault("NUMBA_CACHE_DIR", str(HERE / "cache"))
sys.path.insert(0, str(HERE.parent))
spec = importlib.util.spec_from_file_location("wave75_signals", HERE.parent / "signals.py")
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
numba.config.CACHE_DIR = str(HERE / "cache")


def oracle_features(grid: np.ndarray, delay: int, window: int, data: dict, max_age: int = 30) -> dict:
    """機能: 観測窓を1判断ずつ切り出して、価格・OFI・両気配確認を別計算する。

    引数: grid(np.ndarray)、delay/window/max_age(int)、data(dict)。返り値: 特徴辞書(dict)。
    """
    n = len(grid)
    if not len(data["time_s"]):
        return dict(now=np.full(n, -1), old=np.full(n, -1), short=np.full(n, -1), valid=np.zeros(n, bool),
            mid=np.full(n, np.nan), ret=np.full(n, np.nan), short_ret=np.full(n, np.nan), flow=np.full(n, np.nan),
            fast_flow=np.full(n, np.nan), confirmation=np.zeros(n, np.int8))
    good = data["valid"] & np.isfinite(data["bid"]) & np.isfinite(data["ask"]) & (data["bid"] > 0) & (data["ask"] > data["bid"]) & (data["ask"] - data["bid"] <= 2 * data["tick"] + 1.e-9)
    out = {name: asof_fast(grid - delay - lag, data["time_s"], good, data["reset"], max_age)[0]
        for name, lag in (("now", 0), ("old", window), ("short", 15))}
    out.update(valid=np.zeros(n, bool), confirmation=np.zeros(n, np.int8))
    for name in ("mid", "ret", "short_ret", "flow", "fast_flow"):
        out[name] = np.full(n, np.nan)
    for i in range(n):
        now, old, short = (int(out[name][i]) for name in ("now", "old", "short"))
        if min(now, old, short) < 0 or not old < now or not short < now:
            continue
        if np.any(data["reset"][old + 1:now + 1] | ~data["valid"][old + 1:now + 1]) or np.any(data["reset"][short + 1:now + 1] | ~data["valid"][short + 1:now + 1]):
            continue
        if not np.isfinite(data["best_ofi"][old + 1:now + 1]).all() or not np.isfinite(data["best_ofi"][short + 1:now + 1]).all():
            continue
        out["valid"][i] = True
        out["mid"][i] = data["mid"][now]
        out["ret"][i] = (data["mid"][now] / data["mid"][old] - 1.) * 10000.
        out["short_ret"][i] = (data["mid"][now] / data["mid"][short] - 1.) * 10000.
        for origin, name in ((old, "flow"), (short, "fast_flow")):
            flow = data["best_ofi"][origin + 1:now + 1]
            denominator = float(np.sum(np.abs(flow)))
            out[name][i] = float(np.sum(flow) / denominator) if denominator > 0 else 0.
        bid = (data["bid"][now] - data["bid"][short]) / data["tick"]
        ask = (data["ask"][now] - data["ask"][short]) / data["tick"]
        out["confirmation"][i] = 1 if min(bid, ask) >= 1. - 1.e-8 else -1 if max(bid, ask) <= -1. + 1.e-8 else 0
    return out


def oracle_conditions(own: dict, peer: dict, window: int, level: int, paired: bool) -> tuple[np.ndarray, np.ndarray]:
    """機能: 七仮説の日本語条件を1行ずつ別実装で採点する。

    引数: own/peer(dict)、window/level(int)、paired(bool)。返り値: 七状態と有効性(tuple)。
    """
    n = len(own["valid"])
    states = np.zeros((7, n), np.int8)
    valid = own["valid"] & peer["valid"]
    threshold, pressure = (3., .10) if level == 0 else (6., .20)
    history = max(16, window * 4 // 15)
    for row in range(n):
        if not valid[row]:
            continue
        own_return, other_return = own["ret"][row], peer["ret"][row]
        for d in (-1, 1):
            progress, failure = own["confirmation"][row] == d, own["confirmation"][row] == -d
            if d * own_return >= threshold and progress and (not paired or d * other_return >= threshold and d * peer["short_ret"][row] >= 0):
                states[0, row] = d
            if abs(own_return) <= threshold / 2 and progress and (not paired or d * other_return >= threshold and d * peer["short_ret"][row] >= 0):
                states[1, row] = d
            if d * own_return >= threshold and failure and (not paired or d * other_return < threshold / 2 and d * peer["short_ret"][row] <= 0):
                states[2, row] = -d
            if d * own["flow"][row] >= pressure and abs(own_return) < threshold and progress and (not paired or d * peer["flow"][row] >= pressure and abs(other_return) < threshold and d * peer["short_ret"][row] >= 0):
                states[4, row] = d
            if d * own["flow"][row] >= pressure and abs(own_return) < threshold / 2 and failure and d * own["fast_flow"][row] < 0 and (not paired or d * peer["flow"][row] >= pressure and d * other_return >= threshold):
                states[5, row] = -d
        if row >= history and np.all(valid[row - history:row + 1]):
            x = np.log(own["mid"][row - history:row + 1])
            y = np.log(peer["mid"][row - history:row + 1])
            spread = x - y if paired else x
            center = float(np.mean(spread[:-1]))
            scale = float(np.std(spread[:-1], ddof=1))
            if scale > 1.e-12:
                current, previous = (spread[-1] - center) / scale, (spread[-2] - center) / scale
                side = -1 if current > 0 else 1
                qualifies = abs(current) >= (1.5 if level == 0 else 2.5) and current * previous > 0 and abs(current) < abs(previous) and own["confirmation"][row] == side
                if paired:
                    dx, dy = np.diff(x[:-1]), np.diff(y[:-1])
                    if np.std(dx) * np.std(dy) <= 1.e-20:
                        qualifies = False
                    else:
                        qualifies &= float(np.corrcoef(dx, dy)[0, 1]) >= .3
                if qualifies:
                    states[3, row] = side
        states[6, row] = states[0, row] or states[1, row] or states[3, row]
    return states, valid


def oracle_pulse(grid: np.ndarray, state: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """機能: 有効中立の連続60秒と発火間隔600秒を1状態ずつ独立に追跡する。

    引数: grid/state/valid(np.ndarray)。返り値: 新規イベント(np.ndarray[int8])。
    """
    output = np.zeros(len(grid), np.int8)
    allowed, began, fired = True, None, None
    for row in range(len(grid)):
        if row and grid[row] - grid[row - 1] > 15. + 1.e-7:
            began = None
        if not valid[row]:
            began = None
            continue
        if state[row] == 0:
            began = grid[row] if began is None else began
            if grid[row] - began >= 60.:
                allowed = True
        else:
            began = None
            if allowed and (fired is None or grid[row] - fired >= 600.):
                output[row], allowed, fired = state[row], False, grid[row]
    return output


def oracle_map(grid: np.ndarray, pulse: np.ndarray, own: dict, peer: dict, data: dict) -> np.ndarray:
    """機能: 発火時計以降の最初原本行と品質・遅れを逐次検索する。

    引数: grid/pulse(np.ndarray)、own/peer/data(dict)。返り値: 五列候補(np.ndarray)。
    """
    output = []
    for row in np.flatnonzero(pulse):
        later = np.flatnonzero(data["time_s"] >= grid[row])
        if not len(later):
            continue
        selected = int(later[0])
        if data["time_s"][selected] - grid[row] > 10. or data["time_s"][selected] >= data["limit"] - 300.:
            continue
        if not data["valid"][selected] or data["reset"][selected] or not data["ask"][selected] - data["bid"][selected] <= 2 * data["tick"] + 1.e-9:
            continue
        output.append([row, selected, int(pulse[row]), int(own["now"][row]), int(peer["now"][row])])
    return np.asarray(output, dtype=float).reshape((-1, 5))


def check_features(got: dict, expected: dict) -> None:
    """機能: 参照行・価格・OFI・確認方向を欠測含め一致確認する。

    引数: got/expected(dict)。返り値: なし(None)。
    """
    for field in expected:
        if field in ("mid", "ret", "short_ret", "flow", "fast_flow"):
            np.testing.assert_allclose(got[field], expected[field], atol=1.e-8, rtol=0, equal_nan=True, err_msg=field)
        else:
            np.testing.assert_array_equal(got[field], expected[field], err_msg=field)


def main() -> None:
    """機能: 人工二市場の全特徴と七状態・pulse・写像・片側未来を照合する。

    引数: なし。返り値: なし(None)。実損益は一切読まない。
    """
    cases = paired_cases()
    feature_checks = state_checks = pulse_checks = map_checks = future_checks = swap_checks = 0
    pulse_count = 0
    for name, markets in cases.items():
        start, limit = markets["NK225"]["start"], markets["NK225"]["limit"]
        grid = np.arange(start + 300., limit - 300., 15.)
        for delay in (1, 5, 15, 60):
            for window in (60, 300):
                stats = {}
                for symbol, data in markets.items():
                    got = model.features(grid, delay, window, 30, data, data)
                    expected = oracle_features(grid, delay, window, data)
                    check_features(got, expected)
                    stats[symbol] = got
                    feature_checks += 1
                for symbol in ("TOPIX", "NK225"):
                    peer = "NK225" if symbol == "TOPIX" else "TOPIX"
                    for level in (0, 1):
                        for paired in (True, False):
                            result, valid = model.conditions(stats[symbol], stats[peer], window, level, paired)
                            expected = oracle_conditions(stats[symbol], stats[peer], window, level, paired)
                            np.testing.assert_array_equal(result, expected[0])
                            np.testing.assert_array_equal(valid, expected[1])
                            state_checks += 7
                            for family in range(7):
                                pulse = model.event_pulses(grid, result[family], valid)
                                np.testing.assert_array_equal(pulse, oracle_pulse(grid, result[family], valid))
                                pulse_checks += 1
                                pulse_count += int(np.count_nonzero(pulse))
                                mapped = model.map_pulses(grid, pulse, stats[symbol], stats[peer], markets[symbol], markets[symbol])
                                np.testing.assert_array_equal(mapped, oracle_map(grid, pulse, stats[symbol], stats[peer], markets[symbol]))
                                map_checks += 1
                cutoff = start + 1800.
                earlier = grid <= cutoff
                for changed_symbol in ("TOPIX", "NK225"):
                    for changed in (one_side_future(markets, changed_symbol, cutoff), cut_one_side(markets, changed_symbol, cutoff)):
                        new_stats = {symbol: model.features(grid, delay, window, 30, data, data) for symbol, data in changed.items()}
                        for symbol in ("TOPIX", "NK225"):
                            peer = "NK225" if symbol == "TOPIX" else "TOPIX"
                            for level in (0, 1):
                                for paired in (True, False):
                                    before = model.conditions(stats[symbol], stats[peer], window, level, paired)
                                    after = model.conditions(new_stats[symbol], new_stats[peer], window, level, paired)
                                    np.testing.assert_array_equal(before[0][:, earlier], after[0][:, earlier])
                                    np.testing.assert_array_equal(before[1][earlier], after[1][earlier])
                                    for family in range(7):
                                        old_pulse = model.event_pulses(grid, before[0][family], before[1])
                                        new_pulse = model.event_pulses(grid, after[0][family], after[1])
                                        np.testing.assert_array_equal(old_pulse[earlier], new_pulse[earlier])
                                    future_checks += 1
                swapped = swap(markets)
                swapped_stats = {symbol: model.features(grid, delay, window, 30, data, data) for symbol, data in swapped.items()}
                for level in (0, 1):
                    for paired in (True, False):
                        old = model.conditions(stats["TOPIX"], stats["NK225"], window, level, paired)
                        new = model.conditions(swapped_stats["NK225"], swapped_stats["TOPIX"], window, level, paired)
                        np.testing.assert_array_equal(old[0], new[0])
                        np.testing.assert_array_equal(old[1], new[1])
                        swap_checks += 1
    irregular_grid = np.r_[np.arange(0., 180., 15.), np.arange(225., 900., 15.)]
    signs = np.zeros(len(irregular_grid), np.int8)
    signs[:2] = 1
    signs[12:18] = -1
    signs[-2:] = 1
    valid = np.ones(len(irregular_grid), bool)
    valid[5] = False
    np.testing.assert_array_equal(model.event_pulses(irregular_grid, signs, valid), oracle_pulse(irregular_grid, signs, valid))
    save(HERE / "二市場モデルの人工状態と片側未来の独立監査.json", dict(合格=True,
        signals_SHA256=hashlib.sha256((HERE.parent / "signals.py").read_bytes()).hexdigest(),
        人工経路数=len(cases), 特徴独立比較数=feature_checks, 状態独立比較数=state_checks,
        pulse独立比較数=pulse_checks + 1, 原本行写像独立比較数=map_checks, 発火イベント合計=pulse_count,
        片側未来切断及び改変比較数=future_checks, 銘柄交換比較数=swap_checks,
        検査=["空市場", "全空", "片側停止", "方向矛盾", "日跨ぎ", "同時計先頭", "過去OFI窓", "過去だけの相対平均分散", "七状態", "有効中立60秒", "pulse600秒", "invalidで再準備しない", "原本行へ遡及しない", "片側future", "symbol swap"],
        原本取得=0, API取得=0, 実注文=0, 実損益閲覧=0))
    print(json.dumps(dict(合格=True, 特徴独立比較数=feature_checks, 状態独立比較数=state_checks, pulse独立比較数=pulse_checks, 片側future比較数=future_checks), ensure_ascii=False))


if __name__ == "__main__":
    main()
