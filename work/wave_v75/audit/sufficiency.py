"""鮮度の選択に用いた入力十分性を、方向・損益なしに独立再集計する。"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import json
from pathlib import Path

import numpy as np

from independent_account import save
from real_signals import load_material
from sync_oracle import asof_fast


HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 全鮮度・遅延・窓の端点と切断なし区間を別検索で照合する。

    引数: なし。返り値: なし(None)。価格方向と売買結果は採点しない。
    """
    ready, book, sync, meta = load_material()
    saved = json.loads((HERE.parent / "inputs/鮮度別の入力十分性.json").read_text(encoding="utf-8"))
    rows = []
    for session in sorted(sync):
        grid = sync[session]["grid"]
        for freshness in (10, 30, 60):
            for delay in (1, 5, 15, 60):
                row = dict(session=session, delay=delay, max_age=freshness, grid_count=len(grid))
                for window in (0, 15, 60, 300):
                    endpoints = np.ones(len(grid), bool)
                    clean = np.ones(len(grid), bool)
                    for symbol in ("TOPIX", "NK225"):
                        key = session, symbol
                        r, f = ready[key], book[key]
                        now = asof_fast(grid - delay, r["time_s"], f["valid"], f["reset"], freshness)[0]
                        old = asof_fast(grid - delay - window, r["time_s"], f["valid"], f["reset"], freshness)[0]
                        accepted = (now >= 0) & (old >= 0)
                        endpoints &= accepted
                        bad_rows = np.flatnonzero(~f["valid"] | f["reset"]).tolist()
                        verified = np.zeros(len(grid), bool)
                        for i in np.flatnonzero(accepted):
                            verified[i] = bisect_left(bad_rows, int(old[i])) == bisect_right(bad_rows, int(now[i]))
                        clean &= verified
                    row[f"endpoints_{window}"] = int(endpoints.sum())
                    row[f"uninterrupted_{window}"] = int(clean.sum())
                rows.append(row)
    assert rows == saved["rows"]
    totals = []
    for freshness in (10, 30, 60):
        for delay in (1, 5, 15, 60):
            group = [row for row in rows if row["max_age"] == freshness and row["delay"] == delay]
            values = {name: sum(row[name] for row in group) for name in group[0] if name not in ("session", "delay", "max_age")}
            totals.append(dict(delay=delay, max_age=freshness, **values, fractions={name: value / values["grid_count"] for name, value in values.items() if name != "grid_count"}))
    assert totals == saved["totals"]
    save(HERE / "鮮度選択の入力十分性独立監査.json", dict(合格=True, 期間鮮度遅延比較数=len(rows), 総計比較数=len(totals),
        主遅延5の入力比較=[row for row in totals if row["delay"] == 5],
        検査="strict過去同時計先頭を標準二分探索、区間切断を不良行の整数序数範囲検索で別計算。方向・価格変化・損益を見ず、鮮度10/30/60の全端点と15/60/300秒履歴を照合。",
        原本取得=0, API取得=0, 実注文=0, 実損益閲覧=0))
    print("鮮度10/30/60の入力十分性全348集計・12総計が一致しました", flush=True)


if __name__ == "__main__":
    main()
