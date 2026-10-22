"""既存四十三場の会計を昼夜・方向・前後半へ分け、再生せずに比較する。"""

from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import statistics


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TASK = ROOT / "work/stability126_20261019"


def read(path: Path) -> tuple[dict, dict]:
    """
    機能: 完成済みの会計又は採点用目録を読み、内容指紋を結び付ける。
    引数: path(Path)は既存資料。
    返り値: tuple[dict,dict]は保存内容と位置・ＳＨＡ２５６。
    """
    payload = path.read_bytes()
    return json.loads(payload), dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest())


def statistics_of(rows: list[dict]) -> dict:
    """
    機能: 手数料後の場収支を、赤字頻度・通常幅・大勝ち依存を含めて集計する。
    引数: rows(list[dict])は同じ商品・手法・区分の保存会計。
    返り値: dictは場数、費用前後の収支、中央値、最悪、黒赤平均等。
    """
    assert rows
    values = [r["after_fees"] for r in rows]
    positive, negative = [v for v in values if v > 0], [-v for v in values if v < 0]
    average_black = statistics.mean(positive) if positive else None
    average_red = statistics.mean(negative) if negative else None
    return dict(sessions=len(rows), before_fees=sum(r["before_fees"] for r in rows),
        fees=sum(r["fees"] for r in rows), net=sum(values), black=len(positive), red=len(negative),
        zero=sum(v == 0 for v in values), median=statistics.median(values), average=statistics.mean(values),
        worst=min(values), best=max(values), average_black=average_black, average_red=average_red,
        win_loss_ratio=average_black / average_red if average_black is not None and average_red else None,
        excluding_best=sum(values) - max(positive, default=0),
        excluding_best_three=sum(values) - sum(sorted(positive, reverse=True)[:3]),
        new_orders=sum(r["new_orders"] for r in rows), new_quantity=sum(r["new_quantity"] for r in rows))


def main() -> None:
    """
    機能: レビュアーの昼夜差仮説を保存会計だけで確認し、独立再集計との一致を残す。
    引数: なし。
    返り値: None。金融再生・設定探索・原板読取・現在ＡＰＩ接続は行わない。
    """
    target = HERE / "昼夜と方向及び前後半の保存会計再集計_最終.json"
    assert not target.exists()
    plan = HERE / "再集計の範囲.json"
    assert plan.exists()
    fees, fee_reference = read(TASK / "fees_20261020/二候補の四十三場の注文別手数料と実保有枚数.json")
    old, old_reference = read(TASK / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json")
    added, added_reference = read(TASK / "update_20261020/追加二場の非金融入力準備.json")
    regimes = {(r["session"], r["symbol"]): r["regime"] for r in old["metadata"]}
    for packet in added["packets"]:
        for row in packet["accounts"]:
            regimes[row["session"], row["symbol"]] = {-1: "下落", 0: "同値", 1: "上昇"}[row["direction"]]
    rows = []
    for row in fees["rows"]:
        day = date.fromisoformat(row["session"][:10])
        rows.append(dict(row, kind=row["session"].rsplit("_", 1)[1], regime=regimes[row["session"], row["symbol"]],
                         week_start=(day - timedelta(days=day.weekday())).isoformat()))
    summaries = []
    for method in ("GU_Q", "G_Q"):
        for symbol in ("TOPIX", "NK225"):
            for kind in ("Day", "Night"):
                part = sorted((r for r in rows if r["method"] == method and r["symbol"] == symbol and r["kind"] == kind), key=lambda r: r["session"])
                n = len(part)
                half = n // 2
                groups = defaultdict(list)
                for row in part:
                    groups[row["week_start"]].append(row)
                summaries.append(dict(method=method, symbol=symbol, kind=kind, **statistics_of(part),
                    halves=[statistics_of(part[:half]), statistics_of(part[half:])],
                    weeks=[dict(week_start=key, **statistics_of(values)) for key, values in sorted(groups.items())],
                    regimes=[dict(regime=label, **statistics_of(selected)) for label in ("上昇", "下落", "同値")
                             if (selected := [r for r in part if r["regime"] == label])],
                    previous_41=statistics_of([r for r in part if r["session"] not in added["sessions"]]),
                    added_two=statistics_of([r for r in part if r["session"] in added["sessions"]])))
    index = {(r["method"], r["symbol"], r["kind"]): r for r in summaries}
    expected = {("GU_Q", "TOPIX", "Day"): (445287, 13, 9, 10415, 138125),
                ("GU_Q", "TOPIX", "Night"): (-290701, 10, 11, -16422, -505775),
                ("GU_Q", "NK225", "Day"): (162180, 14, 8, 5200, 5800),
                ("GU_Q", "NK225", "Night"): (-138000, 10, 11, -4520, -220140),
                ("G_Q", "TOPIX", "Night"): (-394960, 7, 14, -26340, -684203),
                ("G_Q", "NK225", "Night"): (-148060, 9, 12, -5760, -247580)}
    for key, values in expected.items():
        assert tuple(index[key][name] for name in ("net", "black", "red", "median", "excluding_best_three")) == values
    day_gu = sorted(({k: v for k, v in r.items() if k != "method"} for r in rows if r["method"] == "GU_Q" and r["kind"] == "Day"), key=lambda r: (r["symbol"], r["session"]))
    day_g = sorted(({k: v for k, v in r.items() if k != "method"} for r in rows if r["method"] == "G_Q" and r["kind"] == "Day"), key=lambda r: (r["symbol"], r["session"]))
    assert day_gu == day_g and len(day_gu) == 44
    for method in ("GU_Q", "G_Q"):
        for symbol in ("TOPIX", "NK225"):
            full = next(r for r in fees["totals"] if r["method"] == method and r["symbol"] == symbol)
            assert sum(index[method, symbol, kind]["net"] for kind in ("Day", "Night")) == full["after_fees"]
    report = ROOT / "アルゴリズム調査/00126_E01の損失抑制と方向偏りの再検証/E01改修のセッション損益.html"
    raw = report.read_bytes()
    payload = json.loads(re.search(r'<script id="accounts" type="application/json">(.*?)</script>', raw.decode("utf-8"), re.S).group(1))
    bbo = next(m for m in payload["models"] if m["id"] == "next_normal_bbo")
    comparators = []
    for method in bbo["methods"]:
        for symbol in ("TOPIX", "NK225"):
            for kind in ("Day", "Night"):
                selected = [r for r in bbo["rows"] if r["method"] == method["id"] and r["symbol"] == symbol and r["session"].endswith("_" + kind)]
                comparators.append(dict(method=method["id"], symbol=symbol, kind=kind, sessions=len(selected), before_fees=sum(r["net"] for r in selected)))
    result = dict(passed=True, summary=summaries, rows=rows, gross_comparators=comparators,
        sources=[fee_reference, old_reference, added_reference, dict(path=report.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(raw).hexdigest())],
        independent_review=dict(agent="/root/daynight126_review", matching_summary_groups=len(expected), day_44_accounts_identical=True),
        financial_replays=0, original_market_reads=0, API=0,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps([{k: r[k] for k in ("method", "symbol", "kind", "net", "black", "red")} for r in summaries if r["method"] == "GU_Q"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
