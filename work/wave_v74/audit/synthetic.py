"""方向制限・連敗休止・次観測約定を人工経路と未来切断で独立検査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import numpy as np

from adapters import check
from fixtures import cases, prefix, reflect
from independent_account import CAP, POINT, save


HERE = Path(__file__).resolve().parent
os.environ.setdefault("NUMBA_CACHE_DIR", str(HERE / "cache"))
spec = importlib.util.spec_from_file_location("wave74_engine", HERE.parent / "engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def historical(data: dict, seconds: float) -> np.ndarray:
    """機能: 過去観測を逐次検索して高速実装と独立に照合する。

    引数: data(dict)、seconds(float)。返り値: 過去行番号(np.ndarray)。
    """
    times, reset = data["time_s"], data["reset"]
    out = np.full(len(times), -1, dtype=np.int64)
    boundary = 0
    for row in range(len(times)):
        if reset[row] or row and times[row] < times[row - 1]:
            boundary = row
        eligible = np.flatnonzero(times[boundary:row] <= times[row] - seconds)
        if len(eligible):
            out[row] = boundary + eligible[-1]
    return out


def direction(data: dict, lag: np.ndarray, mode: int, inverse: bool, open_known: int = 0, previous_known: int = 0) -> np.ndarray:
    """機能: 価格基準ごとに利用可能性を独立判定する。

    引数: data(dict)、lag(np.ndarray)、mode(int)、inverse(bool)、各known(int)。
    返り値: 許可方向(np.ndarray[int8])。人工検査では中立帯を0とする。
    """
    out = np.zeros(len(data["mid"]), dtype=np.int8)
    for row, value in enumerate(data["mid"]):
        if not np.isfinite(value) or value <= 0:
            continue
        opening = int(np.sign(value - data["opening"])) if row >= open_known and np.isfinite(data["opening"]) and data["opening"] > 0 else 0
        previous = int(np.sign(value - data["previous"])) if row >= previous_known and np.isfinite(data["previous"]) and data["previous"] > 0 else 0
        if mode == 0:
            result = opening
        elif mode == 1:
            result = previous
        elif mode == 2:
            result = opening if opening == previous else 0
        else:
            result = int(np.sign(value - data["mid"][lag[row]])) if lag[row] >= 0 else 0
        out[row] = -result if inverse else result
    return out


def run(data: dict, symbol: str, mode: int, entry_type: int, pause_mode: int, inverse: bool = False, exit_on_reverse: bool = True) -> tuple:
    """機能: 共通の人工条件を被検査器へ渡す。

    引数: data(dict)、symbol(str)、mode/entry_type/pause_mode(int)、各bool。
    返り値: simulateの注文・決済・清算時価・休止・統計(tuple)。
    """
    lag30 = engine.historical_rows(data["time_s"], data["reset"], 30.)
    lag60 = engine.historical_rows(data["time_s"], data["reset"], 60.)
    direct = engine.make_direction(data["mid"], lag60, data["opening"], 0, data["previous"], 0, mode, 0., inverse)
    return engine.simulate(data["time_s"], data["bid"], data["ask"], data["valid"], data["reset"], direct, lag30,
        data["tick"], -300., data["limit"], CAP[symbol], POINT[symbol], 41.8 if symbol == "TOPIX" else 11.,
        4., 2., entry_type, pause_mode, exit_on_reverse, 3600., 30., 30.)


def pause_rules(data: dict, result: tuple, direct: np.ndarray, lag30: np.ndarray, entry_width: float, pause_mode: int) -> int:
    """機能: 連敗は料金後の全決済だけで数え、休止中の新規と再開証拠を検査する。

    引数: data(dict)、result(tuple)、direct/lag30(np.ndarray)、entry_width(float)、pause_mode(int)。
    返り値: 確認した休止イベント数(int)。
    """
    orders, trades, _, pauses, _ = result
    by_exit = {int(trade[2]): float(trade[10]) for trade in trades}
    by_event = {int(event[0]): event for event in pauses}
    streak = 0
    active = False
    paused_at = None
    for row in range(len(data["time_s"])):
        if row in by_exit:
            net = by_exit[row]
            streak = streak + 1 if net < 0 else 0 if net > 0 else streak
        if row in by_event:
            event = by_event[row]
            assert int(event[2]) == pause_mode and int(event[4]) == streak
            if event[1] == 0:
                assert not active and streak >= (3 if pause_mode == 5 else 2)
                active, paused_at = True, row
            else:
                assert active and paused_at is not None
                now, start = data["time_s"][row], data["time_s"][paused_at]
                wait = 600. if pause_mode in (1, 4) else 1800. if pause_mode in (2, 5) else 0.
                assert now - start >= wait
                if pause_mode in (3, 4):
                    pause_side, extreme, extreme_time = 0, 0., start
                    for observed in range(paused_at, row + 1):
                        d = int(direct[observed])
                        quote_ok = np.isfinite(data["bid"][observed]) and np.isfinite(data["ask"][observed]) and data["bid"][observed] > 0 and data["ask"][observed] >= data["bid"][observed]
                        if not quote_ok or not data["valid"][observed] or data["reset"][observed] or d == 0:
                            pause_side, extreme_time = 0, data["time_s"][observed]
                            continue
                        mid = (data["bid"][observed] + data["ask"][observed]) / 2.
                        if d != pause_side or d * (mid - extreme) < -data["tick"] * 1.e-8:
                            pause_side, extreme, extreme_time = d, mid, data["time_s"][observed]
                    d, old = int(direct[row]), int(lag30[row])
                    mid = (data["bid"][row] + data["ask"][row]) / 2.
                    assert pause_side == d != 0 and now - extreme_time >= 30.
                    assert d * (mid - extreme) >= entry_width - data["tick"] * 1.e-8
                    assert old >= 0 and d * (data["bid"][row] - data["bid"][old]) >= data["tick"] - 1.e-8
                    assert d * (data["ask"][row] - data["ask"][old]) >= data["tick"] - 1.e-8
                active, streak, paused_at = False, 0, None
        for order in orders:
            if order[7] == 1 and int(order[1]) == row:
                assert not active, ("休止中の新規判断", order)
    return len(pauses)


def invariants(data: dict, symbol: str, result: tuple, direct: np.ndarray, pause_mode: int) -> dict:
    """機能: 約定、売買対称性以外の全行会計と発注理由を独立照合する。

    引数: data(dict)、symbol(str)、result(tuple)、direct(np.ndarray)、pause_mode(int)。
    返り値: 注文数等の検査件数(dict)。
    """
    orders, trades, curve, pauses, stats = result
    account = check(data, symbol, orders, trades, curve, True)
    assert stats[0] == stats[1] == 0
    by_cid = {int(trade[0]): trade for trade in trades}
    qok = np.isfinite(data["bid"]) & np.isfinite(data["ask"]) & (data["bid"] > 0) & (data["ask"] >= data["bid"])
    for order in orders:
        fill, decision, cid, side, amount, price, reason, opened = order
        fill, decision, cid, side, reason = map(int, (fill, decision, cid, side, reason))
        assert amount == CAP[symbol]
        if opened:
            assert side == int(direct[decision]) and data["valid"][decision] and not data["reset"][decision]
            assert data["time_s"][decision] >= 0. and data["time_s"][fill] < data["limit"] - 300.
        else:
            trade = by_cid[cid]
            entry_i, held_side, entry = int(trade[1]), int(trade[3]), float(trade[5])
            assert fill > decision > entry_i and data["time_s"][fill] < data["limit"]
            if reason == 4:
                assert data["time_s"][decision] >= data["limit"] - 60.
            elif reason == 3:
                assert data["time_s"][decision] - data["time_s"][entry_i] >= 3600.
            elif reason in (1, 2):
                observed = np.arange(entry_i + 1, decision + 1)[qok[entry_i + 1:decision + 1]]
                quotes = data["bid"][observed] if held_side == 1 else data["ask"][observed]
                peak = max(entry, float(np.max(quotes))) if held_side == 1 else min(entry, float(np.min(quotes)))
                current = data["bid"][decision] if held_side == 1 else data["ask"][decision]
                assert held_side * (current - peak) <= -4. + 1.e-8
                assert reason == (1 if abs(peak - entry) < 1.e-8 else 2)
            else:
                assert reason == 5 and direct[decision] == -held_side
    count = pause_rules(data, result, direct, engine.historical_rows(data["time_s"], data["reset"], 30.), 2., pause_mode)
    return dict(注文=len(orders), 決済=len(trades), 休止イベント=count, 全手数料=account["fees"])


def main() -> None:
    """機能: 人工の全条件・対称経路・未来切断を実行し検査結果だけ保存する。

    引数: なし。返り値: なし(None)。研究損益を選定には使用しない。
    """
    inputs = cases()
    stretched = {}
    for name, data in inputs.items():
        if name != "同秒原本更新":
            wide = {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in data.items()}
            wide["time_s"] *= 4.
            wide["limit"] = float(wide["time_s"][-2] + 60.)
            stretched[name + "_長時間"] = wide
    inputs.update(stretched)
    combinations = prefix_tests = mirror_tests = order_count = trade_count = pause_count = 0
    examples = []
    for name, data in inputs.items():
        for seconds in (30., 60.):
            np.testing.assert_array_equal(engine.historical_rows(data["time_s"], data["reset"], seconds), historical(data, seconds))
        lag60 = historical(data, 60.)
        for mode in range(4):
            for inverse in (False, True):
                expected = direction(data, lag60, mode, inverse)
                actual = engine.make_direction(data["mid"], lag60, data["opening"], 0, data["previous"], 0, mode, 0., inverse)
                np.testing.assert_array_equal(actual, expected)
            for entry_type in range(2):
                for pause_mode in range(6):
                    for symbol in CAP:
                        result = run(data, symbol, mode, entry_type, pause_mode)
                        check_count = invariants(data, symbol, result, direction(data, lag60, mode, False), pause_mode)
                        combinations += 1
                        order_count += check_count["注文"]
                        trade_count += check_count["決済"]
                        pause_count += check_count["休止イベント"]
                        mirrored = run(reflect(data), symbol, mode, entry_type, pause_mode)
                        np.testing.assert_allclose(mirrored[2], result[2], atol=1.e-4, rtol=0)
                        np.testing.assert_array_equal(mirrored[0][:, :3], result[0][:, :3])
                        np.testing.assert_array_equal(mirrored[0][:, 3], -result[0][:, 3])
                        mirror_tests += 1
                        for cut in sorted(set((max(2, len(data["mid"]) // 3), max(2, len(data["mid"]) // 2), len(data["mid"]) - 1))):
                            reduced = run(prefix(data, cut), symbol, mode, entry_type, pause_mode)
                            check(prefix(data, cut), symbol, reduced[0], reduced[1], reduced[2], False)
                            for index in (0, 1, 3):
                                row_col = 2 if index == 1 else 0
                                np.testing.assert_array_equal(reduced[index], result[index][result[index][:, row_col] < cut])
                            np.testing.assert_allclose(reduced[2], result[2][:cut], atol=1.e-4, rtol=0)
                            altered = {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in data.items()}
                            altered["mid"][cut:] = 50.
                            altered["bid"][cut:] = 49.5
                            altered["ask"][cut:] = 50.5
                            changed = run(altered, symbol, mode, entry_type, pause_mode)
                            for index in (0, 1, 3):
                                row_col = 2 if index == 1 else 0
                                np.testing.assert_array_equal(reduced[index], changed[index][changed[index][:, row_col] < cut])
                            np.testing.assert_allclose(reduced[2], changed[2][:cut], atol=1.e-4, rtol=0)
                            prefix_tests += 2
                        if len(examples) < 12 and check_count["休止イベント"]:
                            examples.append(dict(経路=name, 方式=pause_mode, 入口=entry_type, 商品=symbol, イベント=result[3].tolist()))
    save(HERE / "人工経路と未来切断の独立監査.json", dict(合格=True,
        engine_SHA256=hashlib.sha256((HERE.parent / "engine.py").read_bytes()).hexdigest(),
        経路数=len(inputs), 条件口座数=combinations, 注文検査数=order_count, 決済検査数=trade_count,
        休止イベント検査数=pause_count, 売買反射数=mirror_tests, 未来切断及び改変数=prefix_tests,
        検査=["次有効原本行", "同秒原本順", "全決済料金", "未返済予定料金込み清算曲線", "フル枚数と上限", "場内全返済", "休止の料金後連敗", "収束の過去証拠", "価格基準符号", "未来切断", "将来価格の改変", "価格反射対称"],
        休止の例=examples, 原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, 条件口座数=combinations, 未来検査=prefix_tests), ensure_ascii=False))


if __name__ == "__main__":
    main()
