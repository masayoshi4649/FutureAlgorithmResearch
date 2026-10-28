"""閾値緩和で変わった具体的な売買を、保存約定と価格図で説明する。"""

import argparse
import json
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))


def stamp(value):
    """保存時刻を日本時間の秒まで表示する。

    引数: value(float)はUNIX秒。返り値: strは時刻。
    """
    return datetime.fromtimestamp(value, JST).strftime("%H:%M:%S")


def orders(case, end):
    """前半の全約定を方向・枚数・価格・返済損益付きで列挙する。

    引数: case(dict)は保存約定、end(float)は米国開始。
    返り値: list[str]はMarkdown表。金融経路を変更しない。
    """
    result = ["|判断|約定|担当|売買|枚数|価格|返済損益円|理由|", "|---|---|---|---|---:|---:|---:|---|"]
    for e in case["events"] or []:
        s, f = e["signal"], e["fill"]
        if f["Time"] >= end:
            continue
        action = ("新規" if s["action"] == "new" else "返済") + ("買い" if s["side"] == 1 else "売り")
        result.append(f"|{stamp(s['time'])}|{stamp(f['Time'])}|{s['owner']}|{action}|{f['Quantity']}|{f['Price']:,.0f}|{e['gross']:+,.0f}|{s['reason']}|")
    return result


def main():
    """指定した緩和案の改善・悪化例を同じ手順で選び、当時の約定を図示する。

    引数: --method(str)は既検証ID、標準A15。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", default="A15")
    method_id = parser.parse_args().method
    report = json.loads((HERE / "report150.json").read_text(encoding="utf-8"))
    methods = {m["id"]: m for m in report["methods"]}
    method = methods[method_id]
    baseline = {r["session"]: r for r in methods["A00"]["rows"]}
    ordered = sorted(method["rows"], key=lambda r: r["pre"]["net"] - baseline[r["session"]]["pre"]["net"])
    selected = ordered[:2] + list(reversed(ordered[-2:]))
    plt.rcParams.update({"font.family": "Yu Gothic", "font.size": 10, "axes.unicode_minus": False})
    figure, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True, facecolor="#111923")
    lines = [f"# {method_id}の入口が増えた所・減った所", "", method["description"], "",
             "A00との差が悪い2夜・良い2夜を同じ規則で抽出した事後診断。極値や事後の損益は売買入力に使っていない。日経mini・片方向上限10枚・手数料0。表の返済損益は部分返済ごと、集計の利益損失は親取引合計。", ""]
    for ax, row in zip(axes, selected):
        session = row["session"]
        saved = json.loads((HERE / "results_go" / f"{session}.json").read_text(encoding="utf-8"))
        scene = saved["scene"]
        cases = {c["config"]["id"]: c for c in saved["cases"]}
        if method_id.startswith("B"):
            additional = json.loads((HERE / "results_round2" / f"{session}.json").read_text(encoding="utf-8"))
            cases.update({c["config"]["id"]: c for c in additional["cases"]})
        packet = pickle.loads((ROOT / "work/preus148/inputs" / f"{session}.pkl").read_bytes())
        data = packet["data"]
        times, q = data["ready"]["time_s"], data["quotes"]
        mid = (q["bid"] + q["ask"]) / 2
        start, end = scene["start"], scene["us_open"] - 900
        ids = np.flatnonzero(q["quote_valid"] & (times >= start) & (times < end))
        buckets = ((times[ids] - start) // 60).astype(int)
        terminal = ids[np.r_[buckets[1:] != buckets[:-1], True]]
        minutes = np.full(int((end - start) / 60), np.nan)
        minutes[((times[terminal] - start) // 60).astype(int)] = mid[terminal]
        origin = mid[ids[0]]
        ax.set_facecolor("#111923")
        ax.plot(np.arange(len(minutes)) / 60, minutes - origin, color="#d8e3ef", lw=1)
        for identifier, size, fill in (("A00", 65, False), (method_id, 30, True)):
            for side, color, marker in ((1, "#60bafa", "^"), (-1, "#ffa76b", "v")):
                events = [e for e in cases[identifier]["events"] or [] if e["signal"]["action"] == "new" and e["signal"]["side"] == side and e["fill"]["Time"] < end]
                ax.scatter([(e["fill"]["Time"] - start) / 3600 for e in events], [e["fill"]["Price"] - origin for e in events],
                           s=size, marker=marker, facecolors=color if fill else "none", edgecolors=color,
                           label=identifier + (" 買い" if side == 1 else " 売り"), zorder=3)
        diff = row["pre"]["net"] - baseline[session]["pre"]["net"]
        title = f"{session.replace('_Night', ' ナイト')}  前半A00 {baseline[session]['pre']['net']:+,.0f}円 → {method_id} {row['pre']['net']:+,.0f}円（差{diff:+,.0f}円）"
        ax.set_title(title, color="#d8e3ef", loc="left")
        ax.tick_params(colors="#d8e3ef")
        ax.grid(color="#2a394b", alpha=.7)
        ax.set_ylabel("開始中値比(pt)", color="#d8e3ef")
        for spine in ax.spines.values():
            spine.set_color("#526277")
        lines += ["## " + title, ""]
        for identifier in ("A00", method_id):
            lines += [f"### {identifier}", ""] + orders(cases[identifier], scene["us_open"]) + [""]
    axes[0].legend(facecolor="#111923", labelcolor="#d8e3ef", ncol=4, loc="upper left")
    axes[-1].set_xticks(np.arange(0, 5.5, .5), [f"{17 + int(v):02}:{30 if v % 1 else 0:02}" for v in np.arange(0, 5.5, .5)])
    axes[-1].set_xlabel("日本時間（原板から分末正常中値。空分を補間しない）", color="#d8e3ef")
    figure.tight_layout()
    figure.savefig(HERE / f"{method_id}_前半の入口比較.png", dpi=140, facecolor=figure.get_facecolor())
    plt.close(figure)
    lines.insert(6, f"![入口の比較]({method_id}_前半の入口比較.png)")
    (HERE / f"{method_id}_具体的な売買比較.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print([(r["session"], r["pre"]["net"] - baseline[r["session"]]["pre"]["net"]) for r in selected])


if __name__ == "__main__":
    main()
