"""第三巡の保存結果を原板・所有台帳から検算する。売買条件の新規再生はしない。"""

from collections import defaultdict
from pathlib import Path
from datetime import datetime
import hashlib
import importlib.util
import json
import sys
import traceback
import numpy as np

BASE = Path(__file__).resolve().parents[1]
FIRST = BASE.parent
SECOND = FIRST / "round2"
ROOT = BASE.parents[2]
PREVIOUS = FIRST.parent / "s01_156"
sys.path.insert(0, str(SECOND / "audit"))
sys.path.insert(0, str(FIRST / "audit"))
from raw_result157 import close, read_market, support_arrays, raw_risk, reserved_cap
from raw_result1572 import support_at1572

spec = importlib.util.spec_from_file_location("second157", SECOND / "audit/結果の全原板監査1572.py")
second = importlib.util.module_from_spec(spec)
spec.loader.exec_module(second)
prior = second.prior
read, save = second.read, second.save


def reference(path: Path) -> dict:
    """読取資料の位置と内容指紋を返す。

    引数: path(Path)。返り値: dictはプロジェクト相対位置とSHA256。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def exact_old(case: dict, old: dict) -> dict:
    """O00とJ02を公開名・説明・対照名だけ除き、全保存内容で比較する。

    引数: case/old(dict)。返り値: dictは一致した実約定・判断台帳約定の件数。
    """
    configs = []
    for item in (case, old):
        configs.append({k: v for k, v in item["config"].items() if k not in ("id", "description", "control")})
    assert configs[0] == configs[1], "O00/J02の実条件が異なる"
    a = {k: v for k, v in case.items() if k != "config"}
    b = {k: v for k, v in old.items() if k != "config"}
    assert prior.normalize(a, "O00") == prior.normalize(b, "J02"), "O00/J02の全保存状態が不一致"
    return {"passed": True, "actual_events": len(case["actual"]["Events"] or []), "canonical_events": len(case["canonical"]["Events"] or [])}


def orders_of(ledger: dict) -> list:
    """約定済みと末尾未確定の注文を重複なく集める。

    引数: ledger(dict)。返り値: listは判断原行・保存順の注文。
    """
    values = [e["Order"] for e in ledger["Events"] or []] + (ledger["Pending"] or [])
    assert len({x["ID"] for x in values}) == len(values)
    return sorted(values, key=lambda x: x["DecisionIndex"])


def collapse_evidence(case: dict, order: dict, own: dict, peer: dict, cache: dict) -> dict:
    """崩壊返済の初回判断前15秒以上に、未知・空白・不成立がないことを確認する。

    引数: case/order/own/peer/cache(dict)。返り値: dictは確認開始・終了の原行と観測数。
    """
    index = order["DecisionIndex"]
    at = own["time"][index]
    parent = case["parents"][order["Parent"]]
    side = parent["Side"]
    j = int(np.searchsorted(own["time"], at - 15, side="right")) - 1
    while j >= 0 and not own["valid"][j]:
        j -= 1
    assert j >= 0 and own["time"][j] >= parent["Started"]
    indices = np.flatnonzero(own["valid"][j:index + 1]) + j
    assert len(indices) >= 2 and at - own["time"][indices[0]] >= 15
    previous = None
    for i in indices:
        key = (int(i), side)
        if key not in cache:
            cache[key] = support_at1572(own, peer, int(i), side)
        support = cache[key]
        assert support["Known"] and support["M"] < .1 and support["Opp"] >= .5, (case["config"]["id"], order["Parent"], i, support)
        if previous is not None:
            assert own["time"][i] - previous <= 15
        previous = own["time"][i]
    return {"first_index": int(indices[0]), "last_index": int(index), "normal_observations": len(indices), "elapsed": float(at - own["time"][indices[0]])}


def check_exits(case: dict, raw: np.ndarray, own: dict, peer: dict, cache: dict) -> dict:
    """旧元玉出口の維持、逆玉限定追尾と崩壊の因果証拠を検算する。

    引数: case/own/peer/cache(dict)、raw(ndarray)。返り値: dictは理由別件数・次板損失等。
    """
    config = case["config"]
    assert config["OldExit"] and config["minimum"] == 10
    ledger = case["canonical"]
    orders = orders_of(ledger)
    counts = defaultdict(int)
    first_collapse = {}
    collapse_rows = []
    for order in orders:
        reason = order["Reason"]
        counts["reason:" + reason] += 1
        assert reason not in ("lot_stop", "lot_trail", "親時価8万円"), "新しい元玉出口が混入"
        if reason == "cover_trail":
            assert config.get("cover_trail") and order["Kind"] == "cover" and order["Targets"]
            for target in order["Targets"]:
                lot = ledger["Lots"][target["ID"]]
                assert lot["Kind"] == "cover" and lot["Parent"] == order["Parent"]
                side, entry, i = lot["Side"], lot["Entry"], order["DecisionIndex"]
                start = lot["EntryIndex"]
                segment = raw[start:i + 1]
                valid = own["valid"][start:i + 1]
                marks = segment[valid, 2 if side > 0 else 3]
                best = max(0., float(np.max(side * (marks - entry))))
                gain = side * (raw[i, 2 if side > 0 else 3] - entry)
                assert best >= 40 and gain <= max(0., best - 40) + 1e-7
                counts["cover_trail_target_checks"] += 1
        if reason == "長短支持崩壊":
            assert config.get("separate_collapse") and config["id"] in ("O10", "O11")
            if order["Parent"] not in first_collapse:
                first_collapse[order["Parent"]] = order["DecisionIndex"]
                collapse_rows.append(collapse_evidence(case, order, own, peer, cache))
        if reason == "boundary" and order["DecisionTime"] < case["scene"]["force_close"]:
            counts["early_boundary_orders"] += 1
    # ----------------------------------------
    # 支持崩壊で止めた同じ親を、後続の元通知や独自追加で再び建てない。
    for order in orders:
        if not order["Targets"] and order["Parent"] in first_collapse:
            assert order["DecisionIndex"] < first_collapse[order["Parent"]]
    for event in ledger["Events"] or []:
        if event["Order"]["Reason"] == "cover_trail":
            counts["cover_trail_fill_count"] += 1
            if event["Gross"] < 0:
                counts["cover_trail_negative_fill_count"] += 1
                counts["cover_trail_negative_fill_yen"] += event["Gross"]
    return {"counts": dict(counts), "collapse_first_parent_checks": len(first_collapse), "collapse_evidence": collapse_rows}


def main() -> None:
    """登録済み第三巡の正常終了後に324条件場の保存結果を検算する。

    引数: なし。返り値: None。金融再生・実API接続・原資料変更は行わない。
    """
    target = BASE / "金融監査1573.json"
    proof = {"passed": False, "case_count": 0, "started_at": datetime.now().astimezone().isoformat(), "new_financial_replays": 0}
    try:
        execution = read(BASE / "金融実行1573.json")
        assert execution["終了コード"] == 0 and execution["参照改変数"] == 0 and execution["結果ファイル数"] == 27
        files = sorted((BASE / "results_go").glob("*.json"))
        assert len(files) == 27
        old_files = sorted((SECOND / "results_go").glob("*.json"))
        before = [reference(p) for p in files + old_files]
        totals = defaultdict(int)
        scenes = []
        for scene in read(PREVIOUS / "inputs156.json")["sessions"]:
            name = scene["session"]
            saved = read(BASE / "results_go" / (name + "_S01.json"))
            cases = {c["config"]["id"]: c for c in saved["cases"]}
            assert set(cases) == {f"O{i:02d}" for i in range(12)}
            old = read(SECOND / "results_go" / (name + "_S01.json"))
            j02 = next(c for c in old["cases"] if c["config"]["id"] == "J02")
            assert saved["source"] == old["source"] and saved["counts"] == old["counts"]
            control = exact_old(cases["O00"], j02)
            origins = {}
            c00 = next(c for c in old["cases"] if c["config"]["id"] == "C00")
            for event in c00["actual"]["Events"] or []:
                order = event["Order"]
                if not order["Targets"] and order["Parent"] not in origins:
                    origins[order["Parent"]] = (order["DecisionIndex"], order["DecisionTime"], order["Side"])
            totals["initial_source_parents"] += len(origins)
            raw, own_ref = read_market(scene, "NK225")
            other, peer_ref = read_market(scene, "TOPIX")
            own, peer = support_arrays(raw), support_arrays(other)
            cache, paths, rows = {}, {}, []
            for identifier, case in cases.items():
                risk = raw_risk(raw, case["actual"], scene["start"], identifier in ("O05", "O08"))
                if "_path" in risk:
                    paths[identifier] = risk.pop("_path")
                caps = {label: reserved_cap(case[label]) for label in ("actual", "canonical")}
                supports = second.check_support(case, own, peer, cache)
                initial = second.check_initial(case, origins, raw)
                exits = check_exits(case, raw, own, peer, cache)
                rows.append({"id": identifier, "risk": risk, "caps": caps, "supports": supports, "initial": initial, "exits": exits})
                totals["cases"] += 1
                totals["events"] += risk["event_checks"]
                totals["normal_quote_checks"] += risk["normal_rows"]
                for key, value in supports.items():
                    totals["supports_" + key] += value
                for key, value in initial.items():
                    totals[key] += value
                for key, value in exits["counts"].items():
                    totals["exit_" + key] += value
                totals["collapse_first_parent_checks"] += exits["collapse_first_parent_checks"]
            projection = prior.compare_projection(cases["O05"], cases["O08"], paths["O05"], paths["O08"], raw)
            summary = {"session": name, "partial": scene["partial"], "raw": [own_ref, peer_ref], "o00_j02": control, "source_all_output_equal": True, "rows": rows, "projection": projection}
            save(BASE / "audit/金融結果" / (name + ".json"), summary)
            scenes.append(summary)
            print(json.dumps({"session": name, "passed": True, "cases": 12, "cover_trails": sum(r["exits"]["counts"].get("cover_trail_fill_count", 0) for r in rows)}, ensure_ascii=False), flush=True)
        after = [reference(p) for p in files + old_files]
        assert before == after
        assert totals["cases"] == 324 and totals["initial_source_parents"] == 166 and totals["initial_checks"] == 166 * 12
        assert totals["supports_known"] > 0 and totals["supports_unknown"] > 0
        proof.update(passed=True, case_count=324, totals=dict(totals), result_fingerprints=after[:27], previous_result_fingerprints=after[27:], results_unchanged=True, old_result_unchanged=True, o00_j02_cases=27, source_output_equal_cases=27, h_n_pairs=27, input_raw_fingerprints=[f for s in scenes for f in s["raw"]])
        proof["checks"] = {"source_initial_coverage": True, "source_initial_filter_and_quantity": True, "o00_j02_all_output_exact": True, "source_all_output_exact": True, "quantity_cap_including_pending": True, "next_normal_large_bbo": True, "all_raw_equity_risk": True, "raw_support_and_components": True, "past_normal_endpoint_no_future": True, "base_new_exit_absent": True, "cover_trail_only_and_raw_price_evidence": True, "collapse_supported_when_fired": True, "h_n_canonical_equal": True, "h_n_parent_net_equal": True, "h_n_cashflow_bbo_identity": True, "partial_not_liquidated": True}
        proof["audit_fingerprints"] = [reference(p) for p in (Path(__file__), SECOND / "audit/結果の全原板監査1572.py", SECOND / "audit/raw_result1572.py", FIRST / "audit/raw_result157.py", FIRST / "audit/結果の全原板監査157.py")]
        proof["finished_at"] = datetime.now().astimezone().isoformat()
        save(target, proof)
    except Exception as error:
        proof.update(error=repr(error), traceback=traceback.format_exc(), finished_at=datetime.now().astimezone().isoformat())
        save(target, proof)
        raise


if __name__ == "__main__":
    main()
