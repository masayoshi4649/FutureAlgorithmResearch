"""追加夜間の既知部分・追加部分と仮想売買を図示する。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
import pandas as pd

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent / "wave_v2"))
from plot_v2 import setup_style
from recheck import new_data, CUTOFF, SESSION

JST = ZoneInfo("Asia/Tokyo")
COLORS = {1: "#087e64", -1: "#c45438"}


def number(value: float, symbol: str, signed: bool = False) -> str:
    """機能: 銘柄ごとの価格差を図用に整形する。

    引数: value (float)、symbol (str)、signed (bool)。返り値: 表示文字列 (str)。
    """
    return format(value, ("+" if signed else "") + (",.0f" if symbol == "NK225" else ",.1f"))


def main() -> None:
    """機能: 追加セッションの全取引図と台帳を画像・PDFに保存する。

    引数: なし。返り値: なし (None)。
    """
    setup_style()
    fixed = json.loads((OUT.parent / "wave_v2" / "固定設定.json").read_text(encoding="utf-8"))
    frozen_at = pd.Timestamp(fixed["fixed_at"])
    trades = json.loads((OUT / "追加_取引.json").read_text(encoding="utf-8"))
    for i, trade in enumerate(trades, 1):
        trade["番号"] = i
        for field in ("entry_time", "exit_time"):
            trade[field] = pd.Timestamp(trade[field])
    data = new_data()
    fig = plt.figure(figsize=(16, 12), dpi=150)
    layout = fig.add_gridspec(2, 1, top=.815, bottom=.065, left=.075, right=.97, hspace=.25)
    fig.text(.075, .962, "追加夜間でも長い上昇を検知。TOPIXは明け方に損失", fontsize=21, fontweight="bold", color="#203946", va="top")
    fig.text(.075, .918, "9月22日 17:00〜翌05:54　前回の条件を固定して再生　日本時間・全８取引", fontsize=11, color="#4b606b", va="top")
    handles = [Line2D([0], [0], color=COLORS[1], lw=3, label="ロング"),
               Line2D([0], [0], color=COLORS[-1], lw=3, label="ショート"),
               Patch(facecolor="#eef1f4", label="前回確認済み（00:28まで）"),
               Patch(facecolor="#fff3d9", label="今回追加で確認"),
               Line2D([0], [0], color="#7760a7", ls="--", lw=1.1, label="条件固定 01:17:48")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(.07, .887), ncol=5, frameon=False, fontsize=10)

    # ----------------------------------------
    # 未観測分は価格の線を切り、保有時刻と返済価格を実際の再生結果から表示する。
    for row, symbol in enumerate(("NK225", "TOPIX")):
        one = data[(SESSION, symbol)][0]
        subset = [t for t in trades if t["symbol"] == symbol]
        inner = layout[row].subgridspec(2, 1, height_ratios=[3.2, 1.2], hspace=.28)
        ax = fig.add_subplot(inner[0])
        ledger = fig.add_subplot(inner[1])
        ledger.axis("off")
        grid = pd.date_range(one.index[0], one.index[-1], freq="min")
        close = one.close.reindex(grid)
        ax.axvspan(grid[0], CUTOFF, facecolor="#eef1f4", alpha=.8)
        ax.axvspan(CUTOFF, grid[-1], facecolor="#fff3d9", alpha=.6)
        ax.axvline(CUTOFF, color="#ad9159", ls=":", lw=1)
        ax.axvline(frozen_at, color="#7760a7", ls="--", lw=1.1)
        ax.plot(grid, close, color="#a3afb5", lw=.9)
        ax.scatter(one.index, one.close, color="#a3afb5", s=2, alpha=.45)
        for trade in subset:
            start, end, side = trade["entry_time"], trade["exit_time"], trade["side"]
            mask = (grid >= start) & (grid <= end)
            color = COLORS[side]
            ax.plot(grid[mask], close[mask], color=color, lw=1.7)
            ax.axvspan(start, end, ymin=.015, ymax=.045, color=color, alpha=.75)
            ax.scatter([start], [trade["entry_price"]], s=49, marker="^" if side == 1 else "v", color=color, edgecolor="white", linewidth=.7, zorder=6)
            ax.scatter([end], [trade["exit_price"]], s=25, marker="s", facecolor="white", edgecolor=color, linewidth=1.3, zorder=5)
            ax.annotate(str(trade["番号"]), (start, trade["entry_price"]), xytext=(5, 10 if side == 1 else -18), textcoords="offset points", color=color, fontsize=10, fontweight="bold")
        net = sum(t["net_points"] for t in subset)
        wins = sum(t["net_points"] > 0 for t in subset)
        ax.set_title(f"{symbol}　{len(subset)}回・{wins}勝　通常損益 {number(net, symbol, True)}{'円幅' if symbol == 'NK225' else 'ポイント'}", loc="left", fontsize=14, fontweight="bold", color="#203946", pad=11)
        ax.set_xlim(grid[0] - pd.Timedelta(minutes=5), grid[-1] + pd.Timedelta(minutes=5))
        margin = (one.high.max() - one.low.min()) * .12
        ax.set_ylim(one.low.min() - margin, one.high.max() + margin)
        ax.grid(axis="y", color="#dfe6e9", lw=.6)
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=JST))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, pos: f"{value:,.0f}"))
        ax.set_ylabel("価格")

        # ----------------------------------------
        # 全件の台帳を図と同じ番号で併記し、短い損失取引も省かない。
        for j, trade in enumerate(subset):
            direction = "買" if trade["side"] == 1 else "売"
            line = (f'{trade["番号"]}　{direction}　{trade["entry_time"]:%H:%M} {number(trade["entry_price"], symbol)}'
                    f' → {trade["exit_time"]:%H:%M} {number(trade["exit_price"], symbol)}'
                    f'　 {trade["duration_min"]:.0f}分　 {number(trade["net_points"], symbol, True)}')
            ledger.text(0, .96 - .215 * j, line, transform=ledger.transAxes, color=COLORS[trade["side"]], fontsize=10, va="top")
        if symbol == "NK225":
            ledger.text(.58, .94, "①は前回までに返済済み\n②は前回保有中だったショートの完結\n③は今回追加部分でのロング", transform=ledger.transAxes, color="#5d707a", fontsize=10, va="top", linespacing=1.7)
        else:
            ledger.text(.58, .94, "④は前回までに返済済み\n⑤は前回保有中だったショートの完結\n⑥〜⑧は追加部分での新規\n⑦⑧の合計 −13ポイント", transform=ledger.transAxes, color="#5d707a", fontsize=10, va="top", linespacing=1.7)
    fig.text(.075, .025, "通常損益は往復２ティック控除後の価格差。△/▽は仮想新規、□は返済。夜間全体を未使用検証とは扱わない。", fontsize=9.5, color="#5d707a")
    for extension in ("png", "pdf"):
        fig.savefig(OUT / f"追加夜間の検知.{extension}", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
