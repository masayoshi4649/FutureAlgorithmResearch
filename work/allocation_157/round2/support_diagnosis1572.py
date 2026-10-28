"""当時の未校正支持と、変更前S01の同じ親の保存損益を比較する。"""

from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import math
import random
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyze157 import read, save

HERE = Path(__file__).resolve().parent
FIRST = HERE.parent
FIRST_SHA = "2eaed2a7759a9763abbc69c1c331f6d7c86c708c7fe4b57d6214d61a7b837b26"
BINS = [0, .1, .25, .5, .75, 1]
METRICS = ["baseline_net", "points_per_initial_micro", "points_per_all_new_micro"]


def ranks(values: list[float]) -> list[float]:
    """同順位を平均順位にして順位列を返す。

    引数: values(list[float])は有限数値。返り値: list[float]は1始まりの順位。
    """
    result = [0.] * len(values)
    order = sorted(range(len(values)), key=values.__getitem__)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        for index in order[i:j]:
            result[index] = (i + 1 + j) / 2
        i = j
    return result


def correlation(x: list[float], y: list[float]) -> float | None:
    """同順位を処理したSpearman相関を算出する。

    引数: x/y(list[float])は同数の観測。返り値: float又はNone。3親未満・定数列は未算出。
    """
    assert len(x) == len(y)
    if len(x) < 3:
        return None
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    covariance = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    denominator = math.sqrt(sum((a-mx)**2 for a in rx) * sum((b-my)**2 for b in ry))
    return covariance/denominator if denominator else None


def percentile(values: list[float], p: float) -> float | None:
    """補間による分位点を返す。

    引数: values(list[float])は数値列、p(float)は0〜1。返り値: float又はNone。
    """
    if not values:
        return None
    data = sorted(values)
    index = p*(len(data)-1)
    low, high = math.floor(index), math.ceil(index)
    return data[low]+(data[high]-data[low])*(index-low)


def summarize_parents(rows: list[dict]) -> dict:
    """同じ支持区分の親の件数・元S01損益を集計する。

    引数: rows(list[dict])は同じ区分の親。返り値: dict。空区分の平均はNone。
    """
    out = {"parents": len(rows), "sessions": len({r["session"] for r in rows}),
           "wins": sum(r["baseline_net"] > 0 for r in rows),
           "losses": sum(r["baseline_net"] < 0 for r in rows),
           "flat": sum(r["baseline_net"] == 0 for r in rows),
           "initial_micro": sum(r["baseline_initial_micro"] for r in rows),
           "all_new_micro": sum(r["baseline_all_new_micro"] for r in rows),
           "profit": sum(max(0, r["baseline_net"]) for r in rows),
           "loss": -sum(min(0, r["baseline_net"]) for r in rows),
           "net": sum(r["baseline_net"] for r in rows)}
    for key in METRICS:
        values = [r[key] for r in rows]
        out[key] = {"mean": statistics.mean(values) if values else None,
                    "median": statistics.median(values) if values else None}
    out["pooled_points_per_initial_micro"] = out["net"]/out["initial_micro"]/10 if out["initial_micro"] else None
    out["pooled_points_per_all_new_micro"] = out["net"]/out["all_new_micro"]/10 if out["all_new_micro"] else None
    return out


def describe_group(rows: list[dict], sessions: list[str], seed: int) -> dict:
    """担当別の固定支持帯と、場単位の相関感度を求める。

    引数: rows(list[dict])は同じ担当群、sessions(list[str])は26場、seed(int)は固定種。
    返り値: dict。区間は標本依存であり独立標本の有意性検定ではない。
    """
    known = [r for r in rows if r["score"] is not None]
    unknown = [r for r in rows if r["score"] is None]
    out = {"all": summarize_parents(rows), "known": summarize_parents(known),
           "unknown": summarize_parents(unknown), "bins": [], "correlations": {}, "by_session": []}
    for i, (low, high) in enumerate(zip(BINS, BINS[1:])):
        part = [r for r in known if low <= r["score"] and (r["score"] < high or i == len(BINS)-2)]
        out["bins"].append({"lower": low, "upper": high, "upper_inclusive": i == len(BINS)-2,
                            **summarize_parents(part)})
    for session in sessions:
        part = [r for r in known if r["session"] == session]
        out["by_session"].append({"session": session, "mean_score": statistics.mean(r["score"] for r in part) if part else None,
                                  **summarize_parents(part)})
    session_rows = {session: [r for r in known if r["session"] == session] for session in sessions}
    sampled = {key: [] for key in METRICS}
    rng = random.Random(seed)
    for _ in range(2000):
        sample = [r for session in rng.choices(sessions, k=len(sessions)) for r in session_rows[session]]
        for key in METRICS:
            rho = correlation([r["score"] for r in sample], [r[key] for r in sample])
            if rho is not None:
                sampled[key].append(rho)
    for key in METRICS:
        out["correlations"][key] = {
            "spearman": correlation([r["score"] for r in known], [r[key] for r in known]),
            "session_bootstrap_95": [percentile(sampled[key], .025), percentile(sampled[key], .975)],
            "valid_resamples": len(sampled[key]), "parents": len(known),
            "sessions": len({r["session"] for r in known}),
        }
    return out


def main() -> None:
    """正常終了後の保存結果だけから初回支持と既存損益を対応させる。

    引数: なし。返り値: None。売買判断や約定を新たに作らない。
    """
    execution = read(HERE/"金融実行1572.json")
    assert execution["終了コード"] == 0 and execution["参照改変数"] == 0
    assert hashlib.sha256((FIRST/"report157.json").read_bytes()).hexdigest() == FIRST_SHA
    full, partial, fingerprints = [], [], []
    for path in sorted((HERE/"results_go").glob("*.json")):
        saved = read(path)
        scene, session = saved["scene"], saved["scene"]["session"]
        cases = {c["config"]["id"]: c for c in saved["cases"]}
        case = cases["V_C02"]
        base = read(FIRST/"audit/cases"/session/"C00.json")["actual"]
        outcome = {p["id"]: p for p in base["parents"]}
        entries = defaultdict(list)
        for lot in base["lots"]:
            entries[lot["parent"]].append(lot)
        source_first = {}
        for event in cases["C00"]["actual"]["Events"] or []:
            order = event["Order"]
            if not order.get("Targets"):
                source_first.setdefault(order["Parent"], order)
        first_decisions = {}
        for decision in case["decisions"] or []:
            if decision["Action"] == "初回拒否" or (decision["Action"] == "新規判断" and decision["Reason"] == "initial"):
                assert decision["Parent"] not in first_decisions, "初回決定の重複"
                first_decisions[decision["Parent"]] = decision
        assert set(first_decisions) == set(source_first) == set(outcome), "Source初回親の集合不一致"
        for key, decision in first_decisions.items():
            order = source_first[key]
            assert decision["Index"] == order["DecisionIndex"] and decision["Time"] == order["DecisionTime"]
            support = decision["Support"]
            components = support["components"]
            assert isinstance(components, dict), "支持の成分既知判定がない"
            parent, lots = outcome[key], entries[key]
            assert all(lot["owner"] == parent["owner"] for lot in lots)
            initial, all_new = parent["initial_quantity"], sum(lot["quantity"] for lot in lots)
            score = support["M"]*support["T"] if support["Known"] else None
            assert score is None or 0 <= score <= 1+1e-10
            row = {"session": session, "partial": scene.get("partial", False), "parent": key,
                   "owner": parent["owner"], "index": decision["Index"], "time": decision["Time"],
                   "action": decision["Action"], "reason": decision["Reason"], "support": support,
                   "score": score, "known": support["Known"],
                   "coverage": {k: components[k] for k in ("OwnKnown", "PeerKnown", "OFIKnown")},
                   "baseline_net": parent["realized"], "baseline_unrealized": parent["unrealized"],
                   "baseline_finished": parent["completed"], "baseline_initial_micro": initial,
                   "baseline_all_new_micro": all_new,
                   "points_per_initial_micro": parent["realized"]/initial/10,
                   "points_per_all_new_micro": parent["realized"]/all_new/10}
            (partial if row["partial"] else full).append(row)
        fingerprints.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    assert len(full) == 155 and all(r["baseline_finished"] for r in full)
    sessions = sorted({r["session"] for r in full})
    assert len(sessions) == 26
    groups = {}
    for i, (name, owners) in enumerate((("全体", {"core", "addon", "episode"}), ("core", {"core"}),
                                       ("その他", {"addon", "episode"}), ("addon", {"addon"}), ("episode", {"episode"}))):
        groups[name] = describe_group([r for r in full if r["owner"] in owners], sessions, 1572+i)
    result = {"definition": read(HERE/"支持識別の集計定義1572.json"), "groups": groups,
              "complete_parents": full, "partial_separate": partial,
              "coverage": {flag: dict(Counter(str(r["coverage"][flag]) for r in full)) for flag in ("OwnKnown", "PeerKnown", "OFIKnown")},
              "source_report_sha256": FIRST_SHA, "result_fingerprints": fingerprints}
    save(HERE/"支持と元S01損益の関係1572.json", result)
    lines = ["# 未校正支持と元S01親損益の関係", "", "採否を問わず、当時の初回支持を同じ親の元S01損益へ結んだ。途中場は除外。支持は確率ではない。", "",
             "| 担当 | 全親 | 支持既知 | 未知 | 相関：親純額 | 相関：初回1micro当たりpt | 相関：全新規1micro当たりpt |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, group in groups.items():
        values = [group["correlations"][key]["spearman"] for key in METRICS]
        formatted = ["算出不可" if value is None else f"{value:.3f}" for value in values]
        lines.append(f'| {name} | {group["all"]["parents"]} | {group["known"]["parents"]} | {group["unknown"]["parents"]} | '+" | ".join(formatted)+" |")
    lines += ["", "順位相関は1に近いほど支持順と損益順が一致する。0付近は単調な関係が弱い。すべての場単位95%再標本化区間は0を含んだ。強い支持ほど大きく建てることを、今回の同親データだけで裏付けられない。", "",
              "## 欠測を弱支持と混ぜない", "", "| 担当 | 未知の親数 | 未知群の元S01収支 | 既知群の元S01収支 |", "| --- | ---: | ---: | ---: |"]
    for name in ("core", "addon", "episode"):
        group = groups[name]
        lines.append(f'| {name} | {group["unknown"]["parents"]} | {group["unknown"]["net"]:+,.0f}円 | {group["known"]["net"]:+,.0f}円 |')
    lines += ["", "自己価格は137/155親が既知。相手価格151/155、OFI129/155は個別フラグで保存した。相手・OFIが欠けても、自己価格が既知ならその利用可能な成分による支持であり、全成分既知と同義ではない。", "",
              "## 実測前に固定した支持帯", "", "| M×T | 全親数 | 場数 | 元S01収支 | 1microあたり平均pt・全体 | 同core | 同その他 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for i, band in enumerate(groups["全体"]["bins"]):
        point_means = [groups[name]["bins"][i]["points_per_all_new_micro"]["mean"] for name in ("全体", "core", "その他")]
        formatted = ["対象なし" if value is None else f"{value:+.1f}" for value in point_means]
        upper = "以下" if band["upper_inclusive"] else "未満"
        lines.append(f'| {band["lower"]:.2f}以上〜{band["upper"]:.2f}{upper} | {band["parents"]} | {band["sessions"]} | {band["net"]:+,.0f}円 | '+" | ".join(formatted)+" |")
    lines += ["", "各親の純損益を元の全新規micro枚数で規格化し、親を等重みで平均した。最大支持帯は2親だけで、帯の順位は単調ではない。最良帯だけを選ぶ再設定は行わない。", "",
              "初回枚数で割った値は、その後の追加・部分返済・出口も含む親全体の尺度。全新規枚数で割った尺度とは別物で、いずれも今回の固定Source入口・出口に依存する。", "",
              "固定支持帯、担当ごとの場別内訳、場単位の2000回再標本化区間はJSONへ保存。閾値の再選択は行っていない。日をまたぐ相関や既知資料での選抜を除いた保証ではなく、将来の予測力とは断定しない。", "",
              "根拠：[全親対応と固定帯](支持と元S01損益の関係1572.json)、[実測前の集計定義](支持識別の集計定義1572.json)。"]
    (HERE/"支持と元S01損益の関係1572.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"parents": len(full), "sessions": len(sessions), "groups": {k: v["correlations"] for k, v in groups.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
