"""凍結済み採用結果の指定波を、実在１分足と新規・返済時刻で描画する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import matplotlib.pyplot as plt
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
JST = ZoneInfo("Asia/Tokyo")
COLORS = {1: "#16836d", -1: "#bc4a45"}
SYMBOLS = ("NK225", "TOPIX")
SESSION_NAMES = {
    "2026-09-21_Day": "９月21日 デイ",
    "2026-09-22_Day": "９月22日 デイ",
    "2026-09-22_Night": "９月22日 ナイト（指定波は23日未明）",
    "2026-09-23_Day": "９月23日 デイ・凍結後の答え合わせ",
}


def setup_style() -> None:
    """機能: 日本語フォントと統一配色を指定する。

    引数: なし。返り値: なし (None)。
    """
    font = Path("C:/Windows/Fonts/meiryo.ttc")
    if not font.exists():
        raise FileNotFoundError("日本語描画に必要なメイリオが見つかりません")
    font_manager.fontManager.addfont(str(font))
    name = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({
        "font.family": name, "font.size": 9, "axes.unicode_minus": False,
        "figure.facecolor": "#f7f8fa", "axes.facecolor": "white", "savefig.facecolor": "#f7f8fa",
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#cbd2d8",
        "axes.labelcolor": "#52616b", "xtick.color": "#52616b", "ytick.color": "#52616b",
    })


def read_results(development_only: bool, reference_path: Path | None = None) -> tuple[list[dict], dict, dict]:
    """機能: 採用済み結果と保存価格を読み、現在答え合わせが完成していれば追加する。

    引数: development_only (bool) は保存済み開発３波に限定する指定、
    reference_path (Path | None) は主候補とは別の参考候補明細。
    返り値: 取引、指定波、１分価格 (tuple[list[dict], dict, dict])。
    通信や検知条件の再計算は行わない。
    """
    if reference_path is None:
        payloads = [json.loads((OUT / "採用_開発結果.json").read_text(encoding="utf-8"))]
        current_result = OUT / "答え合わせ_採用.json"
        if not development_only and current_result.exists():
            payloads.append(json.loads(current_result.read_text(encoding="utf-8")))
    else:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        payloads = [reference["開発"], reference["答え合わせ"]]
    trades, targets, prices = [], {}, {}
    for payload in payloads:
        for original in payload["trades"]:
            trade = dict(original)
            for field in ("signal_time", "entry_time", "exit_time"):
                trade[field] = pd.Timestamp(trade[field]) if trade.get(field) else None
            trades.append(trade)
        for original in payload["targets"]:
            target = dict(original)
            target["begin"], target["end"] = pd.Timestamp(target["begin"]), pd.Timestamp(target["end"])
            key = target["session"], target["symbol"]
            targets[key] = target
            if target["session"] == "2026-09-23_Day":
                directory = OUT / "一度取得_2026-09-23_Day"
                record = json.loads((directory / "取得記録.json").read_text(encoding="utf-8"))
                cutoff = pd.Timestamp(record["cutoff"])
                price_payload = json.loads((directory / f"{target['symbol']}_1min.json").read_text(encoding="utf-8"))
                frame = pd.DataFrame(price_payload["data"])
                frame["time"] = pd.to_datetime(frame.time)
                frame = frame[frame.closed.astype(str).str.lower().eq("true") &
                              (frame.time + pd.Timedelta(minutes=1) <= cutoff)]
            else:
                path = ROOT / "candle_1min" / target["symbol"] / f"{target['session']}.csv"
                frame = pd.read_csv(path)
                frame["time"] = pd.to_datetime(frame.time)
                frame = frame[frame.closed.astype(str).str.lower().eq("true")]
            prices[key] = frame.set_index("time").sort_index()
    return trades, targets, prices


def time_label(value: pd.Timestamp) -> str:
    """機能: 日本時間の短い時刻ラベルを作る。

    引数: value (Timestamp)。返り値: 時分 (str)。
    """
    return value.tz_convert(JST).strftime("%H:%M")


def draw_panel(ax: plt.Axes, key: tuple[str, str], trades: list[dict], target: dict, one: pd.DataFrame, show_fresh: bool = False) -> None:
    """機能: １銘柄１セッションの指定区間と全仮想取引を描く。

    引数: ax (Axes)、key (tuple[str, str])、trades (list[dict])、target (dict)、one (DataFrame)、
    show_fresh (bool) は波の開始近傍での新規基準を明記する指定。
    返り値: なし (None)。価格線は各１分足の確定時刻、売買印は実際の仮想約定時刻に置く。
    """
    session, symbol = key
    selected = [trade for trade in trades if (trade["session"], trade["symbol"]) == key]
    begin, end = target["begin"], target["end"]
    ax.axvspan(begin, end, color="#f5cc65", alpha=0.21, zorder=0)
    ax.axvline(begin, color="#c69831", lw=0.8, ls="--", alpha=0.8)
    ax.axvline(end, color="#c69831", lw=0.8, ls="--", alpha=0.8)
    ax.plot(one.index + pd.Timedelta(minutes=1), one.close, color="#334550", lw=1.05, zorder=2)
    first, last = one.index[0], one.index[-1] + pd.Timedelta(minutes=1)
    span = (last - first).total_seconds() / 60
    low, high = float(one.low.min()), float(one.high.max())
    spread = max(high - low, 20 if symbol == "NK225" else 1)
    ax.set_ylim(low - 0.24 * spread, high + 0.29 * spread)
    ax.set_xlim(first - pd.Timedelta(minutes=5), last + pd.Timedelta(minutes=8))

    # ----------------------------------------
    # 保有帯は価格領域を隠さず、下端に方向色を置く。
    for number, trade in enumerate(selected):
        color, side = COLORS[trade["side"]], trade["side"]
        entry = trade["entry_time"]
        exit_time = trade["exit_time"] or last
        ax.axvspan(entry, exit_time, ymin=0.015, ymax=0.060, color=color, alpha=0.82, linewidth=0, zorder=4)
        ax.scatter([entry], [trade["entry_price"]], marker="^" if side == 1 else "v", s=57,
                   color=color, edgecolor="white", linewidth=0.8, zorder=6)
        entry_offset = 30 if side == 1 else -37
        direction = "買い" if side == 1 else "売り"
        ax.annotate(f"{direction} {time_label(entry)}", xy=(entry, trade["entry_price"]),
                    xytext=(0, entry_offset), textcoords="offset points", ha="center", va="center",
                    fontsize=8, color=color, annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.88),
                    arrowprops=dict(arrowstyle="-", color=color, lw=0.6), zorder=8)
        if trade["exit_time"] is not None:
            ax.scatter([exit_time], [trade["exit_price"]], marker="x", s=41, color="#202f38", linewidth=1.3, zorder=7)
            offset = -35 if side == 1 else 30
            near_right = (last - exit_time).total_seconds() / 60 < span * 0.10
            horizontal = -9 if near_right else 0
            ax.annotate(f"返済 {time_label(exit_time)}", xy=(exit_time, trade["exit_price"]),
                        xytext=(horizontal, offset), textcoords="offset points", ha="right" if near_right else "center",
                        va="center", fontsize=8, color="#273c48", annotation_clip=False,
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.88),
                        arrowprops=dict(arrowstyle="-", color="#61737c", lw=0.6), zorder=8)

    # ----------------------------------------
    requested = "ロング" if target["target_side"] == 1 else "ショート"
    ax.set_title(f"{symbol}  ｜  指定 {time_label(begin)}–{time_label(end)} {requested}", loc="left", fontsize=11, fontweight="bold", pad=8)
    coverage = target["correct_coverage"] * 100
    capture = target["capture_ratio"] * 100
    label = f"指定波の時間捕捉 {coverage:.1f}%   値幅捕捉 {capture:.1f}%"
    if show_fresh:
        fresh = "合格" if target["passed"] else "未達（開始前から保有）" if target["coverage_pass"] else "未達"
        label += f"\n開始近傍の新規検知基準：{fresh}"
    ax.text(0.015, 0.965, label, transform=ax.transAxes, ha="left", va="top", fontsize=8, color="#54636c")
    ax.set_ylabel("価格（円）" if symbol == "NK225" else "ポイント", fontsize=8)
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2 if span > 600 else 1, tz=JST))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
    ax.grid(axis="y", color="#d9e0e5", alpha=0.55, lw=0.6)
    ax.tick_params(axis="both", labelsize=8)
    ax.ticklabel_format(axis="y", useOffset=False, style="plain")


def draw_figure(sessions: list[str], trades: list[dict], targets: dict, prices: dict, destination: Path,
                custom_title: str | None = None, note: str | None = None) -> None:
    """機能: 指定セッションを左右２銘柄の図にまとめて保存する。

    引数: sessions (list[str])、trades (list[dict])、targets/prices (dict)、destination (Path)、
    custom_title/note (str | None) は参考比較の表題と注意書き。
    返り値: なし (None)。
    """
    count = len(sessions)
    height = 4.5 * count + 1.2
    figure, axes = plt.subplots(count, 2, figsize=(17.8, height), squeeze=False)
    top_padding = 1.4 if count > 1 else 0.95
    figure.subplots_adjust(left=0.065, right=0.985, top=1 - top_padding / height,
                           bottom=(0.80 if note else 0.58) / height, hspace=0.43, wspace=0.16)
    if count == 1:
        title = f"事前固定候補の検証  ―  {SESSION_NAMES[sessions[0]]}"
    else:
        title = "事前固定候補の検証  ―  共通条件の検知・保有・返済"
    if custom_title is not None:
        title = custom_title
    figure.suptitle(title, x=0.065, y=1 - 0.12 / height, ha="left", fontsize=16, fontweight="bold", color="#233642")
    handles = [Line2D([0], [0], color="#334550", lw=1.2, label="確定１分終値"),
               Patch(facecolor="#f5cc65", alpha=0.35, label="ユーザー指定の波"),
               Line2D([0], [0], marker="^", color=COLORS[1], linestyle="none", label="買い新規"),
               Line2D([0], [0], marker="v", color=COLORS[-1], linestyle="none", label="売り新規"),
               Line2D([0], [0], marker="x", color="#202f38", linestyle="none", label="返済"),
               Patch(facecolor=COLORS[1], label="下端の緑帯：ロング保有"),
               Patch(facecolor=COLORS[-1], label="下端の赤帯：ショート保有")]
    figure.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.06, 1 - 0.42 / height),
                  ncol=7, frameon=False, fontsize=8.5, columnspacing=1.4)
    for row, session in enumerate(sessions):
        for column, symbol in enumerate(SYMBOLS):
            key = session, symbol
            draw_panel(axes[row, column], key, trades, targets[key], prices[key], show_fresh=bool(note))
        if count > 1:
            position = axes[row, 0].get_position()
            figure.text(position.x0, position.y1 + 0.43 / height, SESSION_NAMES[session],
                        ha="left", va="bottom", fontsize=11.5, fontweight="bold", color="#53626d")
    included_current = "2026-09-23_Day" in sessions
    footer = "時刻は日本時間。日中は同日、９月22日ナイトの00時以降は翌23日。取引印は仮想約定。"
    footer += " ９月23日デイは条件凍結後に一度取得した答え合わせ。" if included_current else " 保存済み開発データの結果。"
    if note:
        footer += "\n" + note
    figure.text(0.065, 0.13 / height, footer, ha="left", va="bottom", fontsize=8.2, color="#52616b")
    figure.savefig(destination, dpi=155)
    plt.close(figure)


def main(development_only: bool = False) -> None:
    """機能: 開発図と、存在すれば現在答え合わせを含む指定４波の図を出力する。

    引数: development_only (bool) は開発図のみ作る指定。返り値: なし (None)。
    """
    setup_style()
    trades, targets, prices = read_results(development_only)
    sessions = [session for session in SESSION_NAMES if (session, "NK225") in targets]
    draw_figure(sessions, trades, targets, prices, OUT / "検知結果.png")
    for session in sessions:
        suffix = session.replace("Day", "デイ").replace("Night", "ナイト")
        draw_figure([session], trades, targets, prices, OUT / f"検知結果_{suffix}.png")
    print(f"描画完了: {len(sessions)} 波 × ２銘柄、全体図と各波の拡大図")


def reference_figure() -> None:
    """機能: 事前固定された累積変化候補を、事後比較であると明示して別図にする。

    引数: なし。返り値: なし (None)。主候補の結果や図は変更しない。
    """
    setup_style()
    path = OUT / "固定候補明細" / "009_0.75_stop_0.5_2.5_60_cooldown_1_0_271828_entry_45.json"
    trades, targets, prices = read_results(False, reference_path=path)
    sessions = [session for session in SESSION_NAMES if (session, "NK225") in targets]
    draw_figure(sessions, trades, targets, prices, OUT / "参考_累積変化候補.png",
                custom_title="事前固定した別候補の事後比較：価格累積変化",
                note="参考比較。主候補を変更したものではない。９月21日は09:39からの買い保有で指定波を捕捉したが、開始近傍の新規検知基準は未達。")
    print("描画完了: 参考_累積変化候補.png（主候補の図は変更なし）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="採用済み検知結果の日本語図")
    parser.add_argument("--development-only", action="store_true")
    parser.add_argument("--reference-cusum", action="store_true")
    args = parser.parse_args()
    reference_figure() if args.reference_cusum else main(args.development_only)
