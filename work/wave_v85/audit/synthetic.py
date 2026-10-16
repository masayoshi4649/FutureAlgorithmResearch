"""利益保護・方向別停止・元枠の競合を損益探索なしで反証する。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

os.environ["NUMBA_DISABLE_JIT"] = "1"
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
spec = importlib.util.spec_from_file_location("wave85_strategy", WORK / "strategy.py")
strategy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = strategy
spec.loader.exec_module(strategy)


def fixture(prices, entries, exits, *, mask=0, reflected=False, fee=41.8, quantity=5,
            raw=None, ema=None, bad=None, observed=True, time_values=None, quiet=None, prepare_rows=None):
    """
    機能: 完全に既知の前行注文と当行価格を合成し、制御器だけを検査する。
    引数: prices (list[float])、entries/exits (dict)、mask/quantity (int)、reflected/observed (bool)、
          fee (float)、raw/ema/bad (tuple|None) の公開済み根拠。
    返り値: dict の注文・制御証跡。
    """
    price = np.asarray(prices, float)
    n = len(price)
    sign = -1 if reflected else 1
    if reflected:
        price = 200.0 - price
    time = np.asarray(time_values, float) if time_values is not None else np.arange(n, dtype=float) * 301.
    plans = np.full((n, 37), np.nan)
    for i, (direction, cid) in entries.items():
        plans[i] = 0.
        plans[i, 12:15] = np.nan
        plans[i, 1] = cid - 1
        plans[i, 21:25] = [direction * sign, price[i], time[-1] + 1000., 4.]
        plans[i, 25:29] = [quantity, 1, i - 1, 0]
        plans[i, 28] = cid
        plans[i, 29] = (prepare_rows or {}).get(i, i - 1)
        plans[i, 33] = i - 1
    for i, (direction, cid, reason) in exits.items():
        plans[i] = 0.
        plans[i, 0:2] = [direction * sign, cid]
        plans[i, 7] = quantity
        plans[i, 12:15] = np.nan
        plans[i, 18:20] = [reason, i - 1]
        plans[i, 33] = i - 1
    zero = np.zeros(n, np.int8)
    missing = np.full(n, -1, np.int64)
    invalid = np.zeros(n, bool)
    raw = raw if raw is not None else (zero, missing, invalid)
    bad = bad if bad is not None else (zero, missing)
    ema = ema if ema is not None else (zero, missing, missing, invalid)
    losspar = strategy.legacy.control_parameters(dict(bad=1, bad_mfe=1.5, bad_loss=.25) if mask & 4 else {}, "TOPIX")
    losspar[12] = fee
    losspar = np.r_[losspar, float(bool(mask & 2)), 1.5, .5, float(bool(mask & 8))]
    extra = (quiet['active'], quiet['force'], quiet['not_before']) if quiet is not None else ()
    result = strategy.engine.simulate(time, price, plans, plans, np.zeros((n, 12)),
        bad[0] * sign, bad[1], zero, missing, invalid, time[-1] + 600, 0., quantity, 2 * quantity,
        3, .5, 0, 1, 120., observed, True, True, 0., zero, missing, invalid, zero, 0, -1,
        losspar, raw[0] * sign, raw[1], raw[2], ema[0] * sign, ema[1], ema[2], ema[3], *extra)
    names = strategy.engine.FIELDS + ("control_curve", "slot_curve", "slot_events", "adjustment_events",
        "budget_events", "branch_events", "branch_curve", "risk_events", "guard_curve", "guard_events", "block_events", "time_events")
    value = dict(zip(names, result))
    value["price"] = price
    value["fee"] = fee
    return value


def check_cash(result, quantity=5):
    """
    機能: 注文ごとの在庫・現金と決済脚を、エンジン会計を使わず照合する。
    引数: result (dict)、quantity (int)。
    返り値: None。不一致で停止する。
    """
    held = {}
    cash = 0.
    amounts = np.zeros(len(result["price"]))
    quantities = np.zeros(len(amounts))
    maximum = 0
    for o in result["orders"]:
        i, source, cid, side, qty = map(int, o[:5])
        assert 0 <= source < i and qty > 0
        p = o[5]
        key = cid, side if o[7] else -side
        if o[7]:
            assert key not in held
            held[key] = [qty, p]
        else:
            assert key in held and held[key][0] >= qty
            held[key][0] -= qty
        cash -= side * qty * p
        amounts[i] -= side * qty * p
        quantities[i] += side * qty
        inventory = sum(v[0] for v in held.values())
        maximum = max(maximum, inventory)
        assert 0 <= inventory <= quantity
    assert not any(v[0] for v in held.values())
    assert result["stats"][9] == 0
    raw = np.cumsum(amounts) + np.cumsum(quantities) * result["price"]
    np.testing.assert_allclose(raw, result["curve"][:, 0], atol=1e-9, rtol=0)
    total = sum(t[2] * t[3] * (t[5] - t[4]) for t in result["trades"])
    assert abs(total - cash) < 1e-9
    assert abs(total - result["stats"][0]) < 1e-9
    assert maximum <= quantity


def main():
    """
    機能: P/D/Cの境界と売買反射、原版無効時を人工経路で点検する。
    引数: なし。
    返り値: None。監査JSONのみを保存する。
    """
    tests = []
    for reflected in (False, True):
        for observed in (False, True):
            for mask in range(16):
                path = [100, 100, 108, 103, 110, 111, 111]
                result = fixture(path, {1: (1, 0)}, {4: (1, 0, 7), 6: (1, 0, 9)},
                                 mask=mask, reflected=reflected, observed=observed)
                check_cash(result)
                expected = [20, 7, 70] if mask & 2 else [20, 7, 9]
                assert result["orders"][:, 6].astype(int).tolist() == expected
                assert result["orders"][:, 4].tolist() == [5, 2, 3]
                if mask & 2:
                    assert result["orders"][-1, 0] == 5 and result["orders"][-1, 1] == 3
                    assert result["guard_events"][:, 2].tolist() == [1., 2., 4., 3.]
                    assert abs(result["guard_curve"][2, 0] - (40 - .418)) < 1e-9
                tests.append(dict(検査="P予約は元部分利確後も維持、売買反射と16組合せ", 部品=mask,
                                  ショート=reflected, 観測約定=observed, 合格=True))
    # ----------------------------------------
    # 手数料と到達境界。最高利益は実口座だけで、次行飛越を保証しない。
    for fee, expected in ((0., True), (41.8, False)):
        result = fixture([100, 100, 106, 103, 100, 100], {1: (1, 0)}, {5: (1, 0, 9)}, mask=2, fee=fee)
        check_cash(result)
        assert bool(len(result["guard_events"])) == expected
        if expected:
            assert result["orders"][-1, 6] == 70 and result["orders"][-1, 5] == 100
            assert result["guard_events"][0, 5] == 30
        tests.append(dict(検査="1.5R丁度・50%丁度と料金による未達、次行価格で下限割れ", 手数料=fee, 合格=True))
    # ----------------------------------------
    # Dで消費した元枠を、元2ATR利確や後の悪化で再返済しない。
    for reflected in (False, True):
        path = [100, 100, 99, 98, 108, 109, 104, 110]
        n = len(path)
        raw = (np.array([0, 0, -1, -1, -1, -1, -1, 0], np.int8),
               np.array([-1, -1, 2, 2, 2, 2, 6, -1]), np.ones(n, bool))
        bad = (np.array([0, 0, 0, 0, 0, -1, -1, -1], np.int8),
               np.array([-1, -1, -1, -1, -1, 5, 6, 7]))
        result = fixture(path, {1: (1, 0)}, {4: (1, 0, 7), 7: (1, 0, 9)}, mask=4,
                         reflected=reflected, raw=raw, bad=bad)
        check_cash(result)
        assert result["orders"][:, 6].tolist() == [20, 50, 9]
        assert result["orders"][:, 4].tolist() == [5, 2, 3]
        tests.append(dict(検査="Dと元減量は一回枠を共有、元利確で二重返済なし", ショート=reflected, 合格=True))
        for old_source in (0, 1):
            raw2 = (raw[0], np.where(raw[1] >= 0, old_source, -1), raw[2])
            result = fixture(path, {1: (1, 0)}, {4: (1, 0, 7), 7: (1, 0, 9)}, mask=4,
                             reflected=reflected, raw=raw2)
            check_cash(result)
            assert not np.any(result["orders"][:, 6] == 50)
            tests.append(dict(検査="Dは新規以前と新規行の根拠を拒否", 元行=old_source, ショート=reflected, 合格=True))
    # ----------------------------------------
    # 方向別連敗・欠測・片市場だけ更新・解除行の発注を区別する。
    path = [100, 100, 99, 100, 99, 100, 99, 100, 100, 100, 100, 100, 100, 100, 100, 100, 101]
    n = len(path)
    direction = np.ones(n, np.int8)
    direction[10:13] = 0
    own = np.full(n, -1, np.int64)
    peer = own.copy()
    valid = np.ones(n, bool)
    own[10:] = [10, 11, 12, 13, 14, 15, 16]
    peer[10:] = [10, 6, 12, 12, 14, 15, 16]
    valid[10] = False
    for reflected in (False, True):
        result = fixture(path, {1: (1, 0), 3: (-1, 1), 5: (1, 2), 7: (1, 3),
            8: (-1, 4), 14: (1, 5), 15: (1, 6)},
            {2: (1, 0, 9), 4: (-1, 1, 9), 6: (1, 2, 9), 9: (-1, 4, 9), 16: (1, 6, 9)},
            mask=8, reflected=reflected, ema=(direction, own, peer, valid))
        check_cash(result)
        assert result["orders"][result["orders"][:, 7] == 1, 0].tolist() == [1, 3, 5, 8, 15]
        assert result["block_events"][:, 0].tolist() == [6, 12, 14]
        assert result["block_events"][:, 2].tolist() == [1, 2, 3]
        assert result["guard_curve"][10, 4 if not reflected else 5] == 1
        tests.append(dict(検査="C方向別二連敗、欠測・古い相手・片更新で解除せず、再成立の次行から許可",
                          ショート=reflected, 合格=True))
    result = dict(全合格=True, 検査数=len(tests), 検査=tests,
        実装SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                   (WORK / "engine.py", WORK / "strategy.py", WORK / "catalog.py", Path(__file__))},
        限界="固定された前行計画を用いた制御器の反証。Gの旧R01一致、原本全会計と信号切断は別検査。",
        新原本損益参照=False)
    (HERE / "四部品の人工境界監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(全合格=True, 検査数=len(tests)), ensure_ascii=False))


if __name__ == "__main__":
    main()
