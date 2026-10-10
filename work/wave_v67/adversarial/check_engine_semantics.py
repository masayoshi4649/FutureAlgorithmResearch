"""E01コピー実装の取消順序、枠減量、建値線、手数料を人工経路で点検する。"""

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
import replay
import study


def simulate(prices: list[float], directions: list[int], *, breakeven: bool = False,
             observed: bool = False) -> tuple[dict, dict]:
    """機能: 利益の選別をせず、最小の人工経路でコピー注文器を動かす。

    引数: prices(list[float])、directions(list[int])、breakeven/observed(bool)。
    返り値: 影結果と実数量結果(tuple[dict,dict])。
    """
    n = len(prices)
    price = np.asarray(prices, dtype=float)
    time = np.arange(n, dtype=float)
    atr = np.full(n, 4.0)
    state = np.asarray(directions, dtype=np.int8)
    cfg = {key: 0.0 for key in replay.original.PARAMS}
    cfg.update(initial_qty=5.0, entry_atr=0.25, stop_atr=0.75,
               main_trail=3.0, split_target=2.0, timeout_min=360.0,
               activation_atr=1.5, tighten_atr=3.0, tight_width=0.75,
               cooldown_min=5.0, ttl_seconds=300.0, entry_mode=1.0,
               after_open_factor=1.0)
    if breakeven:
        cfg.update(breakeven_atr=0.75, breakeven_floor=0.0)
    par = np.asarray([cfg[key] for key in replay.original.PARAMS])
    values = replay.original.simulate(time, price, atr, atr, state, state, 1.0,
        0.0, float(n - 2), 1.0e20, par, True, 10, 0, observed,
        np.ones(n, dtype=bool), 0.0, float(n + 10))
    shadow = dict(zip(replay.early.shadow_api.FIELDS, values))
    bad = np.zeros(n, dtype=np.int8)
    source = np.full(n, -1, dtype=np.int64)
    if breakeven:
        bad[3], source[3] = -1, 3
    zeros = np.zeros(n, dtype=np.int8)
    missing = np.full(n, -1, dtype=np.int64)
    invalid = np.zeros(n, dtype=bool)
    values = replay.partial.simulate(time, price, shadow["plans"], shadow["execution_plans"],
        shadow["atr_curve"], bad, source, zeros, missing, invalid,
        float(n - 2), 0.0, 5, 10, 3, 0.5, 0, 1, 120.0,
        observed, True, True, 0.0, zeros, missing, invalid, zeros, 0, -1)
    actual = dict(zip(replay.partial.FIELDS + (
        "control_curve", "slot_curve", "slot_events", "adjustment_events", "budget_events",
        "branch_events", "branch_curve"), values))
    return shadow, actual


def main() -> None:
    """機能: 仕様解釈が利益の見かけを変える点を、注文例とともに保存する。

    引数: なし。
    返り値: なし(None)。書込みはadversarial配下のみ。
    """
    fees = []
    for qty in range(1, 21):
        floating = int(np.floor(qty * 41.8 + 1.0e-8))
        integer = 418 * qty // 10
        assert floating == integer
        assert int(np.floor(qty * 11.0 + 1.0e-8)) == 11 * qty
        fees.append({"枚数": qty, "TOPIXmini": integer, "NKmicro": 11 * qty})

    shadow, actual = simulate([100, 101, 102, 102, 102, 102], [1, 0, 0, 0, 0, 0])
    entries = actual["orders"][actual["orders"][:, 7] == 1]
    assert len(entries) == 1 and entries[0, 0] == 1 and entries[0, 1] == 0
    cancellation = {"前行準備で当行約定後に取消": True, "新規注文": entries.tolist()}
    shadow, actual = simulate([100, 100, 101, 101, 101, 101], [1, 0, 0, 0, 0, 0])
    assert not len(actual["orders"])
    cancellation["失効後次行から未成立新規は消える"] = True

    prices = [100, 101, 107, 102, 102, 110, 95, 95, 95]
    shadow, actual = simulate(prices, [1] * len(prices), breakeven=True)
    assert actual["stats"][9] == 0
    assert (actual["orders"][actual["orders"][:, 7] == 0, 4].sum() == 5)
    assert actual["stats"][0] == -7.0
    assert shadow["stats"][0] > 0
    example = {
        "価格経路": prices,
        "説明": "1.5ATR順行後に新悪化が出て２枠を102で減量。影の２ATR利確は既減量枠へ対応し、実追加返済は０。影の利益を含めた建値線・追跡線で残り３枠が返済されても、実組は料金前で赤字になり得る。",
        "実料金前損益ポイント枚": float(actual["stats"][0]),
        "影料金前損益ポイント枚": float(shadow["stats"][0]),
        "実注文": actual["orders"].tolist(),
        "実組": actual["cycles"].tolist(),
        "既減量枠の二重返済": False,
    }
    # ----------------------------------------
    # 料金配分と決済脚／組／枚数の統計を、整数料金から別に再計算する。
    ready = {
        "symbol": "TOPIX", "session": "人工経路", "last": np.asarray(prices, dtype=float),
        "seq": np.arange(len(prices), dtype=np.int64), "time_s": np.arange(len(prices), dtype=float),
    }
    row, ledger, equity = study.account(ready, actual, {})
    integer_fees = [418 * int(order[4]) // 10 for order in actual["orders"]]
    assert integer_fees == [209, 83, 125]
    assert row["fees"] == sum(integer_fees) == 417
    assert abs(row["net"] - (-7 * 1000 - sum(integer_fees))) < 1.0e-9
    assert row["winning_lots"] == 2 and row["losing_lots"] == 3
    assert row["wins"] == 1 and row["losses"] == 1
    assert row["campaign_wins"] == 0 and row["campaign_losses"] == 1
    assert abs(row["profit"] - 1833.4) < 1.0e-9
    assert abs(row["loss"] - 9250.4) < 1.0e-9
    assert abs(row["sum_r"] - row["net"] / 20000) < 1.0e-12
    example["料金と数量の独立再計算"] = {
        "整数注文料金": integer_fees, "全料金": row["fees"], "純収支": row["net"],
        "決済脚勝負": [row["wins"], row["losses"]],
        "組勝負": [row["campaign_wins"], row["campaign_losses"]],
        "利益損失枚数": [row["winning_lots"], row["losing_lots"]],
        "１ATRを分母にしたR": row["sum_r"],
    }

    shadow, actual = simulate([100, 101, 90, 90, 90, 90], [1] * 6, observed=True)
    assert actual["stats"][0] == -55.0
    assert actual["cycles"][0, 4] == 20.0
    budget = {
        "説明": "実組予算は初回５枚×ATR４＝20ポイント枚。影の0.75ATR線を飛び越えた次観測90で返済すると55ポイント枚の損失。料金も別で、1ATRは約定損失保証ではない。",
        "実リスク単位ポイント枚": float(actual["cycles"][0, 4]),
        "実料金前損益ポイント枚": float(actual["stats"][0]),
        "実注文": actual["orders"].tolist(),
    }
    source_paths = (
        WORK / "replay.py", WORK / "study.py", WORK / "engine_shadow.py", WORK / "engine_partial.py",
        Path(replay.gate.__file__), Path(replay.integration.reference.gate.__file__),
    )
    packet = {"人工経路検査合格": True, "料金１〜20枚一致": fees,
              "ゲート取消の次行効力": cancellation, "影建値と実建値の違い": example,
              "実１ATR予算の限界": budget,
              "実装SHA256": {str(path): sha256(path.read_bytes()).hexdigest() for path in source_paths}}
    (HERE / "人工経路による解釈検査.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"人工検査合格": True, "影建値例の実損益": example["実料金前損益ポイント枚"],
                      "予算超過例": budget["実料金前損益ポイント枚"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
