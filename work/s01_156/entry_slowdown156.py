"""実core新規2件について、固定済み原Lastの確定1分だけで入口拒否条件を診断する。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math


HERE = Path(__file__).resolve().parent
DATA = HERE / "current_20261027"
JST = timezone(timedelta(hours=9))


def iso(value: float) -> str:
    """UNIX秒を日本時間のISO表記へ変換する。

    引数: value(float)はUNIX秒。返り値: strは日本時間のISO日時。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def verified_json(path: Path, fingerprints: dict) -> dict:
    """取得時指紋を確認してJSONを読む。

    引数: path(Path)は保存資料、fingerprints(dict)はファイル名別SHA。
    返り値: dictはJSON内容。不一致なら停止する。
    """
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == fingerprints[path.name]
    return json.loads(data)


def completed_closes(path: Path, expected: str) -> tuple[dict, dict]:
    """原Lastを価格時計の1分区間へまとめ、保存順で最終行を残す。

    引数: path(Path)は原板、expected(str)は取得時SHA。
    返り値: tupleは分開始秒別の終値と読取件数。気配の良否はLast集計に使用しない。
    """
    buckets = {}
    counts = {"rows": 0, "invalid_clock": 0, "regressed_clock": 0, "invalid_last": 0}
    digest = hashlib.sha256()
    latest = -math.inf
    with path.open("rb") as source:
        for line, raw in enumerate(source, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            counts["rows"] += 1
            row = json.loads(raw)
            try:
                at = datetime.fromisoformat(row["CurrentPriceTime"]).timestamp()
            except (ValueError, TypeError, KeyError):
                counts["invalid_clock"] += 1
                continue
            if at < latest:
                counts["regressed_clock"] += 1
                continue
            latest = at
            last = row.get("CurrentPrice")
            if not isinstance(last, (int, float)) or not math.isfinite(last) or last <= 0:
                counts["invalid_last"] += 1
                continue
            minute = math.floor(at / 60) * 60
            buckets[minute] = {"start": minute, "start_iso": iso(minute), "completed_at": iso(minute + 60),
                               "last": last, "source_line": line, "last_price_time": iso(at), "last_price_unix": at}
    assert digest.hexdigest() == expected, "固定原板の指紋が一致しません"
    return buckets, counts


def diagnose(at: str, side: int, buckets: dict, api_by_start: dict) -> dict:
    """実約定時点で完成していた連続6分からE1/E2/E3を判定する。

    引数: at(str)は実約定日時、side(int)は買1/売-1、buckets/api_by_start(dict)は原Last/API足。
    返り値: dictは終値列・先読み排除条件・各条件の診断。取引損益は計算しない。
    """
    time = datetime.fromisoformat(at).timestamp()
    current_minute = math.floor(time / 60) * 60
    closes = []
    for i in range(6):
        start = current_minute - 60 * (i + 1)
        raw = buckets.get(start)
        api = api_by_start.get(start)
        entry = {"name": f"c{i}", "expected_minute": iso(start), "raw": raw,
                 "api_close": api.get("close") if api else None,
                 "api_closed": api.get("closed") if api else None,
                 "raw_api_match": raw is not None and api is not None and raw["last"] == api["close"]}
        if raw is not None:
            assert start + 60 <= current_minute
            assert raw["last_price_unix"] < math.floor(time)
            assert raw["last_price_unix"] < current_minute
        closes.append(entry)
    known = all(r["raw"] is not None for r in closes)
    out = {"actual_entry_time": at, "side": side, "current_minute_excluded": iso(current_minute),
           "known_six_consecutive_minutes": known, "closes": closes}
    if not known:
        out["conditions"] = {name: {"reject": True, "reason": "連続1分足不足・未知拒否"} for name in ("E1", "E2", "E3")}
        return out
    c = [row["raw"]["last"] for row in closes]
    one0, one1 = side * (c[0] - c[1]), side * (c[1] - c[2])
    two, old_three = side * (c[0] - c[2]), side * (c[2] - c[5])
    out["directional_changes_points"] = {"latest_one": one0, "previous_one": one1, "latest_two": two, "older_three": old_three}
    out["conditions"] = {
        "E1": {"reject": two <= 0, "expression": "方向×(c0−c2) <= 0", "observed_points": two},
        "E2": {"reject": not (one0 > 0 and one1 > 0), "expression": "方向×(c0−c1)>0 かつ 方向×(c1−c2)>0 以外", "observed_points": [one0, one1]},
        "E3": {"reject": old_three >= 60 and two <= 20, "expression": "方向×(c2−c5)>=60 かつ 方向×(c0−c2)<=20", "observed_points": [old_three, two]},
    }
    return out


def main() -> None:
    """固定保存資料だけで2入口を診断し、JSONと短い説明を保存する。

    引数: なし。返り値: None。API取得・売買再生・約定推定は行わない。
    """
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    fingerprints = {Path(row["path"]).name: row["sha256"] for row in manifest["files"]}
    raw_path = DATA / "NK225_book.jsonl"
    buckets, counts = completed_closes(raw_path, fingerprints[raw_path.name])
    api = verified_json(DATA / "NK225_candles_1min.json", fingerprints)
    state = verified_json(DATA / "app_state.json", fingerprints)
    api_by_start = {datetime.fromisoformat(row["time"]).timestamp(): row for row in api["data"]}
    trades = next(row for row in state["products"] if row["product"] == "NK225mini")["detached_snapshot"]["recent_trades"]
    selected = [row for row in trades if row["owner"] == "core" and row["action"] == "new"]
    assert len(selected) == 2
    cases = [diagnose(row["at"], 1 if row["side"] == "buy" else -1, buckets, api_by_start) for row in selected]
    assert all(v["raw_api_match"] for c in cases for v in c["closes"]), "当時原LastとAPI確定足が一致しません"
    out = {"spec": {"data": "日経ラージ原Lastのみ", "clock": "CurrentPriceTime。独立受信時刻は未取得",
                    "c0": "実約定の属する分の直前に完了した1分バケット最終Last", "same_second_excluded": True,
                    "unfinished_minute_excluded": True, "missing_minutes": "連続6分不足なら未知として拒否",
                    "api_role": "固定API足は照合だけ。判定には原Lastから復元した終値を使用",
                    "trading_replay": False, "avoided_pnl_calculated": False},
           "source_sha256": {name: fingerprints[name] for name in ["NK225_book.jsonl", "NK225_candles_1min.json", "app_state.json"]},
           "raw_read_counts": counts, "cases": cases}
    (HERE / "実入口の失速条件156.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 実入口2件の失速条件", "", "日経ラージ原Lastだけから、実新規時点で完了していた連続1分終値を復元した。API足の終値12個とも一致。**これは入口条件だけの診断で、返済の変更や避けられた損失は計算していない。**", "",
             "| 実新規 | 直近2分 c0−c2 | 直近1分／その前1分 | その前3分 c2−c5 | E1 | E2 | E3 |",
             "|---|---:|---:|---:|---|---|---|"]
    for c in cases:
        d = c["directional_changes_points"]
        answers = ["拒否" if c["conditions"][name]["reject"] else "通過" for name in ("E1", "E2", "E3")]
        lines.append(f'| {c["actual_entry_time"][11:19]} 買い | {d["latest_two"]:+g}pt | {d["latest_one"]:+g}／{d["previous_one"]:+g}pt | {d["older_three"]:+g}pt | {" | ".join(answers)} |')
    lines += ["", "E1は直近2分の順行が0以下なら拒否。E2は連続2本とも順行していなければ拒否。E3は以前3分が60pt以上順行し、直近2分が20pt以下なら拒否。今回はどちらも買いなので方向は＋1。", "", "## 根拠の確定終値", "", "| 実入口 | 呼称 | 1分区間の開始 | 原Last | 最後の価格時計 | 原行番号 | API終値一致 |", "|---|---|---|---:|---|---:|---|"]
    for c in cases:
        for row in reversed(c["closes"]):
            r = row["raw"]
            lines.append(f'| {c["actual_entry_time"][11:19]} | {row["name"]} | {r["start_iso"][11:16]} | {r["last"]:,.0f} | {r["last_price_time"][11:19]} | {r["source_line"]} | 一致 |')
    lines += ["", "## 15時の上向きと確定2分の停滞は両立する", "", "先の原板図の『10〜180秒が上向き』は、**15:00:07までの最新中値**を使う比較。今回の条件は15:00分を丸ごと除き、**14:59分までの確定Last終値**を比べる。観測の終点と価格種別が違うため、矛盾ではない。15時に始まった上昇を追いかける一方、その直前の完成2分は停滞していた、という別々の情報である。", "", "この拒否条件が一般に有効とはまだいえない。完成2分が横ばいでも、その直後の上抜けが大きな利益になる例はあり得る。全デイの同条件比較で、消えた勝ちも集計する必要がある。", "", "時計は価格時計の代理であり、実受信時刻を復元したものではない。当分と約定同秒は不使用、欠落分の補間なし。原行順を保持して分内最後のLastを採り、事後の高値・安値や未完成分の終値は使っていない。", "", "[判定値・原行・指紋JSON](実入口の失速条件156.json)／[スクリプト](entry_slowdown156.py)／[比較対象の原板診断](実約定3区間の診断156.md)"]
    (HERE / "実入口の失速条件156.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps([{"at": c["actual_entry_time"], "changes": c["directional_changes_points"], "reject": {name: v["reject"] for name, v in c["conditions"].items()}} for c in cases], ensure_ascii=True))


if __name__ == "__main__":
    main()
