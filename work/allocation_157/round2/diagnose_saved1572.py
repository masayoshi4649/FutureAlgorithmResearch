"""第二巡の保存約定だけから数量・出口の具体差を読み取る。金融再生はしない。"""

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=9))
IDS = ["C00", "K01", "J02", "J15", "J05", "J07", "J08", "J10", "J12"]
DATES = ["2026-10-20", "2026-10-21", "2026-10-26", "2026-10-27"]
PAIRS = [("K01", "J02"), ("J02", "J15"), ("J02", "J05"), ("J05", "J07"), ("J07", "J08"), ("J08", "J10"), ("J10", "J12")]


def read(path):
    """UTF-8の保存JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clock(at):
    """保存Unix秒を日本時間で示す。

    引数: at(float)。返り値: str。
    """
    return datetime.fromtimestamp(at, TZ).strftime("%H:%M:%S")


def compact_event(event):
    """約定と判断原行を会計変更なしで小型化する。

    引数: event(dict)。返り値: dict。
    """
    o = event["Order"]
    return {"decision_time": clock(o["DecisionTime"]), "fill_time": clock(event["FillTime"]),
            "decision_index": o["DecisionIndex"], "fill_index": event["FillIndex"],
            "parent": o["Parent"], "kind": o["Kind"], "reason": o["Reason"],
            "action": "close" if o["Targets"] else "new", "side": o["Side"],
            "quantity": o["Quantity"], "price": event["Price"], "gross": event["Gross"],
            "targets": o["Targets"], "hold_id": event["HoldID"],
            "support": {k: o["Support"].get(k) for k in ("Known", "M", "T", "Opp", "Own5", "Own15", "Own120", "Own300")}}


def initial(case, key):
    """親の最初の実新規から当時の量・支持を取得する。

    引数: case(dict)、key(str)。返り値: dict又はNone。
    """
    return next((compact_event(e) for e in case["canonical"]["Events"] if e["Order"]["Parent"] == key and not e["Order"]["Targets"]), None)


def build():
    """26完了場と途中場の保存会計から必要な比較だけを抽出する。

    引数: なし。返り値: dict。原板・売買エンジンは呼ばない。
    """
    report = read(HERE / "report1572.json")
    methods = {m["id"]: m for m in report["methods"]}
    out = {"purpose": "登録済み第二巡の保存約定だけの具体診断、金融再生なし", "methods": {i: methods[i]["summary"] for i in IDS},
           "source_report_sha256": hashlib.sha256((HERE / "report1572.json").read_bytes()).hexdigest(),
           "scenes": {}, "paired_parents": {}, "canonical_kinds": {}, "examples": {}, "files": []}
    deltas = defaultdict(list)
    kinds = defaultdict(lambda: defaultdict(lambda: {"entries": 0, "quantity": 0, "net": 0}))
    picks = {("2026-10-21", "core/1"): ["K01", "J02", "J15"], ("2026-10-21", "core/4"): ["J02", "J05", "J07"],
             ("2026-10-20", "core/1"): ["J02", "J07", "J08"], ("2026-10-26", "addon/0"): ["K01", "J02", "J15", "J05", "J07", "J08", "J10"],
             ("2026-10-27", "core/6"): ["C00", "K01", "J02", "J15", "J05", "J07", "J08", "J10"],
             ("2026-10-23", "episode/8"): ["J10", "J12"]}
    for path in sorted((HERE / "results_go").glob("*_S01.json")):
        doc = read(path)
        date = doc["scene"]["session"].split("_")[0]
        cases = {c["config"]["id"]: c for c in doc["cases"]}
        out["files"].append({"file": str(path.relative_to(HERE)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if not doc["scene"]["partial"]:
            for id in IDS:
                for lot in cases[id]["canonical"]["Lots"].values():
                    k = kinds[id][lot["Kind"]]
                    k["entries"] += 1
                    k["quantity"] += lot["Quantity"]
                    k["net"] += lot["Gross"]
            for a, b in PAIRS:
                ca, cb = cases[a], cases[b]
                for key in sorted(set(ca["parents"]) | set(cb["parents"])):
                    pa = ca["actual"]["Parents"].get(key, {}).get("Realized", 0)
                    pb = cb["actual"]["Parents"].get(key, {}).get("Realized", 0)
                    if pa != pb:
                        deltas[f"{a}->{b}"].append({"session": doc["scene"]["session"], "parent": key, "from": pa, "to": pb,
                                                    "difference": pb-pa, "initial_from": initial(ca, key), "initial_to": initial(cb, key)})
        if date in DATES:
            out["scenes"][date] = {}
            for id in IDS:
                c, l = cases[id], cases[id]["actual"]
                out["scenes"][date][id] = {"realized": l["Realized"], "unrealized": l["Last"]["Unrealized"], "risk": l["Risk"],
                    "parents": {key: {"realized": l["Parents"].get(key, {}).get("Realized", 0), "initial": initial(c, key)} for key in c["parents"]}}
        for (pick_date, key), selected in picks.items():
            if date != pick_date:
                continue
            out["examples"][f"{date}/{key}"] = {}
            for id in selected:
                c = cases[id]
                out["examples"][f"{date}/{key}"][id] = {"initial": initial(c, key), "actual_parent": c["actual"]["Parents"].get(key),
                    "canonical_events": [compact_event(e) for e in c["canonical"]["Events"] if e["Order"]["Parent"] == key],
                    "actual_events": [compact_event(e) for e in c["actual"]["Events"] if e["Order"]["Parent"] == key]}
    for pair, rows in deltas.items():
        rows.sort(key=lambda x: x["difference"])
        out["paired_parents"][pair] = {"delta": sum(x["difference"] for x in rows), "improved": sum(x["difference"]>0 for x in rows),
            "worsened": sum(x["difference"]<0 for x in rows), "worst_three": rows[:3], "best_three": rows[-3:]}
    out["canonical_kinds"] = {id: dict(v) for id, v in kinds.items()}
    return out


def draw(data):
    """4日の保存終端収支と最小時価を暗色の比較図へ描く。

    引数: data(dict)。返り値: なし。未保存の場内価格線は創作しない。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import TwoSlopeNorm
    plt.rcParams["font.family"] = "Yu Gothic"
    ids = IDS[:-1]
    fig, axs = plt.subplots(2, 1, figsize=(14, 8), facecolor="#111722")
    for ax, title, metric in zip(axs, ["保存時点の確定収支（万円）", "全残玉を含む場内最小時価（万円）"], ["realized", "minimum"]):
        values = np.array([[data["scenes"][d][i]["realized"] if metric=="realized" else data["scenes"][d][i]["risk"]["Minimum"] for i in ids] for d in DATES])/10000
        ax.imshow(values, cmap="RdYlGn", norm=TwoSlopeNorm(vmin=-32, vcenter=0, vmax=32), aspect="auto")
        ax.set_title(title, color="#e8eef6", fontsize=13, pad=11)
        ax.set_xticks(range(len(ids)), ids, color="#e8eef6")
        ax.set_yticks(range(4), ["10/20", "10/21", "10/26", "10/27 15:20未満"], color="#e8eef6")
        for y in range(4):
            for x in range(len(ids)):
                ax.text(x,y,f"{values[y,x]:+.2f}",ha="center",va="center",fontsize=11,color="#10151c")
    fig.suptitle("支持の初回量と新出口・追加は別の差：保存約定での4日比較", color="#f2f4f8", fontsize=16)
    fig.text(.05,.02,"C00=旧S01 / K01=初回10micro固定 / J02=線形支持 / J15=二乗支持 / J05=新出口 / J07=順行追加 / J08=カバー / J10=逆行回復追加",color="#c4cedc",fontsize=10)
    fig.tight_layout(rect=(0,.045,1,.95))
    fig.savefig(HERE/"第二巡の4日間の収支と場内最低.png",dpi=150,facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    result = build()
    (HERE/"第二巡の数量政策の具体診断1572.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    draw(result)
