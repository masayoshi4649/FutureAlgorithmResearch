"""保護未起動の負けと、早い保護で伸びを削る勝ち反例を描く。"""

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


def main():
    """
    機能: 既存追加親の原気配と順行Rを二例表示し、新たな注文は生成しない。
    引数: なし。
    返り値: None。PNG二枚と資料一覧を新規保存する。
    """
    data = json.loads((HERE / "第二巡の全追加親と保護未起動損失.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "work/daynight128_20261020/入力準備.json").read_text(encoding="utf-8-sig"))
    refs = {r["session"]: r for r in manifest["packets"]}
    folder = HERE / "画像/第二巡追加"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for scene in ("2026-09-22_Night", "2026-09-25_Night"):
        p = next(r for r in data["parents"] if r["method"] == "S07" and r["symbol"] == "NK225" and r["session"] == scene)
        packet = pickle.loads((ROOT / refs[scene]["path"]).read_bytes())
        ready, q = packet["inputs"][(scene, "NK225")], packet["quotes"][(scene, "NK225")]
        a, b, side, risk = p["entryrow"], p["exitrow"], p["side"], p["width"]
        indices = np.arange(a, b+1)
        dates = [datetime.fromtimestamp(v, JST) for v in ready["time_s"][indices]]
        bid, ask = q["bid"][indices].copy(), q["ask"][indices].copy()
        good = q["quote_valid"][indices] & np.isfinite(bid) & np.isfinite(ask) & (ask > bid) & (bid > 0.)
        bid[~good], ask[~good] = np.nan, np.nan
        gain = side*((bid if side > 0 else ask)-p["entry"])/risk
        peak = np.maximum.accumulate(np.where(np.isfinite(gain), np.maximum(gain, 0.), 0.))
        fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
        axes[0].fill_between(dates, bid, ask, color="#f1c26b", alpha=.35, label="売買気配")
        axes[0].plot(dates, (bid+ask)*.5, color="#f1c26b", lw=1., label="正常気配中値")
        axes[0].axhline(p["entry"], color="#8ad8ff", ls="--", lw=.9, label="実際の新規価格")
        axes[0].axhline(p["entry"]+side*1.5*risk, color="#b8e88a", ls=":", label="元の保護起動位置：1.5R")
        axes[0].scatter([dates[0]], [p["entry"]], color="#8ad8ff", s=45)
        axes[0].scatter([dates[-1]], [p["exit"]], color="#eeaaff", marker="x", s=60)
        axes[0].set_title(scene+" S07 日経追加｜"+("買い" if side > 0 else "売り")+" "
                          +str(p["entry"])+" → "+str(p["exit"])+"｜元収支 "+format(p["net"], "+,.0f")+"円")
        axes[0].set_ylabel("日経価格")
        axes[0].legend(loc="best", fontsize=8)
        axes[1].plot(dates, gain, color="#93c9ff", lw=1.1, label="当時の清算気配からの順行R")
        axes[1].plot(dates, peak, color="#ffe087", lw=1., label="そこまでの最高順行R")
        for value, color in ((.75, "#8d8d8d"), (1., "#bdbdbd"), (1.25, "#c8d8b0"), (1.5, "#b8e88a")):
            axes[1].axhline(value, color=color, lw=.6, ls="--")
        axes[1].axhline(0., color="#aaaaaa", lw=.6)
        axes[1].set_ylabel("初期尺度Rに対する順行")
        axes[1].set_xlabel("日本時刻／原板価格時計。新しい退出ルールの約定・損益は未再生")
        axes[1].legend(loc="best", fontsize=8)
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
        for ax in axes:
            ax.grid(alpha=.15)
            ax.margins(y=.12)
        fig.tight_layout()
        path = folder / (scene+"_S07_NK225_利益保護と反例.png")
        assert not path.exists()
        fig.savefig(path, dpi=130)
        plt.close(fig)
        records.append(dict(session=scene, parent=p, path=path.relative_to(ROOT).as_posix()))
    target = HERE / "第二巡追加の保護待ちと勝ち反例画像.json"
    assert not target.exists()
    target.write_text(json.dumps(dict(financial_replays=0, images=records), ensure_ascii=False, indent=2)+"\n",
                      encoding="utf-8")
    print(target.as_posix(), flush=True)


if __name__ == "__main__":
    main()
