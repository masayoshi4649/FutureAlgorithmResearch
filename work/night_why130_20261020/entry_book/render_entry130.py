"""固定価格の原板・公表活動と、損失及び反例を図解する。"""

import json
import pickle
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from diagnose_entry130 import HERE, ROOT, OLD, read, save

PUBLIC = ROOT / "アルゴリズム調査/00130_夜間損失のなぜ三段階と再改善"
IMAGES = PUBLIC / "画像/入口原板"
JST = timezone(timedelta(hours=9))
plt.rcParams.update({"font.family": "Meiryo", "font.size": 10, "axes.unicode_minus": False,
    "figure.facecolor": "#101720", "axes.facecolor": "#101720", "text.color": "#e9eef5",
    "axes.labelcolor": "#e9eef5", "xtick.color": "#b9c5d7", "ytick.color": "#b9c5d7",
    "axes.edgecolor": "#62728c", "grid.color": "#344256", "legend.facecolor": "#182433",
    "legend.edgecolor": "#62728c", "savefig.facecolor": "#101720"})


def identity(row: dict) -> str:
    """
    機能: 保存親を一意に指す短い識別子を作る。
    引数: row(dict)は保存親。
    返り値: strは方式・場・商品・親番号。
    """
    return f'{row["method"]}_{row["session"]}_{row["symbol"]}_{row["number"]:02d}'


def plot(row: dict, packet: dict, cut: bool) -> str:
    """
    機能: 同一絶対価格の表示数量と公表量を入口前後で描く。
    引数: row(dict)、packet(dict)、cut(bool)は保存親・原入力・入口切断指定。
    返り値: strは公開域内の画像相対位置。金融核は呼ばない。
    """
    scene, symbol = row["session"], row["symbol"]
    rd = packet["inputs"][(scene, symbol)]
    at = float(rd["time_s"][row["decision_row"]])
    maximum = at if cut else at + 180.
    data = dict(np.load(HERE / "cache" / f"{symbol}_{scene}.npz"))
    selected = (data["time"] >= at - 120.) & (data["time"] <= maximum)
    if cut:
        selected &= data["row"] <= row["decision_row"]
    ids = np.flatnonzero(selected)
    ts = data["time"][ids]
    x = ts - at
    p = data["prices"][ids]
    q = data["qty"][ids]
    good = (p[:, 0] > 0.) & (p[:, 10] > p[:, 0])
    mid = np.where(good, (p[:, 0] + p[:, 10]) / 2., np.nan)
    fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True,
        gridspec_kw={"height_ratios": [3, 2, 2, 2]}, layout="constrained")
    axes[0].plot(x, data["last"][ids], color="#a0a7b5", lw=1., label="公表された最終約定値")
    axes[0].plot(x, mid, color="#57c8ff", lw=1.3, label="正常気配中値")
    axes[0].fill_between(x, p[:, 0], p[:, 10], where=good, color="#57c8ff", alpha=.13, label="買い・売り気配")
    axes[0].axhline(row["boundary"], color="#d9ba60", ls="--", label="準備時に固定した突破線")
    markprice = (row["book30"]["final_bid"] + row["book30"]["final_ask"]) / 2. if cut else row["entry"]
    axes[0].scatter([0.], [markprice], color="#ff916f", marker="v" if row["side"] < 0 else "^", s=85, zorder=5)
    axes[0].set_ylabel(symbol)
    peer = "TOPIX" if symbol == "NK225" else "NK225"
    pr, pq = packet["inputs"][(scene, peer)], packet["quotes"][(scene, peer)]
    pi = np.where((pr["time_s"] >= at - 120.) & (pr["time_s"] <= maximum))[0]
    if cut:
        pi = pi[pr["time_s"][pi] < at]
    pg = pq["quote_valid"][pi] & (pq["ask"][pi] > pq["bid"][pi])
    pm = np.where(pg, (pq["ask"][pi] + pq["bid"][pi]) / 2., np.nan)
    axes[1].plot(pr["time_s"][pi] - at, pm, color="#ffa85b", label=peer + " 正常気配中値")
    axes[1].set_ylabel("相手市場")
    # ----------------------------------------
    # 判断前30秒の始端で見えた二つの絶対価格を固定し、その後も同じ価格だけを追う。
    for name, board, color in (("fixed_initial_bid", 0, "#71dcab"), ("fixed_initial_ask", 1, "#ff8a9c")):
        price = row["book30"][name]["price"]
        values = np.full(len(ids), np.nan)
        for n in range(len(ids)):
            loc = np.where(p[n, board * 10:board * 10 + 10] == price)[0]
            if len(loc):
                values[n] = q[n, board * 10 + loc[0]]
        axes[2].plot(x, values, color=color, lw=.9,
            label=f'固定価格 {price:g} の{"買い" if board == 0 else "売り"}表示枚数')
    axes[2].set_ylabel("十段内の表示数量\n圏外は欠測")
    volume = data["volume"][ids]
    inc = np.maximum(0., np.diff(volume, prepend=volume[0]))
    axes[3].step(x, np.cumsum(inc), where="post", color="#d9ba60", label="図示開始後の公表出来高増分")
    axes[3].set_ylabel("公表出来高の増分")
    axes[3].set_xlabel("新規判断からの価格時計秒（受信時計ではない）")
    for ax in axes:
        ax.axvline(0., color="#ff916f", lw=1., ls="--")
        if not cut:
            ax.axvspan(0., 180., color="#526077", alpha=.13)
        ax.grid(alpha=.3)
        ax.legend(loc="best", fontsize=8)
    suffix = "入口まで" if cut else "入口前後"
    detail = (f'{row["decision_time"][11:19]} {row["direction"]}判断 / 判断時中値 {markprice:g}、以降の原行を非表示'
        if cut else f'{row["entry_time"][11:19]} {row["direction"]} {row["entry"]:g} → '
        f'{row["exit_time"][11:19]} 返済 {row["exit"]:g} / {row["net"]:+,.0f}円')
    axes[0].set_title(f'{scene} {symbol} {row["method"]} 親{row["number"]} / {suffix}\n' + detail)
    fig.suptitle("数量増減は表示更新。補充・取消・真の約定方向の識別はできない。", fontsize=11)
    IMAGES.mkdir(parents=True, exist_ok=True)
    target = IMAGES / (identity(row) + "_" + suffix + ".png")
    fig.savefig(target, dpi=120)
    plt.close(fig)
    return target.relative_to(PUBLIC).as_posix()


def main() -> None:
    """
    機能: 指定された失敗例と同じ入口に近い勝ち反例を描画する。
    引数: なし。
    返り値: None。選択基準・時刻・画像一覧をJSONへ保存する。
    """
    data = read(HERE / "全入口の原板活動と固定価格表示数量.json")
    records = data["records"]
    keys = [
        ("NV25", "2026-09-23_Night", "NK225", 1),
        ("NV25", "2026-10-01_Night", "TOPIX", 1),
        ("NV25", "2026-09-30_Night", "TOPIX", 1),
        ("NV25", "2026-09-30_Night", "NK225", 1),
        ("N36", "2026-09-30_Night", "TOPIX", 1),
        ("N36", "2026-09-30_Night", "NK225", 2),
    ]
    selected = [next(r for r in records if (r["method"], r["session"], r["symbol"], r["number"]) == key) for key in keys]
    matches = []
    for loss in selected[:3]:
        candidates = [r for r in records if r["method"] == loss["method"] and r["symbol"] == loss["symbol"]
                      and r["side"] == loss["side"] and r["net"] > 0.]
        features = ("own120", "peer120", "er20")
        distances = [(sum((r["observable"][k] - loss["observable"][k]) ** 2 for k in features), r)
                     for r in candidates if all(r["observable"].get(k) is not None for k in features)]
        distance, matched = min(distances, key=lambda v: v[0])
        matches.append(dict(loss=identity(loss), winning=identity(matched), squared_distance=distance,
            features=features, note="結果を見て勝ち群から当時特徴の最近傍を選ぶ反証用対照。未使用標本による検証ではない。"))
        if not any(identity(matched) == identity(r) for r in selected):
            selected.append(matched)
    refs = {r["session"]: r for r in read(OLD / "入力準備.json")["packets"]}
    images = []
    for scene in sorted({r["session"] for r in selected}):
        packet = pickle.loads((ROOT / refs[scene]["path"]).read_bytes())
        for row in [r for r in selected if r["session"] == scene]:
            paths = [plot(row, packet, cut) for cut in (False, True)]
            images.append(dict(id=identity(row), row=row, images=paths))
            print(identity(row), flush=True)
    save(HERE / "入口の原板画像と勝ち反例.json", dict(financial_replays=0, matches=matches, cases=images))


if __name__ == "__main__":
    main()
