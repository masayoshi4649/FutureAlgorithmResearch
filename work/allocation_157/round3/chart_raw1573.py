"""既存ラージ原板を図示し、保存O01約定の追加位置を示す。売買再生は行わない。"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TZ = timezone(timedelta(hours=9))


def read(path):
    """保存されたUTF-8 JSONを読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def prices(scene, start, end):
    """表示区間の正常原板中値とLastを原資料から抽出する。

    引数: scene(dict)、start/end(float)。返り値: list[tuple]。
    """
    out = []
    with Path(scene["books"]["NK225"]).open(encoding="utf-8-sig") as stream:
        for line in stream:
            raw = json.loads(line)
            stamp = raw.get("CurrentPriceTime")
            if not stamp:
                continue
            at = datetime.fromisoformat(stamp).timestamp()
            if not start <= at <= end:
                continue
            bid, ask = raw.get("Buy1", {}).get("Price", 0), raw.get("Sell1", {}).get("Price", 0)
            last = raw.get("CurrentPrice", 0)
            if not (0 < bid < ask and last > 0):
                continue
            out.append((at, (bid+ask)/2, last))
    return out


def draw():
    """負けと勝ちの2場を暗色価格図へ描き、元玉/追加/返済の実時刻を重ねる。

    引数: なし。返り値: なし。集計済みO01約定だけをマーカーへ使う。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    plt.rcParams["font.family"] = "Yu Gothic"
    manifest = read(ROOT / "work/s01_156/inputs156.json")
    fig, axs = plt.subplots(2, 1, figsize=(15, 10), facecolor="#101722")
    settings = [("2026-10-06_Day", "09:20", "13:15", "下げを追撃した後に反転：元玉 −76,800円＋追加玉 −200,000円"),
                ("2026-10-23_Day", "10:05", "15:36", "途中の逆行後に上伸：元玉 +63,500円＋追加玉 +427,700円")]
    evidence = []
    for ax, (session, start_hm, end_hm, title) in zip(axs, settings):
        scene = next(s for s in manifest["sessions"] if s["session"] == session)
        date = session[:10]
        start = datetime.fromisoformat(date+"T"+start_hm+":00+09:00").timestamp()
        end = datetime.fromisoformat(date+"T"+end_hm+":00+09:00").timestamp()
        raw = prices(scene, start, end)
        doc = read(HERE / "results_go" / (session + "_S01.json"))
        case = next(c for c in doc["cases"] if c["config"]["id"] == "O01")
        events = [e for e in case["canonical"]["Events"] if e["Order"]["Parent"] == "addon/0"]
        x = [datetime.fromtimestamp(p[0], TZ) for p in raw]
        ax.set_facecolor("#151e2c")
        ax.plot(x, [p[1] for p in raw], color="#b6c7df", linewidth=.8, alpha=.9, label="ラージ正常気配の中値")
        ax.plot(x, [p[2] for p in raw], color="#6a819d", linewidth=.45, alpha=.35, label="原板Last")
        labels = []
        number = 0
        closed = {}
        for e in events:
            o = e["Order"]
            if o["Targets"]:
                group = closed.setdefault((e["FillTime"], e["Price"]), {"qty":0,"gross":0})
                group["qty"] += o["Quantity"]
                group["gross"] += e["Gross"]
                continue
            number += 1
            color = "#59e0dc" if o["Kind"] == "initial" else "#ffb64f"
            time = datetime.fromtimestamp(e["FillTime"], TZ)
            ax.scatter([time], [e["Price"]], s=85, color=color, marker="^" if o["Side"]>0 else "v", zorder=5, edgecolors="#101722", linewidth=.8)
            ax.annotate(str(number), (time, e["Price"]), xytext=(3,-17 if o["Side"]>0 else 10), textcoords="offset points", color=color, fontsize=10, weight="bold")
            role = "元玉" if o["Kind"] == "initial" else "追加"
            labels.append(f"{number}  {time:%H:%M:%S}  {role}{o['Quantity']}micro  {e['Price']:,.0f}")
        for (at, price), info in closed.items():
            time = datetime.fromtimestamp(at,TZ)
            ax.scatter([time], [price], color="#ff7f9e", marker="s", s=65, zorder=6)
            text = f"返済 {time:%H:%M:%S}\n{info['qty']}micro @ {price:,.0f}\n{info['gross']:+,}円"
            ax.annotate(text, (time,price), xytext=(-150,20 if session.startswith('2026-10-06') else -65), textcoords="offset points", color="#ffb0c4", fontsize=9,
                        bbox={"facecolor":"#182230","edgecolor":"#744554","alpha":.9}, arrowprops={"arrowstyle":"-","color":"#ff7f9e"})
        ax.text(.015,.97,"\n".join(labels),transform=ax.transAxes,va="top",color="#e9eff8",fontsize=9.5,
                bbox={"facecolor":"#101722","edgecolor":"#3d4c61","alpha":.9})
        ax.set_title(date+"　"+title,color="#e9eff8",fontsize=13,pad=12)
        ax.set_xlim(datetime.fromtimestamp(start,TZ),datetime.fromtimestamp(end,TZ))
        ax.margins(y=.22)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=TZ))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0,30],tz=TZ))
        ax.tick_params(colors="#cbd5e2")
        ax.grid(color="#3a485b",alpha=.4)
        ax.set_ylabel("ラージ価格 / pt",color="#cbd5e2")
        for spine in ax.spines.values():
            spine.set_color("#435268")
        evidence.append({"session":session,"normal_raw_rows_in_plot":len(raw),"raw_path":scene["books"]["NK225"],"policy":"O01","parent":"addon/0","display_from":start,"display_to":end,"event_count":len(events)})
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc="lower center",ncol=2,facecolor="#151e2c",edgecolor="#435268",labelcolor="#cbd5e2",bbox_to_anchor=(.5,.032))
    fig.suptitle("同じ順行40pt追加：続く波は伸ばすが、反転後の旧Source退出は追加玉にも遠い",color="#f1f4f8",fontsize=16)
    fig.text(.04,.012,"価格は保存原板（CurrentPriceTime代理）。▲/▼は実約定の方向、青=元玉・橙=追加、桃色□=返済。次正常BBO約定、費用0。",color="#b6c3d4",fontsize=10)
    fig.tight_layout(rect=(0,.07,1,.95))
    fig.savefig(HERE/"第三巡の順行追加_勝ちと負けの原板図.png",dpi=150,facecolor=fig.get_facecolor())
    (HERE/"原板図の抽出根拠1573.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    plt.close(fig)


if __name__ == "__main__":
    draw()
