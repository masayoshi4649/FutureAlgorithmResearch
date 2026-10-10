"""条件凍結後に現在の日中を一度だけ保存し、凍結候補群の答え合わせを行う。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import pandas as pd

from engine import Config, TICKS, prepare
from research import OUT, ROOT, SYMBOLS, evaluate, evaluate_by_symbol, save_json, summary
from signals import build_features

SNAPSHOT = OUT / "一度取得_2026-09-23_Day"
SESSION = "2026-09-23_Day"


def fetch_one(name: str, url: str) -> dict:
    """機能: 指定URLを一度だけ読み、取得結果とハッシュを残す。

    引数: name/url (str)。返り値: 成否・時刻・応答ハッシュ (dict)。再試行しない。
    """
    record = dict(name=name, url=url, started=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat())
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            value = response.read()
            record["http_status"] = response.status
        (SNAPSHOT / name).write_bytes(value)
        record.update(ok=True, bytes=len(value), sha256=hashlib.sha256(value).hexdigest())
    except Exception as error:
        record.update(ok=False, error=f"{type(error).__name__}: {error}")
    record["finished"] = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()
    return record


def freeze_check() -> dict:
    """機能: 答え合わせ前にコードと候補が凍結記録通りかを確認する。

    引数: なし。返り値: 凍結記録 (dict)。
    """
    fixed = json.loads((OUT / "固定設定.json").read_text(encoding="utf-8"))
    for relative, expected in fixed["code_sha256"].items():
        actual = hashlib.sha256((OUT / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"凍結後のコード変更: {relative}")
    return fixed


def fetch_once() -> None:
    """機能: 保存済み候補を確認して、共通締切の日中データを各URL一回だけ取得する。

    引数: なし。返り値: なし (None)。取得開始記録があれば再取得を拒否する。
    """
    fixed = freeze_check()
    marker = SNAPSHOT / "取得開始.json"
    if marker.exists():
        raise RuntimeError("現在データは既に取得開始済みです。保存物を再利用してください")
    now = pd.Timestamp.now(tz="Asia/Tokyo")
    if now.strftime("%Y-%m-%d") != "2026-09-23" or not 8 <= now.hour < 17:
        raise RuntimeError("指定日の日中セッションの取得時刻ではありません")
    cutoff = min(now.floor("min"), pd.Timestamp("2026-09-23T15:40:00+09:00"))
    SNAPSHOT.mkdir(exist_ok=True)
    save_json(marker, dict(開始=now, cutoff=cutoff, 固定時刻=fixed["fixed_at"], 再試行なし=True))
    query = urllib.parse.urlencode({"from": "2026-09-23T08:45:00+09:00", "to": cutoff.isoformat()})
    base = "http://10.10.100.1:8080/api/v1/history"
    requests = [("status.json", f"{base}/status")]
    for symbol in SYMBOLS:
        requests.extend([(f"{symbol}_1min.json", f"{base}/{symbol}/candles/1min?{query}"),
                         (f"{symbol}_5min.json", f"{base}/{symbol}/candles/5min?{query}"),
                         (f"{symbol}_book.jsonl", f"{base}/{symbol}/book?{query}")])
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(fetch_one, name, url) for name, url in requests]
        records = [future.result() for future in futures]
    save_json(SNAPSHOT / "取得記録.json", dict(cutoff=cutoff, requests=records, 各URLの試行回数=1))
    if not all(record["ok"] for record in records):
        raise RuntimeError("一部の取得に失敗しました。再試行せず取得記録を確認してください")
    print(json.dumps(dict(共通締切=str(cutoff), URL数=len(records), 取得バイト合計=sum(record["bytes"] for record in records)), ensure_ascii=False))


def extract_books(cutoff: pd.Timestamp) -> None:
    """機能: 保存した現在板を既存の保守的利用時刻の定義で一分特徴にする。

    引数: cutoff (Timestamp)。返り値: なし (None)。通信を行わない。
    """
    import csv
    spec = importlib.util.spec_from_file_location("保存板抽出器", OUT.parent / "wave_v2" / "book_features.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for symbol in SYMBOLS:
        destination = SNAPSHOT / f"板特徴_{symbol}_{SESSION}.csv"
        if destination.exists():
            continue
        extractor = module.Extractor(pd.Timestamp("2026-09-23T08:45:00+09:00").to_pydatetime(), cutoff.to_pydatetime(), TICKS[symbol])
        with (SNAPSHOT / f"{symbol}_book.jsonl").open(encoding="utf-8-sig") as stream:
            for line in stream:
                if line.strip():
                    extractor.accept(json.loads(line))
        rows = extractor.rows(symbol, SESSION)
        with destination.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=module.FIELDS)
            writer.writeheader()
            writer.writerows(rows)


def load_snapshot() -> dict:
    """機能: 一度取得した日中を確定締切で切り、比較用の入力に変換する。

    引数: なし。返り値: 再生入力 (dict)。
    """
    meta = json.loads((SNAPSHOT / "取得記録.json").read_text(encoding="utf-8"))
    cutoff = pd.Timestamp(meta["cutoff"])
    extract_books(cutoff)
    data = {}
    for symbol in SYMBOLS:
        frames = {}
        for minutes in (1, 5):
            payload = json.loads((SNAPSHOT / f"{symbol}_{minutes}min.json").read_text(encoding="utf-8"))
            frame = pd.DataFrame(payload["data"])
            frame["time"] = pd.to_datetime(frame.time)
            frame = frame[frame.closed & (frame.time + pd.Timedelta(minutes=minutes) <= cutoff)].set_index("time").sort_index()
            if frame.index.duplicated().any() or frame.empty:
                raise ValueError("答え合わせ足が空か重複しています")
            frames[minutes] = frame
        one, five = frames[1], frames[5]
        z = build_features(one, five, SNAPSHOT / f"板特徴_{symbol}_{SESSION}.csv", TICKS[symbol], cutoff.floor("min")-pd.Timedelta(minutes=1))
        data[(SESSION, symbol)] = prepare(one, z, symbol, SESSION)
    return data


def replay() -> None:
    """機能: 固定済み候補群を現在データへ適用し、再選択せず全結果を保存する。

    引数: なし。返り値: なし (None)。
    """
    fixed = freeze_check()
    data = load_snapshot()
    records = []
    for candidate in fixed["candidates"]:
        cfg = Config(**candidate["config"])
        trades, targets, cells = evaluate(data, cfg)
        row = summary(cfg, trades, targets, cells)
        row["selected_before_current"] = cfg.key == Config(**fixed["config"]).key
        records.append(row)
        if row["selected_before_current"]:
            save_json(OUT / "答え合わせ_共通候補.json", dict(config=candidate["config"], summary=row, trades=trades, targets=targets, cells=cells))
        save_json(SNAPSHOT / f"評価_{cfg.key}.json", dict(summary=row, trades=trades, targets=targets, cells=cells))
    pd.DataFrame(records).to_csv(OUT / "答え合わせ_全固定候補.csv", index=False, encoding="utf-8-sig")
    if "symbol_configs" in fixed:
        trades, targets, cells = evaluate_by_symbol(data, fixed["symbol_configs"])
        save_json(OUT / "答え合わせ_採用.json", dict(symbol_configs=fixed["symbol_configs"], trades=trades, targets=targets, cells=cells))
    if "alternative_symbol_configs" in fixed:
        trades, targets, cells = evaluate_by_symbol(data, fixed["alternative_symbol_configs"])
        save_json(OUT / "答え合わせ_銘柄別対照.json", dict(symbol_configs=fixed["alternative_symbol_configs"], trades=trades, targets=targets, cells=cells))
    print(pd.DataFrame(records)[["family", "entry", "target_pass", "NK225_net", "TOPIX_net", "selected_before_current"]].to_json(orient="records", force_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="条件凍結後一度だけの現在データ答え合わせ")
    parser.add_argument("mode", choices=("fetch", "replay"))
    args = parser.parse_args()
    fetch_once() if args.mode == "fetch" else replay()
