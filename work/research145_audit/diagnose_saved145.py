"""TG04保存約定を変えず、原板全行で含み益の返しと値動き形状を診断する。"""

import json
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "work/nikkei143_20261024"
sys.path.insert(0, str(OLD))
import common143 as shared

JST = ZoneInfo("Asia/Tokyo")


def stamp(value):
    """
    機能: 原価格時計を日本時間へ変換する。
    引数: value(float)はUNIX秒。
    返り値: strは日本時間のISO表記。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def parent_curve(orders, ready, quotes):
    """
    機能: 保存された一親の全約定を維持し、その間の清算側気配による評価価値を測る。
    引数: orders(ndarray)、ready/quotes(dict)は保存注文・原行情報・気配。
    返り値: dictは粗損益、最高評価価値、返し、原行根拠。新しい売買は生成しない。
    """
    begin, end = int(orders[0, 0]), int(orders[-1, 0])
    times = ready["time_s"]
    cash, held, maximum = 0., 0, 0
    peak, peak_at, trough, trough_at = -float("inf"), begin, float("inf"), begin
    after_peak_low, after_peak_low_at = float("inf"), begin
    legs = []
    unique_rows = np.unique(orders[:, 0].astype(int))
    for at_index, at in enumerate(unique_rows):
        group = orders[orders[:, 0] == at]
        for row in group:
            cash -= float(row[3] * row[4] * row[5] * 100.)
            held += int(row[3] * row[4])
            maximum = max(maximum, abs(held))
            legs.append(dict(action="新規" if row[7] else "返済", side="買い" if row[3] > 0 else "売り",
                quantity=int(row[4]), price=float(row[5]), decision_time=stamp(times[int(row[1])]),
                fill_time=stamp(times[at]), reason=int(row[6]), uid=int(row[8]),
                decision_raw_line=int(ready["seq"][int(row[1])])+1, fill_raw_line=int(ready["seq"][at])+1))
        stop = int(unique_rows[at_index+1]) if at_index+1 < len(unique_rows) else at+1
        indices = np.arange(at, stop)
        valid = np.asarray(quotes["quote_valid"][at:stop], dtype=bool)
        if held:
            price = quotes["bid"] if held > 0 else quotes["ask"]
            values = cash + held * np.asarray(price[at:stop]) * 100.
        else:
            values = np.full(stop-at, cash)
        valid &= np.isfinite(values)
        idx, vals = indices[valid], values[valid]
        if not len(vals):
            continue
        local_peak = int(np.argmax(vals))
        if vals[local_peak] > peak:
            peak, peak_at = float(vals[local_peak]), int(idx[local_peak])
            suffix = vals[local_peak:]
            j = int(np.argmin(suffix)) + local_peak
            after_peak_low, after_peak_low_at = float(vals[j]), int(idx[j])
        elif float(vals.min()) < after_peak_low:
            j = int(np.argmin(vals))
            after_peak_low, after_peak_low_at = float(vals[j]), int(idx[j])
        if float(vals.min()) < trough:
            j = int(np.argmin(vals))
            trough, trough_at = float(vals[j]), int(idx[j])
    assert held == 0
    direction = int(orders[0, 3])
    raw_parent = int(orders[0, 2])
    return dict(parent=raw_parent, owner=("基本", "追加", "別入口")[raw_parent//10_000_000],
        side="買い" if direction > 0 else "売り", gross=cash, previous_fees=float(orders[:, 9].sum()),
        peak_gross_equity=peak, peak_time=stamp(times[peak_at]), peak_raw_line=int(ready["seq"][peak_at])+1,
        peak_to_final_giveback=peak-cash, low_gross_equity=trough, low_time=stamp(times[trough_at]),
        after_peak_low=after_peak_low, after_peak_low_time=stamp(times[after_peak_low_at]),
        max_quantity=maximum, entry=stamp(times[begin]), exit=stamp(times[end]),
        minutes=(float(times[end])-float(times[begin]))/60., orders=legs)


def main():
    """
    機能: 全50場の保存TG04会計に原板評価の診断を付け、監査資料を保存する。
    引数: なし。
    返り値: None。元資料と取引列を変更せず、事後分類は診断だけに使用する。
    """
    packets, _, labels = shared.material()
    saved = shared.read(OLD / "第三巡結果143.json")
    original = {r["session"]:r for r in saved["rows"] if r["method"] == "TG04"}
    caches = {r["session"]:r for r in saved["cache"]}
    parent_results, sessions, charts = [], [], {}
    for item in packets:
        scene = item["session"]
        packet = shared.packet_from(item)
        ready, quotes = packet["inputs"][scene,"NK225"], packet["quotes"][scene,"NK225"]
        with np.load(ROOT / caches[scene]["path"]) as archive:
            orders = archive["TG04"]
        selected = []
        for parent in np.unique(orders[:, 2]):
            row = parent_curve(orders[orders[:, 2] == parent], ready, quotes)
            row["session"] = scene
            selected.append(row)
        assert abs(sum(x["gross"] for x in selected)-original[scene]["gross"]) < 1e-5
        parent_results.extend(selected)
        times = np.asarray(ready["time_s"])
        valid = np.asarray(quotes["quote_valid"], dtype=bool)
        mid = (np.asarray(quotes["bid"]) + np.asarray(quotes["ask"]))/2
        valid &= np.isfinite(mid)
        indices = np.flatnonzero(valid)
        minutes = (times[indices]//60).astype(np.int64)
        minute_indices = indices[np.r_[minutes[1:]!=minutes[:-1], True]]
        prices = mid[minute_indices]
        path = float(np.abs(np.diff(prices)).sum())
        netmove = float(prices[-1]-prices[0])
        span = float(prices.max()-prices.min())
        sessions.append(dict(session=scene, gross=original[scene]["gross"], fee_based_net=original[scene]["net"],
            minute_range=span, minute_total_path=path, efficiency=abs(netmove)/path if path else 0.,
            net_move=netmove, direction=labels[scene]["direction"], parent_count=len(selected),
            peak_giveback=sum(x["peak_to_final_giveback"] for x in selected), raw_rows=len(times)))
        charts[scene]=dict(times=[stamp(times[i]) for i in minute_indices], mid=prices.tolist())
        print(scene, len(selected), flush=True)
    summary = dict(financial_replays=0, saved_trade_rule="旧TG04標準手数料込み経路の保存売買列を固定。今回評価は粗損益・費用0。H04予算の経路は再計算していない。",
        quote_basis="日経ラージ清算側気配、原価格時計。当時のmini実約定ではない。",
        caution="全親の最高評価価値を足した値は別々の将来の極値であり実現可能利益や改善目標として扱わない。",
        raw_rows=sum(x["raw_rows"] for x in sessions), sessions=sessions, parents=parent_results)
    (HERE/"保存TG04の全場利益返し診断.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    (HERE/"全場1分気配と保存約定.json").write_text(json.dumps(charts,ensure_ascii=False,allow_nan=False),encoding="utf-8")


if __name__ == "__main__":
    main()
