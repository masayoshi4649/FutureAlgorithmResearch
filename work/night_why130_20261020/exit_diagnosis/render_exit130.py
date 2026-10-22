"""保存親の反転・停止後経路と勝ちの反例を、原行から暗色画像へ描く。"""

import hashlib
import json
from pathlib import Path
import pickle
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np

from classify_exit130 import ROOT, TASK, HERE, read, verified


JST = timezone(timedelta(hours=9))
plt.rcParams.update({"font.family": "Yu Gothic", "font.size": 10, "axes.unicode_minus": False,
    "figure.facecolor": "#0d1117", "axes.facecolor": "#131c27", "axes.edgecolor": "#8795a7",
    "axes.labelcolor": "#d7e2ef", "text.color": "#e0e8f2", "xtick.color": "#bac7d5",
    "ytick.color": "#bac7d5", "grid.color": "#334256"})


def minute_range(times: np.ndarray, values: np.ndarray) -> tuple:
    """
    機能: 表示範囲の1分内最高最低と最後の値を作る。
    引数: times/values(ndarray)は切断済みの観測。
    返り値: tuple[ndarray,...]は分時計・最低・最高・終値。
    """
    minutes = np.floor(times/60)
    begin = np.r_[0, np.flatnonzero(np.diff(minutes))+1]
    end = np.r_[begin[1:]-1, len(values)-1]
    return minutes[begin]*60, np.minimum.reduceat(values, begin), np.maximum.reduceat(values, begin), values[end]


def draw(record: dict, packet: dict, prefix: bool, destination: Path) -> dict:
    """
    機能: 入口まで又は旧出口後までの既存経路を二市場並列で描く。
    引数: record/packet(dict)、prefix(bool)、destination(Path)は対象親と画像指定。
    返り値: dictは表示範囲と画像指紋。相場の再運転はしない。
    """
    scene, symbol = record["session"], record["symbol"]
    ready, q = packet["inputs"][scene, symbol], packet["quotes"][scene, symbol]
    market = packet["markets"][scene, symbol]
    times = ready["time_s"]
    first, last = record["entry_row"], record["exit_row"]
    direction, width, entry = record["direction"], record["width"], record["entry"]
    start = times[first]-600.
    extra = 1800. if record["net"] < 0 else 300.
    end_row = first if prefix else min(len(times)-1, int(np.searchsorted(times, times[last]+extra, side="right")-1))
    valid = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"]) & (q["bid"] < q["ask"])
    rows = np.flatnonzero(valid & (np.arange(len(times)) <= end_row) & (times >= start))
    mark = q["bid"] if direction > 0 else q["ask"]
    values = direction*(mark[rows]-entry)/width
    minute, low, high, close = minute_range(times[rows], values)
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True, gridspec_kw={"height_ratios": [2.4, 1.]})
    ax = axes[0]
    ax.vlines(minute, low, high, color="#78bfff", linewidth=1.2, alpha=.75, label="1分内の清算可能幅")
    ax.plot(minute, close, color="#b1dbff", linewidth=1., label="1分最後の清算可能幅")
    ax.axhline(0., color="#abb7c7", linewidth=.9, label="初回建値")
    ax.axhline(1., color="#66df9a", linestyle="--", linewidth=1., label="旧保護起動 +1R")
    ax.axhline(-1., color="#ff8086", linestyle="--", linewidth=1., label="初期停止 −1R")
    ax.axhline(-1.5, color="#efab6b", linestyle=":", linewidth=.8, label="参考 −1.5R")
    ax.axhline(-2., color="#d994d6", linestyle=":", linewidth=.8, label="参考 −2R")
    ax.scatter(times[first], 0., marker="^", s=85, color="#ffe08a", zorder=5)
    ax.annotate(f'{record["side"]} {entry:g}\n{record["entry_time"][-8:]}', (times[first], 0.),
                xytext=(-10, 14) if prefix else (8, 14), ha="right" if prefix else "left",
                textcoords="offset points", color="#ffe08a")
    if not prefix:
        exit_r = direction*(record["exit"]-entry)/width
        ax.scatter(times[last], exit_r, marker="X", s=85, color="#ff9299", zorder=5)
        ax.annotate(f'旧返済 {record["exit"]:g}\n{record["exit_time"][-8:]}', (times[last], exit_r),
                    xytext=(9, -32), textcoords="offset points", color="#ff9299")
        ax.axvspan(times[last], times[end_row], color="#ffffff", alpha=.035)
        colors = ["#f4ba61", "#b299ef"]
        for (name, event), color in zip(record["proposed_mechanism_contacts"].items(), colors):
            if event:
                label = "案①の条件接触" if name.startswith("起動前") else "案②の条件接触"
                ax.scatter(times[event["row"]], event["movement_R"], marker="o", s=55, color=color, label=label)
                ax.annotate(event["time"][-8:], (times[event["row"]], event["movement_R"]),
                    xytext=(6, 10 if name.startswith("起動前") else -16), textcoords="offset points", color=color)
    ax.set_ylabel("元方向への清算可能幅 / 初期R")
    ax.set_title(f'{record["method"]} {symbol} {scene}　{record["side"]}・初期R={width:.3f}\n'
                 + ("新規約定までの観測だけ" if prefix else f'旧収支 {record["net"]:+,.0f}円：灰色範囲は旧返済後の観測'))
    ax.legend(loc="lower left", ncol=3, fontsize=8)
    peer_entry, peer_width = market[first, 1], market[first, 3]
    peer = direction*(market[rows, 1]-peer_entry)/peer_width
    usable = np.isfinite(peer)
    if np.any(usable):
        pt, pl, ph, pc = minute_range(times[rows[usable]], peer[usable])
        axes[1].vlines(pt, pl, ph, color="#a3b4c8", alpha=.65, linewidth=1.)
        axes[1].plot(pt, pc, color="#a3b4c8", linewidth=1.)
    axes[1].axhline(0., color="#abb7c7", linewidth=.8)
    axes[1].set_ylabel("相手の同方向幅 / 初期ATR")
    axes[1].set_title("相手の保存現在値：新規時起点の参考線（新改修条件には使わない）", fontsize=9)
    for target in axes:
        target.grid(alpha=.35)
        target.axvline(times[first], color="#ffe08a", alpha=.45, linewidth=.8)
        if not prefix:
            target.axvline(times[last], color="#ff9299", alpha=.45, linewidth=.8)
        target.set_xlim(start, times[end_row]+30)
    axes[1].xaxis.set_major_formatter(FuncFormatter(lambda value, _: datetime.fromtimestamp(value, JST).strftime("%H:%M")))
    fig.text(.01, .015, "価格時計での既存経路。条件接触は参考観測で、変更後の注文・損益ではない。入口まで画像の軸も過去資料だけで決定。", fontsize=9, color="#aab9c9")
    fig.tight_layout(rect=(0, .035, 1, .97))
    fig.savefig(destination, dpi=150)
    plt.close(fig)
    return dict(path=destination.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                method=record["method"], symbol=symbol, session=scene, parent=record["parent"],
                prefix=prefix, cutoff_row=end_row, cutoff_time=float(times[end_row]))


def main() -> None:
    """
    機能: 指定損失2件・停止拡大反例・勝ち反例2件を保存画像へ作成する。
    引数: なし。
    返り値: None。画像と表示範囲のJSONを保存する。
    """
    diagnosis = read(HERE/"夜間全親の保護未達と停止後の先着分類.json")
    manifest = read(ROOT/"work/daynight128_20261020/入力準備.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    selections = [
        ("NV15", "2026-09-30_Night", "NK225", 0),
        ("NV25", "2026-09-23_Night", "NK225", 0),
        ("NV25", "2026-10-13_Night", "NK225", 0),
        ("NV25", "2026-10-16_Night", "TOPIX", 1),
        ("NV25", "2026-10-02_Night", "TOPIX", 0)]
    folder = HERE/"画像"
    folder.mkdir(exist_ok=True)
    images = []
    for method, scene, symbol, parent in selections:
        record = next(r for r in diagnosis["rows"] if (r["method"], r["session"], r["symbol"], r["parent"])
                      == (method, scene, symbol, parent))
        packet = pickle.loads(verified(refs[scene]).read_bytes())
        for prefix in (True, False):
            suffix = "新規まで" if prefix else "旧返済後まで"
            path = folder/f"{method}_{scene}_{symbol}_{parent}_{suffix}.png"
            images.append(draw(record, packet, prefix, path))
    (HERE/"出口診断の画像と表示範囲.json").write_text(json.dumps(dict(images=images,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), financial_replays=0),
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("画像", len(images))


if __name__ == "__main__":
    main()
