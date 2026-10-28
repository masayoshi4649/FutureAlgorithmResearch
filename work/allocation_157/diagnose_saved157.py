"""00157の保存結果だけから数量政策の具体原因を抽出する。新しい売買は生成しない。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json

BASE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def clock(value: float) -> str:
    """UNIX秒を日本時間の秒表示にする。

    引数: value(float)。返り値: str。
    """
    return datetime.fromtimestamp(value, JST).strftime("%H:%M:%S")


def event_view(event: dict) -> dict:
    """保存約定を判断と約定の原行を残した簡潔な表へ変換する。

    引数: event(dict)。返り値: dict。数量はmicro単位。
    """
    o = event["Order"]
    return {"parent": o["Parent"], "owner": o["Owner"], "kind": o["Kind"],
            "action": "返済" if o["Targets"] else "新規", "side": o["Side"],
            "quantity_micro": o["Quantity"], "decision_at": clock(o["DecisionTime"]),
            "fill_at": clock(event["FillTime"]), "decision_index": o["DecisionIndex"],
            "fill_index": event["FillIndex"], "price": event["Price"], "gross": event["Gross"],
            "reason": o["Reason"], "support": o["Support"],
            "average_improvement": event["AverageImprovement"],
            "compared_quantity": event["ComparedQuantity"], "pieces": event["Pieces"]}


def main() -> None:
    """完了場と途中を分離し、親対応・数量種別・観測不足を記録する。

    引数: なし。返り値: None。入力ファイルを変更しない。
    """
    files = sorted((BASE / "results_go").glob("*.json"))
    totals, datasets, fingerprints = defaultdict(Counter), {}, []
    parent_differences = defaultdict(list)
    pairs = [("C00", "C01"), ("C00", "B00"), ("B00", "B01"), ("C01", "C02"),
             ("C02", "Q01"), ("Q01", "Q03"), ("Q03", "Q05"), ("Q05", "Q07"),
             ("Q07", "Q08"), ("Q05", "H05"), ("Q05", "D05")]
    selected = []
    for path in files:
        raw = path.read_bytes()
        data = json.loads(raw)
        session = data["scene"]["session"]
        cases = {case["config"]["id"]: case for case in data["cases"]}
        datasets[session] = cases
        fingerprints.append({"file": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        if data["scene"]["partial"]:
            continue
        for key, case in cases.items():
            a, c = case["actual"], case["canonical"]
            z = totals[key]
            assert abs(sum(e["Gross"] for e in a.get("Events") or []) - a["Realized"]) < 1e-6
            z["net"] += a["Realized"]
            z["red_sessions"] += a["Realized"] < 0
            z["inactive_sessions"] += not bool(a.get("Events"))
            z["min_equity"] = min(z["min_equity"], a["Risk"]["Minimum"])
            z["maximum_dd"] = max(z["maximum_dd"], a["Risk"]["MaxDD"])
            for event in c.get("Events") or []:
                if not event["Order"]["Targets"]:
                    z["entries:" + event["Order"]["Kind"]] += 1
            if key == "B00" and a.get("Events"):
                selected.append({"session": session, "B00": a["Realized"],
                                 "B01": cases["B01"]["actual"]["Realized"],
                                 "C02": cases["C02"]["actual"]["Realized"],
                                 "Q01": cases["Q01"]["actual"]["Realized"],
                                 "Q03": cases["Q03"]["actual"]["Realized"],
                                 "Q05": cases["Q05"]["actual"]["Realized"],
                                 "Q07": cases["Q07"]["actual"]["Realized"]})
        for before, after in pairs:
            a, b = cases[before]["actual"]["Parents"], cases[after]["actual"]["Parents"]
            for key in set(a) | set(b):
                x, y = a.get(key, {}).get("Realized", 0), b.get(key, {}).get("Realized", 0)
                if x != y:
                    parent_differences[before + "→" + after].append(
                        {"session": session, "parent": key, "before": x, "after": y, "delta": y-x})
    summary = {}
    for key, rows in parent_differences.items():
        rows.sort(key=lambda x: x["delta"])
        summary[key] = {"difference": sum(x["delta"] for x in rows),
                        "improved_parents": sum(x["delta"] > 0 for x in rows),
                        "worsened_parents": sum(x["delta"] < 0 for x in rows),
                        "avoided_or_added_profit": sum(max(x["delta"], 0) for x in rows),
                        "lost_or_added_loss": sum(max(-x["delta"], 0) for x in rows),
                        "worst_three": rows[:3], "best_three": rows[-3:]}
    focus = {}
    selections = {"2026-10-20_Day": ["C00", "C01", "B01"],
                  "2026-10-21_Day": ["C00", "C01", "B01"],
                  "2026-10-27_Day": ["C00", "C01", "B01"],
                  "2026-10-26_Day": ["B00", "B01", "Q01", "Q03", "Q07"],
                  "2026-10-13_Day": ["B01", "Q05", "Q07"],
                  "2026-10-15_Day": ["Q03", "Q05"]}
    for session, ids in selections.items():
        focus[session] = {}
        for key in ids:
            case = datasets[session][key]
            focus[session][key] = {"actual_net": case["actual"]["Realized"],
                                  "actual_risk": case["actual"]["Risk"],
                                  "canonical_events": [event_view(e) for e in case["canonical"].get("Events") or []],
                                  "actual_events": [event_view(e) for e in case["actual"].get("Events") or []],
                                  "canonical_lots": case["canonical"]["Lots"]}
    diagnosis = json.loads((BASE / "支持未知の原行診断157.json").read_text(encoding="utf-8"))
    completed = [r for r in diagnosis["Rows"] if r["Session"] != "2026-10-27_Day"]
    out = {"financial_replay": False, "complete_sessions": 26, "partial_sessions": 1,
           "units": "micro、10円/pt、片側100micro。元mini10と同額。",
           "totals": totals, "pair_decomposition": summary, "parent_differences": parent_differences,
           "selected_four": selected, "focus": focus,
           "unknown_first_cause_completed": Counter(r["Reason"] for r in completed),
           "source_initial_count": len(completed),
           "known_value_mismatch": diagnosis["ValueMismatch"],
           "proportional_controls": [{"factor": f, "net": totals["C00"]["net"]*f,
                                      "red_sessions": totals["C00"]["red_sessions"],
                                      "min_equity": totals["C00"]["min_equity"]*f,
                                      "maximum_dd": totals["C00"]["maximum_dd"]*f,
                                      "scope": "保存会計の算術比較。整数発注の新成績ではない"} for f in [.5, .2]],
           "zero_effect_factors": ["逆行40/60pt：発火0", "逆行累計25→50：対象追加0", "D場内抑制：開始比−8万円へ到達せず発火0"],
           "result_fingerprints": fingerprints}
    (BASE / "具体的な数量政策と原行診断157.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    # ----------------------------------------
    # 観測不足と同じ4親の比較だけを描き、未知の全板軌跡を補間して作らない。
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Meiryo"
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), facecolor="#101722")
    for ax in axes:
        ax.set_facecolor("#101722")
        ax.tick_params(colors="#dce5f1")
        for spine in ax.spines.values(): spine.set_color("#536176")
        ax.title.set_color("#eef4ff")
    axes[0].barh(["短期窓端の2秒制限", "途中の異常/15秒超空白", "現在OFI不成立", "支持計算できた"], [83,54,8,10], color=["#ee9b55","#cb7278","#ad90c8","#68b7aa"])
    axes[0].invert_yaxis()
    axes[0].set_title("初回155親：採否より前の観測条件")
    for i,v in enumerate([83,54,8,10]): axes[0].text(v+.7,i,str(v),color="#eef4ff",va="center")
    axes[0].set_xlim(0,100)
    labels=["旧出口\n旧数量 B00","旧出口\n支持数量 B01","新出口\n旧数量 C02","新出口\n支持数量 Q01","＋順行追加\nQ03","＋カバー\nQ05"]
    values=[totals[x]["net"]/10000 for x in ["B00","B01","C02","Q01","Q03","Q05"]]
    axes[1].bar(range(len(values)),values,color=["#68b7aa"if x>=0 else"#d3797b"for x in values])
    axes[1].set_xticks(range(len(values)),labels,fontsize=9)
    axes[1].axhline(0,color="#acb9c9",lw=.8)
    axes[1].set_title("採用4親だけの合計収支（万円）")
    for i,v in enumerate(values):axes[1].text(i,v+(1 if v>=0 else-1),f"{v:+.2f}",ha="center",va="bottom"if v>=0 else"top",color="#eef4ff",fontsize=9)
    axes[1].set_ylim(-17,48)
    fig.text(.5,.02,"26完了日中・費用0。残り22場は支持選抜群で無取引。黒字4場だけを安定性の証拠にしない。",color="#b7c5d8",ha="center",fontsize=10)
    fig.tight_layout(rect=(0,.05,1,1))
    fig.savefig(BASE/"支持の観測不足と出口差157.png",dpi=150,facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
