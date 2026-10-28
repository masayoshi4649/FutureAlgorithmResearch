"""第三巡の保存注文・親会計・時価極値を読む具体診断。金融再生は行わない。"""

import hashlib
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = importlib.util.spec_from_file_location("saved_diagnostic1572", HERE.parent / "round2/diagnose_saved1572.py")
PRIOR = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(PRIOR)
PAIRS = [("O00", "O01"), ("O01", "O02"), ("O02", "O03"), ("O03", "O05"), ("O05", "O11"), ("O05", "O09")]
DATES = ["2026-10-20", "2026-10-21", "2026-10-26", "2026-10-27"]


def build():
    """登録済み27結果を読んで全26場差と特定場の根拠を抽出する。

    引数: なし。返り値: dict。元保存値・源・仕様を変更しない。
    """
    out = {"purpose": "第三巡保存会計からの具体診断。原板金融再生なし", "methods": {}, "pairs": {}, "scenes": {}, "examples": {}, "files": []}
    cases_by_scene = {}
    stats = defaultdict(lambda: {"net": 0, "losses": 0, "minimum": 0, "max_dd": 0, "entry_kinds": defaultdict(lambda: {"entries": 0, "quantity": 0, "net": 0}), "adverse": [], "cover_exits": defaultdict(lambda: {"orders": 0, "quantity": 0, "net": 0})})
    pairs = defaultdict(list)
    parent_pairs = defaultdict(list)
    for path in sorted((HERE / "results_go").glob("*_S01.json")):
        doc = PRIOR.read(path)
        scene = doc["scene"]["session"]
        cases = {c["config"]["id"]: c for c in doc["cases"]}
        cases_by_scene[scene] = cases
        out["files"].append({"file": str(path.relative_to(HERE)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if scene[:10] in DATES:
            out["scenes"][scene[:10]] = {id: {"realized": c["actual"]["Realized"], "unrealized": c["actual"]["Last"]["Unrealized"], "risk": c["actual"]["Risk"]} for id, c in cases.items()}
        if doc["scene"]["partial"]:
            continue
        for id, c in cases.items():
            s, a = stats[id], c["actual"]
            s["net"] += a["Realized"]
            s["losses"] += int(a["Realized"] < 0)
            s["minimum"] = min(s["minimum"], a["Risk"]["Minimum"])
            s["max_dd"] = max(s["max_dd"], a["Risk"]["MaxDD"])
            for lot in c["canonical"]["Lots"].values():
                k = s["entry_kinds"][lot["Kind"]]
                k["entries"] += 1
                k["quantity"] += lot["Quantity"]
                k["net"] += lot["Gross"]
            for event in c["canonical"]["Events"]:
                order = event["Order"]
                if order["Kind"] == "adverse" and not order["Targets"]:
                    e = PRIOR.compact_event(event)
                    e.update({"session": scene, "compared_quantity": event["ComparedQuantity"], "previous_average": event["PreviousAverage"], "new_average": event["NewAverage"], "average_improvement": event["AverageImprovement"]})
                    s["adverse"].append(e)
                if order["Kind"] == "cover" and order["Targets"]:
                    k = s["cover_exits"][order["Reason"]]
                    k["orders"] += 1
                    k["quantity"] += order["Quantity"]
                    k["net"] += event["Gross"]
        for a, b in PAIRS:
            key = a + "->" + b
            ca, cb = cases[a], cases[b]
            pairs[key].append({"session": scene, "from": ca["actual"]["Realized"], "to": cb["actual"]["Realized"], "difference": cb["actual"]["Realized"]-ca["actual"]["Realized"]})
            for parent in set(ca["actual"]["Parents"]) | set(cb["actual"]["Parents"]):
                va, vb = ca["actual"]["Parents"].get(parent, {}).get("Realized", 0), cb["actual"]["Parents"].get(parent, {}).get("Realized", 0)
                if va != vb:
                    parent_pairs[key].append({"session": scene, "parent": parent, "from": va, "to": vb, "difference": vb-va, "initial_from": PRIOR.initial(ca, parent), "initial_to": PRIOR.initial(cb, parent)})
    selected = {("2026-10-20_Day", "core/1"), ("2026-10-20_Day", "episode/0"), ("2026-10-20_Day", "addon/1"),
                ("2026-10-21_Day", "core/1"), ("2026-10-21_Day", "core/4"), ("2026-10-26_Day", "addon/0"), ("2026-10-27_Day", "core/6")}
    for key, rows in pairs.items():
        rows.sort(key=lambda x: x["difference"])
        parents = sorted(parent_pairs[key], key=lambda x: x["difference"])
        out["pairs"][key] = {"difference": sum(r["difference"] for r in rows), "worst_three_scenes": rows[:3], "best_three_scenes": rows[-3:], "worst_three_parents": parents[:3], "best_three_parents": parents[-3:]}
        selected.update((p["session"], p["parent"]) for p in parents[:2] + parents[-1:])
        for row in rows[:1]:
            scene = row["session"]
            out["scenes"][scene[:10]] = {id: {"realized": c["actual"]["Realized"], "unrealized": c["actual"]["Last"]["Unrealized"], "risk": c["actual"]["Risk"]} for id, c in cases_by_scene[scene].items()}
    for scene, parent in sorted(selected):
        out["examples"][scene + "/" + parent] = {}
        for id, c in cases_by_scene[scene].items():
            out["examples"][scene + "/" + parent][id] = {"initial": PRIOR.initial(c, parent), "actual_parent": c["actual"]["Parents"].get(parent),
                "canonical_events": [PRIOR.compact_event(e) for e in c["canonical"]["Events"] if e["Order"]["Parent"] == parent],
                "actual_events": [PRIOR.compact_event(e) for e in c["actual"]["Events"] if e["Order"]["Parent"] == parent]}
    for id, s in stats.items():
        rows = s["adverse"]
        known = [e for e in rows if e["compared_quantity"] > 0]
        s["adverse_summary"] = {"entries": len(rows), "comparable": len(known), "better": sum(e["average_improvement"]>1e-8 for e in known), "same": sum(abs(e["average_improvement"])<=1e-8 for e in known), "worse": sum(e["average_improvement"]<-1e-8 for e in known), "basis": "Canonicalの同親元方向残玉の約定直前加重平均。純量実帳簿の平均建値とは別"}
    out["methods"] = dict(stats)
    return out


def draw(data):
    """4日の確定収支と最悪時価を暗色の比較図へ描く。

    引数: data(dict)。返り値: なし。図に使う値は保存された会計だけ。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import TwoSlopeNorm
    plt.rcParams["font.family"] = "Yu Gothic"
    ids = ["O00", "O01", "O02", "O03", "O05", "O09", "O11"]
    fig, axs = plt.subplots(2, 1, figsize=(14, 8), facecolor="#111722")
    for ax, title, metric in zip(axs, ["保存時点の確定収支（万円）", "全残玉を含む場内最小時価（万円）"], ["realized", "minimum"]):
        values = np.array([[data["scenes"][d][i]["realized"] if metric=="realized" else data["scenes"][d][i]["risk"]["Minimum"] for i in ids] for d in DATES])/10000
        ax.imshow(values, cmap="RdYlGn", norm=TwoSlopeNorm(vmin=-40, vcenter=0, vmax=40), aspect="auto")
        ax.set_title(title, color="#e8eef6", fontsize=13, pad=11)
        ax.set_xticks(range(len(ids)), ids, color="#e8eef6")
        ax.set_yticks(range(4), ["10/20", "10/21", "10/26", "10/27 15:20未満"], color="#e8eef6")
        for y in range(4):
            for x in range(len(ids)):
                ax.text(x,y,f"{values[y,x]:+.2f}",ha="center",va="center",fontsize=11,color="#10151c")
    fig.suptitle("旧出口のまま追加・カバー・逆玉回収を分離：4日比較", color="#f2f4f8", fontsize=16)
    fig.text(.06,.02,"O00=旧出口支持量 / O01=順行追加 / O02=カバー / O03=逆玉追尾 / O05=逆行回復 / O09=場赤字抑制 / O11=支持崩壊",color="#c4cedc",fontsize=10)
    fig.tight_layout(rect=(0,.045,1,.95))
    fig.savefig(HERE/"第三巡の4日間の収支と場内最低.png",dpi=150,facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    result = build()
    (HERE/"第三巡の数量管理と逆玉回収の具体診断1573.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    draw(result)
