"""方向先着診断を、木探索を用いず実原本の直接区間比較で検算する。"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from audit_all import read, material, WORK, HERE
from independent_account import near, save


def summary(labels: list[dict], level: str) -> dict:
    """機能: 独立照合済み先着ラベルを全入口分母と到達済み分母で集計する。

    引数: labels(list[dict])、level(str)。返り値: 入口数・先着率・未到達指標(dict)。
    """
    total = len(labels)
    favorable = sum(row[level]["outcome"] == 1 for row in labels)
    adverse = sum(row[level]["outcome"] == -1 for row in labels)
    return dict(total=total, favorable=favorable, adverse=adverse, unreached=total-favorable-adverse,
        censored=sum(row[level]["censored"] for row in labels),
        favorable_rate_all=favorable/total if total else None,
        favorable_rate_reached=favorable/(favorable+adverse) if favorable+adverse else None,
        active_sessions=len({row["session"] for row in labels}),
        mfe_median_ticks=float(np.median([row["mfe_ticks"] for row in labels])) if total else None,
        mae_median_ticks=float(np.median([row["mae_ticks"] for row in labels])) if total else None,
        remaining_minutes_median=float(np.median([row["remaining_seconds"]/60 for row in labels])) if total else None)


def main() -> None:
    """機能: 全入口4983件の先着・極値・終了行と全480集計を別原本走査で照合する。

    引数: なし。返り値: なし(None)。
    """
    ready, features = material()
    schedules = read(WORK / "inputs/schedule.pkl")
    diagnostic = read(WORK / "analysis/入口方向の独立診断.json")
    fixed = read(WORK / "事前固定.json")
    sources = ("T1L1", "T2L0", "T3L1", "T4L0", "E01P", "R01P")
    endpoint = {}
    valid_rows = {}
    for key, r in ready.items():
        bid, ask = features[key]["bid"], features[key]["ask"]
        valid = np.flatnonzero(np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid))
        valid_rows[key] = valid
        decision = np.flatnonzero(r["time_s"] >= r["limit"] - 60.)
        end, complete = len(bid)-1, False
        if len(decision):
            after = valid[valid > decision[0]]
            if len(after):
                end, complete = int(after[0]), True
        endpoint[key] = end, complete
    labels = diagnostic["入口採点"]
    identity = set()
    count = sum(len(series) for schedule in schedules.values() for series in schedule)
    assert len(labels) == count == 4983
    for label in labels:
        key = label["session"], label["symbol"]
        gate = int(label["gate"][1:])
        index = sources.index(label["source"]) * 4 + gate
        unique = key, index, label["cid"]
        assert unique not in identity
        identity.add(unique)
        scheduled = schedules[key][index][label["cid"]]
        row, decision, side = int(scheduled[0]), int(scheduled[1]), int(scheduled[3])
        assert row == label["fill_i"] and decision == label["decision_i"] and side == label["side"]
        r, f = ready[key], features[key]
        price = f["ask" if side == 1 else "bid"][row]
        assert label["entry_price"] == price and label["entry_time_s"] == r["time_s"][row]
        end, complete = endpoint[key]
        assert end == label["label_end_i"] and complete == label["label_complete"]
        remaining = max(0., float(r["time_s"][end] - r["time_s"][row]))
        near(label["remaining_seconds"], remaining, "残り時間")
        rows = valid_rows[key]
        rows = rows[(rows > row) & (rows <= end)]
        quotes = f["bid" if side == 1 else "ask"][rows]
        gains = side * (quotes-price) / r["tick"]
        mfe = max(0., float(gains.max())) if len(gains) else 0.
        mae = max(0., float(-gains.min())) if len(gains) else 0.
        near(label["mfe_ticks"], mfe, "最大順行呼値")
        near(label["mae_ticks"], mae, "最大逆行呼値")
        mfe_row = int(rows[np.flatnonzero(gains == gains.max())[0]]) if mfe > 0 else -1
        mae_row = int(rows[np.flatnonzero(gains == gains.min())[0]]) if mae > 0 else -1
        assert mfe_row == label["mfe_i"] and mae_row == label["mae_i"]
        for level in (8, 16):
            forward = np.flatnonzero(gains >= level)
            adverse = np.flatnonzero(gains <= -level)
            outcome, arrival = 0, -1
            if len(forward) and (not len(adverse) or forward[0] < adverse[0]):
                outcome, arrival = 1, int(rows[forward[0]])
            elif len(adverse) and (not len(forward) or adverse[0] < forward[0]):
                outcome, arrival = -1, int(rows[adverse[0]])
            expected = dict(outcome=outcome, arrival_i=arrival,
                arrival_seconds=float(r["time_s"][arrival]-r["time_s"][row]) if arrival >= 0 else None,
                censored=bool(not complete and outcome == 0))
            assert label[str(level)] == expected, (unique, level, expected, label[str(level)])
    periods = {"前16": fixed["前16"], "後12": fixed["後12"], "全28": fixed["全セッション"],
        "追加1": fixed["追加追試"], "全29": fixed["全セッション"]+fixed["追加追試"]}
    groups = defaultdict(list)
    for label in labels:
        groups[(label["series"], label["symbol"])].append(label)
    comparisons = 0
    for series, by_period in diagnostic["集計"].items():
        for period, by_symbol in by_period.items():
            for symbol, by_level in by_symbol.items():
                subset = [r for r in groups[(series, symbol)] if r["session"] in periods[period]]
                for level, actual in by_level.items():
                    expected = summary(subset, level)
                    for field, value in expected.items():
                        if value is None:
                            assert actual[field] is None
                        else:
                            near(float(actual[field]), float(value), "方向集計/"+field)
                    comparisons += 1
    assert comparisons == 480
    assert diagnostic["API取得"] == diagnostic["実注文"] == 0
    assert diagnostic["入口幅設定へ依存"] is False
    save(HERE / "入口方向先着の独立監査.json", dict(合格=True, 新規件数=count, 先着閾値検査数=count*2,
        区間最大順逆行一致件数=count, 集計一致数=comparisons,
        採点方式="木を呼ばず、実買ask/売bidの翌原本行以後の清算気配を直接区間比較",
        保有60分期限で打切らない=True, 場内返済の次有効行まで=True,
        全件分母と未到達分類一致=True, 右打切件数=sum(r["8"]["censored"] for r in labels),
        未来ラベル用途="検証採点のみ。入口判定と管理 API に渡さない"))
    print(f"入口{count}件・{count*2}先着・極値・480集計: 独立原本走査合格", flush=True)


if __name__ == "__main__":
    main()
