"""時間帯診断の短い日本語説明と確認用の画像を作る。"""

import json
from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from diagnose import JST, OUT, ROOT, LABELS, bounds, read_bars


def number(value: float | None, digits: int = 2) -> str:
    """報告用に数値を整形する。

    引数: value (float | None) は値、digits (int) は小数桁数。
    返り値: str は表示値。
    """
    return "対象外" if value is None else f"{value:.{digits}f}"


def table(summary: dict, names: list[str]) -> str:
    """時間帯別の短い表を作る。

    引数: summary (dict) は商品集計、names (list[str]) は掲載区分。
    返り値: str はMarkdown表。
    """
    lines = ["| 日本時間の区間 | 高安幅中央値 | 1分変化中央値 | 5分効率 | 20分効率 | 大変動分の割合 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name in names:
        r = summary[name]
        lines.append(f"| {LABELS[name]} | {number(r['observed_range_session_median'],1)} | {number(r['abs_1min_bp_median_session_median'])}bp | {number(r['efficiency_5min_median_session_median'],3)} | {number(r['efficiency_20min_median_session_median'],3)} | {r['large_1min_rate']*100:.1f}% |")
    return "\n".join(lines)


def plot_examples(data: dict) -> list[dict]:
    """米国前の単調な例と往復例を同じ表示尺度で図示する。

    引数: data (dict) は診断JSON。
    返り値: list[dict] は選択規則と保存画像。例は事後選択であり入口へ使わない。
    """
    rows = [r for r in data["各場"] if r["product"]=="NK225" and r["group"]=="既知22夜間" and r["segments"]["米朝前全体"]["coverage"]>=.9]
    ordered = sorted(rows, key=lambda r:r["segments"]["米朝前全体"]["observed_absnet_range_ratio"])
    examples = [(ordered[-1], "米朝前の始終差が高安幅に近い例"), (ordered[0], "米朝前の往復が大きい反例")]
    plt.rcParams.update({"font.family":"Yu Gothic", "font.size":10, "figure.facecolor":"#111827", "axes.facecolor":"#111827", "axes.edgecolor":"#64748b", "axes.labelcolor":"#e2e8f0", "text.color":"#e2e8f0", "xtick.color":"#cbd5e1", "ytick.color":"#cbd5e1", "grid.color":"#334155"})
    artifacts = []
    for row,title in examples:
        day = row["session"][:10]
        bb = bounds(day,"Night")
        start = bb["米現物前全体"][0]
        end = bb["利用者指定の夜間移行帯"][1]
        fig, ax = plt.subplots(figsize=(12,4.5))
        for product,color in (("NK225","#38bdf8"),("TOPIX","#fbbf24")):
            bars,_ = read_bars(ROOT / "candle_1min" / product / f"{day}_Night.csv")
            ts = [start+timedelta(minutes=i) for i in range(int((end-start).total_seconds()/60))]
            first = next(bars[t]["open"] for t in ts if t in bars)
            y = [(bars[t]["close"]-first)/first*100 if t in bars else np.nan for t in ts]
            ax.plot(ts,y,color=color,linewidth=1.3,label=f"{product}（17時の最初の値から%）")
        for t,label in ((bb["米朝発表枠"][0],"米08:30枠"),(bb["米現物寄付"][0],"米現物開始")):
            ax.axvline(t,color="#94a3b8",ls="--",alpha=.8)
            ax.text(t,.98,label,transform=ax.get_xaxis_transform(),ha="right",va="top",fontsize=9)
        ax.axhline(0,color="#64748b",lw=.8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M",tz=JST))
        ax.set_title(f"{day} ナイト / {title}（事後の説明例）")
        ax.set_ylabel("始値比（%）")
        ax.set_xlabel("日本時間。欠測区間は線を接続しない")
        ax.grid(alpha=.5)
        legend = ax.legend(loc="lower left",facecolor="#111827",edgecolor="#64748b")
        for text in legend.get_texts():
            text.set_color("#e2e8f0")
        fig.tight_layout()
        name = f"{day}_米国前の例.png"
        fig.savefig(OUT/name,dpi=160)
        plt.close(fig)
        artifacts.append({"session":row["session"],"title":title,"path":name,"selection":"既知22夜の日経17〜21:30観測率90%以上の場から始終差÷観測高安幅の最大/最小。事後の説明専用。","absnet_range_ratio":row["segments"]["米朝前全体"]["observed_absnet_range_ratio"]})
    return artifacts


def main() -> None:
    """短い表、限界、一次資料と画像を保存する。

    引数: なし。
    返り値: None。
    """
    data=json.loads((OUT/"昼夜時間帯診断.json").read_text(encoding="utf-8"))
    day=data["集計"]["既知23日中"]
    night=data["集計"]["既知22夜間"]
    examples=plot_examples(data)
    (OUT/"図の選択.json").write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# 市場時計で変わるのは活動量。方向の持続は別に確認する", "", "保存1分足だけの診断。金融再生・API取得・実注文は各0。既知45場（23日中・22夜間）は2026年9月21日〜10月21日デイ。追加の10月21日ナイト・22日デイは別集計とし、主表へ混ぜない。", "", "**米現物開始まで全部静観する理由は、値動きがないからではない。日経は17:00〜22:30だけでも観測高安幅の場間中央値550円。TOPIXは25.5pt。ただし、この幅を事前に予測して利益にできるとは測っていない。**", "", "## 日経：日中23場", "", table(day["NK225"],["日本寄付前","日本前場","日本昼休み","日本後場","日本引け後"]), "", "前場の活動は昼休み・後場より強い。しかし5分効率は前場0.385、昼休み0.429で、前場だから素直な一方向とは言えない。日中には日本現物休場の4場（9/21〜23・10/12）を含む。JSONでは通常19日と休場4日を別集計している。", "", "## 日経：夜間22場", "", table(night["NK225"],["開始直後","米朝前","米朝発表枠","米現物寄付","米現物以後"]), "", "17:00〜21:30の20分効率中央値は0.191、22:30以後は0.214。場内で前者の方が高いのは8/22場、後者が高いのは14/22場。**『米前の方が一方向に動きやすい』という一般則は今回の尺度では支持されない。** とはいえ、米前にも方向が揃う局面はあるため、全面停止とは別の話である。", "", "米寄付30分の1分変化中央値は19:00〜21:30の約2倍。大変動分も30.0%対7.1%。時計を使うなら、方向を決めるスイッチより、許容枚数・確認量・保護条件を変える根拠としてまず検証する。", "", "## TOPIX参考", "", table(day["TOPIX"],["日本寄付前","日本前場","日本昼休み","日本後場","日本引け後"]), "", table(night["TOPIX"],["開始直後","米朝前","米朝発表枠","米現物寄付","米現物以後"]), "", "## 何を次の金融比較へ渡せるか", "", "- 朝・米寄付の大変動区間：初回枚数を小さくし、二市場の継続と価格帯維持で追加する案。値動きが強いだけで追加しない。", "- 昼休み・夜間の静かな区間：現物前を全面休止せず別入口を検証。ただし小幅の往復で追加・撤退を反復する損失を別に点検する。", "- 時刻が変わった時：過去区間の方向判断をそのまま使わず、必要なら準備を作り直す。引継ぎと強制返済の損益差は未検証。", "- 5分効率・20分効率は過去分だけなら当時計算できる。ただし今回の区間全体の中央値・高安幅・90分位を、区間開始の判断に渡してはならない。", "", "## 図での反例", ""]
    for ex in examples:
        lines.append(f"- [{ex['session']}：{ex['title']}]({ex['path']})。米朝前の始終差÷高安幅={ex['absnet_range_ratio']:.3f}。図は事後説明専用で、ここから取引時刻を選んでいない。")
    lines += ["", "## 定義と欠測", "", "高安幅は足の観測高値−観測安値。日経は円、TOPIXはptであり利益額ではない。1bp=価格の0.01%。1分変化と方向効率は各場の中央値を取り、さらに場間中央値を取った。方向効率=始終差の絶対値÷途中の絶対変化合計。1に近いほど単調。5分は連続6本、20分は連続21本の終値を必要とし、欠測は補間しない。全不変窓は効率0とせず除外。時間の短い日本寄付前・引け後は20分効率の対象外。重複窓の数は独立標本数ではない。", "", "大変動分は各セッションの1分絶対変化の90分位以上（0除外）。その出現数÷各区分の連続1分変化数。終端は当場終了。未来を使う診断分類なので注文条件へ直接使用不可。時刻境界では直前の分足からの変化を境界後の区間に割り当て、寄付・発表の分も含める。", "", "既知22夜の米現物前は日経6,749/7,260分、TOPIX7,031/7,260分、米現物後は日経8,419/9,900分、TOPIX9,159/9,900分。欠測の多い静かな時間の連続20分が除かれる選択性がある。欠測は価格不変ではない。1分足の確定終値の診断であり、原板の新鮮さ・気配差・実約定順位は今回測っていない。", "", "## 時刻の一次資料", "", "- [JPXの内国株立会時間](https://www.jpx.co.jp/equities/trading/domestic/01.html)：前場09:00〜11:30、後場12:30〜15:30。15:25以後の引け板寄せなど細区分は今回の12:30〜15:30に含む。", "- [NYSEの市場時計](https://www.nyse.com/trade/hours-calendars)：主市場09:30米東部、NYSE Arcaの早朝は04:00米東部。対象期間はそれぞれ日本22:30・17:00。", "- [BLSの2026年10月予定](https://www.bls.gov/schedule/2026/10_sched.htm)：10/2雇用統計、10/14CPI、10/15PPIなどは08:30米東部。対象期間は日本21:30。毎日この時刻に発表があるとは扱わない。", "- [CMEのE-mini S&P 500](https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.performance.html)：米株先物はほぼ24時間の取引がある。米国の情報反応が現物開始時刻だけに限られるわけではない。CFDの取引時間は提供業者・商品次第なので、単一の『CFD開始時刻』を原因と断定しない。", "", "日本時計と米東部時計はzoneinfoで個別変換した。対象は全て米夏時間。冬は米08:30枠が日本22:30、現物開始が23:30へ動く。利用者例の21:00・23:30固定区分もJSONへ併記したが、米国市場の時計と一致するとは扱わない。外部資料は2026-10-22確認、方向入力には使っていない。", "", "再現：[診断コード](diagnose.py)、[全区分・各場・入力SHA](昼夜時間帯診断.json)。比較元：[00131の原板診断](../../regime131_20261020/night_diagnosis/時間帯の観測と実装候補.md)。資料資格と観測粒度が異なるため、今回と旧集計の数値差を改善成績としない。"]
    (OUT/"時間区分の診断.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(examples,ensure_ascii=False))


if __name__=="__main__":
    main()
