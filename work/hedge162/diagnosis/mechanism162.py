"""保存約定から追尾起動の純対照と、数量枠・残玉の具体機構を補足する。"""
from collections import Counter
from pathlib import Path
import json
import sys

import numpy as np

from diagnose162 import WORK, HERE, ROOT, JST, completion_gate, read, clock, fingerprint, parent_records


def inventory_at(case: dict, index: int) -> list[dict]:
    """指定原行の約定後に残る保存玉を再構築する。

    引数: case(dict)、index(int)。返り値: list[dict]。新しい売買判断を作らない。
    """
    active = {}
    for event in case["events"]:
        if event["fill_index"] is None or event["fill_index"] > index:
            continue
        order = event["order"]
        if order["action"] == "new":
            active[order["id"]] = {"id": order["id"], "parent": order["parent"], "role": order["role"],
                                    "side": order["side"], "quantity": order["quantity"],
                                    "price": event["price"], "index": event["fill_index"],
                                    "time": event["fill_time"], "jst": clock(event["fill_time"])}
        else:
            lot = active[order["target"]]
            lot["quantity"] -= order["quantity"]
            if lot["quantity"] == 0:
                del active[order["target"]]
    return list(active.values())


def reason_accounts(case: dict) -> dict:
    """カバーの返済理由別に損益・件数・未順行損を数える。

    引数: case(dict)。返り値: dict。
    """
    totals = Counter()
    lots = {lot["id"]: lot for lot in case["lots"]}
    for event in case["events"]:
        order = event["order"]
        if order["action"] != "close" or order["role"] != "cover":
            continue
        reason = order["reason"]
        totals[reason + "_net"] += event["gross"]
        totals[reason + "_count"] += 1
        totals["winning_count"] += event["gross"] > 0
        totals["losing_count"] += event["gross"] < 0
        totals["flat_count"] += event["gross"] == 0
        if lots[order["target"]]["best"] <= 0 and event["gross"] < 0:
            totals["never_positive_loss_count"] += 1
            totals["never_positive_loss_net"] += event["gross"]
    return dict(totals)


def plot_parent(scene: dict, saved: dict, case: dict, decision_index: int, destination: Path) -> dict:
    """保存原板と指定親の約定だけから価格・親時価の暗色図を描く。

    引数: scene/saved/case(dict)、decision_index(int)、destination(Path)。返り値: dictは原板出典と図。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import datetime

    sys.path.insert(0, str(WORK / "engine"))
    from source161_features import read_market

    parent = next(p for p in parent_records(case).values() if p["key"][0] == decision_index)
    entry = parent["main_entry"]
    main_exit = next(e for e in reversed(parent["events"]) if e["role"] == "main" and e["action"] == "close")
    market, proof = read_market(scene, "NK225")
    assert proof["sha256"] == saved["input"]["raw"]["sha256"]
    last_index = main_exit["fill_index"] if main_exit["fill_index"] is not None else main_exit["quote"]["index"]
    first_index = entry["fill_index"]
    valid = market["valid"]
    visible = np.flatnonzero(valid & (market["time"] >= entry["fill_time"] - 60)
                            & (market["time"] <= main_exit["fill_time"] + 60))
    by_index = {}
    for event in parent["events"]:
        if event["fill_index"] is not None:
            by_index.setdefault(event["fill_index"], []).append(event)
    positions, realized, history = {}, 0., []
    for index in visible:
        for event in by_index.get(int(index), []):
            if event["action"] == "new":
                positions[event["id"]] = {"quantity": event["quantity"], "side": event["side"], "entry": event["price"]}
            else:
                positions[event["target"]]["quantity"] -= event["quantity"]
                realized += event["gross"]
        unrealized = sum(p["quantity"] * p["side"] * ((market["bid"][index] if p["side"] == 1 else market["ask"][index]) - p["entry"]) * 100
                         for p in positions.values())
        history.append((int(index), float(market["time"][index]), realized, unrealized, realized + unrealized))
    if main_exit["fill_index"] is not None:
        assert realized == parent["net"]
    # ----------------------------------------
    # 図示は間引くが、約定と表示区間の極値は必ず保持する。
    values = np.asarray(history)
    sample = np.unique(np.r_[np.linspace(0, len(visible) - 1, min(3000, len(visible))).astype(int),
                             np.flatnonzero(np.isin(visible, list(by_index))),
                             np.argmin(values[:, 4]), np.argmax(values[:, 4])])
    indices = visible[sample]
    dates = [datetime.fromtimestamp(float(market["time"][i]), JST) for i in indices]
    plt.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "DejaVu Sans"]
    plt.style.use("dark_background")
    fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True, gridspec_kw={"height_ratios": [1.35, 1]}, constrained_layout=True)
    fig.patch.set_facecolor("#101820")
    for ax in axes:
        ax.set_facecolor("#14232e")
        ax.grid(alpha=.18)
    axes[0].plot(dates, (market["bid"][indices] + market["ask"][indices]) / 2, color="#d4dee7", linewidth=1, label="ラージ板中値")
    for role, color in (("main", "#53d9ff"), ("cover", "#ffb566")):
        for action, marker in (("new", "^"), ("close", "x")):
            events = [e for e in parent["events"] if e["role"] == role and e["action"] == action]
            axes[0].scatter([datetime.fromtimestamp(e["fill_time"], JST) for e in events], [e["price"] for e in events],
                            s=75 if role == "main" else 30, color=color, marker=marker,
                            label=("主玉" if role == "main" else "カバー") + ("新規" if action == "new" else "返済"), zorder=4)
    axes[0].axhline(entry["price"], color="#53d9ff", alpha=.4, linestyle="--")
    axes[0].set_ylabel("価格（円）")
    axes[0].legend(loc="upper left", ncols=3, fontsize=9)
    for column, label, color in ((2, "親の確定損益", "#6ce5ba"), (3, "親の含み損益", "#f096c8"), (4, "親の総時価", "#f5de69")):
        axes[1].plot(dates, values[sample, column] / 10000, color=color, label=label, linewidth=1.3)
    axes[1].axhline(0, color="white", alpha=.4, linewidth=.6)
    axes[1].set_ylabel("損益（万円）")
    axes[1].legend(loc="best", ncols=3, fontsize=9)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=JST))
    axes[1].set_xlabel("日本時間・価格時計。マーカーは保存された次正常原行の約定")
    axes[0].set_title(f"{scene['session']} {case['id']} 親 {parent['parent']}：主 {parent['main_net']/10000:+.1f}万円、カバー {parent['cover_net']/10000:+.1f}万円（{parent['cover_entries']}玉）")
    fig.savefig(destination, dpi=150)
    plt.close(fig)
    return {"file": fingerprint(destination), "raw": proof, "parent": parent["parent"],
            "decision_index": decision_index, "entry_index": first_index, "last_index": last_index,
            "purpose": "保存約定の説明。新規売買判断・結果後の条件変更なし。"}


def main() -> None:
    """両段階完了後のH01/H13と指定3場の機構だけを追加保存する。

    引数: なし。返り値: None。
    """
    frozen, records, sources = completion_gate(WORK)
    totals = {ident: Counter() for ident in ("H01", "H13")}
    reasons = {ident: Counter() for ident in totals}
    rows, examples = [], {}
    targets = {"2026-10-23_Day": "H01", "2026-10-13_Night": "H09", "2026-10-27_Day": "H01"}
    for item in records:
        saved = read(Path(item["path"]))
        cases = {c["id"]: c for c in saved["cases"]}
        for ident in totals:
            case, t = cases[ident], totals[ident]
            summary = case["summary"]
            row = {"session": saved["session"], "split": saved["split"], "id": ident}
            for key in ("realized", "main_entries", "cover_entries"):
                row[key] = summary[key]
                t[key] += summary[key]
            for role in ("main", "cover"):
                for key in ("net", "profit", "loss"):
                    row[role + "_" + key] = summary["roles"][role][key]
                    t[role + "_" + key] += row[role + "_" + key]
            row["losing"] = summary["realized"] < 0
            t["losing_sessions"] += row["losing"]
            account = reason_accounts(case)
            reasons[ident].update(account)
            rows.append({**row, "cover_reasons": account})
        if saved["session"] in targets:
            ident = targets[saved["session"]]
            case = cases[ident]
            parents = parent_records(case)
            refs = {r["index"]: r for r in case["reference"]}
            minimum = case["summary"]["minimum_at"]
            remain = inventory_at(case, minimum["index"])
            quote = refs[minimum["index"]]
            for lot in remain:
                lot["unrealized"] = lot["quantity"] * lot["side"] * ((quote["bid"] if lot["side"] == 1 else quote["ask"]) - lot["price"]) * 100
            assert sum(l["unrealized"] for l in remain) == minimum["unrealized"]
            examples[saved["session"]] = {"id": ident, "summary": case["summary"], "minimum_quote": quote,
                "minimum_remaining": remain, "parents": list(parents.values()),
                "N00_parents": list(parent_records(cases["N00"]).values()), "reference": case["reference"],
                "result": fingerprint(Path(item["path"]))}
            if saved["session"] == "2026-10-13_Night":
                before = inventory_at(case, 47197)
                examples[saved["session"]]["at_sell_decision_47197"] = before
            if saved["session"] == "2026-10-23_Day":
                manifest = read(WORK / "inputs162.json")
                scene = next(s for s in manifest["sessions"] if s["session"] == saved["session"])
                examples[saved["session"]]["chart"] = plot_parent(scene, saved, case, 6786, HERE / "主玉利確と残カバー損162.png")
    value = {"selected_unchanged": frozen["selected"], "immediate_trail_comparison": {k: dict(v) for k, v in totals.items()},
             "cover_reasons": {k: dict(v) for k, v in reasons.items()}, "rows": rows, "examples": examples,
             "sources": sources, "implementation": fingerprint(Path(__file__)), "new_financial_replay": False}
    target = HERE / "即追尾と具体機構162.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"completed": True, "output": fingerprint(target), "immediate": value["immediate_trail_comparison"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
