"""保存済み検証結果から銘柄別の価格と波検知を可視化する。外部通信は行わない。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MaxNLocator
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
JST = ZoneInfo("Asia/Tokyo")
SYMBOLS = ("NK225", "TOPIX")
COLORS = {1: "#16836B", -1: "#C15B43"}
INK = "#233A53"
MUTED = "#607184"
SESSIONS = (
    ("2026-09-21_Day", "９月２１日・日中", "開発"),
    ("2026-09-21_Night", "９月２１日→２２日・夜間", "開発"),
    ("2026-09-22_Day", "９月２２日・日中", "未使用日"),
)


def load_json(path: Path) -> object:
    """機能: 日本語の結果ファイルを読み込む。

    引数: path (Path) は対象ファイル。返り値: 復元した値 (object)。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def prepare_bars(data: pd.DataFrame) -> pd.DataFrame:
    """機能: 確定足だけを残し、時刻を日本時間の索引にする。

    引数: data (DataFrame) は価格データ。返り値: 時刻順の確定足 (DataFrame)。
    """
    frame = data.copy()
    if "closed" in frame:
        frame = frame[frame.closed.astype(str).str.lower().eq("true")].copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True).dt.tz_convert(JST)
    return frame.set_index("time").sort_index()


def format_price(value: float, position: int | None = None) -> str:
    """機能: 価格の目盛りを桁区切り付きで表示する。

    引数: value (float) は価格、position (int | None) は目盛り位置。
    返り値: 末尾の不要な小数点を除いた価格表記 (str)。
    """
    return f"{value:,.1f}".rstrip("0").rstrip(".")


def configure_style() -> None:
    """機能: 日本語フォントと共通の描画書式を設定する。

    引数: なし。返り値: なし (None)。
    """
    plt.rcParams.update({
        "font.family": ["Yu Gothic", "Meiryo", "sans-serif"],
        "font.size": 11,
        "axes.unicode_minus": False,
        "figure.facecolor": "#F8FAFC",
        "axes.facecolor": "#FFFFFF",
        "axes.edgecolor": "#D1DBE5",
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "savefig.facecolor": "#F8FAFC",
    })


def draw_panel(ax: plt.Axes, bars: pd.DataFrame, events: list[dict], symbol: str,
               heading: str, period_type: str, date_ticks: bool = False) -> None:
    """機能: 価格線に開始矢印・決済・継続および仮想保有区間を重ねる。

    引数: ax (Axes)、bars (DataFrame)、events (list[dict])、symbol/heading/period_type (str)、
          date_ticks (bool) は横軸に日付も付けるか。
    返り値: なし (None)。
    """
    if bars.empty:
        raise ValueError(f"描画できる確定足がありません: {symbol} {heading}")
    series = bars.close.reindex(pd.date_range(bars.index[0], bars.index[-1], freq="min"))
    ax.plot(series.index, series, color=INK, linewidth=1.2, zorder=3)
    ax.grid(axis="y", color="#E8EDF3", linewidth=0.8)
    ax.grid(axis="x", color="#EFF3F7", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.set_major_formatter(FuncFormatter(format_price))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=JST, minticks=5, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d\n%H:%M" if date_ticks else "%H:%M", tz=JST))
    ax.tick_params(axis="both", labelsize=10, length=3)
    ax.set_ylabel("価格（円）" if symbol == "NK225" else "価格（指数ポイント）", labelpad=8)
    ax.set_xlim(bars.index[0], bars.index[-1] + pd.Timedelta(minutes=4))
    ax.margins(y=0.24)

    # ----------------------------------------
    # 同時刻に近い開始ラベルは高さを交互に変え、価格線との衝突を抑える。
    long_count = sum(e["side"] == 1 for e in events)
    short_count = sum(e["side"] == -1 for e in events)
    closed_count = sum(bool(e["closed"]) for e in events)
    ax.set_title(f"{symbol}　{heading}  ［{period_type}］", loc="left", fontsize=13, fontweight="bold", pad=28)
    ax.text(0, 1.025, f"ロング {long_count} 件　ショート {short_count} 件　｜　決済 {closed_count} 件・継続 {len(events)-closed_count} 件",
            transform=ax.transAxes, fontsize=10, color=MUTED, ha="left", va="bottom")
    for number, event in enumerate(sorted(events, key=lambda x: x["entry_time"]), start=1):
        start = pd.Timestamp(event["entry_time"]).tz_convert(JST)
        end = pd.Timestamp(event["exit_time"]).tz_convert(JST) if event["closed"] else bars.index[-1]
        side = int(event["side"])
        color = COLORS[side]
        ax.axvspan(start, end, color=color, alpha=0.085, zorder=1)
        ax.scatter(start, event["entry_price"], marker="^" if side == 1 else "v", s=72,
                   color=color, edgecolor="white", linewidth=0.8, zorder=7)
        y_offset = -(26 + 14*(number % 2)) if side == 1 else 26 + 14*(number % 2)
        lower, upper = ax.get_ylim()
        relative_height = (event["entry_price"]-lower)/(upper-lower)
        if y_offset < 0 and relative_height < 0.28:
            y_offset = 26
        elif y_offset > 0 and relative_height > 0.72:
            y_offset = -26
        label = f"{'買' if side == 1 else '売'}{number}"
        ax.annotate(label, xy=(start, event["entry_price"]), xytext=(0, y_offset),
                    textcoords="offset points", ha="center", va="top" if y_offset < 0 else "bottom",
                    fontsize=9, fontweight="bold", color=color,
                    bbox=dict(boxstyle="round,pad=0.20", facecolor="white", edgecolor="none", alpha=0.88),
                    arrowprops=dict(arrowstyle="-", color=color, linewidth=0.75, shrinkA=4, shrinkB=6), zorder=8)
        if event["closed"]:
            ax.scatter(end, event["exit_price"], marker="x", s=43, color=color, linewidth=1.5, zorder=6)
        else:
            ax.scatter(end, float(bars.close.iloc[-1]), marker="o", s=68, facecolor="white",
                       edgecolor=color, linewidth=1.7, zorder=6)


def add_figure_notes(fig: plt.Figure, title: str, subtitle: str) -> None:
    """機能: 図のタイトル、凡例、共通注記を配置する。

    引数: fig (Figure)、title/subtitle (str)。返り値: なし (None)。
    """
    fig.suptitle(title, x=0.055, y=0.986, ha="left", fontsize=22, fontweight="bold")
    fig.text(0.055, 0.95, subtitle, ha="left", va="top", fontsize=11, color=MUTED)
    handles = [
        Line2D([], [], color=INK, lw=1.3, label="１分足終値"),
        Line2D([], [], color=COLORS[1], marker="^", linestyle="none", markersize=8, label="ロング開始"),
        Line2D([], [], color=COLORS[-1], marker="v", linestyle="none", markersize=8, label="ショート開始"),
        Line2D([], [], color=MUTED, marker="x", linestyle="none", markersize=7, label="仮想決済"),
        Line2D([], [], color=MUTED, marker="o", markerfacecolor="white", linestyle="none", markersize=7, label="観測末尾で継続"),
    ]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.052, 0.924), frameon=False,
               ncol=5, fontsize=10, handlelength=1.6, columnspacing=2.0)
    fig.text(0.055, 0.019, "時刻は日本時間（JST）。淡色帯は開始から仮想決済・観測末尾まで。価格線の空白は１分足の欠測。",
             fontsize=10, color=MUTED)


def plot_saved() -> Path:
    """機能: 開発２セッションと未使用日の両銘柄を６パネルで保存する。

    引数: なし。返り値: 図の保存先 (Path)。
    """
    events = load_json(OUT/"開発_採用条件_イベント.json") + load_json(OUT/"未使用日_イベント.json")
    fig, axes = plt.subplots(3, 2, figsize=(19.2, 14.4))
    for row, (session, heading, period_type) in enumerate(SESSIONS):
        for col, symbol in enumerate(SYMBOLS):
            bars = prepare_bars(pd.read_csv(ROOT/"candle_1min"/symbol/f"{session}.csv"))
            chosen = [e for e in events if e["session"] == session and e["symbol"] == symbol]
            draw_panel(axes[row, col], bars, chosen, symbol, heading, period_type, "Night" in session)
    add_figure_notes(fig, "凍結した検知条件を、保存データで確認", "左：NK225先物　／　右：TOPIX先物　　各銘柄の価格単位で表示")
    fig.subplots_adjust(left=0.065, right=0.98, top=0.835, bottom=0.068, hspace=0.47, wspace=0.21)
    path = OUT/"図_保存３セッション.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def plot_current() -> Path:
    """機能: 一度だけ取得済みの現在セッションから両銘柄の図を作る。

    引数: なし。返り値: 図の保存先 (Path)。外部取得は実施しない。
    """
    events = load_json(OUT/"現在_イベント.json")
    fig, axes = plt.subplots(2, 1, figsize=(17, 10.8))
    latest = []
    for ax, symbol in zip(axes, SYMBOLS):
        payload = load_json(OUT/"現在セッション固定"/f"{symbol}_1min.json")
        bars = prepare_bars(pd.DataFrame(payload["data"]))
        chosen = [e for e in events if e["symbol"] == symbol]
        first = bars.index[0]
        heading = f"{first.month}月{first.day}日開始のセッション"
        draw_panel(ax, bars, chosen, symbol, heading, "最終確認", True)
        latest.append(f"{symbol} {bars.index[-1].strftime('%m/%d %H:%M')}")
    add_figure_notes(fig, "凍結した検知条件を、現在セッションで最終確認", "取得済みデータを固定して再生　｜　確定１分足の末尾：" + "　／　".join(latest))
    fig.subplots_adjust(left=0.078, right=0.98, top=0.815, bottom=0.087, hspace=0.48)
    path = OUT/"図_現在セッション.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main() -> None:
    """機能: 保存済み結果の可視化を実行する。

    引数: コマンドラインの対象指定 (list[str])。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description="結果を読み取り専用で可視化する")
    parser.add_argument("target", choices=("saved", "current", "all"), default="all", nargs="?")
    args = parser.parse_args()
    configure_style()
    if args.target in ("saved", "all"):
        print(plot_saved())
    if args.target in ("current", "all"):
        print(plot_current())


if __name__ == "__main__":
    main()
