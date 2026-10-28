"""保存された初回入口を変えず、100円順行と50円逆行の先着を測る。"""

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import hashlib
import json
import math
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "work/audit159/round2"))
from raw_result157 import read_market, normal_mask


def read(path: Path) -> dict:
    """UTF-8の保存結果を読み取る。

    引数: path(Path)。返り値: dictはJSON内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: object) -> None:
    """計測証跡だけを有限JSONで保存する。

    引数: path(Path)、value(object)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def reference(path: Path) -> dict:
    """元資料の内容指紋を記録する。

    引数: path(Path)。返り値: dictは相対パスとSHA256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}


def make_inputs() -> dict:
    """旧日中と159の追加日中・夜間から初回実約定だけを結合する。

    引数: なし。返り値: dictは固定目録と初回行。
    """
    manifests = [ROOT / "work/d07_154/inputs154.json", ROOT / "work/audit159/inputs159.json"]
    scenes = {}
    for path in manifests:
        for scene in read(path)["sessions"]:
            if not scene["partial"]:
                scenes[scene["session"]] = scene
    initial_path = ROOT / "work/score159/初回玉と支持の対応159.json"
    initials = read(initial_path)["rows"]
    files, rows = manifests+[initial_path], []
    old_days = sorted(set(x["session"] for x in initials))
    for session in old_days:
        path = ROOT / "work/s01_156/audit/cases" / session / "S01.json"
        files.append(path)
        lots = {x["id"]: x for x in read(path)["lots"]}
        for old in (x for x in initials if x["session"] == session):
            lot = lots[old["initial_id"]]
            assert lot["decision_index"] == old["decision_index"] and lot["side"] == old["side"]
            rows.append({"session": session, "kind": "Day", "phase": "日中", "method": "S01",
                         "owner": old["owner"], "parent": old["parent"], "initial_id": old["initial_id"],
                         "entry_index": lot["entry_index"], "entry_time": lot["entry_time"], "entry_price": lot["price"],
                         "decision_index": old["decision_index"], "side": lot["side"], "score": old["score"],
                         "known": old["known"], "source": path.relative_to(ROOT).as_posix()})
    assert len(rows) == 155 and len(old_days) == 26
    for path in sorted((ROOT / "work/night159/results_go").glob("*.json")):
        saved = read(path)
        scene = saved["scene"]
        assert scene["session"] in scenes
        files.append(path)
        for source in saved["sources"]:
            new_events = [x for x in source.get("Events") or [] if x["Signal"]["action"] == "new"]
            for initial in source.get("Initials") or []:
                matches = [e for e in new_events if e["Signal"]["owner"] == initial["Owner"]
                           and e["Signal"]["source_index"] == initial["Index"]
                           and e["Signal"]["time"] == initial["Time"]]
                assert len(matches) == 1
                event = matches[0]
                support = initial["Support"]
                rows.append({"session": scene["session"], "kind": scene["kind"], "phase": source["Phase"],
                             "method": source["Method"], "owner": initial["Owner"], "parent": initial["Parent"],
                             "initial_id": event["Signal"]["id"]+"-玉", "entry_index": event["FillIndex"],
                             "entry_time": event["FillTime"], "entry_price": event["Price"], "decision_index": initial["Index"],
                             "side": initial["Side"], "score": support["M"]*support["T"] if support["Known"] else None,
                             "known": support["Known"], "source": path.relative_to(ROOT).as_posix()})
    assert len({(x["session"], x["initial_id"]) for x in rows}) == len(rows)
    assert sum(x["kind"] == "Night" for x in rows) == 138
    selected = sorted(set(x["session"] for x in rows))
    assert len(selected) == 53
    return {"purpose": "保存初回の事後先着ラベル。注文の再生成なし。", "financial_replays": 0,
            "created_at": datetime.now().astimezone().isoformat(), "sources": [reference(p) for p in files],
            "plan": reference(HERE / "計測計画.md"), "implementation": reference(Path(__file__)),
            "scenes": [scenes[s] for s in selected], "entries": rows}


def first_passage(raw: np.ndarray, valid: np.ndarray, row: dict, end: float, last: bool = False) -> dict:
    """新規行以降の価格を原行順に探索し、固定二障壁の先着を返す。

    引数: raw(ndarray)、valid(ndarray)、row(dict)、end(float)、last(bool)。返り値: dictは先着と観測根拠。
    """
    first = row["entry_index"]
    final = int(np.searchsorted(raw[:, 0], end, side="right"))
    indices = np.arange(first, final, dtype=np.int64)
    if not last:
        indices = indices[valid[first:final]]
    assert len(indices)
    base = raw[first, 1] if last else row["entry_price"]
    prices = raw[indices, 1 if last else (2 if row["side"] == 1 else 3)]
    points = row["side"]*(prices-base)
    wins, losses = np.flatnonzero(points >= 100), np.flatnonzero(points <= -50)
    w, l = int(wins[0]) if len(wins) else len(points), int(losses[0]) if len(losses) else len(points)
    position = min(w, l, len(points)-1)
    hit = int(indices[position])
    status = "100先着" if w < l else "50逆行先着" if l < w else "未到達"
    max_gap = float(np.max(np.diff(raw[first:hit+1, 0]), initial=0))
    return {"status": status, "start_price": float(base), "hit_index": hit if status != "未到達" else None,
            "hit_time": float(raw[hit, 0]) if status != "未到達" else None,
            "hit_price": float(prices[position]) if status != "未到達" else None,
            "points_at_hit": float(points[position]) if status != "未到達" else None,
            "end_index": int(indices[-1]), "end_time": float(raw[indices[-1], 0]),
            "elapsed_seconds": float(raw[hit, 0]-raw[first, 0]),
            "worst_to_first": float(np.min(points[:position+1])),
            "best_to_first": float(np.max(points[:position+1])),
            "invalid_quotes_to_first": int(np.sum(~valid[first:hit+1])), "max_price_clock_gap": max_gap,
            "price_clock_gap_over15": bool(max_gap > 15)}


def measure_scene(scene: dict, rows: list[dict]) -> dict:
    """一場の原板を読み、全初回に同じ固定先着定義を適用する。

    引数: scene(dict)、rows(list[dict])。返り値: dictは入力確認と全初回ラベル。
    """
    raw, evidence = read_market(scene, "NK225")
    valid = normal_mask(raw)
    measured = []
    for original in rows:
        row = dict(original)
        i = row["entry_index"]
        assert valid[i] and raw[i, 0] == row["entry_time"]
        assert raw[i, 3 if row["side"] == 1 else 2] == row["entry_price"]
        previous = row["decision_index"]
        assert i > previous and not np.any(valid[previous+1:i])
        phase_end = scene["us_open"]-900 if row["phase"] == "前半" else scene["force_close"]
        row["primary"] = first_passage(raw, valid, row, scene["end"])
        row["within_operation"] = first_passage(raw, valid, row, phase_end)
        row["last_only"] = first_passage(raw, valid, row, scene["end"], last=True)
        measured.append(row)
    return {"session": scene["session"], "input": evidence, "rows": measured}


def summary(rows: list[dict], key: str = "primary") -> dict:
    """全初回を分母に、先着・未到達と場単位の区間を計算する。

    引数: rows(list[dict])、key(str)。返り値: dictは件数と割合。
    """
    total = len(rows)
    wins = sum(r[key]["status"] == "100先着" for r in rows)
    losses = sum(r[key]["status"] == "50逆行先着" for r in rows)
    n_sessions = len(set(x["session"] for x in rows))
    by_scene = []
    for scene in sorted(set(x["session"] for x in rows)):
        values = [r for r in rows if r["session"] == scene]
        by_scene.append((sum(r[key]["status"] == "100先着" for r in values), len(values)))
    interval = None
    if by_scene:
        rng = np.random.default_rng(160)
        counts = np.asarray(by_scene)
        sample = counts[rng.integers(0, len(counts), size=(10000, len(counts)))].sum(axis=1)
        interval = np.quantile(sample[:, 0]/sample[:, 1], [.025, .975]).tolist()
    return {"entries": total, "sessions": n_sessions, "success": wins, "failure": losses, "unresolved": total-wins-losses,
            "rate_all": wins/total if total else None, "rate_reached_only": wins/(wins+losses) if wins+losses else None,
            "session_bootstrap95": interval, "quote_invalid_paths": sum(r[key]["invalid_quotes_to_first"] > 0 for r in rows),
            "clock_gap_paths": sum(r[key]["price_clock_gap_over15"] for r in rows)}


def main() -> None:
    """入力を固定して全53場を事後採点し、件数と全件根拠を保存する。

    引数: なし。返り値: None。新しい売買判断・注文・損益は生成しない。
    """
    inputs = make_inputs()
    save(HERE / "inputs160.json", inputs)
    results = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(measure_scene, scene, [r for r in inputs["entries"] if r["session"] == scene["session"]]): scene["session"]
                for scene in inputs["scenes"]}
        for job in as_completed(jobs):
            result = job.result()
            save(HERE / "cases" / (result["session"]+".json"), result)
            results.extend(result["rows"])
            print(result["session"], len(result["rows"]), flush=True)
    results.sort(key=lambda r:(r["session"], r["entry_index"], r["initial_id"]))
    groups = {"全体": results}
    for phase in ("日中", "前半", "後半"):
        values = [r for r in results if r["phase"] == phase]
        groups[phase] = values
        for owner in ("core", "episode", "addon"):
            part = [r for r in values if r["owner"] == owner]
            if part:
                groups[phase+"/"+owner] = part
        for side in (1, -1):
            groups[phase+("/買い" if side == 1 else "/売り")] = [r for r in values if r["side"] == side]
        sessions = sorted(set(r["session"] for r in values))
        middle = len(sessions)//2
        for label, selected in (("前の期間", sessions[:middle]), ("後の期間", sessions[middle:])):
            groups[phase+"/"+label] = [r for r in values if r["session"] in selected]
        for low, high in ((0,.1),(.1,.25),(.25,.5),(.5,.75),(.75,1.00001)):
            groups[phase+f"/支持{low}～{min(high,1)}"] = [r for r in values if r["known"] and low <= r["score"] < high]
        groups[phase+"/支持未知"] = [r for r in values if not r["known"]]
    aggregate = {k:{label:summary(rows,label) for label in ("primary", "within_operation", "last_only")} for k,rows in groups.items()}
    assert len(results) == len(inputs["entries"])
    save(HERE / "先着の全件160.json", {"input": reference(HERE / "inputs160.json"), "rows": results})
    save(HERE / "先着の集計160.json", {"definition": "実新規後−50円に達する前の＋100円。原行順、場末まで。", "groups": aggregate})
    for k in ("全体", "日中", "前半", "後半"):
        print(k, aggregate[k]["primary"], flush=True)


if __name__ == "__main__":
    main()
