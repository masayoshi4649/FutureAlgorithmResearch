"""第一巡の日中残存損失と、早い利益保護が切り落とした既存勝ち親を診断する。"""

from collections import Counter
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
OLD = ROOT / "work/stability126_20261019"


def read(path: Path) -> dict:
    """
    機能: 完成保存会計を読む。
    引数: path(Path)はJSONの位置。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    """
    機能: 追加金融なしでD05の最悪場とD06の利益減少上位親を具体時刻へ戻す。
    引数: なし。
    返り値: None。診断JSONと出典指紋を新規保存する。
    """
    target = HERE / "第一巡日中の残存損失と利益を失った時刻.json"
    assert not target.exists()
    source = OLD / "diagnosis_notes/bbo/trace_bbo_loss126.py"
    spec = importlib.util.spec_from_file_location("saved_round1_trace", source)
    trace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trace)
    result_path = TASK / "round1/全条件の会計.json"
    manifest_path = TASK / "入力準備.json"
    result, manifest = map(read, (result_path, manifest_path))
    old_paths = [OLD / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json",
                 OLD / "update_20261020/追加二場の八公開選択会計.json"]
    baseline = {}
    for old_path in old_paths:
        for ref in read(old_path)["cache"]:
            if ref.get("model", "next_normal_bbo") == "next_normal_bbo":
                baseline[ref["session"], ref["symbol"]] = ref
    packets = {ref["session"]: ref for ref in manifest["packets"]}
    new_cache = {(ref["session"], ref["symbol"]): ref for ref in result["cache"]}
    logs, accounts, damages = [], {}, []
    for key, ref in new_cache.items():
        if not key[0].endswith("_Day"):
            continue
        with np.load(BytesIO(trace.payload(ref, logs, "完成日中親会計の比較")), allow_pickle=False) as data:
            new = {method: {name: data[method + "__" + name] for name in ("orders", "cycles", "execution_events")}
                   for method in ("D05", "D06")}
        with np.load(BytesIO(trace.payload(baseline[key], logs, "旧G_Q親会計の比較")), allow_pickle=False) as data:
            base = {name: data["G_Q__" + name] for name in ("orders", "cycles", "execution_events")}
        accounts[key] = dict(G_Q=base, **new)
        for parent in base["cycles"]:
            cid = int(parent[0])
            if parent[3] <= 0:
                continue
            changed = new["D06"]["cycles"][new["D06"]["cycles"][:, 0] == cid]
            if not len(changed):
                continue
            mult = 1000. if key[1] == "TOPIX" else 10.
            damages.append(dict(session=key[0], symbol=key[1], parent=cid, base_net=float(parent[3] * mult),
                                new_net=float(changed[0, 3] * mult), delta=float((changed[0, 3] - parent[3]) * mult)))
    worst = []
    for symbol in ("TOPIX", "NK225"):
        worst += sorted([r for r in result["rows"] if r["method"] == "D05" and r["symbol"] == symbol],
                        key=lambda r: r["net"])[:3]
    worst_damages = []
    for symbol in ("TOPIX", "NK225"):
        worst_damages += sorted([r for r in damages if r["symbol"] == symbol], key=lambda r: r["delta"])[:3]
    # ----------------------------------------
    # 元約定を動かさず、既存親の清算可能益と反対・公開尺度を採点する。
    packet_cache, history_cache = {}, {}
    empty = dict(orders=np.empty((0, 8)), cycles=np.empty((0, 10)))
    concrete = []
    for selection, values in (("D05最悪三場", worst), ("D06利益減少上位三親", worst_damages)):
        for selected in values:
            key = selected["session"], selected["symbol"]
            scene, symbol = key
            if scene not in packet_cache:
                packet_cache[scene] = pickle.loads(trace.payload(packets[scene], logs, "第一巡の具体時刻診断"))
                ref = packets[scene]["features"]
                with np.load(BytesIO(trace.payload(ref, logs, "判断時の公開履歴")), allow_pickle=False) as data:
                    history_cache[scene] = {s: data[s + "__history"] for s in ("TOPIX", "NK225")}
            packet, history = packet_cache[scene], history_cache[scene][symbol]
            ready, quotes = packet["inputs"][key], packet["quotes"][key]
            details = {}
            for method in (("G_Q", "D05") if selection == "D05最悪三場" else ("G_Q", "D06")):
                actual = accounts[key][method]
                if "parent" in selected:
                    actual = dict(actual, cycles=actual["cycles"][actual["cycles"][:, 0] == selected["parent"]])
                groups = trace.group_details(packet, symbol, actual, empty)
                for group in groups:
                    source_row = group["exits"][-1]["source_row"]
                    group["final_source_history"] = history[source_row].tolist()
                    group["final_source_current_atr"] = float(ready["atr"][source_row])
                    group["final_source_quote"] = trace.quote_snapshot(ready, quotes, source_row)
                    group["peak_current_atr"] = float(ready["atr"][group["peak_row"]])
                    group["maximum_r"] = group["maximum_observed_liquidation_pnl"] / group["initial_risk_yen"]
                    group["reservations"] = [event.tolist() for event in actual["execution_events"]
                                             if event[2] == group["campaign"] and event[1] == 9.]
                    group.pop("Last_comparison")
                details[method] = groups
            concrete.append(dict(selection=selection, selected=selected, details=details))
    output = dict(
        passed=True, concrete=concrete, all_positive_base_parent_deltas=damages, reads=logs,
        sources=[dict(path=p.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in [source, result_path, manifest_path, *old_paths, Path(__file__)]],
        financial_replays=0, original_market_reads=0, API=0,
        caution="既知成績から選んだ失敗例の診断。途中最高益は実約定成果ではなく、新修正の利益もまだ未測定。",
    )
    target.write_text(json.dumps(trace.primitive(output), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for record in concrete:
        print(record["selection"], record["selected"]["session"], record["selected"]["symbol"])
        for method, groups in record["details"].items():
            for group in sorted(groups, key=lambda r: r["entry_time"]):
                print(method, group["campaign"], group["entry_time"][11:19], group["direction"], group["entry_price"],
                      "→", group["final_time"][11:19], group["net"], "MFE", group["maximum_observed_liquidation_pnl"],
                      "reason", group["final_reason"], "H", group["final_source_history"])


if __name__ == "__main__":
    main()
