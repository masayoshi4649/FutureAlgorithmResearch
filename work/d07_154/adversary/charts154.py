"""保存原板と保存約定を重ねる。売買条件は再生しない。"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
font_manager.fontManager.addfont("C:/Windows/Fonts/meiryo.ttc")
plt.rcParams.update({"font.family": "Meiryo", "font.size": 10, "axes.unicode_minus": False})


@lru_cache(maxsize=4)
def read_quotes(session: str) -> tuple[list, list, list, dict]:
    """保存原板から正常気配を5秒ごとの末尾へ集約して描画する。

    引数: session(str)は保存場ID。返り値: 時刻・買気配・売気配のlistと件数dict。
    """
    path = ROOT.parent / "JP_OSE_Data" / "future/NK225" / session / "book.jsonl"
    sampled = {}
    counts = {"原行": 0, "正常描画行": 0}
    start = datetime.fromisoformat(f"{session[:10]}T08:45:00+09:00").timestamp()
    end = datetime.fromisoformat(f"{session[:10]}T15:45:00+09:00").timestamp()
    previous = start
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            counts["原行"] += 1
            raw = json.loads(line)
            stamp = raw.get("CurrentPriceTime")
            if not stamp:
                continue
            at = datetime.fromisoformat(stamp).timestamp()
            if at < start or at > end or at < previous:
                continue
            previous = at
            bid, ask = raw["Buy1"]["Price"], raw["Sell1"]["Price"]
            if bid <= 0 or ask <= bid or raw["Buy1"]["Qty"] <= 0 or raw["Sell1"]["Qty"] <= 0:
                continue
            counts["正常描画行"] += 1
            sampled[int(at // 5)] = (at, bid, ask)
    values = [sampled[k] for k in sorted(sampled)]
    return [datetime.fromtimestamp(v[0], JST) for v in values], [v[1] for v in values], [v[2] for v in values], counts


def draw(session: str, method: str, zoom: tuple[str, str] | None = None, base_method: str = "D07") -> dict:
    """同一原板へ基準と改修の実約定を重ねて保存する。

    引数: session/method/base_method(str)、zoom(tuple[str,str]|None)。返り値: dictは描画元と出力情報。
    """
    times, bids, asks, counts = read_quotes(session)
    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True)
    fig.patch.set_facecolor("#111827")
    role_names = {"core": "主", "addon": "追", "episode": "別"}
    for ax, ident in zip(axes, [base_method, method]):
        path = BASE / "cases" / f"{session}_{ident}.json"
        if not path.exists():
            path = BASE / "cases_round2" / f"{session}_{ident}.json"
        case = json.loads(path.read_text(encoding="utf-8"))
        ax.set_facecolor("#111827")
        mid = [(b + a) / 2 for b, a in zip(bids, asks)]
        ax.plot(times, mid, color="#94a3b8", linewidth=.9, label="原板の中値（5秒ごとの末尾）")
        ax.fill_between(times, bids, asks, color="#64748b", alpha=.2, label="ラージ売買気配")
        for number, lot in enumerate(case["lots"].values()):
            entry = datetime.fromtimestamp(lot["entry_time"], JST)
            color = "#4ade80" if lot["side"] > 0 else "#fb7185"
            ax.scatter([entry], [lot["price"]], marker="^" if lot["side"] > 0 else "v", s=43 + 6*lot["quantity"], color=color, edgecolors="#111827", zorder=5)
            role = case["parents"][lot["parent"]]["owner"]
            ax.annotate(f"{role_names[role]}{lot['quantity']}", (entry, lot["price"]), xytext=(0, 11 if number % 2 == 0 else -19), textcoords="offset points", color=color, fontsize=8, ha="center")
            for close in lot["closes"]:
                exit_time = datetime.fromtimestamp(close["time"], JST)
                pnl_color = "#4ade80" if close["net"] >= 0 else "#fb7185"
                ax.plot([entry, exit_time], [lot["price"], close["price"]], color=pnl_color, alpha=.38, linewidth=.7)
                ax.scatter([exit_time], [close["price"]], marker="x", s=36, color="#38bdf8" if close["reason"] == 15410 else "#facc15", zorder=6)
        ax.set_title(f"{ident}　確定収支 {case['net']:+,.0f}円", color="#f8fafc", loc="left", fontsize=12)
        ax.set_ylabel("日経先物価格", color="#cbd5e1")
        ax.tick_params(colors="#cbd5e1")
        ax.grid(color="#334155", alpha=.5)
        for spine in ax.spines.values():
            spine.set_color("#475569")
        if zoom:
            day = session[:10]
            left, right = [datetime.fromisoformat(f"{day}T{x}:00+09:00") for x in zoom]
            ax.set_xlim(left, right)
            vals = [v for t, v in zip(times, mid) if left <= t <= right]
            ax.set_ylim(min(vals)-90, max(vals)+90)
        else:
            ax.set_xlim(datetime.fromisoformat(f"{session[:10]}T08:45:00+09:00"),datetime.fromisoformat(f"{session[:10]}T15:45:00+09:00"))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
    axes[-1].xaxis.set_major_locator(mdates.MinuteLocator(byminute=[0,15,30,45] if zoom else [0]))
    fig.suptitle(f"{session}　保存原板上の基準と利益保護の仮想約定比較", color="#f8fafc", fontsize=15)
    fig.text(.065,.016,"▲買い新規／▼売り新規　主＝core・追＝addon・別＝episode、数字＝枚数　×黄＝通常返済、×青＝親利益50%保護返済\n線は玉ごとの返済先を示す。線の傾きは取引中の時価曲線ではない。ラージ気配による仮想約定・手数料0。", color="#cbd5e1", fontsize=9)
    fig.tight_layout(rect=(0,.06,1,.96))
    prefix = "" if base_method == "D07" else f"{base_method}_対_"
    out = BASE / "図" / f"{session}_{prefix}{method}{'_拡大' if zoom else ''}.png"
    out.parent.mkdir(exist_ok=True)
    fig.savefig(out, dpi=145, facecolor=fig.get_facecolor())
    plt.close(fig)
    return {"session":session,"method":method,"base_method":base_method,"zoom":zoom,"path":str(out),**counts}


def main() -> None:
    """改善最大と悪化の代表場を可視化する。

    引数: なし。返り値: None。保存原板と既存約定の図だけを出力する。
    """
    reports = [draw("2026-10-22_Day", "G01"), draw("2026-10-15_Day", "G01"),
               draw("2026-10-15_Day", "G01", ("09:00", "11:15")), draw("2026-10-05_Day", "G01")]
    (BASE / "図の原板読取154.json").write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(reports,ensure_ascii=False))


if __name__ == "__main__":
    main()
