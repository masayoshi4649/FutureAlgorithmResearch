"""同一最終約定時刻内の入口・保護・不利な気配飛びを手計算と照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import model


OUT = Path(__file__).resolve().parent


def verify_same_time_trade(side: int) -> dict:
    """注文成立後の次行約定と、同一時刻内での利益保護ストップを検査する。

    引数: side（int）1は買い、-1は売り。
    返り値: dict。手計算値と一致した取引と確認項目。
    """
    now = pd.Timestamp("2026-09-23T09:30:00+09:00").timestamp()
    bid = np.array([66000., 66000., 66090., 66120., 66160., 66140., 66080.])
    ask = bid + 10
    if side < 0:
        bid, ask = 132000 - ask, 132000 - bid
    tape = {
        "seq": np.arange(10, 17), "time_s": np.full(7, now),
        "bid": bid, "ask": ask,
        "bid_qty": np.ones(7), "ask_qty": np.ones(7),
    }
    frame = pd.DataFrame({"seq": [10], "source_last_seq": [9], "time_s": [now]})
    config = next(item for item in model.configs() if item["id"] == "P00_0_逆指値_利益保護")
    trades = model.simulate(tape, frame, np.array([side]), np.array([20.]), np.array([0]), config, "2026-09-23_Day", "NK225")
    assert len(trades) == 1 and trades[0]["closed"]
    trade = trades[0]
    expected_entry = 66100. if side > 0 else 65900.
    expected_exit = 66080. if side > 0 else 65920.
    assert trade["entry_seq"] == 12
    assert trade["trigger_seq"] == 11
    assert trade["exit_trigger_seq"] == 15
    assert trade["exit_seq"] == 16
    assert trade["entry_price"] == expected_entry
    assert trade["exit_price"] == expected_exit
    assert trade["max_favorable"] == 60.
    assert trade["net_points"] == -40.
    return {
        "方向": "ロング" if side > 0 else "ショート",
        "全行で同じCurrentPriceTime": True,
        "発注から成立と約定を分離": True,
        "2.5ATR順行後の0.5ATR保護": True,
        "ストップ価格でなく次行の不利な価格で返済": True,
        "約定済み気配差に追加往復2tick控除": True,
        "取引": trade,
    }


def main() -> None:
    """方向を反転した二例を手計算と照合し記録する。

    引数: なし。
    返り値: None。監査JSONを作成する。
    """
    result = {
        "モデルSHA256": hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest(),
        "確認": [verify_same_time_trade(side) for side in (1, -1)],
    }
    (OUT / "注文再生手計算監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ロング・ショートの同時刻内注文再生が手計算と一致しました。")


if __name__ == "__main__":
    main()
