"""選定済み00131に対する追加素材を読取専用で棚卸しする。金融再生は行わない。"""

import csv
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TIME = re.compile(rb'"CurrentPriceTime"\s*:\s*(?:"([^"]+)"|null)')


def read(path):
    """
    機能: 日本語の既存証拠JSONを読み取る。
    引数: path(Path) はファイル。
    返り値: dict又はlist は保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def summarize(path):
    """
    機能: 原本を変更せず最新素材の指紋、行数、時計範囲を測定する。
    引数: path(Path) は生板JSONL又は足CSV。
    返り値: dict は素材の検査値。板本文は先頭末尾のみ復号し、価格時計は全原行から抽出する。
    """
    before = path.stat()
    result = {"path": path.relative_to(ROOT).as_posix(), "bytes": before.st_size,
              "mtime_ns": before.st_mtime_ns}
    digest = hashlib.sha256()
    if path.suffix == ".csv":
        body = path.read_bytes()
        digest.update(body)
        rows = list(csv.DictReader(body.decode("utf-8-sig").splitlines()))
        result.update(rows=len(rows), first=rows[0] if rows else None,
                      last=rows[-1] if rows else None,
                      unclosed=sum(r.get("closed", "").lower() != "true" for r in rows),
                      duplicate_times=len(rows)-len({r["time"] for r in rows}))
    else:
        day, kind = path.stem.split("_")
        start = datetime.fromisoformat(day + ("T08:45:00+09:00" if kind == "Day" else "T17:00:00+09:00"))
        end = start.replace(hour=15, minute=45) if kind == "Day" else (start+timedelta(days=1)).replace(hour=6, minute=0)
        count = nulls = previous_session = after_end = backwards = valid_count = 0
        first_line = last_line = first_in = last_in = highest = previous = None
        with path.open("rb") as stream:
            for line in stream:
                digest.update(line)
                if not line.strip():
                    continue
                count += 1
                if first_line is None:
                    first_line = line
                last_line = line
                match = TIME.search(line)
                if match is None or match.group(1) is None:
                    nulls += 1
                    continue
                clock = datetime.fromisoformat(match.group(1).decode("utf-8"))
                if previous is not None and clock < previous:
                    backwards += 1
                previous = clock
                if clock < start:
                    previous_session += 1
                    continue
                if clock > end:
                    after_end += 1
                    continue
                valid_count += 1
                if first_in is None:
                    first_in = clock
                last_in = clock
                highest = max(highest, clock) if highest else clock
        def edge(line):
            """
            機能: 先頭末尾の価格と価格時計を抽出する。
            引数: line(bytes又はNone) は原行。
            返り値: dict又はNone は価格観測。
            """
            if line is None:
                return None
            value = json.loads(line)
            return {key: value.get(key) for key in ("CurrentPriceTime", "CurrentPrice", "Symbol")}
        result.update(rows=count, first=edge(first_line), last=edge(last_line),
                      null_price_clocks=nulls, earlier_session_clocks=previous_session,
                      after_end_clocks=after_end, backwards_price_clocks=backwards,
                      session_price_rows=valid_count,
                      first_session_price_clock=first_in.isoformat() if first_in else None,
                      last_session_price_clock=last_in.isoformat() if last_in else None,
                      latest_session_price_clock=highest.isoformat() if highest else None,
                      reaches_force_close=bool(highest and highest >= end-timedelta(seconds=600)),
                      reaches_last_six_minutes=bool(highest and highest >= end-timedelta(seconds=360)))
    result["sha256"] = digest.hexdigest()
    after = path.stat()
    result["unchanged_during_read"] = before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
    return result


def main():
    """
    機能: 既存43場との差分と最新5場の完全性を保存する。
    引数: なし。
    返り値: None。
    """
    old = read(ROOT / "work/regime131_20261020/公開候補の43場統合.json")
    old_sessions = {r["session"] for r in old["rows"]}
    files = {}
    for kind, ext in (("book", ".jsonl"), ("candle_1min", ".csv"), ("candle_5min", ".csv")):
        for symbol in ("TOPIX", "NK225"):
            files[(kind, symbol)] = {p.stem: p for p in (ROOT / kind / symbol).glob("*"+ext)}
    sessions = set.union(*(set(v) for v in files.values()))
    complete = set.intersection(*(set(v) for v in files.values()))
    latest = sorted(sessions)[-5:]
    selected = [mapping[s] for mapping in files.values() for s in latest if s in mapping]
    with ThreadPoolExecutor(max_workers=2) as pool:
        material = list(pool.map(summarize, selected))
    expected = {}
    origin = ROOT / "work/stability124_20261019/e01c/所有六素材のconsumer資格表示.json"
    for item in read(origin)["read_log"]:
        expected[item["path"]] = {"sha256": item["sha256"], "bytes": item["bytes"], "source": origin.relative_to(ROOT).as_posix()}
    origin = ROOT / "work/stability126_20261019/update_20261020/終了済み追加二場の取得.json"
    for item in read(origin)["files"]:
        key = item["path"].split("/stage/", 1)[1]
        expected[key] = {"sha256": item["sha256"], "bytes": item["bytes"], "source": origin.relative_to(ROOT).as_posix()}
    comparisons = []
    for item in material:
        if item["path"] in expected:
            prior = expected[item["path"]]
            comparisons.append({"path": item["path"], "old": prior,
                                "bytes_equal": prior["bytes"] == item["bytes"],
                                "sha256_equal": prior["sha256"] == item["sha256"]})
    result = {"old_session_count": len(old_sessions), "present_common_session_count": len(complete),
              "new_complete_file_sets": sorted(complete-old_sessions),
              "missing_file_sets": {s: ["/".join(key) for key, mapping in files.items() if s not in mapping]
                                    for s in sorted(sessions-complete)},
              "latest_five_sessions": latest, "materials": material,
              "prior_source_comparisons": comparisons,
              "old_earlier_sessions": "直近3場以外は今回原本の内容指紋を再測定していない。保存済み00131会計を再利用する。",
              "financial_replays": 0, "api_reads": 0, "source_writes": 0}
    (OUT / "最新素材の棚卸し.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("materials", "prior_source_comparisons")}, ensure_ascii=False))
    for item in material:
        if item["path"].startswith("book/"):
            print(json.dumps(item, ensure_ascii=False))
    print("既存指紋比較", len(comparisons), "一致", sum(x["sha256_equal"] for x in comparisons))


if __name__ == "__main__":
    main()
