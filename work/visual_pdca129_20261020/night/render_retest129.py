"""保存した再試験の入口・失敗・勝ち対照を一分足と正常気配へ描く。"""

from datetime import datetime
from pathlib import Path
import json
import pickle
import sys
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
OLD = ROOT/"work/daynight128_20261020"
PUBLIC = ROOT/"アルゴリズム調査/00129_チャートと板からの失敗機構再検証"
IMAGES = PUBLIC/"画像/夜間再試験"
sys.path.insert(0, str(TASK))
from features129 import build
from render_night129 import read, stamp, ohlc, candle, JST, COLORS


def draw(packet: dict, prepared: tuple, focus: dict, path: Path, cut: bool = False) -> None:
    """
    機能: 保存入口と当時の固定線を、二市場の足・気配・支持と共に描く。
    引数: packet(dict)、prepared(tuple)、focus(dict)、path(Path)、cut(bool)は素材・対象・保存先。
    返り値: None。cut=Trueでは判断行以後を足と他市場から除く。
    """
    scene, sy = focus["session"], focus["symbol"]
    peer = "TOPIX" if sy == "NK225" else "NK225"
    inputs, markets, histories, _ = prepared
    ready = inputs[scene, sy]
    ts, start = ready["time_s"], ready["start"]
    d, e, x = (focus[k] for k in ("decision_row", "entry_row", "exit_row"))
    left = max(start, ts[d]-2700.)
    right = ts[d] if cut else min(ready["limit"], max(ts[x]+600., ts[d]+1800.))
    fig, axes = plt.subplots(4, 1, figsize=(17, 12), sharex=True,
                            gridspec_kw={"height_ratios": [3, 2.5, 1.3, 1.3]})
    for ax, symbol in zip(axes[:2], (sy, peer)):
        raw = packet["inputs"][scene, symbol]
        time = raw["time_s"]
        maximum = (d if symbol == sy else np.searchsorted(time, right, side="left")-1) if cut else None
        candle(ax, ohlc(raw, maximum), start, left, right)
        q = packet["quotes"][scene, symbol]
        ids = np.flatnonzero((time >= left) & (time <= right))
        if maximum is not None:
            ids = ids[ids <= maximum]
        good = q["quote_valid"][ids] & (q["bid"][ids] > 0.) & (q["ask"][ids] > q["bid"][ids])
        b = np.where(good, q["bid"][ids], np.nan)
        a = np.where(good, q["ask"][ids], np.nan)
        xx = (time[ids]-start)/60.
        ax.fill_between(xx, b, a, step="post", color="#c3c9d4", alpha=.2, label="正常Bid〜Ask")
        ax.plot(xx, (a+b)/2., color="#f2f2f2", linewidth=.7, label="正常気配中値")
        ax.set_ylabel(symbol+" ラージ価格")
        if symbol == sy:
            side, width = focus["side"], focus["width"]
            points = (("arm_row", "準備", "#ffcb63"), ("progress_row", "0.75R進行", "#c59bff"),
                      ("return_row", "境界への戻り", "#88b6ff"), ("decision_row", "再反発判断", "#55e3ca"))
            for key, label, color in points:
                i = focus[key]
                if ts[i] >= left:
                    ax.scatter((ts[i]-start)/60., ready["last"][i], s=30, color=color, zorder=5)
                    ax.annotate(label, ((ts[i]-start)/60., ready["last"][i]), xytext=(2, 12),
                                textcoords="offset points", fontsize=8, color=color, clip_on=True)
            ll = (max(left, ts[focus["arm_row"]])-start)/60.
            rr = (right-start)/60.
            ax.hlines(focus["boundary"], ll, rr, color="#ffcb63", label="固定突破線")
            ax.hlines(focus["return_extreme"], ll, rr, color="#88b6ff", linestyle=":", label="戻り極値")
            anchor = (q["ask"][d] if side > 0 else q["bid"][d]) if cut else focus["entry"]
            px = (ts[d]-start)/60. if cut else (ts[e]-start)/60.
            ax.hlines(anchor-side*width, px, rr, color="#ff687b", linestyle="--", label="初期停止1R")
            ax.hlines(anchor+side*width, px, rr, color="#74dea6", linestyle="--", label="保護開始1R")
            if not cut:
                ax.plot([(ts[e]-start)/60., (ts[x]-start)/60.], [focus["entry"], focus["exit"]],
                        color="#55e3ca", linewidth=1.3)
                ax.scatter((ts[e]-start)/60., focus["entry"], marker="^" if side > 0 else "v",
                           s=65, color="#55e3ca", zorder=8)
                ax.scatter((ts[x]-start)/60., focus["exit"], marker="x", s=55, color="#ff6d85", zorder=8)
                mark = q["bid"][e:x+1] if side > 0 else q["ask"][e:x+1]
                goodx = q["quote_valid"][e:x+1]
                peak = np.maximum.accumulate(np.maximum(np.where(goodx, side*(mark-anchor), -np.inf), 0.))
                floor = np.where(peak >= width, np.maximum(-width, peak-.75*width), -width)
                ax.plot((ts[e:x+1]-start)/60., anchor+side*floor, color="#e6a3e1", label="当時の停止線", linewidth=1.)
            ylo, yhi = ax.get_ylim()
            levels = [focus["boundary"], anchor-width, anchor+width, float(np.nanmin(b)), float(np.nanmax(a))]
            ax.set_ylim(min(ylo, min(levels)), max(yhi, max(levels)))
        ax.legend(loc="upper left", fontsize=8, ncol=3)
    # ----------------------------------------
    # 二市場の支持は保存と同じ、当時公開済み列だけを描く。
    h, m = histories[scene, sy], markets[scene, sy]
    ids = np.flatnonzero((ts >= left) & (ts <= right))
    if cut:
        ids = ids[ids <= d]
    ids = ids[np.r_[True, np.diff(np.floor(ts[ids]/5.)) > 0]]
    for col, label, symbol, style in ((4,"自己30秒",sy,":"),(5,"自己120秒",sy,"-"),
                                     (6,"相手30秒",peer,":"),(7,"相手120秒",peer,"-")):
        axes[2].plot((ts[ids]-start)/60., m[ids, col], label=label, color=COLORS[symbol], linestyle=style)
    for col, den, label, symbol, style in ((6,2,"自己5分",sy,":"),(7,2,"自己20分",sy,"-"),
                                          (10,3,"相手5分",peer,":"),(11,3,"相手20分",peer,"-")):
        axes[3].plot((ts[ids]-start)/60., h[ids,col]/m[ids,den], label=label, color=COLORS[symbol], linestyle=style)
    for ax in axes[2:]:
        ax.axhline(0., color="#aaaaaa", linewidth=.6)
        ax.set_ylabel("変化/ATR")
        ax.legend(loc="upper left", ncol=4, fontsize=8)
    for ax in axes:
        ax.grid(alpha=.3)
        ax.set_xlim((left-start)/60., (right-start)/60.+.3)
        ax.axvline((ts[d]-start)/60., color="#ffffff", linestyle=":", linewidth=.8)
        if not cut:
            ax.axvline((ts[x]-start)/60., color="#ed7387", linestyle=":", linewidth=.8)
    axes[-1].xaxis.set_major_locator(MultipleLocator(10 if right-left < 6000 else 20))
    axes[-1].xaxis.set_major_formatter(FuncFormatter(lambda v, _: datetime.fromtimestamp(start+v*60., JST).strftime("%H:%M")))
    desc = "入口判断まで（右側と当分足を切断）" if cut else f"{focus['entry_time'][11:19]} → {focus['exit_time'][11:19]} {focus['net']:+,.0f}円"
    fig.suptitle(f"{scene} {sy} {focus['method']} #{focus['number']} {focus['direction']}　{desc}", fontsize=14)
    source_name = "Last" if focus["method"] in ("NV15","NV22","NV24") else "正常気配中値"
    fig.text(.01, .01, f"足=原Last、白線=正常気配中値。入口指標の観測価格={source_name}。原時計≠実受信時計。ラージ気配代理・手数料後。", fontsize=9)
    fig.tight_layout(rect=(0,.03,1,.96))
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> None:
    """
    機能: 最大損失の各局所・右側切断図と勝ち対照を保存する。
    引数: なし。
    返り値: None。保存図一覧をJSONへ残す。
    """
    IMAGES.mkdir(parents=True, exist_ok=True)
    data = read(HERE/"再試験入口の全親と固定線診断.json")
    refs = {r["session"]: r for r in read(OLD/"入力準備.json")["packets"]}
    result = []
    for selection in data["selections"]:
        focus = selection["trade"]
        scene, symbol, method = focus["session"], focus["symbol"], focus["method"]
        packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        prepared = build(packet, "last" if method == "NV15" else "mid")
        for cut in (False, True):
            suffix = "入口まで" if cut else "局所"
            path = IMAGES/f"{scene}_{symbol}_{method}_{focus['number']:02d}_{suffix}.png"
            draw(packet, prepared, focus, path, cut)
            result.append(dict(kind=selection["kind"], method=method, symbol=symbol, session=scene,
                               number=focus["number"], cut=cut, path=path.relative_to(ROOT).as_posix()))
        print(scene, symbol, method, focus["number"], "描画", flush=True)
    (HERE/"再試験入口の画像一覧.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf8")


if __name__ == "__main__":
    main()
