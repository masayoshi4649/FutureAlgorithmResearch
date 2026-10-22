"""保存した持続確認の注文を、失敗条件と二市場チャートで比較する。"""

import pickle
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
from common129 import HERE, PREV, ROOT, PUBLIC, read, save, sha, reference

sys.path.insert(0, str(HERE / "day_diagnosis"))
import render_day129 as plot
from render_retry129 import marked_equity
plt.rcParams["font.family"] = "Meiryo"
plt.rcParams["axes.unicode_minus"] = False


def main():
    """
    機能: 改善した損失・保った勝ち・なお切った勝ちの保存経路を描く。
    引数: なし。3例を固定し、金融判断は再実行しない。
    返り値: None。画像と各図の参照資料を保存する。
    """
    cases = [("2026-10-16_Day", "TOPIX", 0, "DV07"),
             ("2026-09-28_Day", "NK225", 1, "DV05"),
             ("2026-10-08_Day", "NK225", 4, "DV05")]
    refs = {r["session"]: r for r in read(PREV / "入力準備.json")["packets"]}
    records = []
    for scene, symbol, shadow, method in cases:
        ref = refs[scene]
        assert sha(ROOT / ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT / ref["path"]).read_bytes())
        ready, q, market = packet["inputs"][scene, symbol], packet["quotes"][scene, symbol], packet["markets"][scene, symbol]
        other_symbol = "NK225" if symbol == "TOPIX" else "TOPIX"
        other = packet["inputs"][scene, other_symbol]
        paths = [PREV / f"round3/measurement/{symbol}_{scene}.npz",
                 HERE / f"day_round1/measurement/{symbol}_{scene}.npz",
                 HERE / f"day_round2/measurement/{symbol}_{scene}.npz"]
        parents, orders = {}, {}
        for path, name in zip(paths, ("D17", "DV01", method)):
            with np.load(path, allow_pickle=False) as data:
                if name == "D17":
                    real_id = shadow
                else:
                    mapping = data[name + "__parent_mapping"]
                    matched = mapping[(mapping[:, 1] == shadow) & (mapping[:, 2] == 0)]
                    assert len(matched) == 1
                    real_id = matched[0, 0]
                orders[name] = data[name + "__orders"][data[name + "__orders"][:, 2] == real_id]
                parents[name] = data[name + "__cycles"][data[name + "__cycles"][:, 0] == real_id][0]
        entry = int(orders["D17"][0, 0])
        end = int(parents["D17"][2])
        width, side = float(parents["D17"][5]), int(orders["D17"][0, 3])
        end_time = ready["time_s"][end]
        other_end = np.searchsorted(other["time_s"], end_time, side="right")
        bars = plot.candles(ready["time_s"][:end + 1], ready["last"][:end + 1], ready["start"])
        peer_bars = plot.candles(other["time_s"][:other_end], other["last"][:other_end], ready["start"])
        xleft = max(0., (ready["time_s"][entry] - ready["start"]) / 60 - 15)
        fig, axes = plt.subplots(4, 1, figsize=(17, 12), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 2, 1.5, 2]})
        fig.patch.set_facecolor("#0e1520")
        for ax in axes:
            ax.set_facecolor("#142031")
            ax.grid(color="#455267", alpha=.4)
            ax.tick_params(colors="#dce7f6")
            ax.yaxis.label.set_color("#dce7f6")
            for spine in ax.spines.values():
                spine.set_color("#46566e")
        for ax, data, name in ((axes[0], bars, symbol), (axes[1], peer_bars, other_symbol)):
            plot.draw_candles(ax, data, name)
            values = data[data[:, 0] + 1 >= xleft, 2:4]
            low, high = np.min(values), np.max(values)
            margin = max((high - low) * .08, .5)
            ax.set_ylim(low - margin, high + margin)
        colors = {"D17": "#8fc8ff", "DV01": "#eea68f", method: "#76deb8"}
        for name in orders:
            for order in orders[name]:
                if order[7] == 0:
                    x = (ready["time_s"][int(order[0])] - ready["start"]) / 60
                    axes[0].scatter(x, order[5], marker="x", s=65, color=colors[name], zorder=5)
                    axes[0].annotate(name, (x, order[5]), xytext=(3, 8), textcoords="offset points",
                                     color=colors[name], fontsize=9)
        xentry = (ready["time_s"][entry] - ready["start"]) / 60
        axes[0].scatter(xentry, orders["D17"][0, 5], marker="^" if side > 0 else "v", s=90, color="#ffe287")
        idx = bars[:, 5].astype(int)
        x = (ready["time_s"][idx] - ready["start"]) / 60
        own = side * (market[idx, 0] - market[entry, 0]) / width
        peer = side * (market[idx, 1] - market[entry, 1]) / market[entry, 3]
        axes[2].plot(x, own, color="#efbb78", label="自己：新規時からの方向調整差")
        axes[2].plot(x, peer, color="#b3a4ef", label="相手：新規時からの方向調整差")
        axes[2].axhline(-.25, color="#f49aaa", linestyle="--")
        axes[2].set_ylabel("初期ATR倍")
        axes[2].legend(facecolor="#142031", labelcolor="#dce7f6", fontsize=9)
        final = {}
        for name, data in orders.items():
            equity = marked_equity(data, q, len(ready["time_s"]), symbol)
            final[name] = float(equity[-1])
            axes[3].plot(x, equity[idx] / 1000, color=colors[name],
                         label=f"{name}：{equity[-1]:+,.0f}円")
        axes[3].set_ylabel("費用後清算価値・千円")
        axes[3].legend(facecolor="#142031", labelcolor="#dce7f6", fontsize=9)
        axes[3].xaxis.set_major_locator(MultipleLocator(30 if end_time - ready["time_s"][entry] > 7200 else 10))
        axes[3].xaxis.set_major_formatter(FuncFormatter(lambda x, _: plot.clock(ready["start"] + x * 60)[:5]))
        axes[3].set_xlim(xleft, (end_time - ready["start"]) / 60 + 1)
        axes[3].set_xlabel("日本時間", color="#dce7f6")
        fig.suptitle(f"{scene} {symbol}：D17／瞬間撤退DV01／持続確認{method}（元建玉{shadow}）",
                     color="#e8effa", fontsize=15)
        fig.text(.02, .01, "保存注文の事後比較。下段の価格差は1分の抜粋表示で、実際の継続判定は全原行。未来の高安は注文判断に使用しない。",
                 color="#aebbd0", fontsize=9)
        fig.tight_layout(rect=[.01, .035, .99, .97])
        target = PUBLIC / "画像/持続確認" / f"{scene}_{symbol}_{method}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(target, dpi=120, facecolor=fig.get_facecolor())
        plt.close(fig)
        records.append(dict(session=scene, symbol=symbol, shadow=shadow, method=method,
                            parent_net=final, image=reference(target), inputs=[reference(p) for p in paths]))
    save(HERE / "day_round2/持続確認の比較画像_字体修正.json", dict(financial_replays=0, records=records))


if __name__ == "__main__":
    main()
