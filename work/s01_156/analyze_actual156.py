"""実約定3区間と固定済み全原板を照合する。新規金融再生・API取得は行わない。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import bisect
import hashlib
import json
import math

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.font_manager import FontProperties


HERE = Path(__file__).resolve().parent
DATA = HERE / "current_20261027"
JST = timezone(timedelta(hours=9))


def seconds(value: str) -> float:
    """日時を秒へ変換する。

    引数: value(str)はISO日時。返り値: floatはUNIX秒。
    """
    return datetime.fromisoformat(value).timestamp()


def clock(value: float) -> str:
    """時刻を日本時間へ表示変換する。

    引数: value(float)はUNIX秒。返り値: strは秒までの時計。
    """
    return datetime.fromtimestamp(value, JST).strftime("%H:%M:%S")


def read_all(path: Path, expected: str) -> tuple[np.ndarray, dict]:
    """全文を読んで指紋を検算し、正常な原気配を保存順で抽出する。

    引数: path(Path)は固定原板、expected(str)は取得時SHA。
    返り値: tupleは構造化気配配列と除外数。価格時計逆行は採用せず、同秒行は残す。
    """
    dtype = [("time", "f8"), ("line", "i8"), ("bid", "f8"), ("ask", "f8"), ("last", "f8"), ("bidqty", "f8"), ("askqty", "f8")]
    records, examples = [], []
    counts = {"all_rows": 0, "missing_or_invalid_clock": 0, "clock_regressions": 0, "outside_window": 0, "invalid_last": 0, "invalid_bbo": 0, "normal_quotes": 0, "same_clock_changed_bbo": 0}
    hasher = hashlib.sha256()
    last_time, last_quote = -math.inf, None
    start, end = seconds("2026-10-27T08:45:00+09:00"), seconds("2026-10-27T15:20:00+09:00")
    with path.open("rb") as stream:
        for line, raw in enumerate(stream, 1):
            hasher.update(raw)
            if not raw.strip():
                continue
            counts["all_rows"] += 1
            row = json.loads(raw)
            try:
                time = seconds(row["CurrentPriceTime"])
            except (ValueError, TypeError, KeyError):
                counts["missing_or_invalid_clock"] += 1
                continue
            if not start <= time < end:
                counts["outside_window"] += 1
                continue
            if time < last_time:
                counts["clock_regressions"] += 1
                continue
            last_time = time
            last = row.get("CurrentPrice")
            if not isinstance(last, (int, float)) or not math.isfinite(last) or last <= 0:
                counts["invalid_last"] += 1
                continue
            buy, sell = row.get("Buy1") or {}, row.get("Sell1") or {}
            bid, ask = buy.get("Price"), sell.get("Price")
            if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)) or not math.isfinite(bid) or not math.isfinite(ask) or not 0 < bid < ask:
                counts["invalid_bbo"] += 1
                continue
            if last_quote is not None and time == last_quote[0] and (bid, ask) != last_quote[2:4]:
                counts["same_clock_changed_bbo"] += 1
                if len(examples) < 3:
                    examples.append({"time": time, "previous_line": last_quote[1], "line": line, "previous_bbo": list(last_quote[2:4]), "bbo": [bid, ask]})
            last_quote = (time, line, bid, ask, last, float(buy.get("Qty") or 0), float(sell.get("Qty") or 0))
            records.append(last_quote)
    actual = hasher.hexdigest()
    assert actual == expected, f"固定原板が変化した: {path.name}"
    counts["normal_quotes"] = len(records)
    return np.array(records, dtype=dtype), {"path": str(path), "sha256": actual, "counts": counts, "same_clock_changed_examples": examples, "full_read": True}


def quote(row) -> dict:
    """原行の気配と代理時計をJSON用にする。

    引数: row(np.void)は原気配。返り値: dictは原行番号・時計・価格。
    """
    return {"time": float(row["time"]), "clock": clock(row["time"]), "line": int(row["line"]), "bid": float(row["bid"]), "ask": float(row["ask"]), "mid": float((row["bid"] + row["ask"]) / 2), "last": float(row["last"])}


def entry_features(rows: np.ndarray, at: float, side: int) -> dict:
    """実約定と同秒の原行を使わず、入口直前の進行と既知高低を測る。

    引数: rows(np.ndarray)は正常気配、at(float)は約定時刻、side(int)は買1/売-1。
    返り値: dictは10/30/60/180秒前の気配との差と当時までの位置。
    """
    cutoff = math.floor(at)
    right = int(np.searchsorted(rows["time"], cutoff, side="left"))
    assert right > 0
    current = rows[right-1]
    mid = (rows["bid"] + rows["ask"]) / 2
    current_mid = float(mid[right-1])
    out = {"available_before_exclusive": cutoff, "quote": quote(current), "quote_age_to_fill_seconds": at-float(current["time"]), "windows": {}}
    for width in (10, 30, 60, 180):
        anchor = int(np.searchsorted(rows["time"], cutoff-width, side="right"))-1
        left = int(np.searchsorted(rows["time"], cutoff-width, side="left"))
        if anchor < 0 or left >= right:
            out["windows"][str(width)] = None
            continue
        high, low = float(mid[left:right].max()), float(mid[left:right].min())
        change = current_mid-float(mid[anchor])
        out["windows"][str(width)] = {"anchor_quote": quote(rows[anchor]), "anchor_age_seconds": cutoff-width-float(rows[anchor]["time"]), "mid_change_points": change, "side_progress_points": side*change, "known_high_mid": high, "known_low_mid": low, "distance_below_high": high-current_mid, "distance_above_low": current_mid-low, "position_in_range": (current_mid-low)/(high-low) if high > low else None}
    high_index, low_index = int(np.argmax(mid[:right])), int(np.argmin(mid[:right]))
    out["session_to_entry"] = {"high": quote(rows[high_index]), "low": quote(rows[low_index]), "distance_below_high": float(mid[high_index])-current_mid, "distance_above_low": current_mid-float(mid[low_index])}
    return out


def held_diagnosis(rows: np.ndarray, at: float, end: float, price: float, side: int, qty: int) -> dict:
    """実運転区間だけの返済側ラージ気配による最大順行・逆行を記録する。

    引数: rows(np.ndarray)、at/end(float)、price(float)、side/qty(int)は気配と実保有情報。
    返り値: dictは事後診断。返済約定や実miniの含み益を新しく仮定しない。
    """
    selected = rows[(rows["time"] > math.floor(at)) & (rows["time"] < math.floor(end))]
    assert len(selected)
    gains = (selected["bid"]-price) if side == 1 else (price-selected["ask"])
    peak, worst = int(np.argmax(gains)), int(np.argmin(gains))
    positive = np.flatnonzero(gains > 0)
    first_positive = int(positive[0]) if len(positive) else None
    after_first = np.flatnonzero(gains[first_positive+1:] <= 0) if first_positive is not None else []
    after_peak = np.flatnonzero(gains[peak+1:] <= 0)
    def moment(index):
        """診断上の特定原行と未決済代理値を記録する。

        引数: index(int)は区間添字。返り値: dictは気配とポイント・円代理。
        """
        return {**quote(selected[index]), "gain_points": float(gains[index]), "proxy_gross_yen": float(gains[index]*qty*100)}
    return {"observed_quotes": len(selected), "first_quote": moment(0), "last_quote": moment(len(selected)-1), "max_favorable": moment(peak), "max_adverse": moment(worst), "first_positive": moment(first_positive) if first_positive is not None else None, "first_nonpositive_after_profit": moment(first_positive+1+int(after_first[0])) if len(after_first) else None, "first_nonpositive_after_peak": moment(peak+1+int(after_peak[0])) if len(after_peak) else None, "mfe_to_final_proxy_giveback_points": float(gains[peak]-gains[-1])}


def draw(rows: np.ndarray, cases: list, path: Path) -> None:
    """実約定と原板の事後診断を暗背景で図示する。

    引数: rows(np.ndarray)、cases(list)は原気配と3区間、path(Path)はPNG保存先。
    返り値: None。約定不明の売買点を作らない。
    """
    font_path = Path("C:/Windows/Fonts/meiryo.ttc")
    if font_path.exists():
        matplotlib.rcParams["font.family"] = FontProperties(fname=str(font_path)).get_name()
    plt.style.use("dark_background")
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), constrained_layout=True)
    fig.patch.set_facecolor("#10151f")
    for ax, case in zip(axes, cases):
        ax.set_facecolor("#151c29")
        start, end = case["entry_time"], case["end_time"]
        window = rows[(rows["time"] >= start-180) & (rows["time"] < math.floor(end))]
        prices = window["bid"] if case["side"] == 1 else window["ask"]
        times = [datetime.fromtimestamp(v, JST) for v in window["time"]]
        ax.plot(times, prices, color="#67c4f5", linewidth=.8, label="ラージ返済側気配（代理）")
        ax.axhline(case["entry_price"], color="#f1c76d", linestyle="--", linewidth=1, label="実mini新規建値")
        ax.axvline(datetime.fromtimestamp(start, JST), color="#f1c76d", linewidth=.8)
        ax.scatter([datetime.fromtimestamp(start, JST)], [case["entry_price"]], color="#f1c76d", marker="^" if case["side"] == 1 else "v", s=70, zorder=5)
        if case.get("exit_price") is not None:
            ax.scatter([datetime.fromtimestamp(end, JST)], [case["exit_price"]], color="#f27984", marker="x", s=70, zorder=6, label="実mini返済約定")
        else:
            ax.axvline(datetime.fromtimestamp(end, JST), color="#d098f4", linestyle=":", label="OFF・管理終了（返済なし）")
        for name, color in [("max_favorable", "#68dfa9"), ("max_adverse", "#f27984")]:
            point=case["future_diagnostic"][name]
            value=point["bid"] if case["side"] == 1 else point["ask"]
            ax.scatter([datetime.fromtimestamp(point["time"], JST)], [value], color=color, s=28, zorder=6)
            near_right = point["time"] > end-(end-start+180)*.2
            ax.annotate(f'{point["clock"]} {point["gain_points"]:+.1f}pt', (datetime.fromtimestamp(point["time"], JST), value), xytext=(-6 if near_right else 6, 9 if name=="max_favorable" else -18), textcoords="offset points", ha="right" if near_right else "left", color=color, fontsize=9)
        ax.set_title(case["label"] + " / " + ("買い" if case["side"] == 1 else "売り") + f' {case["quantity"]}枚', loc="left", fontsize=12)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
        ax.grid(alpha=.15)
        ax.legend(loc="best", fontsize=8)
    fig.suptitle("2026-10-27 S01 実運用3区間：ラージ気配代理とmini実約定\n緑・赤の極値は事後診断。新しい返済約定を仮定した損益ではない", fontsize=14)
    fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    """固定原板を全行読取し、指定した実保有3区間の診断を保存する。

    引数: なし。返り値: None。API呼出・新たな売買再生・App変更なし。
    """
    manifest = json.loads((DATA/"manifest.json").read_text(encoding="utf-8"))
    fingerprints = {Path(row["path"]).name: row["sha256"] for row in manifest["files"]}
    books, audit = {}, {}
    for symbol in ("NK225", "TOPIX"):
        books[symbol], audit[symbol] = read_all(DATA/(symbol+"_book.jsonl"), fingerprints[symbol+"_book.jsonl"])
    state = json.loads((DATA/"app_state.json").read_text(encoding="utf-8"))
    snapshot = next(p for p in state["products"] if p["product"]=="NK225mini")["detached_snapshot"]
    trades = snapshot["recent_trades"]
    pairs = [(0, 3, "主担当：14:03買い→14:28損切り"), (6, 7, "別入口：14:52売り→14:55損切り"), (8, None, "主担当：15:00買い→15:07管理終了")]
    cases=[]
    for number, (entry_index, exit_index, label) in enumerate(pairs, 1):
        entry = trades[entry_index]
        exit_trade = trades[exit_index] if exit_index is not None else None
        assert entry["action"]=="new"
        if exit_trade:
            assert exit_trade["action"]=="close" and entry["owner"]==exit_trade["owner"] and entry["quantity"]==exit_trade["quantity"] and entry["side"]!=exit_trade["side"]
        at = seconds(entry["at"])
        end = seconds(exit_trade["at"] if exit_trade else snapshot["updated_at"])
        side = 1 if entry["side"]=="buy" else -1
        item={"id":number,"label":label,"entry_event_index":entry_index,"exit_event_index":exit_index,"entry_time":at,"end_time":end,"entry_price":entry["price"],"exit_price":exit_trade["price"] if exit_trade else None,"side":side,"quantity":entry["quantity"],"owner":entry["owner"],"entry":entry,"exit":exit_trade,"end_kind":"実返済" if exit_trade else "OFF時の最終公開snapshot、返済ではない","actual_realized_net_yen":entry["pnl_yen"]+(exit_trade["pnl_yen"] if exit_trade else 0),"entry_available":{symbol:entry_features(rows,at,side) for symbol,rows in books.items()},"future_diagnostic":held_diagnosis(books["NK225"],at,end,entry["price"],side,entry["quantity"])}
        if exit_trade:
            item["actual_gross_yen"]=(exit_trade["price"]-entry["price"])*side*entry["quantity"]*100
            assert abs(item["actual_gross_yen"]-entry["fee_yen"]-exit_trade["fee_yen"]-item["actual_realized_net_yen"])<1e-6
        cases.append(item)
    result={"spec":{"API_calls":0,"new_trade_replays":0,"markets":"ラージ板代理・実約定はmini","entry_boundary":"約定時刻の同秒を除外し、価格時計がその秒未満の原行だけで計算","hold_boundary":"新規同秒・返済/管理終了同秒は除外","clock":"CurrentPriceTime代理、独立原受信時計なし、補間なし","quote_model":"有限0<Buy1.Price<Sell1.Price。買い玉はbid・売り玉はaskで代理評価","entry_features_use_only_earlier_price_clock":True,"reception_clock_causality_verified":False,"future_extrema_are_diagnostic_only":True,"addon_matching":"HoldIDなしのため個別玉へ配賦しない"},"input_audit":audit,"cases":cases,"recent_trade_sum_net":sum(t["pnl_yen"] for t in trades),"snapshot_realized":snapshot["session_realized_yen"],"snapshot_unrealized_at_detach":snapshot["unrealized_yen"],"snapshot_detach_at":snapshot["updated_at"],"addon_visible_net":sum(t["pnl_yen"] for t in trades if t["owner"]=="addon"),"snapshot_positions":snapshot["positions"]}
    assert abs(result["recent_trade_sum_net"]-result["snapshot_realized"])<1e-6
    (HERE/"実約定3区間の原板診断156.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    draw(books["NK225"],cases,HERE/"実約定3区間の原板156.png")
    print(json.dumps({"read_rows":{s:audit[s]["counts"] for s in audit},"cases":[{"id":c["id"],"entry_clock":clock(c["entry_time"]),"actual_net":c["actual_realized_net_yen"],"pre_progress":{w:v["side_progress_points"] for w,v in c["entry_available"]["NK225"]["windows"].items()},"peak":c["future_diagnostic"]["max_favorable"],"worst":c["future_diagnostic"]["max_adverse"],"back":c["future_diagnostic"]["first_nonpositive_after_peak"]} for c in cases]},ensure_ascii=True))


if __name__=="__main__":
    main()
