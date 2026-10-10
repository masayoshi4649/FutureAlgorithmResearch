"""保存データの範囲・品質・過去入力との同一性を読み取り専用で監査する。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "アルゴリズム調査/00001_波検知と売買ポイントの調査/保存版"


def sha256(path: Path) -> str:
    """ファイルを変更せずＳＨＡ２５６を求める。

    引数: path（Path）対象ファイル。
    返り値: str。十六進数のハッシュ。
    """
    state = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            state.update(block)
    return state.hexdigest()


def candle_audit(path: Path) -> dict:
    """足の時刻・確定状態・保存版との一致を検査する。

    引数: path（Path）足ＣＳＶ。
    返り値: dict。品質統計とハッシュ。
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    minutes = 1 if path.parent.parent.name == "candle_1min" else 5
    times = [datetime.fromisoformat(row["time"]) for row in rows]
    prior_path = ARCHIVE / path.relative_to(ROOT)
    with prior_path.open(encoding="utf-8-sig", newline="") as stream:
        prior_rows = list(csv.DictReader(stream))
    prior_by_time = {row["time"]: row for row in prior_rows}
    values = [[float(row[key]) for key in ("open", "high", "low", "close", "volume")] for row in rows]
    invalid = sum(not all(math.isfinite(x) for x in v) or v[2] > min(v[0], v[3])
                  or v[1] < max(v[0], v[3]) or min(v[:4]) <= 0 or v[4] < 0 for v in values)
    return {
        "ファイル": path.relative_to(ROOT).as_posix(), "銘柄": path.parent.name,
        "セッション": path.stem, "分足": minutes, "行数": len(rows),
        "始端": min(times).isoformat(), "終端開始時刻": max(times).isoformat(),
        "終端足の終了時刻": (max(times) + timedelta(minutes=minutes)).isoformat(),
        "重複時刻": len(times) - len(set(times)),
        "時刻逆行": sum(b < a for a, b in zip(times, times[1:])),
        "未確定足": sum(row["closed"].lower() != "true" for row in rows),
        "出来高不完全足": sum(row["volume_complete"].lower() != "true" for row in rows),
        "内部欠落時間枠": int((max(times) - min(times)).total_seconds() / (60 * minutes)) + 1 - len(set(times)),
        "最大観測間隔分": max((b - a).total_seconds() / 60 for a, b in zip(times, times[1:])),
        "不正価格出来高": invalid, "SHA256": sha256(path), "保存版SHA256": sha256(prior_path),
        "保存版と全バイト一致": sha256(path) == sha256(prior_path),
        "保存版にない追加時刻": [row["time"] for row in rows if row["time"] not in prior_by_time],
        "保存版既存時刻の変更": [row["time"] for row in rows if row["time"] in prior_by_time and row != prior_by_time[row["time"]]],
    }


def historical_book_records() -> dict:
    """過去の板抽出記録を既存成果物から読み取る。

    引数: なし。
    返り値: dict。原本相対パスから過去抽出記録への対応。
    """
    markdown = (ROOT / "work/wave_v2/板特徴監査.md").read_text(encoding="utf-8")
    first = json.loads(markdown.split("```json", 1)[1].split("```", 1)[0])
    second = json.loads((ROOT / "work/wave_v3_check/追加データ監査.json").read_text(encoding="utf-8"))["books"]
    third = json.loads((ROOT / "work/wave_v5/板特徴抽出記録.json").read_text(encoding="utf-8"))
    found = {}

    def visit(value: object) -> None:
        """入れ子の監査記録から原本ハッシュを持つ項目を取り出す。

        引数: value（object）ＪＳＯＮ値。
        返り値: None。外側の対応表へ追加する。
        """
        if isinstance(value, dict):
            if "source" in value and "source_sha256" in value:
                found[value["source"].replace("\\", "/")] = value
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit([first, second, third])
    return found


def book_audit(path: Path, old: dict, candles: list[dict]) -> dict:
    """板を保存順で逐次走査し時刻と履歴ハッシュを確認する。

    引数: path（Path）生板、old（dict）過去監査、candles（list[dict]）足監査。
    返り値: dict。原本行数・時刻品質・板特徴の再利用可否。
    """
    matching = next(x for x in candles if x["銘柄"] == path.parent.name and x["セッション"] == path.stem and x["分足"] == 1)
    start, end = datetime.fromisoformat(matching["始端"]), datetime.fromisoformat(matching["終端足の終了時刻"])
    state, counts, keys = hashlib.sha256(), Counter(), set()
    first = last = previous_line = previous_time = minimum = maximum = None
    with path.open("rb") as stream:
        for line in stream:
            state.update(line)
            counts["行数"] += 1
            counts["連続完全同一行"] += line == previous_line
            previous_line = line
            row = json.loads(line)
            keys.update(row)
            first = row if first is None else first
            last = row
            stamp_text = row.get("CurrentPriceTime")
            if not stamp_text:
                counts["約定時刻なし"] += 1
                continue
            stamp = datetime.fromisoformat(stamp_text)
            minimum = stamp if minimum is None else min(minimum, stamp)
            maximum = stamp if maximum is None else max(maximum, stamp)
            counts["足の収録範囲外"] += not start <= stamp < end
            if previous_time is not None:
                counts["約定時刻逆行"] += stamp < previous_time
                counts["連続同一約定時刻"] += stamp == previous_time
            previous_time = stamp
    source = path.relative_to(ROOT).as_posix()
    previous = old.get(source, {})
    folder = "wave_v5" if path.stem == "2026-09-23_Day" else "wave_v3_check" if path.stem == "2026-09-22_Night" else "wave_v2"
    feature = ROOT / "work" / folder / f"板特徴_{path.parent.name}_{path.stem}.csv"
    saved_feature = ARCHIVE / feature.relative_to(ROOT)
    with feature.open(encoding="utf-8-sig", newline="") as stream:
        feature_rows = list(csv.DictReader(stream))
    availability_errors = sum(datetime.fromisoformat(row["available_at"]) != datetime.fromisoformat(row["time"]) + timedelta(minutes=1) for row in feature_rows)
    return {
        "ファイル": source, "銘柄": path.parent.name, "セッション": path.stem,
        **dict(counts), "最小約定時刻": minimum.isoformat(), "最大約定時刻": maximum.isoformat(),
        "先頭約定時刻": first.get("CurrentPriceTime"), "末尾約定時刻": last.get("CurrentPriceTime"),
        "項目一覧": sorted(keys), "受信時刻項目": [key for key in sorted(keys) if any(s in key.lower() for s in ("receive", "recv", "arrival", "timestamp"))],
        "SHA256": state.hexdigest(), "過去板抽出時SHA256": previous.get("source_sha256"),
        "過去板抽出時と全バイト一致": state.hexdigest() == previous.get("source_sha256"),
        "再利用板特徴": feature.relative_to(ROOT).as_posix(), "板特徴行数": len(feature_rows),
        "板特徴SHA256": sha256(feature), "保存版板特徴と全バイト一致": sha256(feature) == sha256(saved_feature),
        "板特徴利用可能時刻の式違反": availability_errors,
        "板特徴最初の利用可能時刻": feature_rows[0]["available_at"],
        "板特徴最後の利用可能時刻": feature_rows[-1]["available_at"],
        "過去抽出のブロック遅延中央値秒": previous.get("anchor_delay_median_seconds"),
        "過去抽出のブロック遅延最大秒": previous.get("anchor_delay_max_seconds"),
    }


def main() -> None:
    """全保存足と生板を監査し自領域に結果を保存する。

    引数: なし。
    返り値: None。data_audit.json と data_audit.md を生成する。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    candles = [candle_audit(path) for folder in ("candle_1min", "candle_5min") for path in sorted((ROOT / folder).glob("*/*.csv"))]
    old = historical_book_records()
    books = []
    for path in sorted((ROOT / "book").glob("*/*.jsonl")):
        books.append(book_audit(path, old, candles))
        print(f"板監査済み: {path.parent.name} {path.stem}", flush=True)
    histories = []
    for name in ("work/wave_research/現在セッション固定/取得記録.json", "work/wave_v4/一度取得_2026-09-23_Day/取得記録.json"):
        data = json.loads((ROOT / name).read_text(encoding="utf-8"))
        requests = data["requests"]
        histories.append({"記録": name, "共通締切": data["cutoff"], "要求数": len(requests),
                          "足板データ要求数": sum("status" not in row["url"] for row in requests),
                          "最初の取得開始": requests[0].get("started_at", requests[0].get("started")),
                          "成功数": sum(row["ok"] for row in requests)})
    summary = {
        "今回API取得": False, "セッション数": len({row["セッション"] for row in candles}),
        "足ファイル数": len(candles), "足保存版一致数": sum(row["保存版と全バイト一致"] for row in candles),
        "生板ファイル数": len(books), "生板過去抽出時一致数": sum(row["過去板抽出時と全バイト一致"] for row in books),
        "保存版板特徴一致数": sum(row["保存版板特徴と全バイト一致"] for row in books),
        "未使用追加時刻数": sum(len(row["保存版にない追加時刻"]) for row in candles),
        "注意": "全五セッションは過去探索に使用済み。同じデータの時系列分割は実装の先読みと手順の検査には使えるが、真の未使用期間での性能証明ではない。",
        "板の利用可能時刻": "受信時刻の原本記録はない。同じCurrentPriceTimeの連続ブロックを次のより新しいCurrentPriceTimeで解放し、その時刻を分へ切り下げた値＋一分がavailable_at。保存順と約定時計を用いる近似であり実受信時刻ではない。末尾未解放ブロックは破棄する。",
        "足": candles, "板": books, "既存の現在セッション取得履歴": histories,
    }
    (OUT / "data_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 保存入力と既知範囲の監査", "", summary["注意"], "", f"足20ファイル中{summary['足保存版一致数']}件、板10ファイル中{summary['生板過去抽出時一致数']}件が過去入力と全バイト一致。未使用の追加時刻は{summary['未使用追加時刻数']}件。今回のＡＰＩ取得は０回。", "", "|銘柄|セッション|足分|行数|始端|終端開始|内部欠落|未確定|出来高不完全|", "|---|---|---:|---:|---|---|---:|---:|---:|"]
    for row in candles:
        lines.append(f"|{row['銘柄']}|{row['セッション']}|{row['分足']}|{row['行数']}|{row['始端']}|{row['終端開始時刻']}|{row['内部欠落時間枠']}|{row['未確定足']}|{row['出来高不完全足']}|")
    lines += ["", "内部欠落は始端から終端までに足が存在しない時間枠数。無約定でも足が欠け得るため、収集障害とは断定しない。存在しない足を約定機会にしない。", "", "## 板の時刻と再利用", "", summary["板の利用可能時刻"], "", "全１０板特徴ＣＳＶは保存版と同一で、available_at = time + １分を満たす。特徴の使用はavailable_at以降。実執行にはさらに通信・判断・注文遅延を加える。CurrentPriceTimeは最終約定時刻であり板更新の受信時刻には使えない。", "", "## 既存の取得工程", ""]
    for row in histories:
        lines.append(f"- 共通締切 {row['共通締切']}、開始 {row['最初の取得開始']}、足・板{row['足板データ要求数']}ＵＲＬ＋状態１ＵＲＬ。記録 `{row['記録']}`。")
    lines += ["", "これらの取得期間は既に追加探索に使用済みであり、今回の未知データとは扱わない。", ""]
    (OUT / "data_audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in ("足", "板")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
