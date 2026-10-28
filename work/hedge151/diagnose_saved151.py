"""登録済み保存約定・時価だけを再集計し、原因図と根拠JSONを作る。原板・金融再生は呼ばない。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def load_results():
    """完了した26場の保存結果を読む。

    引数: なし。返り値: dictは場名ごとの保存会計。未完成なら停止する。
    """
    files = sorted((HERE / "results_go").glob("*.json"))
    assert len(files) == 26
    result = {}
    for path in files:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert len(value["cases"]) == 18
        result[value["scene"]["session"]] = value
    return result


def select(value, identifier):
    """指定条件を保存会計から取り出す。

    引数: value(dict)、identifier(str)。返り値: dictは指定条件。
    """
    return next(case for case in value["cases"] if case["config"]["id"] == identifier)


def equity_positions(case, snapshot):
    """保存時価の原行までの約定から保有玉を独立再構築する。

    引数: case(dict)、snapshot(dict)。返り値: list[dict]は当時の残玉と気配評価。
    """
    positions = {}
    realized = 0
    for event in case["events"]:
        if event["fill_index"] > snapshot["index"]:
            continue
        order = event["order"]
        if order["action"] == "new":
            positions[order["lot_id"]] = {"id": order["lot_id"], "side": order["side"], "quantity": order["quantity"], "entry_price": event["price"], "entry_time": event["fill_time"]}
        else:
            assert positions.pop(order["lot_id"])["quantity"] == order["quantity"]
            realized += event["gross"]
    unrealized = 0
    for item in positions.values():
        mark = snapshot["bid"] if item["side"] > 0 else snapshot["ask"]
        item["unrealized"] = item["side"] * item["quantity"] * (mark-item["entry_price"]) * 100
        unrealized += item["unrealized"]
    assert realized == snapshot["realized"]
    assert unrealized == snapshot["unrealized"]
    assert realized + unrealized == snapshot["equity"]
    return list(positions.values())


def case_details(case):
    """利確、境界、再参加、最悪時価を保存会計から分解する。

    引数: case(dict)。返り値: dictは担当別でなく実玉に基づく具体根拠。
    """
    by_reason = defaultdict(float)
    for event in case["events"]:
        if event["order"]["action"] == "close":
            by_reason[event["order"]["reason"]] += event["gross"]
    result = {key: case[key] for key in ("gross", "profit", "loss", "minimum_equity", "minimum_unrealized", "maximum_drawdown", "max_long", "max_short", "long_cap_seconds", "short_cap_seconds", "hedged_seconds", "reentry_new_count", "reentry_cap_wait_rows")}
    result["exit_net"] = dict(by_reason)
    result["worst_lots"] = sorted(case["lots"], key=lambda item: item["gross"])[:5]
    result["best_lots"] = sorted(case["lots"], key=lambda item: item["gross"], reverse=True)[:5]
    result["source_rejections"] = [item for item in case["decisions"] if item["rejected"]]
    for key in ("minimum_equity_at", "minimum_unrealized_at"):
        snapshot = case[key]
        result[key] = snapshot
        result[key + "_positions"] = equity_positions(case, snapshot) if snapshot["time"] else []
    result["events"] = case["events"]
    return result


def plot_data(case, end):
    """保存した時価点だけを時系列へ並べる。

    引数: case(dict)、end(float)。返り値: list[dict]は当該時間までの時価。原板補間はしない。
    """
    by_index = {s["index"]: s for s in case["snapshots"] if s["time"] <= end}
    for key in ("minimum_equity_at", "minimum_unrealized_at", "maximum_drawdown_at"):
        s = case[key]
        if s["time"] and s["time"] <= end:
            by_index[s["index"]] = s
    return sorted(by_index.values(), key=lambda item: item["index"])


def chart(results, choices, title, filename):
    """価格、両方向枚数、確定と含みを暗色図として保存する。

    引数: results(dict)、choices(list[tuple])、title/filename(str)。返り値: None。
    """
    plt.rcParams.update({"font.family": "Yu Gothic", "axes.unicode_minus": False, "font.size": 10, "figure.facecolor": "#0d1320", "axes.facecolor": "#131d2c", "text.color": "#e5edf8", "axes.labelcolor": "#e5edf8", "xtick.color": "#b9c9df", "ytick.color": "#b9c9df", "axes.edgecolor": "#42516a", "grid.color": "#334159", "legend.facecolor": "#18263a", "legend.edgecolor": "#42516a"})
    fig, axes = plt.subplots(3, 2, figsize=(17, 11), sharex="col", gridspec_kw={"height_ratios": [1.3, 0.75, 1.35]})
    fig.suptitle(title, fontsize=16, y=0.985)
    for column, (session, identifier, baseline, subtitle) in enumerate(choices):
        value = results[session]
        case, base = select(value, identifier), select(value, baseline)
        end = case["scheduled_close"] + 120 if case["config"]["scope"] == "pre" else value["scene"]["end"]
        points = plot_data(case, end)
        times = [datetime.fromtimestamp(s["time"], JST) for s in points]
        axes[0, column].plot(times, [(s["bid"]+s["ask"])/2 for s in points], color="#e7c765", linewidth=1.1, label="保存気配の中値")
        for side, marker, color, label in [(1, "^", "#58d6a3", "買い新規"), (-1, "v", "#ff8b92", "売り新規")]:
            events = [e for e in case["events"] if e["order"]["action"] == "new" and e["order"]["side"] == side and e["fill_time"] <= end]
            axes[0, column].scatter([datetime.fromtimestamp(e["fill_time"], JST) for e in events], [e["price"] for e in events], marker=marker, s=22, color=color, label=label, zorder=3)
        axes[0, column].set_title(subtitle + f"\n{session[:10]}  {identifier} {case['gross']:+,.0f}円 ／ {baseline} {base['gross']:+,.0f}円", fontsize=11)
        axes[0, column].set_ylabel("日経価格（pt）")
        axes[0, column].legend(loc="best", fontsize=8)
        axes[1, column].step(times, [s["long"] for s in points], where="post", color="#58d6a3", label="買い枚数")
        axes[1, column].step(times, [-s["short"] for s in points], where="post", color="#ff8b92", label="売り枚数（下向き）")
        axes[1, column].axhline(0, color="#7b8da7", linewidth=0.7)
        axes[1, column].set_ylim(-11, 11)
        axes[1, column].set_yticks([-10, -5, 0, 5, 10])
        axes[1, column].set_ylabel("同時保有枚数")
        axes[1, column].legend(loc="best", fontsize=8)
        for key, color, label in [("realized", "#72b9ff", "確定収支"), ("unrealized", "#ff8b92", "残玉の含み"), ("equity", "#58d6a3", "合計時価")]:
            axes[2, column].plot(times, [s[key]/10000 for s in points], color=color, label=label, linewidth=1.6 if key == "equity" else 1)
        base_points = plot_data(base, end)
        axes[2, column].plot([datetime.fromtimestamp(s["time"], JST) for s in base_points], [s["equity"]/10000 for s in base_points], color="#c2cbda", linestyle="--", linewidth=1, label=f"{baseline} 合計時価")
        axes[2, column].axhline(0, color="#7b8da7", linewidth=0.7)
        axes[2, column].set_ylabel("損益（万円）")
        axes[2, column].legend(loc="best", fontsize=8, ncol=2)
        axes[2, column].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
        axes[2, column].xaxis.set_major_locator(mdates.HourLocator(interval=2 if end-value["scene"]["start"] > 7*3600 else 1, tz=JST))
        axes[2, column].set_xlabel("日本時間（0時以後は翌日）")
        for row in range(3):
            axes[row, column].grid(alpha=0.5)
    fig.text(0.5, 0.012, "NK225mini・片側上限10枚・手数料0。保存時価（原則1分＋約定・極値）だけを図示。P群は米国前だけ。価格線は分足ではありません。", ha="center", fontsize=9, color="#b9c9df")
    fig.tight_layout(rect=[0, 0.035, 1, 0.955])
    fig.savefig(HERE/filename, dpi=145, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    """完了保存結果から固定比較の診断資料を作る。

    引数: なし。返り値: None。新条件の金融再生はしない。
    """
    results = load_results()
    comparisons = {}
    for base, changed in [("P02", "P10"), ("N02", "N06")]:
        rows = []
        for session, value in results.items():
            if value["scene"]["partial"]:
                continue
            a, b = select(value, base), select(value, changed)
            rows.append({"session": session, "base": a["gross"], "changed": b["gross"], "delta": b["gross"]-a["gross"]})
        comparisons[base+"_"+changed] = sorted(rows, key=lambda item: item["delta"])
    details = {}
    for day in ["2026-09-30", "2026-10-19", "2026-10-01", "2026-10-16", "2026-10-20", "2026-10-07", "2026-10-21", "2026-10-13"]:
        session = day+"_Night"
        details[session] = {identifier: case_details(select(results[session], identifier)) for identifier in ["P02", "P05", "P10", "N02", "N03", "N06"]}
    sources = []
    for path in sorted((HERE/"results_go").glob("*.json")):
        raw = path.read_bytes()
        sources.append({"path":str(path.relative_to(HERE)), "sha256":hashlib.sha256(raw).hexdigest()})
    (HERE/"engine_保存会計の具体診断151.json").write_text(json.dumps({"source_fingerprints":sources, "comparisons":comparisons, "details":details}, ensure_ascii=False, indent=2), encoding="utf-8")
    chart(results, [("2026-09-30_Night", "N06", "N02", "回転利益が残負け玉を補えなかった夜"), ("2026-10-16_Night", "N06", "N02", "下落への再参加が残負け玉を上回った夜")], "再参加の効果は、確定利益と残玉の含みを足して判断する", "再参加_損失と改善151.png")
    chart(results, [("2026-10-21_Night", "P05", "P02", "40pt開始で回収でき、80pt開始では残った売玉"), ("2026-10-20_Night", "N03", "N02", "160pt開始に届かない売玉が夜末まで残った")], "利益追尾を始める値幅で、同じ入口の結果が変わる", "同一入口_利益開始幅の比較151.png")
    print("保存会計の具体根拠JSON・暗色図2枚を保存。金融再生なし。")


if __name__ == "__main__":
    main()
