"""改修前後の保存注文を同じ価格経路へ重ね、変わった損失を読む。"""

import argparse
from datetime import datetime, timedelta, timezone
import pickle
import sys
import numpy as np
from common129 import HERE, PREV, ROOT, PUBLIC, read

sys.path.insert(0, str(HERE/"night"))
from render_night129 import plt, ohlc, candle
from matplotlib.ticker import FuncFormatter

JST = timezone(timedelta(hours=9))


def main():
    """
    機能: 指定場の保存金融結果だけを比較画像へ描く。
    引数: --session/--symbol(str)、--methods(str複数)は対象場・商品・比較。
    返り値: None。注文生成や損益の再シミュレーションはしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--symbol", default="NK225")
    parser.add_argument("--methods", nargs="+", required=True)
    args = parser.parse_args()
    ref = next(r for r in read(PREV/"入力準備.json")["packets"] if r["session"] == args.session)
    packet = pickle.loads((ROOT/ref["path"]).read_bytes())
    key = args.session, args.symbol
    ready, q = packet["inputs"][key], packet["quotes"][key]
    other = args.session, "TOPIX" if args.symbol == "NK225" else "NK225"
    peer = packet["inputs"][other]
    start, end = ready["us_open"]-1800., ready["limit"]
    bars, peerbars = ohlc(ready), ohlc(peer)
    fig, axes = plt.subplots(len(args.methods)+1, 1, figsize=(17, 4*(len(args.methods)+1)),
                             sharex=True, constrained_layout=True)
    colors = ("#55c8ef", "#f3b64e", "#d398ee", "#5ed3a4")
    for ax, method, color in zip(axes, args.methods, colors):
        folder = HERE/("round1" if method in ("NV01", "NV02", "NV03") else "round2")
        with np.load(folder/"measurement"/f"{args.symbol}_{args.session}.npz", allow_pickle=False) as data:
            trades = data[method+"__trades"]
        candle(ax, bars, start, start, end)
        normal = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
        normal &= (ready["time_s"] >= start) & (ready["time_s"] <= end)
        ix = np.flatnonzero(normal)[::max(1, int(normal.sum()/6000))]
        ax.plot((ready["time_s"][ix]-start)/60., (q["bid"][ix]+q["ask"][ix])/2.,
                color="#c9d1df", alpha=.4, linewidth=.6, label="正常気配中値")
        for n, tr in enumerate(trades, 1):
            er, xr, side = int(tr[0]), int(tr[1]), int(tr[2])
            x1, x2 = (ready["time_s"][er]-start)/60., (ready["time_s"][xr]-start)/60.
            ax.plot([x1, x2], tr[4:6], color=color, linewidth=1.2)
            ax.scatter([x1], [tr[4]], color=color, marker="^" if side > 0 else "v", s=50, zorder=6)
            ax.scatter([x2], [tr[5]], color=color, marker="x", s=50, zorder=6)
            ax.annotate(f"{n} {int(tr[8]):+,}円", (x2, tr[5]), xytext=(3, 7 if n%2 else -18),
                        textcoords="offset points", color=color, fontsize=9)
        ax.set_title(f"{method}  手数料後 {int(trades[:,8].sum()):+,}円 / {len(trades)}組", loc="left", color=color)
        ax.set_ylabel(args.symbol)
        ax.grid(alpha=.3)
    candle(axes[-1], peerbars, start, start, end)
    axes[-1].set_ylabel(other[1])
    axes[-1].set_title("相手市場の同じ価格経路", loc="left")
    axes[-1].grid(alpha=.3)
    axes[-1].xaxis.set_major_formatter(FuncFormatter(
        lambda minute, _: datetime.fromtimestamp(start+minute*60., JST).strftime("%H:%M")))
    axes[-1].set_xlim(0., (end-start)/60.)
    axes[-1].set_xlabel("日本時間（価格時計）／▲買い・▼売り・×返済。金融再生ではなく保存注文の描画。")
    fig.suptitle(args.session+" "+args.symbol+" 改修による売買位置の変化", fontsize=17)
    folder = PUBLIC/"画像/改修比較"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder/(args.session+"_"+args.symbol+"_"+"_".join(args.methods)+".png")
    assert not target.exists()
    fig.savefig(target, dpi=145)
    plt.close(fig)
    print(target)


if __name__ == "__main__":
    main()
