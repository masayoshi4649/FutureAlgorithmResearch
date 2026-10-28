"""保存した約定原行と正常ラージ気配から、数量判断の失敗例を図示する。金融再生なし。"""

from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "work/night159/diagnosis"
JST = timezone(timedelta(hours=9))


def read(path):
    """JSONを読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_quotes(path, start, end, session_start):
    """正常原行の価格を選び、採用添字を同時刻の並びを含めて保持する。

    引数: path(Path)、start/end/session_start(float)。返り値: list[dict]。
    """
    rows = []
    previous = session_start
    index = -1
    with path.open(encoding="utf-8-sig") as source:
        for line, text in enumerate(source, 1):
            raw = json.loads(text)
            stamp = raw.get("CurrentPriceTime")
            if not stamp:
                continue
            at = datetime.fromisoformat(stamp).timestamp()
            if at < session_start or at < previous or (raw.get("CurrentPrice") or 0) <= 0:
                continue
            previous = at
            index += 1
            if not start <= at <= end:
                continue
            bid = (raw.get("Buy1") or {}).get("Price") or 0
            ask = (raw.get("Sell1") or {}).get("Price") or 0
            if math.isfinite(bid + ask) and 0 < bid < ask:
                rows.append({"time": at, "bid": bid, "ask": ask, "index": index, "line": line})
    return rows


def main():
    """三つの原板経路を暗背景で描画し、図の約定一致証跡を保存する。

    引数: なし。返り値: None。
    """
    source = HERE / "悪化三夜の保存会計と原板159.json"
    saved = read(source)
    scenes = {s["session"]: s for s in read(ROOT / "work/audit159/inputs159.json")["sessions"]}
    examples = [
        ("2026-10-19_Night", "後半/episode/0", "① 支持0.524で増枚したが、54秒で逆行", 120, 90,
         "元10 → N04 57 micro\nこの親：元 −10,000円 → N04 −57,000円"),
        ("2026-10-19_Night", "後半/addon/2", "② 支持0.560で増枚。100pt順行を残せず逆行", 180, 100,
         "元20 → N04 60 micro\nこの親：元 −32,000円 → N04 −96,000円"),
        ("2026-10-14_Night", "後半/core/1", "③ 支持が計算できず減枚し、大きな勝ちも縮小", 120, 60,
         "元50 → N04 10 micro\nこの親：元 +197,000円 → N04 +39,400円"),
    ]
    font = Path("C:/Windows/Fonts/meiryo.ttc")
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({"font.size": 11, "axes.unicode_minus": False})
    fig, axes = plt.subplots(3, 1, figsize=(16, 13.5))
    fig.patch.set_facecolor("#101722")
    fig.subplots_adjust(left=.07, right=.98, top=.90, bottom=.08, hspace=.45)
    fig.suptitle("支持の高低だけで数量を変えた結果 — 保存原板で見る三例", color="#f1f5f9", fontsize=20, y=.977)
    fig.text(.07, .935, "N04＝米国開始後だけ支持で数量変更。ラージ気配を約定代理に使用／micro 1枚=10円/pt、費用0", color="#aebed0", fontsize=11)
    proof = []
    for ax, (session, key, title, before, after, note) in zip(axes, examples):
        s = next(x for x in saved["worst_three"] if x["session"] == session)
        parent = next(x for x in s["parents"] if x["parent"] == key)
        events = parent["events"]
        start, end = min(e["FillTime"] for e in events)-before, max(e["FillTime"] for e in events)+after
        quotes = load_quotes(Path(s["book_paths"]["NK225"]), start, end, scenes[session]["start"])
        indexed = {q["index"]: q for q in quotes}
        for e in events:
            q = indexed[e["FillIndex"]]
            assert (q["time"],q["bid"],q["ask"],q["line"]) == (e["FillTime"],e["Bid"],e["Ask"],e["raw_exact_fill"]["line"])
        t = np.array([q["time"] for q in quotes])
        x = mdates.date2num([datetime.fromtimestamp(v, JST) for v in t])
        bid, ask = np.array([q["bid"] for q in quotes],dtype=float), np.array([q["ask"] for q in quotes],dtype=float)
        # ----------------------------------------
        # 観測時計の空白を線でつながず、欠測と価格変化を混同させない。
        gaps = np.r_[False,np.diff(t)>30]
        bid[gaps] = np.nan
        ask[gaps] = np.nan
        ax.set_facecolor("#172230")
        ax.plot(x, ask, color="#58c9e9", linewidth=.9, label="売気配（売玉の返済側）", alpha=.95)
        ax.plot(x, bid, color="#637f9f", linewidth=.65, label="買気配", alpha=.85)
        ax.fill_between(x,bid,ask,color="#58c9e9",alpha=.12)
        ax.set_title(title, loc="left", color="#f1f5f9", fontsize=14, pad=15)
        ax.text(.99,.98,note,transform=ax.transAxes,va="top",ha="right",color="#e2e8f0",fontsize=11,
                bbox={"facecolor":"#101722","edgecolor":"#304358","alpha":.93,"pad":8})
        display_events = []
        for e in events:
            if display_events and (e["FillTime"], e["Price"], bool(e["Order"]["Targets"])) == (display_events[-1]["FillTime"], display_events[-1]["Price"], bool(display_events[-1]["Order"]["Targets"])):
                display_events[-1]["display_quantity"] += e["Order"]["Quantity"]
            else:
                display_events.append({**e, "display_quantity": e["Order"]["Quantity"]})
        for i,e in enumerate(display_events):
            close = bool(e["Order"]["Targets"])
            clock = datetime.fromtimestamp(e["FillTime"],JST)
            marker, color = ("^","#68e0ac") if close else ("v","#ffb566")
            ax.scatter([clock],[e["Price"]],s=85,marker=marker,color=color,zorder=5,edgecolor="#0b111a",linewidth=.7)
            label = f"{clock:%H:%M:%S} {'返済' if close else '売新規'} {e['display_quantity']}枚\n{e['Price']:,.0f}"
            dx,dy = ((12,-48) if i == 0 else (-12,25))
            if key == "後半/episode/0" and i == 0:
                dx,dy = 16,40
            if key == "後半/addon/2":
                dx,dy = (20,38) if i == 0 else (-16,-52)
            if key == "後半/core/1" and i==1:
                dx,dy = -12,30
            ax.annotate(label,(mdates.date2num(clock),e["Price"]),xytext=(dx,dy),textcoords="offset points",
                        color=color,fontsize=10,ha="left" if i==0 else "right",va="center",
                        arrowprops={"arrowstyle":"-","color":color,"lw":.8},
                        bbox={"facecolor":"#101722","edgecolor":"none","alpha":.87,"pad":3})
        if key=="後半/core/1":
            ax.text(.02,.08,"初回の支持は未知：5秒前の正常価格端が24秒遅れ。\n未知を弱い支持と同じにして最小10枚へ縮小した。",transform=ax.transAxes,
                    color="#d4c3f5",fontsize=10,bbox={"facecolor":"#101722","edgecolor":"none","alpha":.9,"pad":6})
        if key=="後半/addon/2":
            best = parent["lots"][0]
            ax.axhline(best["Entry"]-100,color="#e4d069",linestyle=":",linewidth=1)
            ax.text(.02,.08,"点線：売建値から100pt順行の返済気配\nその後の損失拡大は、支持による増枚で3倍になった。",transform=ax.transAxes,
                    color="#e4d069",fontsize=10,bbox={"facecolor":"#101722","edgecolor":"none","alpha":.9,"pad":6})
        locator = mdates.MinuteLocator(interval=1,tz=JST) if key == "後半/episode/0" else mdates.AutoDateLocator(minticks=4,maxticks=8,tz=JST)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=JST))
        ax.tick_params(colors="#b8c7d7")
        ax.set_ylabel("日経先物価格",color="#b8c7d7")
        ax.grid(color="#344457",alpha=.5,linewidth=.6)
        for spine in ax.spines.values():
            spine.set_color("#344457")
        ax.text(0,-.19,session.replace("_Night"," ナイト")+" ／ 図中は日本時間（翌日の時刻を含む）", transform=ax.transAxes,color="#94a8bd",fontsize=10)
        if ax is axes[0]:
            ax.legend(loc="lower left",facecolor="#101722",edgecolor="#304358",labelcolor="#cad8e5",fontsize=9)
        proof.append({"session":session,"parent":key,"normal_quotes":len(quotes),"fill_indices":[e["FillIndex"] for e in events],"fill_raw_exact":True,"base_net":parent["base"]["Realized"],"N04_net":parent["N04"]["Realized"]})
    fig.text(.07,.022,"事後診断として選んだ3例。図の先の高安・返済結果は入口判断に使用していない。価格時計は受信時計と異なり、30秒超の空白は線を切った。",color="#9aacbf",fontsize=10)
    destination = HERE/"原板三例159.png"
    fig.savefig(destination,dpi=140,facecolor=fig.get_facecolor())
    plt.close(fig)
    (HERE/"原板三例159_照合.json").write_text(json.dumps({"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"image_sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),"passed":True,"financial_replay":0,"panels":proof},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"path":str(destination),"panels":len(proof),"passed":True},ensure_ascii=False))


if __name__ == "__main__":
    main()
