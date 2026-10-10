"""新規以前の根拠、次行効力、数量枠、料金後休止を人工経路で独立点検する。"""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sys

os.environ["NUMBA_DISABLE_JIT"] = "1"
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK))
import risk_replay as risk


def simulate(prices: list[float], control: dict, *, directions: list[int] | None = None,
             times: list[float] | None = None, bad_from: int = -1, bad_source: int = -1,
             ema_from: int = -1, ema_source: int = -1, maximum: int = 1,
             changes: dict | None = None, reflect: bool = False) -> tuple[dict, dict]:
    """機能: 完結した人工価格・公開根拠の列で影と実枠の注文を生成する。

    引数: prices/times(list[float])、control/changes(dict)、directions(list[int]|None)、
    bad_from/bad_source/ema_from/ema_source/maximum(int)、reflect(bool)。
    返り値: 実結果と影結果(tuple[dict,dict])。
    """
    n = len(prices)
    price = np.asarray(prices, float)
    state = np.asarray(directions if directions is not None else [1] * n, np.int8)
    sign = -1 if reflect else 1
    if reflect:
        price = 200.0 - price
        state = -state
    time = np.asarray(times if times is not None else np.arange(n), float)
    atr = np.full(n, 4.0)
    config = {name: 0.0 for name in risk.shadow_engine.PARAMS}
    config.update(initial_qty=5.0, entry_atr=.25, stop_atr=.75, main_trail=3.0,
        split_target=2.0, timeout_min=360.0, activation_atr=1.5, tighten_atr=3.0,
        tight_width=.75, cooldown_min=5.0, ttl_seconds=300.0, entry_mode=1.0,
        after_open_factor=1.0, audit_cap=10)
    config.update(changes or {})
    ready = dict(time_s=time, last=price, atr=atr, tick=1.0, start=0.0,
                 limit=float(time[-2]), us_open=1.0e20, session_close=float(time[-1] + 10))
    shadow = risk.shadow_run(ready, state, config, np.ones(n, bool))
    zero = np.zeros(n, np.int8)
    missing = np.full(n, -1, np.int64)
    invalid = np.zeros(n, bool)
    raw, raw_source, raw_valid = zero.copy(), missing.copy(), invalid.copy()
    if bad_from >= 0:
        raw[bad_from:] = -sign
        raw_source[bad_from:] = bad_source
        raw_valid[bad_from:] = True
    ema, ema_src = state.copy(), missing.copy()
    if ema_from >= 0:
        ema[ema_from:] = 0
        ema_src[ema_from:] = ema_source
    values = risk.engine.simulate(time, price, shadow["plans"], shadow["execution_plans"],
        shadow["atr_curve"], zero, missing, zero, missing, invalid,
        ready["limit"], 0.0, 5, 10, 3, .5, 0, maximum, 120.0,
        True, True, True, 0.0, zero, missing, invalid, zero, 0, -1,
        risk.control_parameters(control, "TOPIX"), raw, raw_source, raw_valid, ema, ema_src)
    fields = risk.engine.FIELDS + ("control_curve", "slot_curve", "slot_events", "adjustment_events",
                                  "budget_events", "branch_events", "branch_curve", "risk_events")
    return dict(zip(fields, values)), shadow


def confirm_inventory(result: dict) -> None:
    """機能: 全返済、建玉保存、次行注文と元建値の損益を独立確認する。

    引数: result(dict)。返り値: なし(None)。
    """
    inventory = 0
    gross = 0.0
    entry = {}
    for order in result["orders"]:
        row, source, campaign, side, quantity, price, _, new = order
        assert 0 <= source < row
        inventory += int(quantity) if new else -int(quantity)
        assert 0 <= inventory <= 5
        if new:
            entry[int(campaign)] = (side, quantity, price)
    for trade in result["trades"]:
        side, _, price = entry[int(trade[0])]
        assert side == trade[2] and price == trade[4]
        value = trade[3] * side * (trade[5] - price)
        assert abs(value - trade[10]) < 1.0e-9
        gross += value
    assert inventory == 0 and result["stats"][9] == 0
    assert abs(gross - result["stats"][0]) < 1.0e-9
    assert result["stats"][6] < 1.0e-8


def main() -> None:
    """機能: 損失制御を利益と無関係な小経路で反証し証跡を保存する。

    引数: なし。返り値: なし(None)。
    """
    tests = []
    half = dict(bad=1, bad_mfe=1.5, bad_loss=.25)
    path = [100, 101, 100, 99, 103, 109, 110, 104, 104, 104]
    for reflected in (False, True):
        result, shadow = simulate(path, half, bad_from=2, bad_source=2, reflect=reflected)
        confirm_inventory(result)
        orders = result["orders"]
        reduction = orders[orders[:, 6] == 50]
        assert len(reduction) == 1 and reduction[0, 0] == 3 and reduction[0, 1] == 2
        assert reduction[0, 4] == 2
        assert not np.any(orders[:, 6] == 7), "既減量枠に対応する影利確は実玉を追加返済しない"
        assert orders[-1, 4] == 3
        assert result["stats"][0] == 5.0
        assert shadow["stats"][0] == 25.0
        tests.append(dict(検査="新しい悪化→次行半減→影2ATR利確で二重返済なし", ショート=reflected,
                          合格=True, 実損益=5.0, 影損益=25.0, 注文=orders.tolist()))

    for source in (0, 1):
        result, _ = simulate(path, half, bad_from=2, bad_source=source)
        confirm_inventory(result)
        assert not np.any(result["orders"][:, 6] == 50)
        tests.append(dict(検査="新規以前／新規行の古い根拠を拒否", 根拠行=source, 合格=True))

    result, _ = simulate(path, half, bad_from=2, bad_source=2, maximum=3)
    assert np.count_nonzero(result["orders"][:, 6] == 50) == 1
    confirm_inventory(result)
    tests.append(dict(検査="3回許可しても同じ根拠の保持を再減量と数えない", 合格=True))

    for reflected in (False, True):
        result, shadow = simulate(path, dict(bad=2, bad_mfe=.5, bad_loss=.25),
                                  bad_from=2, bad_source=2, reflect=reflected)
        confirm_inventory(result)
        orders = result["orders"]
        assert len(orders) == 2 and orders[-1, 0] == 3 and orders[-1, 4] == 5
        assert orders[-1, 6] == 50 and result["stats"][0] == -10.0
        assert shadow["stats"][0] == 25.0
        tests.append(dict(検査="早期全返済後の影利確を実損益に加えない", ショート=reflected,
                          合格=True, 実損益=-10.0, 影損益=25.0))

    time_path = [100, 101, 100, 100, 99, 100, 100, 100]
    times = [0, 1, 300, 301, 302, 303, 304, 305]
    for action, qty in ((1, 2), (2, 5)):
        result, _ = simulate(time_path, dict(time=300., time_mfe=.5, time_loss=.25, time_action=action), times=times)
        confirm_inventory(result)
        changed = result["orders"][result["orders"][:, 6] == 51]
        assert len(changed) == 1 and changed[0, 0] == 4 and changed[0, 1] == 3 and changed[0, 4] == qty
        tests.append(dict(検査="5分直前は維持、5分到達後の次行で失敗整理", 行動=action, 返済枚数=qty, 合格=True))

    result, _ = simulate([100, 101, 103, 100, 100, 100, 100], dict(bad=2, bad_mfe=.5, bad_loss=.25),
                         bad_from=3, bad_source=3)
    confirm_inventory(result)
    assert not np.any(result["orders"][:, 6] == 50)
    tests.append(dict(検査="過去MFEが丁度0.5ATRなら0.5ATR未達条件に該当しない", 合格=True))

    # ----------------------------------------
    # 競合時は元返済を優先し、早期整理と実損失予算で異なる取消仕様を確認する。
    conflict = [100, 101, 100, 109, 100, 100, 100]
    for action in (1, 2):
        result, shadow = simulate(conflict, dict(bad=action, bad_mfe=1.5, bad_loss=.25),
                                  bad_from=2, bad_source=2)
        confirm_inventory(result)
        assert not np.any(result["orders"][:, 6] == 50)
        original_split = result["orders"][result["orders"][:, 6] == 7]
        assert len(original_split) == 1 and original_split[0, 0] == 3 and original_split[0, 4] == 2
        assert result["stats"][0] == shadow["stats"][0] == 13.0
        tests.append(dict(検査="元2ATR部分利確が早期整理を取消し古いbadを再利用しない",
                          行動=action, 合格=True, 実損益=13.0))

    result, _ = simulate(conflict, dict(ema=1, ema_loss=.25), ema_from=2, ema_source=2)
    confirm_inventory(result)
    ema_exits = result["orders"][result["orders"][:, 6] == 52]
    assert len(ema_exits) == 1 and ema_exits[0, 0] == 5 and ema_exits[0, 1] == 4
    assert ema_exits[0, 4] == 3
    tests.append(dict(検査="元利確はEMA撤退を取消すが持続失効と再逆行で翌行予約し直す",
                      合格=True, EMA公開行=2, 再予約行=4, 実返済行=5))

    result, _ = simulate([100, 101, 99, 109, 110, 110, 110], dict(risk=.5))
    confirm_inventory(result)
    assert result["orders"][:, 6].astype(int).tolist() == [20, 7, 32]
    assert result["orders"][:, 4].astype(int).tolist() == [5, 2, 3]
    assert result["orders"][:, 0].astype(int).tolist() == [1, 3, 4]
    tests.append(dict(検査="実予算予約は元部分利確の翌行にも維持し残3枚を返済", 合格=True))

    for source, expected in ((-1, 0), (1, 0), (2, 1)):
        result, _ = simulate(path, dict(ema=1, ema_loss=.25), ema_from=2, ema_source=source)
        confirm_inventory(result)
        assert np.count_nonzero(result["orders"][:, 6] == 52) == expected
        tests.append(dict(検査="EMA失効は新規後の公開根拠だけを利用", 根拠行=source, 撤退回数=expected, 合格=True))

    for stop in (.75, .5, .375):
        result, _ = simulate([100, 101, 90, 90, 90, 90], {}, changes=dict(stop_atr=stop))
        confirm_inventory(result)
        assert result["stats"][0] == -55.0 and result["cycles"][0, 4] == 20.0
        tests.append(dict(検査="狭い停止幅でも次観測の飛び越えは残る、R分母を変更しない", 幅=stop,
                          合格=True, 実損益=-55.0, 固定R=20.0))

    result, _ = simulate([100, 101, 99, 99, 99, 99], dict(risk=.5))
    confirm_inventory(result)
    assert result["orders"][-1, 0] == 3 and result["orders"][-1, 1] == 2
    assert result["orders"][-1, 6] == 32
    assert result["stats"][0] == -10.0
    fees = sum(418 * int(o[4]) // 10 for o in result["orders"])
    assert fees == 418
    tests.append({"検査": "A50は支払済み料金込みの次行判断、返済料金で最終0.5Rを超える",
                  "合格": True, "料金前円": -10000, "料金後円": -10418, "0.5R円": 10000})

    # ----------------------------------------
    # 通常影に3組目があっても、実2連敗後の休止は実3組目を抑止する。
    prices = [100, 101, 97, 97, 100, 101, 97, 100, 101, 97, 100, 101, 109, 109, 109, 109]
    times = [0, 1, 2, 3, 304, 305, 306, 607, 608, 609, 2200, 2201, 2202, 2203, 2504, 2505]
    result, shadow = simulate(prices, dict(streak=2, pause=1800.), times=times)
    confirm_inventory(result)
    entry_rows = result["orders"][result["orders"][:, 7] == 1, 0].astype(int).tolist()
    assert entry_rows == [1, 5, 11], entry_rows
    assert shadow["orders"][shadow["orders"][:, 7] == 1, 0].astype(int).tolist() == [1, 5, 8, 11]
    tests.append(dict(検査="料金後2連敗で30分休止し、その後の通常影準備で再開", 合格=True, 実新規行=entry_rows))

    prices = [100, 101, 101, 101, 101, 100, 100, 100, 100, 101, 101, 101]
    times = [0, 1, 2, 3, 304, 305, 306, 307, 608, 609, 610, 611]
    state = [1, 1, -1, -1, -1, -1, 1, 1, 1, 1, -1, -1]
    result, shadow = simulate(prices, dict(streak=2, pause=-1.), directions=state, times=times,
                              changes=dict(signal_exit=1.))
    confirm_inventory(result)
    assert len(result["cycles"]) == 2 and all(result["cycles"][:, 3] == 0)
    assert len(shadow["cycles"]) == 3
    tests.append(dict(検査="価格損益0でも料金後赤字の2組を連敗と数える", 合格=True,
                      実組数=2, 実料金前=0.0))

    packet = dict(全合格=True, 検査数=len(tests), 検査=tests,
                  注記="人工列による実装検査。利益条件の選定、過適合、mini/micro実約定を保証しない。",
                  実装SHA256={p.name: sha256(p.read_bytes()).hexdigest() for p in
                      (WORK / "loss_engine.py", WORK / "loss_shadow.py", WORK / "risk_replay.py", Path(__file__))})
    (HERE / "人工経路の独立検査.json").write_text(json.dumps(packet, ensure_ascii=False, allow_nan=False,
                                                         indent=2), encoding="utf-8")
    print(json.dumps(dict(全合格=True, 検査数=len(tests)), ensure_ascii=False))


if __name__ == "__main__":
    main()
