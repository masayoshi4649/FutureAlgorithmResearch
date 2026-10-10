"""確定済み一分終値で時価評価し、実現損失だけでは見えない保有中のリスクを示す。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
TICKS = {"NK225": 10.0, "TOPIX": 0.5}


def read_one(session: str, symbol: str) -> pd.DataFrame:
    """機能: 原本を変更せず確定済み一分足を読み込む。

    引数: session/symbol (str) はセッションと銘柄。
    返り値: 実在時刻を索引とする確定足 (DataFrame)。
    """
    frame = pd.read_csv(ROOT / "candle_1min" / symbol / f"{session}.csv")
    frame["time"] = pd.to_datetime(frame.time)
    frame = frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()
    if frame.index.duplicated().any():
        raise AssertionError("確定足の時刻に重複があります。")
    return frame


def mark_to_close(one: pd.DataFrame, trades: list[dict], tick: float) -> tuple[dict, pd.DataFrame]:
    """機能: 各脚の費用を新規時に控除し、分末の実現・未実現損益から資産曲線を作る。

    引数: one (DataFrame) は実在一分足、trades (list[dict]) は同一セッション・銘柄の取引、
        tick (float) は呼値。
    返り値: 終値観測のDD・含み損集計と各分の曲線 (tuple[dict, DataFrame])。
    新規・返済が同分なら分末には返済済みとし、その分の足内の最大逆行は推測しない。
    """
    index = one.index
    prices = one.close.to_numpy(dtype=float)
    cost_flow = np.zeros(len(one))
    realized_flow = np.zeros(len(one))
    unrealized = np.zeros(len(one))
    single_leg = np.zeros(len(one))
    active_legs = np.zeros(len(one), dtype=int)
    realized_net = 0.0
    for trade in trades:
        if not trade["closed"] or trade.get("exit_time") is None:
            raise AssertionError("今回の全セッション集計に未返済取引があります。")
        if float(trade.get("quantity", 1)) != 1:
            raise AssertionError("１脚１枚以外の費用定義は別途指定が必要です。")
        entry = pd.Timestamp(trade["entry_time"])
        exit_time = pd.Timestamp(trade["exit_time"])
        if entry not in index or exit_time not in index:
            raise AssertionError("新規または返済時刻に実在する足がありません。")
        if exit_time < entry:
            raise AssertionError("返済が新規より前です。")
        left, right = index.get_loc(entry), index.get_loc(exit_time)
        gross = int(trade["side"]) * (float(trade["exit_price"]) - float(trade["entry_price"]))
        cost = 2 * tick
        if not np.isclose(gross - cost, float(trade["net_points"])):
            raise AssertionError("既存の実現純損益と１脚の費用定義が一致しません。")
        cost_flow[left] += cost
        realized_flow[right] += gross
        realized_net += float(trade["net_points"])
        marked = int(trade["side"]) * (prices[left:right] - float(trade["entry_price"]))
        unrealized[left:right] += marked
        single_leg[left:right] = np.minimum(single_leg[left:right], marked)
        active_legs[left:right] += 1

    # ----------------------------------------
    paid_cost = cost_flow.cumsum()
    realized_gross = realized_flow.cumsum()
    equity = realized_gross + unrealized - paid_cost
    peaks = np.maximum.accumulate(np.r_[0.0, equity])[1:]
    drawdown = peaks - equity
    trough = int(np.argmax(drawdown))
    peak_index = int(np.argmax(equity[:trough + 1]))
    worst_unrealized = int(np.argmin(unrealized))
    worst_single = int(np.argmin(single_leg))
    if not np.isclose(equity[-1], realized_net) or active_legs[-1] != 0:
        raise AssertionError("最終時価評価と実現純損益が一致しません。")
    result = dict(
        count=len(trades), realized_net_points=realized_net, final_equity_points=float(equity[-1]),
        paid_round_trip_cost_points=float(paid_cost[-1]),
        realized_loss_points=sum(max(0.0, -float(trade["net_points"])) for trade in trades),
        max_drawdown_points=float(drawdown[trough]),
        drawdown_peak_equity_points=float(peaks[trough]), drawdown_trough_equity_points=float(equity[trough]),
        drawdown_peak_close_time=index[peak_index] + pd.Timedelta(minutes=1) if peaks[trough] > 0 else index[0],
        drawdown_trough_close_time=index[trough] + pd.Timedelta(minutes=1),
        worst_aggregate_unrealized_loss_points=float(max(0.0, -unrealized[worst_unrealized])),
        worst_aggregate_unrealized_close_time=index[worst_unrealized] + pd.Timedelta(minutes=1),
        worst_single_leg_unrealized_loss_points=float(max(0.0, -single_leg[worst_single])),
        worst_single_leg_unrealized_close_time=index[worst_single] + pd.Timedelta(minutes=1),
        worst_equity_below_session_start_points=float(max(0.0, -equity.min())),
        accounting_match=True,
    )
    curve = pd.DataFrame(dict(close_time=index + pd.Timedelta(minutes=1), close=prices,
                              paid_cost_points=paid_cost, realized_gross_points=realized_gross,
                              aggregate_unrealized_points=unrealized, worst_single_leg_unrealized_points=single_leg,
                              equity_points=equity, drawdown_points=drawdown, active_legs=active_legs))
    return result, curve


def run() -> None:
    """機能: 報告対象５方式の全セルを終値時価評価し、会計一致を確認して保存する。

    引数: なし。返り値: なし (None)。設定と原本を変更せず、現在APIには接続しない。
    """
    methods = json.loads((OUT / "報告対象手法.json").read_text(encoding="utf-8"))
    rows, curves = [], []
    cache = {}
    for method in methods:
        if not method.get("trades"):
            continue
        for cell in method["cells"]:
            key = cell["session"], cell["symbol"]
            if key not in cache:
                cache[key] = read_one(*key)
            trades = [trade for trade in method["trades"] if (trade["session"], trade["symbol"]) == key]
            risk, curve = mark_to_close(cache[key], trades, TICKS[key[1]])
            if not np.isclose(risk["realized_net_points"], float(cell["net"])):
                raise AssertionError("報告用セルと時価評価の最終損益が一致しません。")
            rows.append(dict(method=method["id"], name=method["name"], session=key[0], symbol=key[1], **risk))
            curve["method"], curve["session"], curve["symbol"] = method["id"], key[0], key[1]
            curves.append(curve)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "終値評価リスク.csv", index=False, encoding="utf-8-sig")
    pd.concat(curves, ignore_index=True).to_csv(OUT / "終値評価リスク_時系列.csv.gz", index=False, encoding="utf-8-sig", compression="gzip")
    (OUT / "終値評価リスク.json").write_text(json.dumps(dict(
        method="新規時に往復２ティックを全額控除。同分末で返済済みなら実現gross、保有中ならside×(close-entry)。同分の全脚を合算。セッションごとゼロ開始。",
        scope="実在する１分終値観測の最大DDと含み損であり、足内や瞬間の最大損失ではない。",
        rows=rows, accounting_match_all=True,
    ), ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    lines = ["# 一分終値による時価評価リスク", "",
             "確定損失がゼロでも、保有中の含み損や利益からの減少は生じる。報告対象５方式を、各セッション・銘柄ごとにゼロから開始する資産曲線として評価した。全取引の往復２ティックを新規時にまとめて控除し、返済した分の終値時点には実現gross、保有中の脚には方向×（終値−新規価格）を計上した。全セルで最後の資産額と既存の実現純損益が一致した。", "",
             "以下は**実在する１分終値で観測したDD・含み損**であり、瞬間最大の損失ではない。新規・返済した分の高安の先後は推測していない。新規と返済が同分なら、その分末では返済済みになる。価格の観測がない分の途中変動も分からない。", "",
             "|方式|セッション|銘柄|実現純損益|確定損失合計|終値評価の最大DD|最悪合算含み損|最悪単脚含み損|", "|---|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append(f'|{row["method"]}|{row["session"]}|{row["symbol"]}|{row["realized_net_points"]:+.2f}|{row["realized_loss_points"]:.2f}|{row["max_drawdown_points"]:.2f}|{row["worst_aggregate_unrealized_loss_points"]:.2f}|{row["worst_single_leg_unrealized_loss_points"]:.2f}|')
    lines.extend(["", "NK225は円幅、TOPIXはポイント。DDはそれ以前の資産曲線の最高値からの減少額で、累積実現損益と未実現損益、先に控除した費用を含む。含み損の欄は費用を重複して差し引かない純粋な未実現価格差である。", "", "両建ては同分の全脚を合算して資産曲線を作った。買いと売りの含み損益が相殺される場合があるため、合算含み損と単脚の最悪含み損を分けた。単脚欄は脚単位で観測した最も悪い値であり、その時点の口座全体の損失と同じではない。", "", "全て１脚１枚の取引を評価しており、両建ては買売各１枚である。証拠金必要額・約定不能・ギャップ中の未観測損失・注文遅延はこの時価評価に含まれない。現在APIの取得も、検知・注文条件の変更も行っていない。", ""])
    (OUT / "終値評価リスク.md").write_text("\n".join(lines), encoding="utf-8")
    print(frame[frame.method.eq("方向主候補")][["session", "symbol", "realized_net_points", "realized_loss_points", "max_drawdown_points", "worst_aggregate_unrealized_loss_points"]].to_json(orient="records", force_ascii=False), flush=True)


if __name__ == "__main__":
    run()
