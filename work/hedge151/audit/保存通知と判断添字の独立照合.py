"""保存済みB04の通知網羅性と、1場の原板採番だけを照合する。金融判断は実行しない。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def read_json(path: Path) -> dict:
    """
    機能: 保存JSONを読取専用で読み込む。
    引数: path(Path)は保存先。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    """
    機能: 読取ファイルの内容指紋を求める。
    引数: path(Path)は保存先。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 26保存結果の注文連番と、10月21日1場の全新規判断を照合する。
    引数: なし。取引条件や約定は再計算しない。
    返り値: None。監査JSONだけを担当領域へ保存する。
    """
    rows = []
    selected = None
    total_events = 0
    total_entries = 0
    for path in sorted((ROOT / "work/preus150/results_round2").glob("*.json")):
        saved = read_json(path)
        case = next(c for c in saved["cases"] if c["config"]["id"] == "B04")
        assert not case["final_pending"], path.name
        sequences = defaultdict(list)
        new_by_owner = defaultdict(int)
        for event in case["events"]:
            signal = event["signal"]
            sequences[event["phase"]].append(int(signal["id"].rsplit("-", 1)[1]))
            assert event["decision_index"] == signal["source_index"]
            assert event["fill_index"] > signal["source_index"]
            if signal["action"] == "new":
                new_by_owner[event["phase"] + "/" + signal["owner"]] += 1
        for phase, sequence in sequences.items():
            assert sequence == list(range(1, len(sequence) + 1)), (path.name, phase, sequence)
        for owner, count in new_by_owner.items():
            assert case["diagnostics"][owner]["実新規"] == count
        entries = sum(new_by_owner.values())
        total_entries += entries
        total_events += len(case["events"])
        rows.append({
            "session": saved["scene"]["session"],
            "source_sha256": sha256(path),
            "events": len(case["events"]),
            "entries": entries,
            "all_phase_sequences_contiguous_from_1": True,
            "final_pending_empty": True,
            "new_by_owner": dict(new_by_owner),
        })
        if saved["scene"]["session"] == "2026-10-21_Night":
            selected = saved
    assert len(rows) == 26 and selected is not None

    # ----------------------------------------
    # 採番の技術照合だけを行う。特徴量・売買判断・新しい損益は計算しない。
    scene = selected["scene"]
    case = next(c for c in selected["cases"] if c["config"]["id"] == "B04")
    entries_by_index = defaultdict(list)
    for event in case["events"]:
        if event["signal"]["action"] == "new":
            entries_by_index[event["decision_index"]].append(event["signal"])
    counts = defaultdict(int)
    index = 0
    previous = scene["start"]
    found = []
    raw_hash = hashlib.sha256()
    with Path(scene["books"]["NK225"]).open("rb") as stream:
        for physical_row, line in enumerate(stream, 1):
            raw_hash.update(line)
            counts["NK225_原行"] += 1
            book = json.loads(line)
            clock = book.get("CurrentPriceTime")
            try:
                if clock is None:
                    raise ValueError("時計なし")
                at = datetime.fromisoformat(clock.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                counts["NK225_時計欠測"] += 1
                continue
            if at < scene["start"] or at > scene["end"] or (scene.get("cutoff", 0) > 0 and at >= scene["cutoff"]):
                counts["NK225_範囲外"] += 1
                continue
            if at < previous:
                counts["NK225_逆行"] += 1
                continue
            last = book.get("CurrentPrice", 0)
            if last is None or last <= 0 or not math.isfinite(last):
                counts["NK225_Last欠測"] += 1
                continue
            previous = at
            for signal in entries_by_index.get(index, []):
                observation = signal["evidence"]["observation"]
                assert at == signal["time"] == observation["Time"]
                assert index == signal["source_index"] == observation["Index"]
                assert last == observation["Last"]
                assert book["Buy1"]["Price"] == observation["Bid"]
                assert book["Sell1"]["Price"] == observation["Ask"]
                found.append({"id": signal["id"], "physical_row_1based": physical_row,
                              "source_index_0based": index, "time": clock,
                              "last": last, "bid": observation["Bid"], "ask": observation["Ask"]})
            index += 1
            counts["NK225_採用"] += 1
    assert len(found) == sum(map(len, entries_by_index.values()))
    for key, count in selected["counts"].items():
        if key.startswith("NK225_"):
            assert counts[key] == count, (key, counts[key], count)

    # ----------------------------------------
    # 網羅性のコード根拠を指紋化し、保存値の確認と区別する。
    source_files = ["main.go", "internal/strategy/features.go", "internal/strategy/research143.go", "internal/strategy/portfolio.go"]
    source_root = ROOT / "work/preus150/engine_go_round2"
    result = {
        "financial_replays": 0,
        "technical_raw_files_scanned": 1,
        "saved_cases_checked": len(rows),
        "events_checked": total_events,
        "entry_notifications_checked": total_entries,
        "code_sources": {x: sha256(source_root / x) for x in source_files},
        "saved_cases": rows,
        "source_index_check": {
            "session": scene["session"], "raw_sha256": raw_hash.hexdigest(),
            "counts": dict(counts), "all_new_decisions_matched": found,
            "independent_market_counter": True,
            "invalid_bbo_not_removed_before_index": True,
        },
        "all_checks_passed": True,
        "limits": [
            "注文連番・末尾予約なしだけで網羅性を独立証明するのではなく、旧コードの全通知保留・全件約定・予約なしの場合のみ位相変更という経路と合わせた確認。",
            "特徴量やD07を再計算していない。二市場結合でも市場別カウンタが独立である点をソース確認し、原板添字の実測照合は日経1場だけ。",
            "採番済み新規はB04が実際に発注を判断した機会であり、B04内部で保有制限等により発注しなかった候補まで再生する方式ではない。",
        ],
    }
    (OUT / "保存通知と判断添字の独立照合.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("saved_cases", "code_sources", "source_index_check", "limits")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
