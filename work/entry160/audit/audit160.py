"""保存初回と原板を独立に読み直し、100円順行・50円逆行の先着を検算する。"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "work/entry160"
AUDIT = HERE / "audit"


def read(path: Path) -> dict:
    """固定済みJSONを読み取る。

    引数: path(Path)。返り値: dictは保存値。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: dict) -> None:
    """監査先だけへUTF-8の証跡を保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def sha(path: Path) -> str:
    """読取りだけで内容指紋を取得する。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def same(got: object, expected: object, name: str) -> None:
    """型別に検算値の一致を要求する。

    引数: got/expected(object)、name(str)。返り値: None。
    """
    if isinstance(expected, dict):
        assert isinstance(got, dict) and got.keys() == expected.keys(), (name, "キー差")
        for key in expected:
            same(got[key], expected[key], name+"/"+str(key))
    elif isinstance(expected, list):
        assert isinstance(got, list) and len(got) == len(expected), (name, "長さ差")
        for index, value in enumerate(expected):
            same(got[index], value, name+"/"+str(index))
    elif isinstance(expected, float):
        assert isinstance(got, (int, float)) and math.isfinite(got) and abs(got-expected) <= 1e-9, (name, got, expected)
    else:
        assert got == expected, (name, got, expected)


def entry_source_check(entry: dict, source: dict) -> None:
    """保存元の初回実玉を直接同定し、起点を検算する。

    引数: entry/source(dict)。返り値: None。過去MFE/MAEや最終収支は使用しない。
    """
    if "lots" in source:
        lot = next(x for x in source["lots"] if x["id"] == entry["initial_id"])
        peers = [x for x in source["lots"] if x["parent"] == lot["parent"]]
        assert lot["decision_index"] == min(x["decision_index"] for x in peers)
        assert sum(x["decision_index"] == lot["decision_index"] for x in peers) == 1
        mapping = {"entry_price": "price", "entry_index": "entry_index", "entry_time": "entry_time", "side": "side", "owner": "owner", "parent": "parent", "decision_index": "decision_index"}
        for key, old in mapping.items():
            same(entry[key], lot[old], "旧日中初回/"+key)
        assert entry["phase"] == "日中" and entry["method"] == "S01"
        return
    src = next(s for s in source["sources"] if s["Phase"] == entry["phase"])
    initial = next(x for x in src["Initials"] if x["Parent"] == entry["parent"])
    events = [e for e in src["Events"] if e["Signal"]["action"] == "new" and e["Signal"]["owner"] == initial["Owner"] and e["Signal"]["source_index"] == initial["Index"] and e["Signal"]["time"] == initial["Time"]]
    assert len(events) == 1
    event = events[0]
    sig = event["Signal"]
    assert sig["id"]+"-玉" == entry["initial_id"]
    assert f'{sig["owner"]}/{sig["campaign"]}' == entry["parent"]
    expected = {"entry_price": event["Price"], "entry_index": event["FillIndex"], "entry_time": event["FillTime"], "decision_index": initial["Index"], "side": initial["Side"], "owner": initial["Owner"], "method": src["Method"], "known": initial["Support"]["Known"]}
    for key, value in expected.items():
        same(entry[key], value, "159初回/"+key)
    score = initial["Support"]["M"]*initial["Support"]["T"] if initial["Support"]["Known"] else None
    same(entry["score"], score, "159初回支持")


def raw_read(scene: dict) -> tuple[list[tuple], dict]:
    """原資料の採番を別の逐次readerで再構築する。

    引数: scene(dict)。返り値: tupleは採用原行と読取証跡。
    """
    path = Path(scene["books"]["NK225"])
    expected = next(x["sha256"] for x in scene["fingerprints"] if Path(x["path"]) == path)
    digest, counts, rows = hashlib.sha256(), Counter(), []
    prior = scene["start"]
    with path.open("rb") as stream:
        for physical_line, line in enumerate(stream, 1):
            digest.update(line)
            counts["physical"] += 1
            obj = json.loads(line)
            clock = obj.get("CurrentPriceTime")
            try:
                assert isinstance(clock, str)
                at = datetime.fromisoformat(clock).timestamp()
            except (AssertionError, ValueError, TypeError):
                counts["clock_missing"] += 1
                continue
            if at < scene["start"] or at > scene["end"] or scene.get("cutoff", 0) > 0 and at >= scene["cutoff"]:
                counts["outside"] += 1
                continue
            if at < prior:
                counts["backwards"] += 1
                continue
            last = float(obj.get("CurrentPrice") or 0)
            if not math.isfinite(last) or last <= 0:
                counts["last_missing"] += 1
                continue
            prior = at
            bid = float((obj.get("Buy1") or {}).get("Price") or 0)
            ask = float((obj.get("Sell1") or {}).get("Price") or 0)
            valid = math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask
            rows.append((at, last, bid, ask, valid, physical_line))
            counts["adopted"] += 1
    assert digest.hexdigest() == expected
    assert rows
    return rows, {"path": str(path), "sha256": digest.hexdigest(), "counts": dict(counts)}


def scan_label(raw: list[tuple], entry: dict, bound: float, last: bool) -> dict:
    """原行を前から追い、最初の閾値到達だけで分類する。

    引数: raw(list[tuple])、entry(dict)、bound(float)、last(bool)。返り値: dictは独立の先着ラベル。
    """
    first = entry["entry_index"]
    candidates = [i for i in range(first, len(raw)) if raw[i][0] <= bound and (last or raw[i][4])]
    assert candidates
    end = candidates[-1]
    base = raw[first][1] if last else entry["entry_price"]
    direction = entry["side"]
    hit, points_at_hit, hit_price = None, None, None
    status = "未到達"
    low, high = math.inf, -math.inf
    for i in candidates:
        price = raw[i][1 if last else 2 if direction == 1 else 3]
        points = direction*(price-base)
        low, high = min(low, points), max(high, points)
        if points >= 100:
            hit, points_at_hit, hit_price, status = i, points, price, "100先着"
            break
        if points <= -50:
            hit, points_at_hit, hit_price, status = i, points, price, "50逆行先着"
            break
    observed = hit if hit is not None else end
    gap = max((raw[i][0]-raw[i-1][0] for i in range(first+1, observed+1)), default=0)
    return {"status": status, "start_price": float(base), "hit_index": hit, "hit_time": float(raw[hit][0]) if hit is not None else None,
            "hit_price": float(hit_price) if hit is not None else None, "points_at_hit": float(points_at_hit) if hit is not None else None,
            "end_index": end, "end_time": float(raw[end][0]), "elapsed_seconds": float(raw[observed][0]-raw[first][0]),
            "worst_to_first": float(low), "best_to_first": float(high), "invalid_quotes_to_first": sum(not raw[i][4] for i in range(first, observed+1)),
            "max_price_clock_gap": float(gap), "price_clock_gap_over15": gap > 15}


def scene_audit(scene: dict, entries: list[dict], saved_rows: list[dict]) -> dict:
    """一場の初回同値・三種類の先着・原資料指紋を検算する。

    引数: scene(dict)、entries/saved_rows(list[dict])。返り値: dictは一致根拠。
    """
    raw, evidence = raw_read(scene)
    sources, originals = {}, {e["initial_id"]: e for e in entries}
    outputs = {e["initial_id"]: e for e in saved_rows}
    assert originals.keys() == outputs.keys()
    endpoints = []
    kinds = ("primary", "within_operation", "last_only")
    cases = read(HERE / "cases" / (scene["session"]+".json"))
    assert cases["rows"] == saved_rows
    assert cases["input"]["sha256"] == evidence["sha256"]
    assert cases["input"]["counts"] == evidence["counts"]
    for ident, row in originals.items():
        path = ROOT / row["source"]
        if path not in sources:
            sources[path] = read(path)
        entry_source_check(row, sources[path])
        saved = outputs[ident]
        same({k: saved[k] for k in row}, row, "固定入口")
        first, previous = row["entry_index"], row["decision_index"]
        assert first > previous and raw[first][4]
        assert not any(raw[i][4] for i in range(previous+1, first))
        assert row["entry_time"] == raw[first][0]
        assert row["entry_price"] == raw[first][3 if row["side"] == 1 else 2]
        for name in kinds:
            bound = (scene["us_open"]-900 if row["phase"] == "前半" else scene["force_close"]) if name == "within_operation" else scene["end"]
            got = scan_label(raw, row, bound, name == "last_only")
            same(saved[name], got, scene["session"]+"/"+ident+"/"+name)
            endpoints.append({"initial_id": ident, "label": name, "status": got["status"], "hit_index": got["hit_index"], "hit_physical_line": raw[got["hit_index"]][5] if got["hit_index"] is not None else None, "end_index": got["end_index"], "end_physical_line": raw[got["end_index"]][5]})
    out = {"passed": True, "session": scene["session"], "entries": len(entries), "labels": len(endpoints), "raw": evidence, "endpoints": endpoints}
    save(AUDIT / "cases" / (scene["session"]+".json"), out)
    return out


def summarize(rows: list[dict], key: str) -> dict:
    """全初回の整数件数と場単位再標本化を独立に再計算する。

    引数: rows(list[dict])、key(str)。返り値: dictは件数・分母・区間。
    """
    statuses = Counter(r[key]["status"] for r in rows)
    assert set(statuses) <= {"100先着", "50逆行先着", "未到達"}
    count = len(rows)
    wins, losses = statuses["100先着"], statuses["50逆行先着"]
    buckets = defaultdict(list)
    for row in rows:
        buckets[row["session"]].append(row)
    names = sorted(buckets)
    interval = None
    if names:
        rng = np.random.default_rng(160)
        draw = rng.integers(0, len(names), size=(10000, len(names)))
        numerators = np.array([sum(r[key]["status"] == "100先着" for r in buckets[s]) for s in names])
        denominators = np.array([len(buckets[s]) for s in names])
        ratios = numerators[draw].sum(axis=1)/denominators[draw].sum(axis=1)
        interval = np.quantile(ratios, [.025, .975]).tolist()
    return {"entries": count, "sessions": len(names), "success": wins, "failure": losses, "unresolved": statuses["未到達"], "rate_all": wins/count if count else None,
            "rate_reached_only": wins/(wins+losses) if wins+losses else None, "session_bootstrap95": interval,
            "quote_invalid_paths": sum(r[key]["invalid_quotes_to_first"] > 0 for r in rows), "clock_gap_paths": sum(r[key]["price_clock_gap_over15"] for r in rows)}


def groups_check(rows: list[dict], saved: dict) -> int:
    """固定区分の全件分母と未知区分を再構成する。

    引数: rows(list[dict])、saved(dict)。返り値: intは集計欄数。
    """
    groups = {"全体": rows}
    bands = [(0, .1), (.1, .25), (.25, .5), (.5, .75), (.75, 1.00001)]
    for phase in ("日中", "前半", "後半"):
        values = [r for r in rows if r["phase"] == phase]
        groups[phase] = values
        for owner in ("core", "episode", "addon"):
            selected = [r for r in values if r["owner"] == owner]
            if selected:
                groups[phase+"/"+owner] = selected
        for side, label in ((1, "買い"), (-1, "売り")):
            groups[phase+"/"+label] = [r for r in values if r["side"] == side]
        sessions = sorted(set(r["session"] for r in values))
        midpoint = len(sessions)//2
        for label, names in (("前の期間", sessions[:midpoint]), ("後の期間", sessions[midpoint:])):
            groups[phase+"/"+label] = [r for r in values if r["session"] in names]
        for low, high in bands:
            groups[phase+f"/支持{low}～{min(high,1)}"] = [r for r in values if r["known"] and low <= r["score"] < high]
        groups[phase+"/支持未知"] = [r for r in values if not r["known"]]
    assert groups.keys() == saved["groups"].keys()
    checks = 0
    for name, selected in groups.items():
        for key in ("primary", "within_operation", "last_only"):
            same(saved["groups"][name][key], summarize(selected, key), "集計/"+name+"/"+key)
            checks += 1
    return checks


def main() -> None:
    """固定済み全件ファイルを確認後、独立先着監査だけを行う。

    引数: なし。返り値: None。新規注文・出口変更・損益再生を実行しない。
    """
    proof = {"passed": False, "new_financial_replays": 0, "started_at": datetime.now().astimezone().isoformat()}
    try:
        paths = [HERE / name for name in ("inputs160.json", "先着の全件160.json", "先着の集計160.json")]
        frozen = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
        inputs, results, aggregate = (read(p) for p in paths)
        assert results["input"]["sha256"] == frozen["work/entry160/inputs160.json"]
        for item in inputs["sources"]+[inputs["plan"], inputs["implementation"]]:
            assert sha(ROOT / item["path"]) == item["sha256"]
        assert len(inputs["scenes"]) == 53 and len(inputs["entries"]) == len(results["rows"]) == 304
        assert len({(r["session"], r["initial_id"]) for r in results["rows"]}) == 304
        assert Counter(r["phase"] for r in results["rows"]) == {"日中": 166, "前半": 32, "後半": 106}
        evidence, errors = [], []
        with ProcessPoolExecutor(max_workers=6) as pool:
            jobs = {pool.submit(scene_audit, scene, [r for r in inputs["entries"] if r["session"] == scene["session"]], [r for r in results["rows"] if r["session"] == scene["session"]]): scene["session"] for scene in inputs["scenes"]}
            for future in as_completed(jobs):
                try:
                    row = future.result()
                    evidence.append(row)
                    print(json.dumps({"session": row["session"], "passed": True, "labels": row["labels"]}, ensure_ascii=False), flush=True)
                except Exception as error:
                    errors.append({"session": jobs[future], "error": repr(error), "traceback": traceback.format_exc()})
                    print(json.dumps(errors[-1], ensure_ascii=False), flush=True)
        if errors:
            proof["errors"] = errors
            raise AssertionError("独立原板の先着照合に不一致")
        groups = groups_check(results["rows"], aggregate)
        assert frozen == {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
        proof.update(passed=True, scenes=53, initial_entries=304, label_checks=sum(r["labels"] for r in evidence), group_checks=groups,
                     primary=summarize(results["rows"], "primary"), sources=frozen, raw_sources=[r["raw"] for r in sorted(evidence, key=lambda r:r["session"])],
                     independent_implementation={"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha(Path(__file__))}, finished_at=datetime.now().astimezone().isoformat())
        save(AUDIT / "audit160.json", proof)
    except Exception as error:
        proof.update(error=repr(error), traceback=traceback.format_exc(), finished_at=datetime.now().astimezone().isoformat())
        save(AUDIT / "audit160.json", proof)
        raise


if __name__ == "__main__":
    main()
