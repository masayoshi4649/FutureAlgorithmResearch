"""固定後確認の完了後だけ、選択済み入口の観測品質と具体的経路を説明する。"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/"features"))
from features161 import read_market

JST = timezone(timedelta(hours=9))
PHASES = ("Day", "preUS", "postUS")
FEATURE_CONTEXT = ("mid", "spread", "ret5_pt", "ret15_pt", "ret30_pt", "ret60_pt", "ret120_pt", "ret300_pt",
                   "vel5_pt_s", "vel15_pt_s", "accel5_15_pt_s", "er60", "range60_pt", "pos60", "ofi5", "ofi15",
                   "imb1", "depth_imb", "bid_refill15", "ask_refill15", "peer_ret15_bp", "peer_ret60_bp", "peer_age_s")


def read_json(path: Path) -> dict:
    """UTF-8のJSONを読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """ファイルを読み取り、内容指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def authorize(path: Path, locked_path: Path, freeze_path: Path) -> dict:
    """rootの完了許可を確認してから固定後結果の読取りを許す。

    引数: path/locked_path/freeze_path(Path)。返り値: dictは許可証跡。
    """
    permission = read_json(path)
    if permission.get("root_completed") is not True:
        raise ValueError("rootの固定後確認完了通知がないため結果を読まない")
    if permission.get("locked_test_sha256") != sha(locked_path) or permission.get("freeze_sha256") != sha(freeze_path):
        raise ValueError("完了した固定後確認又は選択の指紋と一致しない")
    return {"path": str(path), "sha256": sha(path), **permission}


def scalar(value):
    """NumPy値と非有限値をJSONで表現できる値へ変える。

    引数: value(数値又は配列)。返り値: 数値/bool/list/None。
    """
    if np.ndim(value):
        return [scalar(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    return float(value) if np.isfinite(value) else None


def clock(at: float | None) -> str:
    """保存時計を日本時間の表示へ変える。

    引数: at(float|None)。返り値: str。
    """
    return datetime.fromtimestamp(at, JST).isoformat() if at is not None and np.isfinite(at) else "未観測"


def load_npz(path: Path) -> dict:
    """Pickleを許さず保存配列を読み込む。

    引数: path(Path)。返り値: dict[str,ndarray]。
    """
    with np.load(path, allow_pickle=False) as packed:
        return {name: packed[name].copy() for name in packed.files}


def verify_event(event: dict, features: dict, labels: dict) -> dict:
    """保存された選択イベントを正本NPZの時計・方向・先着・品質へ再接続する。

    引数: event/features/labels(dict)。返り値: dictは候補再評価を含まない診断行。
    """
    row = event["row"]
    side = event["side"]
    column = 0 if side == 1 else 1
    assert side in (-1, 1)
    assert event["decision_index"] == int(features["decision_index"][row]) == int(labels["decision_index"][row])
    assert event["decision_time"] == float(features["time"][row]) == float(labels["decision_time"][row])
    assert event["phase"] == PHASES[int(features["phase"][row])]
    assert event["physical_line"] == int(features["physical_line"][row])
    for key, value in (("entry_index", labels["entry_index"][row]), ("status", labels["primary_status"][row, column]),
                       ("resolution_index", labels["primary_resolution_index"][row, column])):
        assert event[key] == int(value), (key, event)
    for key, value in (("entry_time", labels["entry_time"][row]), ("entry_price", labels["entry_price"][row, column]),
                       ("resolution_time", labels["primary_resolution_time"][row, column])):
        assert event[key] == scalar(value), (key, event)
    answer = {key: event[key] for key in ("session", "phase", "candidate", "side", "row", "decision_index", "physical_line",
                                         "decision_time", "entry_index", "entry_time", "entry_price", "status", "resolution_index", "resolution_time")}
    answer["jst_hour"] = datetime.fromtimestamp(event["decision_time"], JST).hour
    answer["decision_jst"] = clock(event["decision_time"])
    for key in ("entry_price_clock_gap_s", "entry_skipped_bad_bbo", "entry_cross_phase", "entry_gap_gt60"):
        answer[key] = scalar(labels[key][row])
    answer["entry_gap_gt15"] = answer["entry_price_clock_gap_s"] is not None and answer["entry_price_clock_gap_s"] > 15
    for definition in ("primary", "last"):
        for field in ("status", "first_up_index", "first_up_time", "first_down_index", "first_down_time", "path_bad_bbo",
                      "path_gap", "path_gap_count", "path_gap_gt60", "path_cross_phase"):
            answer[f"{definition}_{field}"] = scalar(labels[f"{definition}_{field}"][row, column])
    answer["elapsed_to_resolution_s"] = (event["resolution_time"]-event["entry_time"]) if event["entry_time"] is not None else None
    return answer


def summarize(rows: list[dict]) -> dict:
    """成功率の分母を変えず、欠測・境界・未決を件数と率でまとめる。

    引数: rows(list[dict])。返り値: dict。
    """
    n = len(rows)
    entered = sum(r["entry_index"] >= 0 for r in rows)
    counts = {name: sum(r["status"] == status for r in rows) for name, status in (("success", 1), ("adverse_first", -1), ("unresolved", 0), ("no_entry", -2))}
    timing = {}
    for name, status in (("success", 1), ("adverse_first", -1)):
        selected = [r for r in rows if r["status"] == status]
        timing[name] = {"decision_to_entry_s": quantiles([r["entry_price_clock_gap_s"] for r in selected]),
                        "entry_to_resolution_s": quantiles([r["elapsed_to_resolution_s"] for r in selected])}
    quality = {}
    fields = ("entry_gap_gt15", "entry_gap_gt60", "entry_cross_phase", "entry_skipped_bad_bbo", "primary_path_bad_bbo",
              "primary_path_gap", "primary_path_gap_gt60", "primary_path_cross_phase", "last_path_gap", "last_path_gap_gt60")
    for field in fields:
        affected = [r for r in rows if r["entry_index"] >= 0 and r[field] is not None and r[field] > 0]
        quality[field] = {"count": len(affected), "all_signal_denominator": n, "all_signal_rate": len(affected)/n if n else None,
                          "entered_denominator": entered, "entered_rate": len(affected)/entered if entered else None,
                          "success": sum(r["status"] == 1 for r in affected), "adverse_first": sum(r["status"] == -1 for r in affected)}
    return {"events": n, "entered": entered, **counts, "success_rate": counts["success"]/n if n else None,
            "resolved_rate": (counts["success"]+counts["adverse_first"])/n if n else None, "quality": quality,
            "timing_by_outcome": timing}


def quantiles(values: list) -> dict:
    """事後の経過秒を件数・四分位・範囲へまとめる。

    引数: values(list[float|None])。返り値: dict。入口の選択には使用しない。
    """
    known = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if not len(known):
        return {"count": 0, "min": None, "q25": None, "median": None, "q75": None, "max": None}
    return {"count": len(known), **dict(zip(("min", "q25", "median", "q75", "max"), np.quantile(known, [0, .25, .5, .75, 1]).tolist()))}


def grouped(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    """指定した当時の区分ごとに同じ観測品質を集計する。

    引数: rows(list[dict])、fields(tuple[str,...])。返り値: list[dict]。
    """
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[name] for name in fields)].append(row)
    return [{**dict(zip(fields, key)), **summarize(value)} for key, value in sorted(groups.items())]


def raw_example(event: dict, market: dict, features: dict) -> dict:
    """最初の成功又は失敗を原行で再確認し、決着より前の順行逆行幅を保存する。

    引数: event/market/features(dict)。返り値: dict。決着以後の値動きを理由へ混ぜない。
    """
    decision, entry, finish = (event[key] for key in ("decision_index", "entry_index", "resolution_index"))
    assert entry > decision and finish >= entry
    normal = np.flatnonzero(market["valid"])
    assert int(normal[np.searchsorted(normal, decision, side="right")]) == entry
    side, price = event["side"], event["entry_price"]
    assert price == market["ask" if side == 1 else "bid"][entry]
    indices = normal[normal >= entry]
    gain = side*(market["bid" if side == 1 else "ask"][indices]-price)
    hits = np.flatnonzero((gain >= 100) | (gain <= -50))
    assert len(hits) and int(indices[hits[0]]) == finish
    assert (1 if gain[hits[0]] >= 100 else -1) == event["status"]
    before = indices < finish
    through = indices <= finish
    selected = np.flatnonzero(through)
    best_at, worst_at = selected[np.argmax(gain[through])], selected[np.argmin(gain[through])]
    points = []
    for name, index in (("判断", decision), ("次正常入口", entry), ("決着", finish),
                        ("決着まで最高順行", int(indices[best_at])), ("決着まで最大逆行", int(indices[worst_at]))):
        points.append({"role": name, "index": index, "physical_line": int(market["line"][index]), "time": float(market["time"][index]),
                       "jst": clock(market["time"][index]), "bid": float(market["bid"][index]), "ask": float(market["ask"][index]), "last": float(market["last"][index])})
    names = [str(name) for name in features["feature_names"]]
    contexts = []
    for lag in (60, 30, 15, 5, 0):
        row = int(np.searchsorted(features["time"], event["decision_time"]-lag, side="right")-1)
        if row < 0:
            contexts.append({"target_lag_s": lag, "observed": False})
            continue
        contexts.append({"target_lag_s": lag, "observed": True, "actual_age_s": event["decision_time"]-float(features["time"][row]),
                         "index": int(features["decision_index"][row]), "time": float(features["time"][row]),
                         "features": {name: scalar(features["features"][row, names.index(name)]) for name in FEATURE_CONTEXT}})
    return {"event": event, "points": points, "before_resolution": {"normal_rows": int(before.sum()),
               "maximum_favorable_pt": max(0., float(gain[before].max())) if before.any() else None,
               "maximum_adverse_pt": max(0., -float(gain[before].min())) if before.any() else None},
            "through_resolution": {"maximum_favorable_pt": max(0., float(gain[through].max())),
                                     "maximum_adverse_pt": max(0., -float(gain[through].min()))},
            "context": contexts, "decision_features": {name: scalar(features["features"][event["row"], index]) for index, name in enumerate(names)},
            "interpretation": "発生した条件と経路の説明。予兆の因果的効能をこの一例から証明せず、選択の修正には使わない。"}


def markdown(report: dict) -> str:
    """少数の具体例と品質を短い日本語表へ変換する。

    引数: report(dict)。返り値: strはMarkdown。
    """
    lines = ["# 固定後入口の観測品質と具体例", "", "選択を変えず、固定後確認のイベントだけを再集計した。欠測・未到達・未約定は全信号分母に残した。後半も過去研究で既知の期間であり、完全未見の市場期間ではない。", "",
             "|区分|候補|全信号|100円先着|50円逆行先着|未到達|未約定|成功率|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in report["phase"]:
        rate = f'{row["success_rate"]:.1%}' if row["success_rate"] is not None else "—"
        lines.append(f'|{row["phase"]}|{report["selected"][row["phase"]]}|{row["events"]}|{row["success"]}|{row["adverse_first"]}|{row["unresolved"]}|{row["no_entry"]}|{rate}|')
    lines += ["", "|区分|先着|判断→入口 秒 中央値［25%,75%］|入口→決着 秒 中央値［25%,75%］|", "|---|---|---:|---:|"]
    for row in report["phase"]:
        for name, label in (("success", "100円先着"), ("adverse_first", "50円逆行先着")):
            values = row["timing_by_outcome"][name]
            rendered = []
            for field in ("decision_to_entry_s", "entry_to_resolution_s"):
                q = values[field]
                rendered.append(f'{q["median"]:g} ［{q["q25"]:g}, {q["q75"]:g}］' if q["count"] else "—")
            lines.append(f'|{row["phase"]}|{label}|{rendered[0]}|{rendered[1]}|')
    lines += ["", "|区分・最初の例|判断（日本時間）|方向・次板建値|先着時計|先着前最大順行/逆行|", "|---|---|---|---|---|"]
    for example in report["examples"]:
        e, b = example["event"], example["before_resolution"]
        label = "成功" if e["status"] == 1 else "逆行先着"
        direction = "買" if e["side"] == 1 else "売"
        before = "決着が入口行" if b["normal_rows"] == 0 else f'{b["maximum_favorable_pt"]:g} / {b["maximum_adverse_pt"]:g}円'
        lines.append(f'|{e["phase"]}・{label}|{clock(e["decision_time"])}|{direction} {e["entry_price"]:g}|{clock(e["resolution_time"])}|{before}|')
    lines += ["", "『先着前』は障壁に触れた原行を除く。接触行の板飛びを含む極値はJSONへ別記した。利益や実現可能な利確額を表す値ではない。価格時計の空白中の到達順序は不明で、観測された最初の原行を判定している。", "",
              "phase・買売・日本時間の時間帯別の品質率、原行/物理行、判断前60/30/15/5秒と判断時の特徴は `診断161.json` に保存した。具体例は各区分で時計順の最初の成功・最初の逆行先着を機械的に選び、分かりやすい例への差替えをしていない。", ""]
    return "\n".join(lines)


def main() -> None:
    """完了許可後だけ選択イベントを読み、正本NPZ・原板の具体例を保存する。

    引数: CLIのauthorization/locked/freeze/manifest/cache/out。返り値: None。
    """
    parser = argparse.ArgumentParser()
    for key in ("authorization", "locked", "freeze", "manifest", "cache", "out"):
        parser.add_argument("--"+key, type=Path, required=True)
    args = parser.parse_args()
    authorization = authorize(args.authorization, args.locked, args.freeze)
    locked, frozen, manifest = read_json(args.locked), read_json(args.freeze), read_json(args.manifest)
    assert locked["selected"] == frozen["selected"] and locked["freeze_sha256"] == sha(args.freeze)
    assert frozen["manifest_sha256"] == sha(args.manifest)
    assert not (args.out/"診断161.json").exists() and not (args.out/"診断161.md").exists()
    scenes = {s["session"]: s for s in manifest["sessions"] if s["split"] == "test"}
    events = [e for phase, rows in locked["events"].items() for e in rows]
    assert all(e["phase"] in frozen["selected"] and e["candidate"] == frozen["selected"][e["phase"]] and e["session"] in scenes for e in events)
    rows_by_scene = defaultdict(list)
    for event in events:
        rows_by_scene[event["session"]].append(event)
    examples_to_take = set()
    for phase in frozen["selected"]:
        for status in (1, -1):
            candidates = [e for e in events if e["phase"] == phase and e["status"] == status]
            if candidates:
                first = min(candidates, key=lambda e: (e["decision_time"], e["decision_index"], e["side"]))
                examples_to_take.add((first["session"], phase, first["decision_index"], first["side"]))
    access = {a["session"]: a for a in locked["access"]}
    evidence, rows, examples = [], [], []
    for name, selected in sorted(rows_by_scene.items()):
        fp = args.cache/"features"/"test"/(name+".npz")
        lp = args.cache/"labels"/"test"/(name+".npz")
        assert sha(fp) == access[name]["feature_sha256"] and sha(lp) == access[name]["label_sha256"]
        feature, label = load_npz(fp), load_npz(lp)
        np.testing.assert_array_equal(feature["decision_index"], label["decision_index"])
        np.testing.assert_array_equal(feature["time"], label["decision_time"])
        evidence.append({"session": name, "feature_sha256": sha(fp), "label_sha256": sha(lp)})
        current = [verify_event(e, feature, label) for e in selected]
        rows.extend(current)
        picked = [e for e in current if (name, e["phase"], e["decision_index"], e["side"]) in examples_to_take]
        if picked:
            market, raw_evidence = read_market(scenes[name], "NK225")
            evidence[-1]["raw"] = raw_evidence
            examples.extend(raw_example(e, market, feature) for e in picked)
    phase = [{"phase": p, **summarize([r for r in rows if r["phase"] == p])} for p in frozen["selected"]]
    for summary in phase:
        old = locked["reports"][summary["phase"]]
        for key, original in (("events", "events"), ("success", "successes"), ("adverse_first", "adverse_first"), ("unresolved", "unresolved"), ("no_entry", "no_entry")):
            assert summary[key] == old[original]
    report = {"passed": True, "candidate_reselection": False, "financial_replays": 0, "selected": frozen["selected"],
              "authorization": authorization, "manifest_sha256": sha(args.manifest), "evidence": evidence,
              "phase": phase, "phase_side": grouped(rows, ("phase", "side")), "phase_hour": grouped(rows, ("phase", "jst_hour")),
              "phase_side_hour": grouped(rows, ("phase", "side", "jst_hour")), "rows": rows,
              "examples": sorted(examples, key=lambda e: (e["event"]["phase"], -e["event"]["status"])),
              "limitations": ["同じ価格時計の空白中の順序は分からない", "予兆特徴と成功の因果を具体例だけで断定しない", "先着分類であり数量・出口を伴う利益実績ではない"]}
    assert authorization == authorize(args.authorization, args.locked, args.freeze)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out/"診断161.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (args.out/"診断161.md").open("x", encoding="utf-8") as stream:
        stream.write(markdown(report))
    print(json.dumps({"passed": True, "events": len(rows), "raw_examples": len(examples), "financial_replays": 0}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
