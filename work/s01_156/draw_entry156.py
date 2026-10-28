"""15時の実新規について、事後経路と入口前の確定情報を分離して描画する。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle


HERE = Path(__file__).resolve().parent
DATA = HERE / "current_20261027"
JST = timezone(timedelta(hours=9))


def seconds(value: str) -> float:
    """日本時間の日時文字列を秒へ変換する。

    引数: value(str)はISO日時。返り値: floatはUNIX秒。
    """
    return datetime.fromisoformat(value).timestamp()


def candle(rows: list, minute: float) -> dict:
    """保存順の原Lastから指定分のOHLCを作る。

    引数: rows(list)は選別済み原行、minute(float)は分開始。
    返り値: dictはOHLCと最初/最後の原行。入力の外へ価格を補完しない。
    """
    inside = [row for row in rows if minute <= row["time"] < minute + 60]
    if not inside:
        raise ValueError("原Lastのない1分を補完してはいけません")
    values = [row["last"] for row in inside]
    return {"time": minute, "label": datetime.fromtimestamp(minute, JST).strftime("%H:%M"),
            "open": values[0], "high": max(values), "low": min(values), "close": values[-1],
            "first_line": inside[0]["line"], "last_line": inside[-1]["line"],
            "first_price_time": inside[0]["clock"], "last_price_time": inside[-1]["clock"]}


def chart(bars: list, entry: dict, path: Path, before_only: bool, latest: dict, end: float) -> None:
    """確定足だけの入口図と、事後足を含む診断図を別々に描画する。

    引数: bars(list)は原Last足、entry(dict)は実約定、path(Path)はPNG先。
    before_only(bool)は入口前限定、latest(dict)は入口前最新原行、end(float)は管理終了。
    返り値: None。事後足を入口の既知情報として表示しない。
    """
    font = Path("C:/Windows/Fonts/meiryo.ttc")
    if font.exists():
        matplotlib.rcParams["font.family"] = FontProperties(fname=str(font)).get_name()
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(14, 7), constrained_layout=True)
    fig.patch.set_facecolor("#10151f")
    ax.set_facecolor("#151c29")
    base = bars[0]["time"]
    for index, bar in enumerate(bars):
        color = "#62cfa3" if bar["close"] >= bar["open"] else "#ed8191"
        if bar["time"] >= math.floor(end / 60) * 60:
            color = "#a5adbd"
        ax.vlines(index, bar["low"], bar["high"], color=color, linewidth=1.5)
        height = abs(bar["close"] - bar["open"])
        if height == 0:
            ax.hlines(bar["close"], index - .3, index + .3, color=color, linewidth=2.2)
        else:
            ax.add_patch(Rectangle((index - .3, min(bar["open"], bar["close"])), .6, height,
                                   facecolor=color, edgecolor=color, alpha=.86))
        if bar["label"] in ("14:55", "14:56", "14:57", "14:58", "14:59"):
            previous = bars[index-1]["close"]
            ax.annotate(f'{bar["close"]-previous:+.0f}', (index, bar["close"]), xytext=(0, 14),
                        textcoords="offset points", ha="center", color="#e4e9f2", fontsize=11)
    at = seconds(entry["at"])
    entry_x = (at-base) / 60
    ax.scatter([entry_x], [entry["price"]], marker="^", color="#f1c76d", s=90, zorder=6)
    ax.annotate(f'実新規 15:00:08\n買い5枚 63,504.7', (entry_x, entry["price"]),
                xytext=(-16, 31), textcoords="offset points", ha="right", color="#f1c76d", fontsize=11)
    x0 = (seconds("2026-10-27T14:57:00+09:00")-base)/60
    x1 = (seconds("2026-10-27T14:59:00+09:00")-base)/60
    ax.plot([x0, x1], [63480, 63480], color="#a9b9f4", linestyle="--", linewidth=1.2)
    ax.annotate("完成2分の終値差 0pt", ((x0+x1)/2, 63480), xytext=(-35, -45),
                textcoords="offset points", color="#c1cdf9", fontsize=11)
    ticks = list(range(len(bars)))
    labels = [bar["label"] for bar in bars]
    if before_only:
        ticks.append(len(bars))
        labels.append("15:00")
        ax.axvspan(len(bars)-.45, len(bars)+.8, color="#4a4d59", alpha=.25)
        ax.scatter([(latest["time"]-base)/60], [latest["last"]], color="#67c4f5", marker="o", s=34, zorder=5)
        ax.annotate("15:00足は未確定なので不使用\n青点は15:00:07の最新Lastだけ", (len(bars)+.1, 63405),
                    ha="center", color="#b9c5d8", fontsize=10)
        ax.set_xlim(-.7, len(bars)+1.35)
        title = "入口前の確定情報：14:59分までの1分足だけ"
        note = "実新規の価格は位置の照合用。15:00分の完成OHLCや後の高安は含めない。"
    else:
        off_x = (end-base)/60
        ax.axvline(off_x, color="#b894ee", linestyle=":", linewidth=1.5)
        ax.annotate("15:07:03 最後の管理状態\n返済した扱いにはしない", (off_x, 63370), ha="right", color="#cbb2ee", fontsize=10)
        ax.set_xlim(-.7, len(bars)-.25)
        title = "事後診断：14:50～15:07の原Last 1分足と実新規"
        note = "15:00以後は後から分かった経路。15:07足は管理終了同秒を除く途中値。"
    ax.set_xticks(ticks, labels, rotation=0, fontsize=10)
    ax.set_ylabel("日経ラージ Last（pt）")
    ax.grid(alpha=.15)
    ax.set_ylim(min(b["low"] for b in bars)-20, max(max(b["high"] for b in bars), entry["price"])+80)
    ax.set_title(title, loc="left", fontsize=14, pad=16)
    fig.suptitle("2026-10-27 日経mini 15:00:08 買い5枚\n"+note, fontsize=12)
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    """原Lastの足と取得済みAPI足を照合して2枚の図を保存する。

    引数: なし。返り値: None。API取得・売買再生・実約定の追加推定なし。
    """
    manifest = json.loads((DATA/"manifest.json").read_text(encoding="utf-8"))
    sha = {Path(r["path"]).name:r["sha256"] for r in manifest["files"]}
    state = json.loads((DATA/"app_state.json").read_text(encoding="utf-8"))
    snap = next(p for p in state["products"] if p["product"]=="NK225mini")["detached_snapshot"]
    entry = snap["recent_trades"][8]
    end = math.floor(seconds(snap["updated_at"]))
    start = seconds("2026-10-27T14:50:00+09:00")
    at = seconds(entry["at"])
    rows = []
    digest = hashlib.sha256()
    with (DATA/"NK225_book.jsonl").open("rb") as source:
        for line, raw in enumerate(source, 1):
            digest.update(raw)
            record = json.loads(raw)
            try:
                time = seconds(record["CurrentPriceTime"])
            except (ValueError, TypeError, KeyError):
                continue
            last = record.get("CurrentPrice")
            if start <= time < end and isinstance(last, (int,float)) and math.isfinite(last) and last > 0:
                rows.append({"time":time,"clock":record["CurrentPriceTime"],"line":line,"last":last})
    assert digest.hexdigest()==sha["NK225_book.jsonl"]
    bars = [candle(rows, minute) for minute in range(int(start),int(end),60)]
    before = [bar for bar in bars if bar["time"]+60 <= math.floor(at/60)*60]
    api = json.loads((DATA/"NK225_candles_1min.json").read_text(encoding="utf-8"))["data"]
    api_by_time = {seconds(r["time"]):r for r in api}
    for bar in bars[:-1]:
        assert all(bar[key]==api_by_time[bar["time"]][key] for key in ("open","high","low","close"))
    latest = next(r for r in reversed(rows) if r["time"] < math.floor(at))
    chart(before,entry,HERE/"15時新規直前の確定1分足156.png",True,latest,end)
    chart(bars,entry,HERE/"15時新規の事後1分足156.png",False,latest,end)
    out = {"source_sha256":sha["NK225_book.jsonl"],"entry":entry,"management_end_exclusive":snap["updated_at"],
           "same_second_management_end_excluded":end,"bars":bars,"entry_known_bars":before,"latest_price_before_entry":latest,
           "api_complete_ohlc_checks":len(bars)-1,"known_chart_has_unfinished_candle":False,"future_chart_is_diagnostic_only":True}
    (HERE/"15時新規の1分足図根拠156.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"bars":len(bars),"entry_known_bars":len(before),"api_ohlc_checks":len(bars)-1,"latest":latest},ensure_ascii=True))


if __name__=="__main__":
    main()
