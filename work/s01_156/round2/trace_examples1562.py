"""第2巡の対象3親を保存約定だけで比較する。原板は図の値動きと既存約定の時価評価だけに用いる。"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
TARGETS = [("2026-10-22_Day", 0), ("2026-10-15_Day", 0), ("2026-10-01_Day", 1)]


def clock(t: float) -> str:
    """時計を日本時間の時分秒へ変換する。

    引数: t(float)。返り値: str。
    """
    return datetime.fromtimestamp(t, JST).strftime("%H:%M:%S")


def compact_event(e: dict) -> dict:
    """保存注文から判断と実約定を分けた説明用記録を作る。

    引数: e(dict)。返り値: dict。
    """
    s, f = e["signal"], e["fill"]
    return {"action":s["action"],"reason":s["reason_code"],"side":s["side"],
            "decision_at":s["time"],"decision_clock":clock(s["time"]),"decision_index":e["decision_index"],
            "filled_at":f["Time"],"filled_clock":clock(f["Time"]),"fill_index":e["fill_index"],
            "quantity":f["Quantity"],"price":f["Price"],"gross":e["gross"]}


def source_end(case: dict, campaign: int, first_index: int) -> dict:
    """元sourceの全返済判断と仮想約定での完済を保存点から区別する。

    引数: case(dict)、campaign/first_index(int)。返り値: dict。
    疎な保存だけなら正確なイベント時刻とせず、保存点であることを示す。
    """
    seen_live, seen_paper = False, False
    target_zero, filled_zero = None, None
    for snap in case["snapshots"] or []:
        if snap["Index"] < first_index:
            continue
        d = next(d for d in snap["Diagnostics"] if d["owner"] == "core")
        if d["campaign"] != campaign:
            continue
        live = d.get("virtual_quantity", 0)
        paper = d.get("core_exit_shadow", {}).get("virtual_quantity", 0)
        note = {"index":snap["Index"],"time":snap["Time"],"clock":clock(snap["Time"]),
                "source_actual_virtual_quantity":live,"paper_target_quantity":paper,
                "real_quantity":d["actual_quantity"]}
        if seen_paper and paper == 0 and target_zero is None:
            exact = any(e["decision_index"] == snap["Index"] and e["signal"]["owner"] == "core"
                        and e["signal"]["campaign"] == campaign and e["signal"]["action"] == "close"
                        and e["signal"]["reason_code"] not in (15601,15602)
                        for e in case["events"] or [])
            target_zero = dict(note, event_confirmed=exact)
        if seen_live and live == 0 and filled_zero is None:
            exact = any(e["fill_index"] == snap["Index"] and e["signal"]["owner"] == "core"
                        and e["signal"]["campaign"] == campaign and e["signal"]["action"] == "close"
                        and e["signal"]["reason_code"] not in (15601,15602)
                        for e in case["events"] or [])
            filled_zero = dict(note, event_confirmed=exact)
        seen_live |= live > 0
        seen_paper |= paper > 0
    return {"exit_target_zero":target_zero,"virtual_filled_zero":filled_zero}


def summarize(case: dict, campaign: int) -> dict:
    """対象親の元玉・再参加玉・未順行損失と具体注文を分ける。

    引数: case(dict)、campaign(int)。返り値: dict。
    """
    events = [e for e in case["events"] or [] if e["signal"]["owner"] == "core" and e["signal"]["campaign"] == campaign]
    new = [e for e in events if e["signal"]["action"] == "new"]
    parent = (case["parents"] or {}).get(f"core/{campaign}")
    records = []
    for e in new:
        lot = case["entries"][e["fill"]["HoldID"]]
        exits = [x for x in events if any(p["ID"] == lot["ID"] for p in x.get("pieces") or [])]
        snap = next(s for s in case["snapshots"] if s["Index"] == e["decision_index"])
        diag = next(d for d in snap["Diagnostics"] if d["owner"] == "core")
        records.append({"entry":compact_event(e),"lot":lot,"exits":[compact_event(x) for x in exits],
                        "source_exit_at_entry":diag.get("core_exit_shadow"),
                        "is_reentry":e["signal"]["reason_code"] == 15630})
    re = [r for r in records if r["is_reentry"]]
    original = [r for r in records if not r["is_reentry"]]
    assert abs(sum(r["lot"]["Gross"] for r in records) - (parent["Realized"] if parent else 0)) < 1e-7
    return {"id":case["config"]["id"],"parent":parent,"entries":records,
            "original_net":sum(r["lot"]["Gross"] for r in original),
            "reentry_count":len(re),"reentry_quantity":sum(r["lot"]["Quantity"] for r in re),
            "reentry_net":sum(r["lot"]["Gross"] for r in re),
            "reentry_profit":sum(max(0,r["lot"]["Gross"]) for r in re),
            "reentry_loss":sum(max(0,-r["lot"]["Gross"]) for r in re),
            "never_positive_loss":sum(max(0,-r["lot"]["Gross"]) for r in re if r["lot"]["BestPoints"] <= 0),
            "source_end":source_end(case,campaign,new[0]["decision_index"]) if new else None}


def minute_quotes(scene: dict) -> list[dict]:
    """ラージ原板の正常中値を1分へ集め、図用に高安と最終BBOを保存する。

    引数: scene(dict)。返り値: list[dict]。取引判断・新金融再生はしない。
    """
    cache = ROOT / (scene["session"] + "_図用原板1分.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    buckets, previous = {}, scene["start"]
    with open(scene["books"]["NK225"], encoding="utf-8-sig") as f:
        for line in f:
            row = json.loads(line)
            stamp = row.get("CurrentPriceTime")
            if stamp is None:
                continue
            at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            if at < scene["start"] or at > scene["end"] or at < previous or not row.get("CurrentPrice"):
                continue
            previous = at
            bid, ask = row["Buy1"]["Price"], row["Sell1"]["Price"]
            if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask):
                continue
            mid = (bid + ask) / 2
            key = int(at // 60)
            b = buckets.setdefault(key, {"time":at,"low":mid,"high":mid,"mid":mid,"bid":bid,"ask":ask})
            b.update(time=at,low=min(b["low"],mid),high=max(b["high"],mid),mid=mid,bid=bid,ask=ask)
    quotes = list(buckets.values())
    cache.write_text(json.dumps(quotes, ensure_ascii=False), encoding="utf-8")
    return quotes


def marked_curve(quotes: list[dict], case: dict, campaign: int) -> tuple[list[float],list[int]]:
    """保存約定で実在した玉だけを図用BBO時点に評価する。

    引数: quotes(list[dict])、case(dict)、campaign(int)。返り値: 時価円list、実枚数list。
    """
    events = [e for e in case["events"] or [] if e["signal"]["owner"] == "core" and e["signal"]["campaign"] == campaign]
    lots, cash, cursor, values, quantities = {}, 0., 0, [], []
    for q in quotes:
        while cursor < len(events) and events[cursor]["fill"]["Time"] <= q["time"]:
            e = events[cursor]
            s,f = e["signal"],e["fill"]
            if s["action"] == "new":
                lots[f["HoldID"]] = {"side":s["side"],"qty":f["Quantity"],"price":f["Price"]}
            else:
                for target in f["Closed"]:
                    l = lots[target["id"]]
                    cash += l["side"] * target["quantity"] * (f["Price"] - l["price"]) * 100
                    l["qty"] -= target["quantity"]
            cursor += 1
        unrealized = sum(l["side"] * l["qty"] * ((q["bid"] if l["side"] > 0 else q["ask"]) - l["price"]) * 100 for l in lots.values())
        values.append(cash+unrealized);quantities.append(sum(l["qty"] for l in lots.values()))
    return values,quantities


def draw(scene: dict, cases: dict, campaign: int, focus: str) -> str:
    """原板価格と既存約定の親時価・実枚数を暗色図にまとめる。

    引数: scene/cases(dict)、campaign(int)、focus(str)。返り値: 保存PNG名。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    plt.rcParams["font.family"] = "Yu Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    initial = next(e for e in cases["S01"]["events"] if e["signal"]["owner"] == "core" and e["signal"]["campaign"] == campaign and e["signal"]["action"] == "new")
    all_quotes = minute_quotes(scene)
    quotes = [q for q in all_quotes if q["time"] >= initial["signal"]["time"] - 300 and q["time"] <= scene["force_close"]+60]
    dates = [datetime.fromtimestamp(q["time"],JST) for q in quotes]
    fig,axes = plt.subplots(3,1,figsize=(15,10),sharex=True,gridspec_kw={"height_ratios":[2.1,1.5,1]})
    fig.patch.set_facecolor("#10151f")
    for ax in axes:
        ax.set_facecolor("#161e2c");ax.tick_params(colors="#cdd8e8")
        ax.grid(color="#324156",alpha=.55);ax.spines[:].set_color("#42536a")
        ax.yaxis.label.set_color("#d6e1ef")
    axes[0].fill_between(dates,[q["low"] for q in quotes],[q["high"] for q in quotes],color="#9caac0",alpha=.18,label="原板中値の分内高安")
    axes[0].plot(dates,[q["mid"] for q in quotes],color="#c4cfdf",linewidth=1,label="原板中値の各分最終値")
    es=[e for e in cases[focus]["events"] if e["signal"]["owner"]=="core" and e["signal"]["campaign"]==campaign]
    for action,marker,color in [("new","^","#58b5ff"),("close","v","#ffae67")]:
        selected=[e for e in es if e["signal"]["action"]==action]
        axes[0].scatter([datetime.fromtimestamp(e["fill"]["Time"],JST) for e in selected],[e["fill"]["Price"] for e in selected],s=26,marker=marker,color=color,label=f"{focus} 実新規" if action=="new" else f"{focus} 実返済",zorder=4)
    for method,color in [("S01","#ffd166"),("F05","#9d90ca"),(focus,"#58b5ff")]:
        equity,qty=marked_curve(all_quotes,cases[method],campaign)
        selected=[(q,e,n) for q,e,n in zip(all_quotes,equity,qty) if quotes[0]["time"]<=q["time"]<=quotes[-1]["time"]]
        at=[datetime.fromtimestamp(q["time"],JST) for q,_,_ in selected]
        axes[1].plot(at,[e/10000 for _,e,_ in selected],color=color,label=f"{method} 親の実現＋含み",linewidth=1.4)
        axes[2].step(at,[n for _,_,n in selected],where="post",color=color,label=method,linewidth=1.2)
    axes[0].set_ylabel("日経価格");axes[1].set_ylabel("親の時価（万円）");axes[2].set_ylabel("実保有枚数")
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=JST))
    for ax in axes:
        legend=ax.legend(loc="upper left",fontsize=9,facecolor="#161e2c",edgecolor="#42536a")
        for label in legend.get_texts():label.set_color("#e7edf7")
    fig.suptitle(f'{scene["session"]} core親{campaign}：全量回収後の再参加を追加した結果',color="#eff5ff",fontsize=17)
    fig.text(.06,.025,"新しい金融再生は行わず、保存済み約定だけを原板BBOで再評価。手数料0／日経mini。Source仮想玉を実保有へ含めない。",color="#b8c7dc",fontsize=10)
    fig.tight_layout(rect=[.025,.045,1,.955])
    name=f'{scene["session"]}_{focus}_同波再参加.png'
    fig.savefig(ROOT/name,dpi=140,facecolor=fig.get_facecolor());plt.close(fig)
    return name


def main() -> None:
    """完了済み3親の比較JSON・短い表・暗色原板図を保存する。

    引数: なし。返り値: なし。第二巡の正常終了記録を必須とする。
    """
    run = json.loads((ROOT/"金融実行1562.json").read_text(encoding="utf-8-sig"))
    assert run["終了コード"] == 0 and run["参照改変数"] == 0 and run["結果ファイル数"] == 27
    result=[];lines=["# 第二巡：失った大勝ち3親の再参加追跡","","金額は対象のcore親だけ。全場成績とは分ける。新規の列は元玉を除いた再参加回数。未順行損は再参加した実玉が保有中に一度も正にならず終わった損失。手数料0・日経mini。",""]
    for scene_name,campaign in TARGETS:
        doc=json.loads((ROOT/"results_go"/(scene_name+"_S01.json")).read_text(encoding="utf-8"))
        cases={c["config"]["id"]:c for c in doc["cases"]}
        rows=[summarize(c,campaign) for c in cases.values()]
        result.append({"session":scene_name,"owner":"core","campaign":campaign,"rows":rows})
        lines += [f"## {scene_name} core親{campaign}","","|手法|親収支|再参加回数|再参加だけの収支|未順行の再参加損|","|---|---:|---:|---:|---:|"]
        for row in rows:
            if row["id"] not in ["S01","F05","F09","R01","R02","R03","R04","R05","R06"]:continue
            net=row["parent"]["Realized"] if row["parent"] else 0
            lines.append(f'|{row["id"]}|{net:+,.0f}円|{row["reentry_count"]}|{row["reentry_net"]:+,.0f}円|−{row["never_positive_loss"]:,.0f}円|')
        if scene_name in ("2026-10-22_Day","2026-10-01_Day"):
            focus="R01" if scene_name=="2026-10-22_Day" else "R03"
            name=draw(doc["scene"],cases,campaign,focus)
            lines += ["",f"![{scene_name}の原板と実玉]({name})",""]
    (ROOT/"3親の具体追跡1562.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (ROOT/"3親の具体追跡1562.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
