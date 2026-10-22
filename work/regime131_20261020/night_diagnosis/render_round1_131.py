"""夜間失敗三例を、原板気配と現在値の違いが見える画像へ保存する。"""

from datetime import datetime
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = ZoneInfo("Asia/Tokyo")
plt.rcParams["font.family"] = "Yu Gothic"
plt.rcParams["axes.unicode_minus"] = False
plt.style.use("dark_background")
CASES = (
    ("R05", "TOPIX", "2026-09-25_Night", "2026-09-25T17:10:00+09:00", "2026-09-25T20:00:00+09:00", 0),
    ("R09", "NK225", "2026-10-02_Night", "2026-10-02T17:10:00+09:00", "2026-10-02T18:10:00+09:00", 0),
    ("R09", "NK225", "2026-10-02_Night", "2026-10-02T22:40:00+09:00", "2026-10-02T23:55:00+09:00", 6),
)


def timestamp(text):
    """
    機能: 日本時刻付き文字列をＵＮＩＸ秒へ変換する。
    引数: text(str)は時刻。
    返り値: floatはＵＮＩＸ秒。
    """
    return datetime.fromisoformat(text).timestamp()


def minute_lines(packet, key, start, end):
    """
    機能: 各分端の厳密前にある正常原板から中値と現在値を表示する。
    引数: packet(dict)、key(tuple)、start/end(float)は表示する入力と時刻範囲。
    返り値: tuple[ndarray,...]は分端、買気配、売気配、現在値。
    """
    source, q = packet["inputs"][key], packet["quotes"][key]
    times = source["time_s"]
    grid = np.arange(np.ceil(start/60)*60, end+.001, 60)
    ix = np.searchsorted(times, grid, side="left")-1
    safe = np.maximum(ix, 0)
    good = (ix >= 0) & (grid-times[safe] <= 60) & q["quote_valid"][safe]
    good &= np.isfinite(q["bid"][safe]) & np.isfinite(q["ask"][safe]) & (q["ask"][safe] > q["bid"][safe])
    bid, ask, last = [np.full(len(grid), np.nan) for _ in range(3)]
    bid[good], ask[good], last[good] = q["bid"][safe[good]], q["ask"][safe[good]], source["last"][safe[good]]
    return grid, bid, ask, last


def main():
    """
    機能: 具体例の全経路と発注判断までで切った二種類の画像を描く。
    引数: なし。
    返り値: None。金融再生・既存結果の編集は行わない。
    """
    data = json.loads((HERE / "第一巡の夜間入口と順行反復の全親診断.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "work/daynight128_20261020/入力準備.json").read_text(encoding="utf-8-sig"))
    refs = {r["session"]: r for r in manifest["packets"]}
    out = HERE / "画像/第一巡"
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for method, symbol, scene, begin, finish, parent in CASES:
        packet = pickle.loads((ROOT / refs[scene]["path"]).read_bytes())
        own = [r for r in data["parents"] if (r["method"], r["symbol"], r["session"]) == (method, symbol, scene)]
        focus = next(r for r in own if r["parent"] == parent)
        peer = "NK225" if symbol == "TOPIX" else "TOPIX"
        start = timestamp(begin)
        for cut in (False, True):
            end = timestamp(focus["decisiontime"]) if cut else timestamp(finish)
            fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
            for ax, market in zip(axes, (symbol, peer)):
                grid, bid, ask, last = minute_lines(packet, (scene, market), start, end)
                dates = [datetime.fromtimestamp(v, JST) for v in grid]
                ax.fill_between(dates, bid, ask, color="#e6b450", alpha=.3, label="売買気配の幅")
                ax.plot(dates, (bid+ask)*.5, color="#ffcf70", lw=1.7, label="正常気配中値（分端の直前値）")
                ax.plot(dates, last, color="#a5afbd", lw=.9, alpha=.9, label="公表現在値（更新が古い場合あり）")
                ax.set_ylabel(market)
                ax.grid(alpha=.16)
                ax.legend(loc="upper left", fontsize=8)
            for r in own:
                a, b = timestamp(r["entrytime"]), timestamp(r["exittime"])
                if not cut and start <= a <= end:
                    dt = datetime.fromtimestamp(a, JST)
                    axes[0].scatter([dt], [r["entry"]], color="#6ee7ac" if r["side"] > 0 else "#ff8888",
                                    marker="^" if r["side"] > 0 else "v", s=60)
                    axes[0].annotate(("買" if r["side"] > 0 else "売")+str(r["parent"])+"\n"+str(r["entry"]),
                                     (dt, r["entry"]), xytext=(3, 18 if r["side"] > 0 else -30),
                                     textcoords="offset points", fontsize=8)
                if not cut and start <= b <= end:
                    dt = datetime.fromtimestamp(b, JST)
                    axes[0].scatter([dt], [r["exit"]], color="#c4b5fd", marker="x", s=55)
                    axes[0].annotate("返済 "+format(r["net"], "+,.0f")+"円", (dt, r["exit"]),
                                     xytext=(3, 12), textcoords="offset points", fontsize=8)
            if cut:
                decision = timestamp(focus["decisiontime"])
                i = focus["decisionrow"]
                q = packet["quotes"][(scene, symbol)]
                price = (q["bid"][i]+q["ask"][i])*.5
                axes[0].scatter([datetime.fromtimestamp(decision, JST)], [price], color="#80d7ff", s=55)
                subtitle = "発注判断まで：右側の将来を表示しない"
            else:
                subtitle = "保存注文の全経路：初期停止幅 "+format(focus["width"], ".2f")
            axes[0].set_title(f"{scene} {method} {symbol} 親{parent}｜{subtitle}", fontsize=13)
            axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
            axes[-1].set_xlabel("日本時刻／CurrentPriceTime原時計。受信時計・実ミニ約定ではない")
            fig.tight_layout()
            path = out / (scene+"_"+method+"_"+symbol+"_親"+str(parent)+("_判断まで" if cut else "_全経路")+".png")
            fig.savefig(path, dpi=125)
            plt.close(fig)
            records.append(dict(method=method, symbol=symbol, session=scene, parent=parent,
                                decision_only=cut, path=path.relative_to(ROOT).as_posix()))
    target = HERE / "第一巡の具体失敗画像.json"
    assert not target.exists()
    target.write_text(json.dumps(dict(financial_replays=0, images=records), ensure_ascii=False, indent=2)+"\n",
                      encoding="utf-8")
    print(target.as_posix(), flush=True)


if __name__ == "__main__":
    main()
