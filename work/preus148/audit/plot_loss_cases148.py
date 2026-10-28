"""保存赤字場の価格と注文、および隣接原板の飛びを画像化する。"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pickle
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import engine

JST = timezone(timedelta(hours=9))
plt.rcParams.update({"font.family": "Yu Gothic", "font.size": 10, "axes.facecolor": "#101b2a", "figure.facecolor": "#101b2a", "axes.edgecolor": "#7b8ea4", "text.color": "#e6edf6", "axes.labelcolor": "#e6edf6", "xtick.color": "#c5d3e2", "ytick.color": "#c5d3e2", "grid.color": "#344459"})


def plot_market(ax, data, records, start, end):
    """原気配と保存約定を同一時間軸に描く。

    引数: ax(Axes)、data(dict)、records(list[dict])、start/end(float)。
    返り値: None。既存の注文だけを表示する。
    """
    r, q = data["ready"], data["quotes"]
    t = r["time_s"]
    mask = q["quote_valid"] & (t >= start) & (t <= end)
    x = [datetime.fromtimestamp(value, JST) for value in t[mask]]
    ax.plot(x, (q["bid"][mask] + q["ask"][mask]) / 2, color="#94b7ed", lw=1.0, label="最良気配の中値")
    ax.fill_between(x, q["bid"][mask], q["ask"][mask], color="#7295c7", alpha=.16, label="買気配～売気配")
    shown = set()
    for record in records:
        at = datetime.fromisoformat(record["time"])
        if not start <= at.timestamp() <= end:
            continue
        buying = record["side"] == "買い"
        if record["new"]:
            color, marker = ("#50d5a4", "^") if buying else ("#f6b764", "v")
            label = "買い新規" if buying else "売り新規"
        else:
            color, marker = ("#f8748b", "x") if record["pnl"] < 0 else ("#6bdaae", "x")
            label = "損切り" if record["pnl"] < 0 else "利確"
        ax.scatter([at], [record["price"]], s=65, color=color, marker=marker, zorder=6, label=label if label not in shown else None)
        shown.add(label)
        if not record["new"]:
            ax.annotate(f"{record['pnl'] / 10000:+.1f}万円", (at, record["price"]), xytext=(0, 14 if record["pnl"] >= 0 else -19), textcoords="offset points", ha="center", fontsize=9, color=color)
    ax.set_xlim(datetime.fromtimestamp(start, JST), datetime.fromtimestamp(end, JST))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
    ax.grid(alpha=.5)
    ax.set_ylabel("日経ラージ気配（円）")
    ax.legend(loc="upper right", ncol=3, facecolor="#172638", edgecolor="#526b85", fontsize=9)


def main():
    """二つの最悪例と急変前後の原板証拠を保存する。

    引数: なし。
    返り値: None。画像と原板引用だけを専用監査フォルダへ書く。
    """
    scene = "2026-10-14_Night"
    payload = pickle.loads((WORK / "inputs" / f"{scene}.pkl").read_bytes())
    result = json.loads((WORK / "results" / f"{scene}.json").read_text(encoding="utf-8"))["P01"]["pre"]
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [1.5, 1]}, constrained_layout=True)
    start = datetime.fromisoformat("2026-10-14T21:20:00+09:00").timestamp()
    end = datetime.fromisoformat("2026-10-14T22:10:00+09:00").timestamp()
    plot_market(axes[0], payload["data"], result["records"], start, end)
    axes[0].set_title("P01　10月14日夜：急変直前の買いと、その後の往復売買で前段 −32.5万円", loc="left", fontsize=13, pad=12)
    raw = []
    source = ROOT.parent / "JP_OSE_Data/future/NK225" / scene / "book.jsonl"
    with source.open("rb") as stream:
        for seq, line in enumerate(stream):
            if seq > 45855:
                break
            if 45835 <= seq <= 45855:
                item = json.loads(line)
                raw.append({"seq0": seq, "time": item.get("CurrentPriceTime"), "last": item.get("CurrentPrice"), "buy1": item.get("Buy1"), "sell1": item.get("Sell1"), "volume_time": item.get("TradingVolumeTime")})
    (HERE / "10月14日2130の隣接原板.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    seq = [r["seq0"] for r in raw]
    axes[1].step(seq, [r["buy1"]["Price"] for r in raw], where="post", color="#f8748b", lw=2, label="最良買値（買い玉の返済価格）")
    axes[1].step(seq, [r["sell1"]["Price"] for r in raw], where="post", color="#94b7ed", lw=2, label="最良売値")
    axes[1].axvline(45845, color="#ffe088", ls="--")
    axes[1].text(45845.3, 68350, "隣接原行 45844 → 45845\n両方の価格時計は21:30:01\n買値 68,320 → 68,030（−290）", color="#ffe088", fontsize=10, va="top")
    axes[1].set_ylabel("気配価格（円）")
    axes[1].set_xlabel("保存ファイルの原連番（0始まり）")
    axes[1].set_title("欠測区間を補完した結果ではなく、保存された隣接気配そのものの飛び。受信時計は別途未記録。", loc="left", fontsize=10)
    axes[1].ticklabel_format(useOffset=False, style="plain", axis="x")
    axes[1].grid(alpha=.5)
    axes[1].legend(loc="lower left", facecolor="#172638", edgecolor="#526b85", fontsize=9)
    fig.savefig(HERE / "P01_10月14日急変と往復.png", dpi=130)
    plt.close(fig)
    # ----------------------------------------
    scene = "2026-10-22_Night"
    payload = pickle.loads((WORK / "inputs" / f"{scene}.pkl").read_bytes())
    result = json.loads((WORK / "results" / f"{scene}.json").read_text(encoding="utf-8"))["P01"]["pre"]
    prepared = engine.prepare(payload["data"])
    start = datetime.fromisoformat("2026-10-22T17:00:00+09:00").timestamp()
    end = datetime.fromisoformat("2026-10-22T19:15:00+09:00").timestamp()
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [1.5, 1]}, constrained_layout=True)
    plot_market(axes[0], payload["data"], result["records"], start, end)
    axes[0].set_title("P01　10月22日夜：往復の途中で追撃し、利益保護前に反転。前段 −28.5万円", loc="left", fontsize=13, pad=12)
    mask = (prepared["bar_end"] >= start) & (prepared["bar_end"] <= end)
    x = [datetime.fromtimestamp(value, JST) for value in prepared["bar_end"][mask]]
    axes[1].plot(x, prepared["bars"][mask, 1], color="#8bb9fa", label="5分窓の傾き")
    axes[1].plot(x, prepared["bars"][mask, 2], color="#edb065", label="10分窓の傾き")
    axes[1].axhline(0, color="#c5d3e2", lw=.8)
    axes[1].set_xlim(datetime.fromtimestamp(start, JST), datetime.fromtimestamp(end, JST))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
    axes[1].set_ylabel("確定終値の傾き（pt/分）")
    axes[1].set_title("二つの傾きが同方向でも、その方向への新しい値動きが続くとは限らない。", loc="left", fontsize=10)
    axes[1].grid(alpha=.5)
    axes[1].legend(loc="upper right", facecolor="#172638", edgecolor="#526b85", fontsize=9)
    fig.savefig(HERE / "P01_10月22日往復と追撃.png", dpi=130)
    plt.close(fig)
    print("最悪例の図2枚と隣接原板を保存しました。")


if __name__ == "__main__":
    main()
