"""既存夜間会計から失敗した組の時刻と価格成分を復元する。金融再生は行わない。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "work/stability126_20261019"
JST = timezone(timedelta(hours=9))
REASONS = {
    1: "紙上組の損失上限", 2: "追跡返済", 5: "判断撤回", 7: "一部利確",
    8: "保有上限", 9: "場内返済", 12: "米開始静観", 13: "方向撤回",
    30: "悪化による半減", 32: "実組の損失上限", 70: "追加利益床",
    71: "予定静観", 73: "場損失停止",
    90: "新規", 91: "紙上全返済", 92: "方向不在", 93: "場末",
}


def read(path: Path, references: list) -> bytes:
    """
    機能: 保存済み資料を読み、診断根拠として位置と指紋を残す。
    引数: path(Path)は既存資料、references(list)は読取記録。
    返り値: bytesは保存内容。
    """
    raw = path.read_bytes()
    references.append(dict(path=path.relative_to(ROOT).as_posix(),
                           sha256=hashlib.sha256(raw).hexdigest()))
    return raw


def clock(seconds: float) -> str:
    """
    機能: 保存された価格時計を日本時刻へ表記する。
    引数: seconds(float)は保存価格時計のＵｎｉｘ秒。
    返り値: strは年月日時分秒。受信時計とは区別する。
    """
    return datetime.fromtimestamp(float(seconds), JST).isoformat()


def summarize(rows: list) -> dict:
    """
    機能: 保存組を損失の順行有無と価格成分で整理する。
    引数: rows(list[dict])は既存の完結組。
    返り値: dictは件数・円損益・失敗分類。
    """
    losses = [r for r in rows if r["net"] < 0]
    no_positive = [r for r in losses if r["peak_gross"] <= 0]
    weak = [r for r in losses if 0 < r["peak_gross"] < r["risk_yen"]]
    strong = [r for r in losses if r["peak_gross"] >= r["risk_yen"]]
    return dict(groups=len(rows), winners=sum(r["net"] > 0 for r in rows), losers=len(losses),
        gross=sum(r["gross"] for r in rows), fees=sum(r["fees"] for r in rows),
        net=sum(r["net"] for r in rows), last_direction=sum(r["last_direction"] for r in rows),
        entry_quote_difference=sum(r["entry_quote_difference"] for r in rows),
        exit_quote_difference=sum(r["exit_quote_difference"] for r in rows),
        never_positive=dict(groups=len(no_positive), net=sum(r["net"] for r in no_positive)),
        positive_less_than_risk=dict(groups=len(weak), net=sum(r["net"] for r in weak)),
        positive_at_least_risk=dict(groups=len(strong), net=sum(r["net"] for r in strong)),
        profit_giveback_on_losses=sum(r["peak_gross"] for r in losses))


def main() -> None:
    """
    機能: 全夜間二候補の保存注文と曲線を読み、両商品の赤字上位三場を具体診断する。
    引数: なし。
    返り値: None。結果を自分の作業先へ保存し、元会計・原市場データは変更しない。
    """
    target = HERE / "夜間二候補の全組と赤字上位三場の具体診断_最終.json"
    assert not target.exists()
    references = []
    fees = json.loads(read(BASE / "fees_20261020/二候補の四十三場の注文別手数料と実保有枚数.json", references))
    fee_index = {(r["method"], r["session"], r["symbol"]): r for r in fees["rows"]}
    source_paths = [
        BASE / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json",
        BASE / "update_20261020/追加二場の八公開選択会計.json",
    ]
    caches = {}
    for source_path in source_paths:
        source = json.loads(read(source_path, references))
        for item in source["cache"]:
            if item["session"].endswith("_Night") and item.get("model", "next_normal_bbo") == "next_normal_bbo":
                caches[item["session"], item["symbol"]] = item
    groups, session_rows = [], []
    packets = {}
    for (scene, symbol), item in sorted(caches.items()):
        if scene not in packets:
            path = BASE / "input_audit/attempt2/prepared126" / (scene + ".pkl")
            if not path.exists():
                path = BASE / "update_20261020/prepared" / (scene + ".pkl")
            packets[scene] = pickle.loads(read(path, references))
        packet = packets[scene]
        ready = packet["inputs"][scene, symbol]
        q = packet["quotes"][scene, symbol]
        times, last = ready["time_s"], ready["last"]
        point_value, unit_tenths = (1000., 418) if symbol == "TOPIX" else (10., 110)
        cache_path = ROOT / item["path"]
        with np.load(cache_path, allow_pickle=False) as archive:
            references.append(dict(path=item["path"], sha256=item["sha256"], verification="既存監査で拘束済みのＮＰＺ参照。今回全ファイル指紋の再走査なし"))
            for method in ("GU_Q", "G_Q"):
                orders, cycles, trades, curve = (
                    archive[method + "__" + name] for name in ("orders", "cycles", "trades", "curve"))
                current_groups = []
                for cycle in cycles:
                    cid, first, final = map(int, cycle[:3])
                    side, risk = int(cycle[8]), float(cycle[4])*point_value
                    selected_orders = orders[orders[:, 2] == cid]
                    selected_trades = trades[trades[:, 0] == cid]
                    quantity = int(selected_orders[selected_orders[:, 7] == 1, 4].sum())
                    parent_fees = int(sum(int(o[4])*unit_tenths//10 for o in selected_orders))
                    base = curve[first-1, 0] if first else 0.
                    assert first == 0 or np.all(curve[first-1, 2:4] == 0.)
                    path = (curve[first:final+1, 0] - base)*point_value
                    peak_position = int(np.argmax(path))
                    peak = max(0., float(path[peak_position]))
                    gross = float(cycle[3])*point_value
                    assert np.isclose(path[-1], gross)
                    last_component = entry_difference = exit_difference = 0.
                    exit_orders = []
                    for trade in selected_trades:
                        e, x = int(trade[6]), int(trade[7])
                        direction, qty = int(trade[2]), int(trade[3])
                        last_component += direction*(last[x]-last[e])*qty*point_value
                        entry_difference += direction*(trade[4]-last[e])*qty*point_value
                        exit_difference += direction*(last[x]-trade[5])*qty*point_value
                    assert np.isclose(last_component-entry_difference-exit_difference, gross, atol=1e-5)
                    for order in selected_orders[selected_orders[:, 7] == 0]:
                        x, decision = int(order[0]), int(order[1])
                        exit_orders.append(dict(time=clock(times[x]), decision_time=clock(times[decision]),
                            row=x, decision_row=decision, price=float(order[5]), quantity=int(order[4]),
                            reason=REASONS.get(int(order[6]), str(int(order[6]))),
                            gross=float(selected_trades[selected_trades[:, 7] == x, 10].sum())*point_value))
                    entry = selected_orders[selected_orders[:, 7] == 1][0]
                    decision = int(entry[1])
                    elapsed_open = float(times[first]-ready["us_open"])
                    segment = "米開始前" if elapsed_open < -900 else "米開始前後15分" if elapsed_open <= 900 else "米開始後"
                    result = dict(method=method, session=scene, symbol=symbol, cid=cid,
                        entry_time=clock(times[first]), decision_time=clock(times[decision]),
                        entry_row=first, decision_row=decision, exit_time=clock(times[final]), exit_row=final,
                        direction="買い" if side > 0 else "売り", entry_price=float(entry[5]),
                        quantity=quantity, atr=float(cycle[5]), risk_yen=risk, gross=gross,
                        fees=parent_fees, net=gross-parent_fees, peak_gross=peak,
                        peak_time=clock(times[first+peak_position]), worst_gross=float(path.min()),
                        last_direction=float(last_component),
                        entry_quote_difference=float(entry_difference),
                        exit_quote_difference=float(exit_difference),
                        holding_seconds=float(times[final]-times[first]), segment=segment,
                        entry_us_open_minutes=elapsed_open/60.,
                        entry_last=float(last[first]), entry_bid=float(q["bid"][first]), entry_ask=float(q["ask"][first]),
                        exits=exit_orders)
                    groups.append(result)
                    current_groups.append(result)
                summary = summarize(current_groups)
                expected = fee_index[method, scene, symbol]
                assert np.isclose(summary["net"], expected["after_fees"])
                assert summary["fees"] == expected["fees"]
                ordered = sorted(current_groups, key=lambda r:r["entry_row"])
                changes = sum(a["direction"] != b["direction"] for a,b in zip(ordered, ordered[1:]))
                session_rows.append(dict(method=method, session=scene, symbol=symbol, **summary,
                    direction_changes=changes,
                    losing_groups_same_direction_after_loss=sum(a["net"]<0 and b["net"]<0 and a["direction"]==b["direction"] for a,b in zip(ordered,ordered[1:])),
                    direction_net={direction:sum(r["net"] for r in ordered if r["direction"]==direction) for direction in ("買い","売り")}))
        print(scene, symbol, flush=True)
        # ----------------------------------------
        # 同じ場の二商品を処理後に大きい保存市場配列を解放する。
        if symbol == sorted([s for sc,s in caches if sc == scene])[-1]:
            del packets[scene]
    rankings = []
    all_summaries = []
    for method in ("GU_Q", "G_Q"):
        for symbol in ("TOPIX", "NK225"):
            part = [r for r in session_rows if r["method"] == method and r["symbol"] == symbol]
            worst = sorted(part, key=lambda r:r["net"])[:3]
            rankings.extend(worst)
            selected = [r for r in groups if r["method"]==method and r["symbol"]==symbol]
            all_summaries.append(dict(method=method,symbol=symbol,**summarize(selected),
                segments=[dict(segment=segment,**summarize([r for r in selected if r["segment"]==segment]))
                          for segment in ("米開始前","米開始前後15分","米開始後")]))
    target.write_text(json.dumps(dict(passed=True, summaries=all_summaries, worst_three=rankings,
        session_rows=session_rows, groups=groups, sources=references,
        financial_replays=0, original_market_reads=0, API=0,
        limits=["全21夜間は既知開発データ。時分は保存価格時計で受信時計ではない。",
                "途中最大清算利益は実現可能利益の保証ではなく、当時の実返済成績に加算しない。",
                "価格方向成分とLast対約定気配差の会計分解であり、気配差を全て異常データと断定しない。",
                "米開始前後の帰属は新規時刻で区分し、その後の損益原因を米市場のみに帰属しない。"],
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
        ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(all_summaries,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
