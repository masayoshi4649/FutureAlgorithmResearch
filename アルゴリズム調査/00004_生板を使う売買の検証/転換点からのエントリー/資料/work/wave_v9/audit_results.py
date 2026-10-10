"""売買価格からの損益再集計と、未学習期間の改変に対する選択の不変性を確認する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import execution
import research


OUT = Path(__file__).resolve().parent


def main() -> None:
    """全条件の集計と、評価期間を改変しても採用条件が変わらないことを検査する。

    引数: なし。
    返り値: None。独立再集計と選択の監査JSONを保存する。
    """
    trades = json.loads((OUT / "全取引.json").read_text(encoding="utf-8"))
    cells = pd.read_csv(OUT / "全条件セッション集計.csv")
    by_cell = {}
    for trade in trades:
        tick = execution.TICKS[trade["銘柄"]]
        if trade["closed"]:
            exit_price = trade["exit_price"]
            assert trade["exit_in_session"]
        else:
            exit_price = trade["mark_price"]
        independent_points = trade["side"] * (exit_price - trade["entry_price"]) - 2 * tick
        assert trade["net_points"] == independent_points
        assert trade["stress_points"] == independent_points - 2 * tick
        key = trade["方式"], trade["セッション"], trade["銘柄"]
        by_cell.setdefault(key, []).append(trade)
    for cell in cells.to_dict("records"):
        values = by_cell.get((cell["方式"], cell["セッション"], cell["銘柄"]), [])
        closed = [trade for trade in values if trade["closed"]]
        yen = [trade["net_points"] * execution.MULTIPLIERS[cell["銘柄"]] for trade in closed]
        assert cell["取引数"] == len(closed)
        assert cell["未返済数"] == len(values) - len(closed)
        assert cell["勝ち数"] == sum(value > 0 for value in yen)
        assert cell["利益円"] == sum(value for value in yen if value > 0)
        assert cell["損失円"] == -sum(value for value in yen if value < 0)
        assert cell["収支円"] == sum(yen)

    # ----------------------------------------
    # 未来の全収支を巨大な利益に変えても、学習期間までの候補順位は一切変わらない。
    records = []
    groups = ["転換方式全体"] + list(dict.fromkeys(config["group"] for config in execution.configs()))
    for count in range(2, 6):
        train = execution.SESSIONS[:count]
        changed = cells.copy()
        future = ~changed.セッション.isin(train)
        changed.loc[future, "取引数"] = 99999
        changed.loc[future, "費用倍ATR収支"] = np.arange(future.sum()) + 1e9
        changed.loc[future, "収支円"] = 1e12
        for group in groups:
            observed = research.choose(changed, group, train)
            expected = research.choose(cells, group, train)
            assert observed == expected
            selected = observed["採用"]
            if selected:
                assert all(value >= len(train) for value in selected["銘柄別取引数"].values())
            records.append(dict(学習期間=train, 群=group, 採用=selected["方式"] if selected else None,
                                未来収支改変後も全順位一致=True, 無取引採用なし=True))
    result = dict(実装SHA256={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in [Path(execution.__file__), Path(research.__file__)]},
                  全取引数=len(trades), 全集計セル数=len(cells), 気配約定価格からの収支一致=True,
                  利益損失勝敗未返済の再集計一致=True, 採用順位の未来改変照合数=len(records), 選択検査=records)
    (OUT / "損益再集計と選択監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"全{len(trades)}取引・{len(cells)}集計セルの損益と{len(records)}選択順位を確認しました。", flush=True)


if __name__ == "__main__":
    main()
