"""報告用に確定した手法の利益・損失・収支と入口比較を日本語で描く。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
SYMBOLS = ("NK225", "TOPIX")
SESSION_ORDER = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night", "2026-09-23_Day")
SESSION_LABELS = ("9/21\n日中", "9/21\n夜間", "9/22\n日中", "9/22\n夜間", "9/23\n日中")
COLORS = dict(profit="#248571", loss="#bf625e", net="#233d53", grid="#e4e9ed", background="#f7f9fb")


def setup_style() -> None:
    """日本語フォントと科学比較向けの統一描画設定を適用する。

    引数: なし。
    返り値: None。
    """
    font = Path("C:/Windows/Fonts/meiryo.ttc")
    if not font.exists():
        raise FileNotFoundError("日本語表示に必要なメイリオフォントがありません")
    font_manager.fontManager.addfont(str(font))
    name = font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({
        "font.family": name, "font.size": 11, "axes.unicode_minus": False,
        "figure.facecolor": COLORS["background"], "axes.facecolor": "white",
        "savefig.facecolor": COLORS["background"], "axes.spines.top": False,
        "axes.spines.right": False, "axes.edgecolor": "#cbd4dc",
        "xtick.color": "#536574", "ytick.color": "#536574", "axes.labelcolor": "#536574",
    })


def read_report() -> tuple[list[dict], pd.DataFrame]:
    """報告対象手法と金額換算済みの正本表を読み、突合する。

    引数: なし。
    返り値: tuple[list[dict], DataFrame]。手法記録とセッション収支表。
    """
    methods = json.loads((OUT / "報告対象手法.json").read_text(encoding="utf-8"))
    rows = pd.read_csv(OUT / "セッション別利益損失.csv")
    assert np.allclose(rows["利益円"] - rows["損失円"], rows["収支円"])
    for method in methods:
        selected = rows[rows["手法"].eq(method["name"])]
        assert len(selected) == 10
        assert set(selected["セッション"]) == set(SESSION_ORDER)
        assert set(selected["銘柄"]) == set(SYMBOLS)
        for cell in method["cells"]:
            row = selected[selected["セッション"].eq(cell["session"]) & selected["銘柄"].eq(cell["symbol"])].iloc[0]
            assert np.isclose(row["収支価格幅"], cell["net"])
            assert np.isclose(row["利益価格幅"], cell["profit"])
            assert np.isclose(row["損失価格幅"], cell["loss"])
    return methods, rows


def money_label(value: float) -> str:
    """差引収支を符号付きの簡潔な万円表記にする。

    引数: value（float）万円。
    返り値: str。小数一桁までの値。
    """
    return f"{value:+.1f}".replace("-0.0", "0.0")


def plot_sessions(methods: list[dict], rows: pd.DataFrame) -> None:
    """主候補と両建て追跡を同じ銘柄目盛で利益・損失・差引へ分けて描く。

    引数: methods（list[dict]）報告手法、rows（DataFrame）換算済み金額正本。
    返り値: None。セッション収支.png と同名ＰＤＦを保存する。
    """
    identifiers = ("方向主候補", "両建て_勝ち脚追跡")
    selected = [next(method for method in methods if method["id"] == identifier) for identifier in identifiers]
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 11.1), dpi=180, sharex=True, sharey="col")
    fig.subplots_adjust(left=.07, right=.975, top=.755, bottom=.17, hspace=.49, wspace=.16)
    fig.text(.07, .95, "セッションごとの利益・損失・差引収支", fontsize=23, color=COLORS["net"], weight="bold")
    fig.text(.07, .91, "保存５セッションで条件を探索した結果  ／  単位：万円  ／  各脚の往復２ティック控除後", fontsize=12.3, color="#536574")
    handles = [Patch(facecolor=COLORS["profit"], label="利益だった取引の合計"),
               Patch(facecolor=COLORS["loss"], label="損失だった取引の合計（負で表示）"),
               Line2D([0], [0], color=COLORS["net"], marker="D", linestyle="", markersize=7, label="差引収支（利益 − 損失）")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(.067, .88), ncol=3, frameon=False, fontsize=11)
    for col, symbol in enumerate(SYMBOLS):
        values = rows[rows["手法"].isin([method["name"] for method in selected]) & rows["銘柄"].eq(symbol)]
        upper = max(values["利益円"].max() / 10000, 1)
        lower = -max(values["損失円"].max() / 10000, 1)
        span = upper - lower
        limits = (lower - .15 * span, upper + .23 * span)
        for row_index, method in enumerate(selected):
            ax = axes[row_index, col]
            cell = rows[rows["手法"].eq(method["name"]) & rows["銘柄"].eq(symbol)].set_index("セッション").loc[list(SESSION_ORDER)]
            profits, losses, nets = [cell[name].to_numpy(float) / 10000 for name in ("利益円", "損失円", "収支円")]
            x = np.arange(len(cell))
            ax.bar(x-.19, profits, width=.32, color=COLORS["profit"], zorder=2)
            ax.bar(x+.19, -losses, width=.32, color=COLORS["loss"], zorder=2)
            ax.plot(x, nets, linestyle="", marker="D", markersize=7, color=COLORS["net"], markeredgecolor="white", markeredgewidth=1, zorder=5)
            for location, net in zip(x, nets):
                ax.annotate(money_label(net), (location, net), textcoords="offset points", xytext=(0, 10 if net >= 0 else -18),
                            ha="center", fontsize=10.5, color=COLORS["net"], weight="bold",
                            bbox=dict(facecolor="white", edgecolor="none", pad=1.6, alpha=.9), zorder=6)
            ax.axhline(0, color="#9daeba", linewidth=1.05, zorder=1)
            ax.yaxis.grid(True, color=COLORS["grid"], linewidth=.8)
            ax.set_axisbelow(True)
            ax.set_ylim(*limits)
            ax.set_xticks(x, SESSION_LABELS, fontsize=11)
            ax.tick_params(axis="x", length=0, labelbottom=True, pad=8)
            label = "方向を検知する主候補" if row_index == 0 else "両建て＋勝ち脚追跡"
            quantity = "ラージ１枚" if row_index == 0 else "買い１枚 ＋ 売り１枚"
            ax.set_title(f"{label}  ｜  {symbol}\n{quantity}", loc="left", fontsize=13.5, pad=16, color=COLORS["net"])
            ax.set_ylabel("万円")
            total = f"５セッション差引  {money_label(float(nets.sum()))} 万円"
            ax.text(.975, .965, total, transform=ax.transAxes, ha="right", va="top", fontsize=10.5,
                    color=COLORS["net"], bbox=dict(facecolor="#eef3f6", edgecolor="none", pad=5))
    time_exits = sum(trade["reason"] == "セッション内の時刻返済" for trade in selected[0]["trades"])
    fig.text(.07, .101, f"主候補は{len(selected[0]['trades'])}取引中{time_exits}取引が時刻返済。日中15:35／夜間05:50以後の最初の実在足で返済する長い保有が中心。", fontsize=10.5, color="#536574")
    fig.text(.07, .073, "利益・損失は費用控除後の各取引を分類。両建ては各脚を分けて合計。各銘柄は上下の図で同じ目盛。", fontsize=10.5, color="#536574")
    fig.text(.07, .045, "同じ保存データで条件を選んだ仮想売買であり、未使用期間の成績ではありません。金額換算の正本：セッション別利益損失.csv", fontsize=10.5, color="#536574")
    for extension in ("png", "pdf"):
        fig.savefig(OUT / f"セッション収支.{extension}", dpi=180)
    plt.close(fig)


def plot_entries(methods: list[dict], variant: str = "entry") -> bool:
    """同じ主候補で入口または追跡幅だけ変えた収支と短時間取引の件数を並べる。

    引数: methods（list[dict]）主候補の設定を含む報告手法、variant（str）entryまたはtrail。
    返り値: bool。元比較表が存在して描画した場合にTrue。
    """
    path = OUT / "入口と微細波比較.csv"
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    primary = next(method for method in methods if method["id"] == "方向主候補")
    is_entry = variant == "entry"
    names = ("signal_limit", "stop", "pullback", "trail") if is_entry else ("1.5", "2.5", "4", "6")
    labels = ("価格許容指値", "逆指値", "押し目・戻り待ち", "反発・反落待ち") if is_entry else tuple(f"{name} ＡＴＲ" for name in names)
    keys = [f"新規方式_{name}" for name in names] if is_entry else [f"追跡幅_{name}ATR" for name in names]
    filename = "入口比較" if is_entry else "追跡幅比較"
    fig, axes = plt.subplots(2, 2, figsize=(14.8, 9.4), dpi=180)
    fig.subplots_adjust(left=.17, right=.965, top=.78, bottom=.14, hspace=.52, wspace=.18)
    fig.text(.06, .95, "入口だけ変えると、収支と短い往復はどう変わるか" if is_entry else "追跡幅を変えると、収支と取引回数はどう変わるか", fontsize=21, color=COLORS["net"], weight="bold")
    fig.text(.06, .905, ("主候補の検知・返済条件を固定した比較" if is_entry else "主候補の他条件を固定した追跡倍率の比較") + "  ／  ラージ１枚  ／  保存５セッション・費用控除後", fontsize=12, color="#536574")
    fig.legend(handles=[Patch(facecolor=COLORS["loss"], label="保有15分以内"), Patch(facecolor="#7996ad", label="保有15分超")],
               loc="upper left", bbox_to_anchor=(.595, .87), ncol=2, frameon=False, fontsize=11)
    for row_index, symbol in enumerate(SYMBOLS):
        selected = frame[frame["銘柄"].eq(symbol)].set_index("比較").loc[keys]
        y = np.arange(4)
        factor = .1 if symbol == "NK225" else 1.0
        nets = selected["収支"].to_numpy(float) * factor
        counts = selected["件数"].to_numpy(float)
        shorts = selected["十五分以内"].to_numpy(float)
        assert (shorts <= counts).all()
        original = primary["config"]["entry"] if is_entry else f"{primary['config']['trail']:g}"
        label_names = [label + (" ＊" if name == original else "") for name, label in zip(names, labels)]
        left, right = axes[row_index]
        colors = [COLORS["profit"] if value >= 0 else COLORS["loss"] for value in nets]
        left.barh(y, nets, color=colors, height=.6, zorder=2)
        left.axvline(0, color="#9daeba", linewidth=1)
        left.set_yticks(y, label_names)
        left.invert_yaxis()
        scale = max(float(np.ptp(nets)), max(abs(nets)), 1)
        left.set_xlim(min(0, float(nets.min())) - .12*scale, max(0, float(nets.max())) + .22*scale)
        for position, value in zip(y, nets):
            left.annotate(money_label(value), (value, position), textcoords="offset points", xytext=(5 if value >= 0 else 8, 0),
                          ha="left", va="center", fontsize=11, color=COLORS["net"] if value >= 0 else "white")
        left.set_title(f"{symbol}  差引収支", loc="left", fontsize=14, pad=14, color=COLORS["net"])
        left.set_xlabel("万円")
        right.barh(y, shorts, color=COLORS["loss"], height=.6, label="保有15分以内", zorder=2)
        right.barh(y, counts-shorts, left=shorts, color="#7996ad", height=.6, label="保有15分超", zorder=2)
        right.set_yticks(y, [""]*4)
        right.invert_yaxis()
        right.set_xlim(0, max(counts)*1.3)
        right.xaxis.set_major_locator(MaxNLocator(integer=True))
        for position, total, short in zip(y, counts, shorts):
            right.annotate(f"{total:g}回（短期 {short:g}）", (total, position), textcoords="offset points", xytext=(5,0), ha="left", va="center", fontsize=10.5, color=COLORS["net"])
        right.set_title(f"{symbol}  取引回数", loc="left", fontsize=14, pad=14, color=COLORS["net"])
        right.set_xlabel("回")
        for ax in (left,right):
            ax.xaxis.grid(True, color=COLORS["grid"], linewidth=.8)
            ax.set_axisbelow(True)
            ax.tick_params(axis="y", length=0)
    fig.text(.06,.075,("＊は主候補の入口。" if is_entry else "＊は主候補の追跡幅。")+"15分以内は細かい往復を調べる代理指標であり、すべてを無意味な波と見なすものではありません。",fontsize=10.5,color="#536574")
    if not is_entry:
        plan = json.loads((OUT / "入口比較計画.json").read_text(encoding="utf-8"))
        controls = [item["config"] for item in plan["条件"] if item["name"] in keys]
        initial_values = {float(config["stop_loss"]) for config in controls}
        assert len(controls) == 4 and len(initial_values) == 1
        assert all(config["exit_mode"] == "small_stop_trail" for config in controls)
        initial = initial_values.pop()
        fig.text(.06,.048,f"初期損切りを全て{initial:g}ＡＴＲに固定して、追跡幅だけを変えています。",fontsize=10.5,color="#536574")
        fig.text(.06,.021,"この比較の結果で主候補を選び直していません。正本：入口と微細波比較.csv",fontsize=10.5,color="#536574")
    else:
        fig.text(.06,.045,"この比較の結果で主候補を選び直していません。正本：入口と微細波比較.csv",fontsize=10.5,color="#536574")
    for extension in ("png", "pdf"):
        fig.savefig(OUT / f"{filename}.{extension}", dpi=180)
    plt.close(fig)
    return True


def main() -> None:
    """正本表と記録を突合し、比較図と使用入力のハッシュを保存する。

    引数: なし。
    返り値: None。
    """
    setup_style()
    methods, rows = read_report()
    plot_sessions(methods, rows)
    entries = plot_entries(methods)
    trail = plot_entries(methods, "trail")
    sources = [OUT/"報告対象手法.json",OUT/"セッション別利益損失.csv"]
    if entries:
        sources.append(OUT/"入口と微細波比較.csv")
    if trail:
        sources.append(OUT/"入口比較計画.json")
    record = dict(入力SHA256={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
                  金額単位="万円", 正本利益損失差引突合=True, 入口図=entries, 追跡幅図=trail,
                  セッション=list(SESSION_ORDER), 描画対象=["方向主候補","両建て_勝ち脚追跡"])
    (OUT/"図の生成記録.json").write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
    print("セッション収支図を作成" + ("。入口比較図も作成" if entries else ""))


if __name__ == "__main__":
    main()
