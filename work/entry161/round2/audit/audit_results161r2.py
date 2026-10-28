"""完了許可後に第二巡の選択、先着、板指標を原板から独立に検算する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
BASE = WORK.parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE / "audit"))
import audit_results161 as common


def board_signal(f, candidate, side, phases, thresholds):
    """登録した板条件を、戦略関数を呼ばず別式で計算する。

    引数: f/candidate/thresholds(dict)、side(int)、phases(ndarray)。返り値: ndarray[bool]。
    """
    out = np.zeros(len(phases), dtype=bool)
    for phase in set(phases):
        t = {k: v["quantiles"][candidate["quantile"]] for k, v in thresholds[phase].items()}
        own = "bid_refill15" if side > 0 else "ask_refill15"
        other = "ask_refill15" if side > 0 else "bid_refill15"
        a = side * f["ofi15"] >= t["ofi15"]
        b = side * f["depth_imb"] >= t["depth_imb"]
        c = (f[own] >= t[own]) & (f[own] > f[other])
        opposite = side * f["ofi15"] <= -t["ofi15"]
        r15, r5 = side * f["ret15_pt"], side * f["ret5_pt"]
        family = candidate["family"]
        if family == "BF":
            valid = a
        elif family == "BD":
            valid = b
        elif family == "BR":
            valid = c
        elif family == "BA":
            valid = a & (r15 >= 0) & (r5 >= 0)
        elif family == "BP":
            valid = c & (r15 >= -10) & (r5 >= 0)
        elif family == "BC":
            valid = a & b
        elif family == "BS":
            valid = opposite & (r15 >= -10) & (r5 >= 10)
        elif family == "BU":
            valid = (opposite | c) & (r15 >= -10) & (r5 >= 10)
        else:
            raise AssertionError(family)
        out |= (phases == phase) & valid
    return out & np.isfinite(f["spread"]) & (f["spread"] > 0) & (f["spread"] <= 20)


def read_board(scene, wanted):
    """物理順を保って原板を読み、選択判断行の10段板だけ別に保持する。

    引数: scene(dict)、wanted(set[int])。返り値: tuple[ndarray,dict]。
    """
    path = Path(scene["books"]["NK225"])
    before = path.stat(); digest = hashlib.sha256(); prior = scene["start"]
    rows, depth = [], {}
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            obj = json.loads(line)
            clock = obj.get("CurrentPriceTime")
            if not isinstance(clock, str):
                continue
            try:
                t = datetime.fromisoformat(clock).timestamp()
            except (ValueError, TypeError):
                continue
            if t < scene["start"] or t > scene["end"] or t >= scene["cutoff"] or t < prior:
                continue
            last = float(obj.get("CurrentPrice") or 0)
            if not math.isfinite(last) or last <= 0:
                continue
            prior = t
            buy, sell = obj.get("Buy1") or {}, obj.get("Sell1") or {}
            index = len(rows)
            rows.append([t, last, float(buy.get("Price") or 0), float(sell.get("Price") or 0),
                         float(buy.get("Qty") or 0), float(sell.get("Qty") or 0), line_number])
            if index in wanted:
                depth[index] = dict(object=obj, physical_line=line_number, raw_line_sha256=hashlib.sha256(line).hexdigest())
    after = path.stat()
    record = next(r for r in scene["fingerprints"] if Path(r["path"]) == path)
    assert digest.hexdigest() == record["sha256"]
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return np.asarray(rows, dtype=float), depth


def distance_depth(obj):
    """10段の価格順と数量を逐次検査して距離加重不均衡を計算する。

    引数: obj(dict)。返り値: dict は重み付き買売数量と偏り。
    """
    totals = []
    for prefix, direction in (("Buy", -1), ("Sell", 1)):
        best = float((obj.get(prefix + "1") or {}).get("Price") or 0)
        previous = best; weighted = 0.; valid = True
        for level in range(1, 11):
            quote = obj.get(prefix + str(level)) or {}
            price, qty = float(quote.get("Price") or 0), float(quote.get("Qty") or 0)
            if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty < 0 or direction * (price - previous) < 0:
                valid = False
                continue
            weighted += qty / (1 + abs(price - best) / 10.)
            previous = price
        totals.append(weighted if valid else math.nan)
    denominator = sum(totals)
    value = (totals[0] - totals[1]) / denominator if math.isfinite(denominator) and denominator > 0 else math.nan
    return dict(depth_imb=value, weighted_bid=totals[0], weighted_ask=totals[1])


def displayed_flow(raw, decision, seconds=15):
    """当時原行までの隣接正常板の表示変化を単純な逐次式で平均する。

    引数: raw(ndarray)、decision(int)、seconds(int)。返り値: dict。
    """
    t = raw[decision, 0]
    first = int(np.searchsorted(raw[:, 0], t - seconds, side="left"))
    good = common.normal(raw)
    endpoints = np.flatnonzero(good & (raw[:, 0] <= t - seconds))
    known = len(endpoints) > 0 and t - seconds - raw[endpoints[-1], 0] <= 15
    totals = [0., 0., 0.]; count = 0
    for i in range(max(1, first), decision + 1):
        if not good[i] or not good[i-1] or raw[i, 0] - raw[i-1, 0] > 15:
            continue
        bp, ap, bq, aq = raw[i, 2:6]
        pbp, pap, pbq, paq = raw[i-1, 2:6]
        if not all(math.isfinite(q) and q > 0 for q in (bq, aq, pbq, paq)):
            continue
        numerator = 0.
        if bp >= pbp:
            numerator += bq
        if bp <= pbp:
            numerator -= pbq
        if ap <= pap:
            numerator -= aq
        if ap >= pap:
            numerator += paq
        denominator = bq + aq + pbq + paq
        if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0:
            continue
        count += 1
        totals[0] += numerator / denominator
        if bp == pbp and bq > pbq:
            totals[1] += (bq - pbq) / (bq + pbq)
        if ap == pap and aq > paq:
            totals[2] += (aq - paq) / (aq + paq)
    keys = ("ofi15", "bid_refill15", "ask_refill15")
    result = {key: value / count if known and count >= 2 else math.nan for key, value in zip(keys, totals)}
    result.update(ofi15_count=count, ofi15_coverage=count / max(1, decision-first+1), first_index=first, endpoint_known=bool(known))
    return result


def numeric_same(actual, expected, context):
    """欠測同士を許し、それ以外は小さい算術誤差まで照合する。

    引数: actual/expected(float)、context(str)。返り値: None。
    """
    assert (math.isnan(actual) and math.isnan(expected)) or math.isclose(actual, expected, rel_tol=1e-8, abs_tol=2e-11), (context, actual, expected)


def finite_json(value):
    """JSON向けに診断の非有限値だけをnullへ変換する。

    引数: value(object)。返り値: object。
    """
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_json(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


def audit_scene(scene, selected, candidates, thresholds, expected, feature_path):
    """原板先着の旧独立監査に、第二巡条件と板指標の独立監査を結合する。

    引数: scene/selected/candidates/thresholds/expected(dict)、feature_path(str)。返り値: dict。
    """
    wanted = {e["decision_index"] for events in expected.values() for e in events}
    raw, objects = read_board(scene, wanted)
    with np.load(feature_path, allow_pickle=False) as packed:
        phases = np.array(common.PHASES)[packed["phase"]]
        f = {str(n): packed["features"][:, i].copy() for i, n in enumerate(packed["feature_names"])}
    # ----------------------------------------
    # ファイルを変更せず、このワーカープロセスの独立監査関数だけへ条件を接続する。
    with patch.object(common, "raw_market", lambda *args: raw), patch.object(common, "signals", lambda values, c, side, model: board_signal(values, c, side, phases, thresholds)):
        result = common.audit_scene(scene, selected, candidates, {}, expected, feature_path)
    board_checks = []
    for event in result["proof"]:
        index, row = event["decision_index"], event["row"]
        flow = displayed_flow(raw, index)
        depth = distance_depth(objects[index]["object"])
        for key in ("ofi15", "bid_refill15", "ask_refill15", "ofi15_count", "ofi15_coverage"):
            numeric_same(f[key][row], flow[key], scene["session"] + "/" + key)
        numeric_same(f["depth_imb"][row], depth["depth_imb"], scene["session"] + "/depth_imb")
        board_checks.append(finite_json(dict(candidate=event["candidate"], phase=event["phase"], side=event["side"], decision_index=index,
                                            physical_line=objects[index]["physical_line"], decision_time=event["decision_time"],
                                            raw_line_sha256=objects[index]["raw_line_sha256"], flow=flow, depth=depth)))
    result["board_feature_checks"] = len(board_checks) * 6
    result["board_proof"] = board_checks
    return result


def main():
    """root完了許可と凍結指紋を確認後、保存結果だけを監査する。

    引数: CLI --completion(Path)、--workers(int)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--completion", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    permit = common.read(args.completion)
    assert permit.get("completed") is True and permit.get("root_completed") is True
    assert type(permit.get("returncode")) is int and permit["returncode"] == 0
    test_path, freeze_path = WORK / "results/locked_test161.json", WORK / "results/selection_frozen161.json"
    assert common.sha(test_path) == permit["locked_test_sha256"] and common.sha(freeze_path) == permit["freeze_sha256"]
    target = HERE / "audit161r2.json"
    assert not target.exists()
    manifest = common.read(BASE / "inputs161.json"); scenes = manifest["sessions"]
    scene_by_id = {s["session"]: s for s in scenes}
    train = common.read(WORK / "results/train_validation161.json")
    test, frozen = common.read(test_path), common.read(freeze_path)
    assert all(x["confirmation_is_known_development"] is True for x in (train, test, frozen))
    assert frozen["test_opened"] is False
    assert test["selected"] == frozen["selected"] and test["freeze_sha256"] == common.sha(freeze_path)
    sources = common.read(HERE / "preflight161r2_corrected.json")["sources"]
    for record in sources:
        assert common.sha(ROOT / record["path"]) == record["sha256"], record["path"]
    assert all(r["split"] in {"train", "validation"} for r in train["access"])
    assert all(r["split"] == "test" for r in test["access"])
    for record in train["access"] + test["access"]:
        assert common.sha(record["features"]) == record["feature_sha256"] and common.sha(record["labels"]) == record["label_sha256"]
    features = {r["session"]: r["features"] for r in train["access"] + test["access"]}
    candidates = {c["id"]: c for c in common.read(WORK / "search/candidates161.json")}
    assert len(candidates) == 24
    thresholds = common.read(WORK / "search/thresholds161r2.json")["thresholds"]
    chosen, summary_checks = {}, 0
    for phase in common.PHASES:
        ranking = []
        for key in candidates:
            stats = {}
            for stage in ("train", "validation"):
                events = train["events"][stage][phase][key]
                common.check_event_order(events, scene_by_id, phase)
                names = [s["session"] for s in scenes if s["split"] == stage and s["kind"] == ("Day" if phase == "Day" else "Night")]
                value = common.summarize(events, names)
                common.same(train["reports"][phase][key][stage], value, phase + "/" + key + "/" + stage)
                fails = common.exclusions(value, stage)
                assert fails == train["reports"][phase][key][stage + "_exclusions"]
                stats[stage] = (value, fails); summary_checks += 1
            if not stats["train"][1] and not stats["validation"][1]:
                value = stats["validation"][0]
                ranking.append((min(value["wilson95"][0], value["session_cluster95"][0]), value["success_probability"], value["events"], key))
        if ranking:
            ranking.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3]))
            chosen[phase] = ranking[0][3]
    assert chosen == frozen["selected"]
    for phase, events in test["events"].items():
        common.check_event_order(events, scene_by_id, phase)
        names = [s["session"] for s in scenes if s["split"] == "test" and s["kind"] == ("Day" if phase == "Day" else "Night")]
        common.same(test["reports"][phase], common.summarize(events, names), "test/" + phase)
        summary_checks += 1
    rows = []
    with ProcessPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        jobs = []
        for scene in scenes:
            expected = {}
            for phase, key in chosen.items():
                events = test["events"][phase] if scene["split"] == "test" else train["events"][scene["split"]][phase][key]
                expected[phase] = [e for e in events if e["session"] == scene["session"]]
            jobs.append(pool.submit(audit_scene, scene, chosen, candidates, thresholds, expected, features[scene["session"]]))
        for future in as_completed(jobs):
            result = future.result(); rows.append(result)
            out = HERE / "結果照合" / (result["session"] + ".json")
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            print(json.dumps({k: result[k] for k in ("session", "events", "board_feature_checks", "passed")}, ensure_ascii=False), flush=True)
    for record in sources:
        assert common.sha(ROOT / record["path"]) == record["sha256"]
    assert common.sha(test_path) == permit["locked_test_sha256"] and common.sha(freeze_path) == permit["freeze_sha256"]
    report = dict(passed=True, created_at=datetime.now().astimezone().isoformat(), selected=chosen, sessions=len(rows),
                  selected_events=sum(r["events"] for r in rows), summary_checks=summary_checks,
                  raw_rows=sum(r["raw_rows"] for r in rows), feature_endpoint_checks=sum(r["feature_endpoint_checks"] for r in rows),
                  board_feature_checks=sum(r["board_feature_checks"] for r in rows),
                  new_candidate_evaluations=0, financial_replays=0, api_calls=0,
                  known_confirmation=True, scope="保存選択候補の原板先着・表示数量代理を独立式で監査。条件の再選択なし。後半は既知追加開発資料。",
                  proof_files=[dict(path=(HERE / "結果照合" / (r["session"] + ".json")).relative_to(ROOT).as_posix(), sha256=common.sha(HERE / "結果照合" / (r["session"] + ".json"))) for r in sorted(rows, key=lambda x: x["session"])],
                  sources=[dict(path=p.relative_to(ROOT).as_posix(), sha256=common.sha(p)) for p in (Path(__file__), BASE / "audit/audit_results161.py")],
                  completion=dict(path=str(args.completion), sha256=common.sha(args.completion)),
                  results=[dict(path=p.relative_to(ROOT).as_posix(), sha256=common.sha(p)) for p in (test_path, freeze_path, WORK / "results/train_validation161.json")])
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: report[k] for k in ("passed", "sessions", "selected_events", "summary_checks", "board_feature_checks")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
