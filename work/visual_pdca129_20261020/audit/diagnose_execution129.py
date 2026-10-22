"""保存された売買を固定し、時計・価格代理・呼値単位の影響を診断する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/daynight128_20261020"
JST = timezone(timedelta(hours=9))


def read(path):
    """
    機能: 保存済みJSONを読み取る。
    引数: path(Path)は資料位置。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def finite(value):
    """
    機能: 非有限の観測をJSONの不明値へ変換する。
    引数: value(float)は観測値。
    返り値: float又はNone。
    """
    return float(value) if np.isfinite(value) else None


def stamp(value):
    """
    機能: 保存価格時計を日本時刻で表示する。
    引数: value(float)はUnix秒。
    返り値: strは時差付き時刻。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def stats(rows):
    """
    機能: 固定した既存親の診断群を集計する。
    引数: rows(list[dict])は保存売買を分類した親。
    返り値: dictは分母・勝敗・価格代理差と損益。
    """
    return {
        "親数": len(rows),
        "黒字": sum(r["net"] > 0 for r in rows),
        "赤字": sum(r["net"] < 0 for r in rows),
        "収支": sum(r["net"] for r in rows),
        "実気配粗損益": sum(r["gross"] for r in rows),
        "同じ注文行のLast粗損益": sum(r["last_gross"] for r in rows),
        "実気配とLastとの差": sum(r["gross"] - r["last_gross"] for r in rows),
        "手数料": sum(r["fees"] for r in rows),
        "実気配赤字だが同時刻Last手数料後黒字": sum(r["net"] < 0 < r["last_gross"] - r["fees"] for r in rows),
        "同時刻Lastでも赤字の実赤字親": sum(r["net"] < 0 and r["last_gross"] - r["fees"] < 0 for r in rows),
    }


def main():
    """
    機能: D17・N27・N36の保存親を固定し、実行価格と時計の特徴を比較する。
    引数: なし。
    返り値: None。自分の診断JSONのみ保存し、入口や出口の金融再生は行わない。
    """
    target = HERE / "価格時計と気配及び呼値尺度の独立診断.json"
    assert not target.exists()
    manifest = read(OLD / "入力準備.json")
    cases = []
    order_rows = []
    sources = []
    market_quality = []
    for packet_ref in manifest["packets"]:
        scene = packet_ref["session"]
        payload = (ROOT / packet_ref["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == packet_ref["sha256"]
        packet = pickle.loads(payload)
        sources.append({"path": packet_ref["path"], "sha256": packet_ref["sha256"]})
        for symbol in ("TOPIX", "NK225"):
            key = scene, symbol
            ready, quote, market = packet["inputs"][key], packet["quotes"][key], packet["markets"][key]
            t, last, bid, ask = ready["time_s"], ready["last"], quote["bid"], quote["ask"]
            mid = (bid + ask) * .5
            good = quote["quote_valid"] & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
            tick = ready["tick"]
            same_clock = np.r_[False, np.diff(t) == 0]
            changed_quote = np.r_[False, (np.diff(bid) != 0) | (np.diff(ask) != 0)]
            outside = good & ((last < bid) | (last > ask))
            market_quality.append({
                "session": scene, "symbol": symbol, "原行数": len(t),
                "正常気配行": int(good.sum()), "同価格時計行": int(same_clock.sum()),
                "同価格時計かつ気配価格変更": int((same_clock & changed_quote & good).sum()),
                "Lastが正常気配外": int(outside.sum()),
            })
            methods = ("D17",) if scene.endswith("_Day") else ("N27", "N36")
            for method in methods:
                folder = "round5" if method == "N36" else "round3"
                path = OLD / folder / "measurement" / (symbol + "_" + scene + ".npz")
                with np.load(path, allow_pickle=False) as saved:
                    orders = saved[method + "__orders"]
                    trades = saved[method + "__trades"]
                    cycles = saved[method + "__cycles"] if method == "D17" else None
                parents = defaultdict(list)
                for o in orders:
                    parents[int(o[2])].append(o)
                for parent, rows in parents.items():
                    entry = rows[0]
                    e, d, side, qty = int(entry[0]), int(entry[1]), int(entry[3]), int(entry[4])
                    end = int(rows[-1][0])
                    mult, fee = (1000., 418) if symbol == "TOPIX" else (10., 110)
                    fees = sum(int(o[4]) * fee // 10 for o in rows)
                    gross = sum(-o[3] * o[4] * o[5] * mult for o in rows)
                    last_gross = sum(-o[3] * o[4] * last[int(o[0])] * mult for o in rows)
                    decision_last_gross = sum(-o[3] * o[4] * last[int(o[1])] * mult for o in rows)
                    if cycles is not None:
                        cycle = next(c for c in cycles if int(c[0]) == parent)
                        width = float(cycle[5])
                    else:
                        trade = next(v for v in trades if int(v[0]) == e)
                        width = float(trade[11])
                    earlier = int(np.searchsorted(t, t[d] - 30., side="right") - 1)
                    previous_mid_change = side * (mid[d] - mid[earlier]) if earlier >= 0 and good[earlier] else np.nan
                    own_last_change = side * (last[d] - last[earlier]) if earlier >= 0 else np.nan
                    low = np.searchsorted(t, t[d], side="left")
                    high = np.searchsorted(t, t[d], side="right")
                    moves = side * ((bid[e:end+1] if side > 0 else ask[e:end+1]) - entry[5])
                    selected = good[e:end+1]
                    item = {
                        "method": method, "session": scene, "symbol": symbol, "parent": parent,
                        "side": side, "quantity": qty, "decision_row": d, "entry_row": e, "exit_row": end,
                        "decision_seq": int(ready["seq"][d]), "entry_seq": int(ready["seq"][e]),
                        "exit_seq": int(ready["seq"][end]),
                        "decision_time": stamp(t[d]), "entry_time": stamp(t[e]), "exit_time": stamp(t[end]),
                        "entry_price": float(entry[5]), "exit_price": float(rows[-1][5]),
                        "gross": float(gross), "net": float(gross-fees), "fees": fees,
                        "last_gross": float(last_gross), "decision_last_gross": float(decision_last_gross),
                        "width": width, "width_ticks": width/tick,
                        "spread": float(ask[d]-bid[d]), "spread_r": float((ask[d]-bid[d])/width),
                        "fee_r": fees/(qty*width*mult),
                        "entry_adverse_last_ticks": float(side*(entry[5]-last[e])/tick),
                        "entry_last": float(last[e]), "entry_bid": float(bid[e]), "entry_ask": float(ask[e]),
                        "decision_last_outside": bool(outside[d]),
                        "decision_mid_gap_r": float(side*(mid[d]-last[d])/width),
                        "own30_last_direction_points": finite(own_last_change),
                        "own30_mid_direction_points": finite(previous_mid_change),
                        "own30_market_atr": finite(side*market[d,4]),
                        "peer30_market_atr": finite(side*market[d,6]),
                        "peer_source_age_sec": finite(t[d]-market[d,8]),
                        "entry_fill_priceclock_delay_sec": float(t[e]-t[d]),
                        "entry_fill_originalrow_gap": int(ready["seq"][e]-ready["seq"][d]),
                        "same_priceclock_totalrows_at_decision": int(high-low),
                        "same_priceclock_future_rows_at_decision": int(high-d-1),
                        "mfe": float(max(0., moves[selected].max())),
                        "mae": float(min(0., moves[selected].min())),
                    }
                    cases.append(item)
                    for o in rows:
                        f, source, oside, oqty = int(o[0]), int(o[1]), int(o[3]), int(o[4])
                        order_rows.append({
                            "method": method, "session": scene, "symbol": symbol, "parent": parent,
                            "entry": bool(o[7]), "source_row": source, "fill_row": f,
                            "source_seq": int(ready["seq"][source]), "fill_seq": int(ready["seq"][f]),
                            "source_time": stamp(t[source]), "fill_time": stamp(t[f]),
                            "same_priceclock": bool(t[f] == t[source]),
                            "priceclock_delay_sec": float(t[f]-t[source]),
                            "adverse_last_points": float(oside*(o[5]-last[f])),
                            "decision_to_fill_quote_points": finite(oside*(o[5]-(ask[source] if oside > 0 else bid[source]))) if good[source] else None,
                            "last_outside": bool(outside[f]),
                            "price": float(o[5]), "last": float(last[f]), "bid": float(bid[f]), "ask": float(ask[f]),
                        })
        print(scene, flush=True)

    # ----------------------------------------
    # 閾値の最適化はせず、同じ保存親を一定の観測軸で区分する。
    summaries = []
    for method in ("D17", "N27", "N36"):
        for symbol in ("TOPIX", "NK225"):
            part = [r for r in cases if r["method"] == method and r["symbol"] == symbol]
            values = np.array([r["width_ticks"] for r in part])
            item = {
                "method": method, "symbol": symbol, **stats(part),
                "幅の呼値数_最小中央値最大": [float(values.min()), float(np.median(values)), float(values.max())],
                "気配差Rの中央値": float(np.median([r["spread_r"] for r in part])),
                "費用Rの中央値": float(np.median([r["fee_r"] for r in part])),
                "Lastが気配外の判断親": stats([r for r in part if r["decision_last_outside"]]),
                "方向Last正だが中値非正": stats([r for r in part if r["own30_last_direction_points"] is not None
                                                 and r["own30_last_direction_points"] > 0
                                                 and r["own30_mid_direction_points"] is not None
                                                 and r["own30_mid_direction_points"] <= 0]),
                "呼値尺度別": [
                    {"区分": label, **stats([r for r in part if lower <= r["width_ticks"] < upper])}
                    for lower, upper, label in ((0.,5.,"5呼値未満"),(5.,10.,"5以上10呼値未満"),(10.,float("inf"),"10呼値以上"))
                ],
                "気配差対幅別": [
                    {"区分": label, **stats([r for r in part if lower <= r["spread_r"] < upper])}
                    for lower, upper, label in ((0.,.1,"0.1R未満"),(.1,.2,"0.1以上0.2R未満"),(.2,float("inf"),"0.2R以上"))
                ],
            }
            summaries.append(item)
    matched = []
    for method in ("D17", "N27", "N36"):
        for symbol in ("TOPIX", "NK225"):
            part = [r for r in cases if r["method"] == method and r["symbol"] == symbol]
            worst = sorted([r for r in part if r["net"] < 0], key=lambda r:r["net"])[:2]
            wins = [r for r in part if r["net"] > 0]
            for loss in worst:
                winner = min(wins, key=lambda r: abs(np.log(r["width_ticks"]/loss["width_ticks"]))
                             + abs(r["spread_r"]-loss["spread_r"])
                             + (0.25 if r["side"] != loss["side"] else 0.))
                matched.append({"負け": loss, "幅と気配比が近い勝ち": winner,
                                "照合基準": "同手法同商品、幅呼値数比の対数距離＋気配R差＋売買方向不一致0.25。事後説明用で予測精度ではない。"})
    result = {
        "passed": True, "financial_replays": 0, "API": 0,
        "対象": "D17全22日中、N27及びN36全21夜間の保存親と同一注文列。新戦略の売買は生成しない。",
        "注意": ["同じ注文行のLast損益は価格代理の差分診断。Lastを使う別戦略の成績ではない。",
                 "分類閾値は事後診断用。分類の親を除外しても新戦略の成績にはならない。",
                 "同価格時計の将来行数はデータ品質診断だけ。当時の入口条件には利用不可。",
                 "幅は日中の初期ATR、夜間のmax(ATR,4呼値)。固定の手数料とラージ気配代理を継承。"],
        "summary": summaries, "matched": matched, "trades": cases, "orders": order_rows,
        "market_quality": market_quality, "sources": sources,
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(summaries,ensure_ascii=False))


if __name__ == "__main__":
    main()
