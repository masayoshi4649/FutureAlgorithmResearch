"""複数玉管理を人工経路・売買反射・将来変更で独立検査する。"""

from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path
import sys

import numba
import numpy as np

from independent_account import reconstruct, near, save
from audit_all import trade_array
from paths import cases, reflect


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
LEGACY = ROOT / "work/wave_v70/engine.py"
numba.config.CACHE_DIR = str(HERE / "numba_cache")
ENGINE_SHA = hashlib.sha256(LEGACY.read_bytes()).hexdigest()
SPEC = importlib.util.spec_from_file_location("management71_independent_engine", LEGACY)
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)


def run(data: dict, symbol: str = "TOPIX", **changes: object) -> tuple:
    """機能: 独立監査の固定設定で人工原本を被検査管理器へ与える。

    引数: data(dict)、symbol(str)、changes(dict)。返り値: 結果と設定(tuple)。
    """
    side = int(data["signal"][0])
    anchor = data["ask"][0] if side == 1 else data["bid"][0]
    schedule = np.array([[1., 0., 0., float(side), anchor]])
    params = dict(tick=1., limit=1000., cap=10 if symbol == "TOPIX" else 20,
        value=1000. if symbol == "TOPIX" else 10., fee_unit=41.8 if symbol == "TOPIX" else 11.,
        kind=1, stop=48., activation=8., trail=8., hold_seconds=600.,
        grid=4., step_fraction=.25, cover_activation=2., cover_trail=2.,
        basket_stop=64., basket_activation=8., basket_trail=8.,
        flip_fraction=.5, partial_level=8., partial_fraction=.5,
        tighten_minutes=1., ratchet_step=8., ratchet_keep=2., grid_mode=0)
    params.update(changes)
    result = ENGINE.simulate(data["time_s"], data["bid"], data["ask"], data["signal"], schedule, **params)
    return (*result, params)


def check(data: dict, result: tuple, symbol: str) -> dict:
    """機能: 全注文と部分決済・全玉評価を被検査エンジン外で検算する。

    引数: data(dict)、result(tuple)、symbol(str)。返り値: 監査指標(dict)。
    """
    orders, trades, curve, counters, _ = result
    account, other_curve = reconstruct(data, dict(symbol=symbol, session="人工", orders=orders))
    np.testing.assert_allclose(curve, other_curve, rtol=0, atol=1.e-4)
    np.testing.assert_allclose(trades, trade_array(account["details"]), rtol=0, atol=1.e-4)
    assert counters[0] == account["max_long"] and counters[1] == account["max_short"]
    assert counters[2] == counters[3] == 0 and counters[5] == 1
    return account


def core_oracle(data: dict, params: dict) -> tuple[int, int, int]:
    """機能: 保険なしの最初の返済判断を独立 Python 状態機械で算出する。

    引数: data/params(dict)。返り値: 判断行・約定行・理由(tuple[int,int,int])。
    """
    side = int(data["signal"][0])
    anchor = float(data["ask"][0] if side == 1 else data["bid"][0])
    opened = 1
    started = False
    extreme = 0.
    valid = np.isfinite(data["bid"]) & np.isfinite(data["ask"]) & (data["bid"] > 0) & (data["ask"] >= data["bid"])
    for i in range(opened + 1, len(data["bid"])):
        reason = 0
        if data["time_s"][i] >= params["limit"] - 60:
            reason = 4
        elif data["time_s"][i] - data["time_s"][opened] >= params["hold_seconds"]:
            reason = 3
        elif valid[i]:
            close = float(data["bid"][i] if side == 1 else data["ask"][i])
            advance = side * (close - anchor) / params["tick"]
            if advance <= -params["stop"]:
                reason = 1
            else:
                if not started and advance >= params["activation"]:
                    started, extreme = True, close
                if started:
                    if side * (close - extreme) > 0:
                        extreme = close
                    if side * (close - extreme) <= -params["trail"] * params["tick"]:
                        reason = 2
        if reason:
            following = np.flatnonzero(valid & (np.arange(len(valid)) > i))
            assert len(following)
            return i, int(following[0]), reason
    raise AssertionError("人工経路で返済なし")


def synthetic() -> list[dict]:
    """機能: 六管理系と九価格経路を売買反射・別会計・子判断で検査する。

    引数: なし。返り値: 合格した検査記録(list[dict])。
    """
    records = []
    for symbol in ("TOPIX", "NK225"):
        for name, data in cases().items():
            for kind in range(6):
                for grid_mode in ((0, 1) if kind in (1, 2) else (0,)):
                    original = run(data, symbol, kind=kind, grid_mode=grid_mode)
                    account = check(data, original, symbol)
                    reflection = run(reflect(data), symbol, kind=kind, grid_mode=grid_mode)
                    reverse_account = check(reflect(data), reflection, symbol)
                    near(account["net"], reverse_account["net"], "売買反射収支")
                    np.testing.assert_allclose(original[2], reflection[2], atol=1.e-4, rtol=0)
                    np.testing.assert_array_equal(original[0][:, :3], reflection[0][:, :3])
                    records.append(dict(銘柄=symbol, 経路=name, 管理kind=kind, grid_mode=grid_mode,
                        収支=account["net"], 最大買い=account["max_long"], 最大売り=account["max_short"],
                        注文数=len(original[0]), 部分決済数=len(original[1]), 合格=True))
            base = run(data, symbol, kind=0, basket_stop=0., basket_activation=0.)
            check(data, base, symbol)
            source, fill, reason = core_oracle(data, base[-1])
            assert int(base[0][1, 1]) == source and int(base[0][1, 0]) == fill and int(base[0][1, 6]) == reason
    return records


def causality() -> list[dict]:
    """機能: 未来価格・信号・時計の変更及び原本切断が過去を変えないと確認する。

    引数: なし。返り値: 合格した因果検査記録(list[dict])。
    """
    records = []
    for name in ("急落後回復", "同幅往復", "無効気配中断", "同秒原本更新"):
        data = cases()[name]
        for kind in range(6):
            original = run(data, kind=kind)
            cuts = sorted({int(len(data["bid"]) * fraction) for fraction in (.22, .57, .83)})
            for cut in cuts:
                truncated = {name: value[:cut].copy() for name, value in data.items()}
                altered = {name: value.copy() for name, value in data.items()}
                altered["bid"][cut:] = 500. + np.arange(len(data["bid"]) - cut)
                altered["ask"][cut:] = altered["bid"][cut:] + 3.
                altered["time_s"][cut:] = altered["time_s"][cut] + 2. * np.arange(len(data["bid"]) - cut)
                altered["signal"][cut:] = -1
                for modified in (truncated, altered):
                    result = run(modified, kind=kind)
                    np.testing.assert_array_equal(original[0][original[0][:, 0] < cut], result[0][result[0][:, 0] < cut])
                    np.testing.assert_array_equal(original[1][original[1][:, 2] < cut], result[1][result[1][:, 2] < cut])
                    np.testing.assert_allclose(original[2][:cut], result[2][:cut], atol=1.e-4, rtol=0)
            records.append(dict(経路=name, 管理kind=kind, 切断行=cuts, 過去一致=True))
    return records


def edge_cases() -> list[dict]:
    """機能: 持ち替え・不足追加・新規cut・部分料金の未到達枝を検査する。

    引数: なし。返り値: 境界経路の検査記録(list[dict])。
    """
    records = []
    data = cases()["急落後回復"]
    data["signal"][15:18] = -1
    flipped = run(data, kind=2)
    account = check(data, flipped, "TOPIX")
    assert np.any(flipped[0][:, 6] == 9), "反対信号と保険量により主方向を持ち替える"
    assert np.any(flipped[0][:, 6] == 11), "持ち替え後の不足追加"
    retained = flipped[0][(flipped[0][:, 7] == 1) & (flipped[0][:, 8] == 1)]
    assert len(retained)
    records.append(dict(検査="保険保持で持ち替え・不足追加・役割維持", 収支=account["net"], 合格=True))

    # ----------------------------------------
    # 発注判断はcut前でも、有効気配が戻った時にcut後なら新規保険を取消す。
    bids = np.array([100., 100., 94., np.nan, np.nan, 94., 95., 95.])
    late = dict(bid=bids, ask=bids+1., time_s=np.array([300., 301., 698., 699., 700., 701., 940., 941.]),
        seq=np.arange(8), signal=np.array([1, 0, 0, 0, 0, 0, 0, 0], dtype=np.int8), reset=np.zeros(8, bool))
    canceled = run(late)
    check(late, canceled, "TOPIX")
    assert not np.any(canceled[0][:, 6] == 7), "cut越えの保険新規を取消"
    assert len(canceled[0]) == 2
    records.append(dict(検査="無効気配を跨いだ保険fillcut取消", 合格=True))

    rising = cases()["一方向上昇"]
    partial = run(rising, kind=3, partial_fraction=.25, basket_activation=0.)
    check(rising, partial, "TOPIX")
    cuts = partial[0][partial[0][:, 6] == 12]
    assert len(cuts) == 1 and int(cuts[0, 4]) == 3
    assert partial[1][:, 7].sum() == 418
    records.append(dict(検査="25%のceil3枚分割と累積料金全量一致", 合格=True))
    bids = np.array([100., 100., 105., 105., 105., 105.])
    line = dict(bid=bids, ask=bids+1., time_s=300.+np.arange(6), seq=np.arange(6),
        signal=np.array([1, 0, 0, 0, 0, 0], dtype=np.int8), reset=np.zeros(6, bool))
    ratchet = run(line, kind=5, activation=4., ratchet_step=4., ratchet_keep=0., basket_activation=0.)
    check(line, ratchet, "TOPIX")
    assert int(ratchet[0][1, 1]) == 3 and int(ratchet[0][1, 0]) == 4
    assert int(ratchet[0][1, 6]) == 13
    records.append(dict(検査="段階保護線の更新当行は不発動、次観測でのみ成立", 合格=True))
    return records


def main() -> None:
    """機能: 人工検査と未来不変性を実施し監査領域へ結果保存する。

    引数: なし。返り値: なし(None)。
    """
    artificial = synthetic()
    past = causality()
    edges = edge_cases()
    assert hashlib.sha256(LEGACY.read_bytes()).hexdigest() == ENGINE_SHA
    save(HERE / "人工経路と因果検査.json", dict(合格=True, 人工経路=artificial, 因果検査=past,
        人工数=len(artificial), 売買反射数=len(artificial), 保険なし独立子判定数=18,
        途中切断と未来変更組数=len(past) * 3 * 2, 境界検査=edges, engine_SHA256=ENGINE_SHA))
    print(f"人工 {len(artificial)} + 売買反射同数 + 因果 {len(past)}×3×2 + 境界 {len(edges)} 合格", flush=True)


if __name__ == "__main__":
    main()
