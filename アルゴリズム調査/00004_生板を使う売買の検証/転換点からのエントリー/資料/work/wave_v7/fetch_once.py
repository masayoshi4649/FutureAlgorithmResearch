"""凍結済みコード・モデルを照合した後だけ現在セッションを一度保存する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
LIVE = OUT / "live"
FROZEN = OUT / "凍結記録.json"
JST = ZoneInfo("Asia/Tokyo")
SYMBOLS = ("NK225", "TOPIX")
BASE_URL = "http://10.10.100.1:8080/api/v1/history"
EXTRACTOR = ROOT / "work/wave_v2/book_features.py"
CANDLE_FIELDS = ("time", "open", "high", "low", "close", "volume", "volume_complete", "closed")


def now_jst() -> datetime:
    """日本時間の現在時刻を返す。

    引数: なし。
    返り値: datetime。タイムゾーン付き現在時刻。
    """
    return datetime.now(JST)


def sha256(path: Path) -> str:
    """ファイルを読み取り専用でハッシュ化する。

    引数: path（Path）対象。
    返り値: str。ＳＨＡ２５６の十六進表現。
    """
    state = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            state.update(chunk)
    return state.hexdigest()


def write_json(path: Path, value: object) -> None:
    """自領域の監査記録をＵＴＦ８で保存する。

    引数: path（Path）保存先、value（object）ＪＳＯＮ化可能な値。
    返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_stamp(value: object) -> datetime:
    """タイムゾーン付き日時だけを受け付ける。

    引数: value（object）ＩＳＯ日時文字列。
    返り値: datetime。日本時間にそろえた日時。
    """
    if not isinstance(value, str):
        raise ValueError("日時が文字列ではありません")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("タイムゾーンのない日時です")
    return stamp.astimezone(JST)


def freeze_check() -> dict:
    """取得前に凍結コード・モデル・抽出器の全ハッシュを照合する。

    引数: なし。
    返り値: dict。照合済みの凍結記録。失敗時は通信を行わない。
    凍結記録の files_sha256 はプロジェクトルート基準の相対パスとハッシュの対応。
    """
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    fixed_at = parse_stamp(frozen["fixed_at"])
    if fixed_at > now_jst():
        raise ValueError("凍結日時が現在より未来です")
    files = frozen.get("files_sha256")
    if not isinstance(files, dict) or not files:
        raise ValueError("凍結記録に files_sha256 がありません")
    checked = set()
    for relative, expected in files.items():
        target = (ROOT / relative).resolve()
        if not target.is_relative_to(ROOT.resolve()) or not re.fullmatch(r"[0-9a-fA-F]{64}", str(expected)):
            raise ValueError(f"凍結記録のパスまたはハッシュが不正です: {relative}")
        if sha256(target) != expected.lower():
            raise RuntimeError(f"凍結後にファイルが変更されています: {relative}")
        checked.add(target)
    if Path(__file__).resolve() not in checked or EXTRACTOR.resolve() not in checked:
        raise ValueError("fetch_once.py と板抽出器を凍結対象に含めてください")
    if not any(path.suffix.lower() in (".npz", ".pt", ".pth", ".pkl", ".joblib", ".onnx") for path in checked):
        raise ValueError("凍結対象に保存済みモデルがありません")
    return frozen


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """一回の要求を別ＵＲＬへ自動的に再送しないＨＴＴＰ処理。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """リダイレクト先への追加要求を拒否する。

        引数: req・fp・headers（object）応答、code（int）状態、msg・newurl（str）説明と転送先。
        返り値: None。標準処理が元の転送応答を例外として扱う。
        """
        return None


def fetch_one(name: str, url: str, destination: Path) -> dict:
    """一つのＵＲＬを再試行なしで一度読み、応答をそのまま保存する。

    引数: name・url（str）識別子とＵＲＬ、destination（Path）live 内の保存先。
    返り値: dict。成功・失敗、開始終了時刻、バイト数とハッシュ。
    """
    record = {"name": name, "url": url, "started_at": now_jst().isoformat(), "attempts": 1, "timeout_seconds": 45}
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(url, timeout=45) as response, destination.open("xb") as stream:
            record["http_status"] = response.status
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        record.update(ok=True, bytes=destination.stat().st_size, sha256=sha256(destination))
    except Exception as error:
        record.update(ok=False, error=f"{type(error).__name__}: {error}")
        if destination.exists():
            record.update(partial_bytes=destination.stat().st_size, partial_sha256=sha256(destination))
    record["finished_at"] = now_jst().isoformat()
    record["path"] = destination.relative_to(ROOT).as_posix()
    write_json(LIVE / "要求記録" / f"{name}.json", record)
    return record


def identify_session(payload: object, cutoff: datetime) -> tuple[str, datetime, datetime]:
    """状態応答の両銘柄から現在のセッションを確定する。

    引数: payload（object）状態ＪＳＯＮ、cutoff（datetime）共通締切。
    返り値: tuple[str, datetime, datetime]。識別子、開始、終了時刻。
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("current"), list):
        raise ValueError("状態応答の current 配列がありません")
    current = {symbol: [row for row in payload["current"] if row.get("code") == symbol] for symbol in SYMBOLS}
    if any(len(rows) != 1 for rows in current.values()):
        raise ValueError("状態応答に両銘柄が一件ずつ存在しません")
    ids = {rows[0].get("sessionId") for rows in current.values()}
    if len(ids) != 1:
        raise ValueError("両銘柄のセッションが一致しません")
    session = ids.pop()
    if not isinstance(session, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}_(Day|Night)", session):
        raise ValueError("セッション識別子が不正です")
    midnight = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    if cutoff.hour >= 17:
        expected = midnight.strftime("%Y-%m-%d") + "_Night"
    elif cutoff >= midnight + timedelta(hours=8, minutes=45):
        expected = midnight.strftime("%Y-%m-%d") + "_Day"
    else:
        expected = (midnight - timedelta(days=1)).strftime("%Y-%m-%d") + "_Night"
    if session != expected:
        raise ValueError(f"状態応答が現在の時間帯と異なります: 応答={session}, 期待={expected}")
    day = datetime.strptime(session[:10], "%Y-%m-%d").replace(tzinfo=JST)
    start = day + (timedelta(hours=17) if session.endswith("Night") else timedelta(hours=8, minutes=45))
    end = day + (timedelta(days=1, hours=6) if session.endswith("Night") else timedelta(hours=15, minutes=45))
    return session, start, end


def convert_candles(path: Path, symbol: str, minutes: int, session: str, start: datetime, end: datetime, cutoff: datetime) -> dict:
    """応答の所属と品質を検査し確定足だけを元ＣＳＶ形式へ変換する。

    引数: path（Path）応答、symbol・session（str）所属、minutes（int）足分数、start・end・cutoff（datetime）範囲。
    返り値: dict。変換行数、除外数、時刻範囲、出力ハッシュ。
    """
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or not isinstance(payload.get("snapshot"), dict):
        raise ValueError("足応答の data または snapshot がありません")
    snapshot = payload["snapshot"]
    if snapshot.get("code") != symbol or snapshot.get("sessionId") != session:
        raise ValueError(f"足応答が別の銘柄またはセッションです: {symbol} {minutes}分")
    bounds = snapshot.get("session", {})
    if parse_stamp(bounds.get("startsAt")) != start or parse_stamp(bounds.get("endsAt")) != end:
        raise ValueError("足応答のセッション開始・終了時刻が一致しません")
    as_of = parse_stamp(snapshot.get("asOf"))
    if as_of < cutoff:
        raise ValueError("応答の作成時刻が共通締切より古いため、今回のスナップショットとして使用しません")
    retained, previous, excluded = [], None, 0
    for row in payload["data"]:
        stamp = parse_stamp(row.get("time"))
        if not start <= stamp < min(end, cutoff) or stamp.second or stamp.microsecond or stamp.minute % minutes:
            raise ValueError(f"足時刻が取得範囲外または足境界外です: {stamp}")
        if previous is not None and stamp <= previous:
            raise ValueError("足時刻が重複または逆行しています")
        previous = stamp
        if not isinstance(row.get("closed"), bool) or not isinstance(row.get("volumeComplete"), bool):
            raise ValueError("足の確定・出来高完全フラグが真偽値ではありません")
        values = [row.get(key) for key in ("open", "high", "low", "close", "volume")]
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in values):
            raise ValueError("足の価格または出来高が不正です")
        opening, high, low, close, volume = values
        if min(values[:4]) <= 0 or low > min(opening, close) or high < max(opening, close) or volume < 0:
            raise ValueError("足の高安関係または出来高が不正です")
        if not row["closed"] or stamp + timedelta(minutes=minutes) > min(cutoff, end):
            excluded += 1
            continue
        retained.append({"time": stamp.isoformat(), **dict(zip(("open", "high", "low", "close", "volume"), values)),
                         "volume_complete": str(row["volumeComplete"]).lower(), "closed": "true"})
    if not retained:
        raise ValueError(f"確定済み足がありません: {symbol} {minutes}分")
    destination = LIVE / f"candle_{minutes}min" / symbol / f"{session}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CANDLE_FIELDS)
        writer.writeheader()
        writer.writerows(retained)
    return {"symbol": symbol, "minutes": minutes, "received_rows": len(payload["data"]), "rows": len(retained),
            "excluded_unclosed_or_after_cutoff": excluded, "first": retained[0]["time"], "last": retained[-1]["time"],
            "path": destination.relative_to(ROOT).as_posix(), "sha256": sha256(destination), "snapshot": snapshot}


def extract_book(path: Path, symbol: str, session: str, start: datetime, end: datetime, cutoff: datetime) -> dict:
    """保存した生板だけから既存と同じ保守的な板特徴を作る。

    引数: path（Path）生板、symbol・session（str）所属、start・end・cutoff（datetime）範囲。
    返り値: dict。原本時刻・品質・特徴ファイルの監査。
    """
    spec = importlib.util.spec_from_file_location("今回取得の保存板抽出器", EXTRACTOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    processor = module.Extractor(start, min(end, cutoff), 10.0 if symbol == "NK225" else 0.5)
    minimum = maximum = None
    names, contracts, keys = set(), set(), set()
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or "CurrentPriceTime" not in row or "Buy1" not in row or "Sell1" not in row:
                raise ValueError("生板の必要項目がありません")
            keys.update(row)
            if row.get("SymbolName"):
                names.add(row["SymbolName"])
            if row.get("Symbol"):
                contracts.add(str(row["Symbol"]))
            if row["CurrentPriceTime"]:
                stamp = parse_stamp(row["CurrentPriceTime"])
                if stamp >= cutoff:
                    raise ValueError("生板に共通締切以降の約定時刻があります")
                if start <= stamp < end:
                    minimum = stamp if minimum is None else min(minimum, stamp)
                    maximum = stamp if maximum is None else max(maximum, stamp)
            processor.accept(row)
    expected_name = "日経" if symbol == "NK225" else "TOPIX"
    if not names or any(expected_name not in name for name in names) or len(contracts) != 1:
        raise ValueError("生板の銘柄名または限月識別子が不一致です")
    if minimum is None:
        raise ValueError("生板に対象セッションの有効時刻がありません")
    rows = processor.rows(symbol, session)
    if not rows:
        raise ValueError("板特徴に利用可能な確定ブロックがありません")
    destination = LIVE / f"板特徴_{symbol}_{session}.csv"
    with destination.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=module.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return {"symbol": symbol, "source": path.relative_to(ROOT).as_posix(), "source_sha256": sha256(path),
            "first": minimum.isoformat(), "last": maximum.isoformat(), "symbol_names": sorted(names),
            "contracts": sorted(contracts), "schema": sorted(keys), "audit": dict(processor.audit),
            "features": destination.relative_to(ROOT).as_posix(), "feature_rows": len(rows), "features_sha256": sha256(destination),
            "available_at_first": rows[0]["available_at"], "available_at_last": rows[-1]["available_at"],
            "利用可能時刻の限界": "受信時刻がなく、次の約定時刻の分終了へ遅延させる近似。実受信時刻の証明ではない。"}


def fetch_once() -> dict:
    """明示実行時だけ一度の現在セッション取得を行い再取得を永久に拒否する。

    引数: なし。
    返り値: dict。取得物と変換の監査。開始後の失敗でもロックを残す。
    """
    frozen = freeze_check()
    started = now_jst()
    cutoff = started.replace(second=0, microsecond=0)
    LIVE.mkdir(parents=True, exist_ok=True)
    marker = LIVE / "一回取得開始.json"
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    record = {"started_at": started.isoformat(), "cutoff": cutoff.isoformat(), "再試行なし": True,
              "fixed_at": frozen["fixed_at"], "manifest_sha256": sha256(FROZEN), "files_sha256": frozen["files_sha256"],
              "requests": [], "candles": [], "books": [], "ok": False}
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    try:
        write_json(LIVE / "凍結記録の写し.json", frozen)
        status_path = LIVE / "status.json"
        status_result = fetch_one("status", f"{BASE_URL}/status", status_path)
        record["requests"].append(status_result)
        write_json(LIVE / "取得記録.json", record)
        if not status_result["ok"]:
            raise RuntimeError("状態の取得に失敗しました。データＵＲＬへ進まず終了します")
        session, start, end = identify_session(json.loads(status_path.read_text(encoding="utf-8-sig")), cutoff)
        record.update(session=session, session_start=start.isoformat(), session_end=end.isoformat(),
                      known_session=(ROOT / "candle_1min/NK225" / f"{session}.csv").exists(),
                      結果の位置付け="凍結後に一回取得した現在スナップショット。取得前の過去を含むため前向き実発注試験ではない。")
        query = urllib.parse.urlencode({"from": start.isoformat(), "to": cutoff.isoformat()})
        requests = []
        for symbol in SYMBOLS:
            for minutes in (1, 5):
                name = f"{symbol}_{minutes}min"
                requests.append((name, f"{BASE_URL}/{symbol}/candles/{minutes}min?{query}", LIVE / "応答原本" / f"{name}.json"))
            requests.append((f"{symbol}_book", f"{BASE_URL}/{symbol}/book?{query}", LIVE / "book" / symbol / f"{session}.jsonl"))
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(fetch_one, *item) for item in requests]
            record["requests"].extend(future.result() for future in futures)
        write_json(LIVE / "取得記録.json", record)
        if not all(result["ok"] for result in record["requests"]):
            raise RuntimeError("一部のデータ取得に失敗しました。再試行しません")

        # ----------------------------------------
        # 取得を完了してから保存物だけを検査・変換し、元のデータ領域には書かない。
        for symbol in SYMBOLS:
            for minutes in (1, 5):
                record["candles"].append(convert_candles(LIVE / "応答原本" / f"{symbol}_{minutes}min.json", symbol, minutes, session, start, end, cutoff))
            record["books"].append(extract_book(LIVE / "book" / symbol / f"{session}.jsonl", symbol, session, start, end, cutoff))
        freeze_check()
        if sha256(FROZEN) != record["manifest_sha256"]:
            raise RuntimeError("取得中に凍結記録が変更されました")
        record["ok"] = True
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        record["finished_at"] = now_jst().isoformat()
        write_json(LIVE / "取得記録.json", record)
    return record


def main() -> None:
    """通信を明示的な fetch 引数に限定したコマンド入口。

    引数: なし。コマンド行から mode（str）を読む。
    返り値: None。成否の監査要約を標準出力へ表示する。
    """
    parser = argparse.ArgumentParser(description="凍結後に現在セッションを各ＵＲＬ一回だけ取得する。再試行しない。")
    parser.add_argument("mode", choices=("fetch",))
    parser.parse_args()
    result = fetch_once()
    print(json.dumps({key: result[key] for key in ("ok", "session", "cutoff", "known_session", "finished_at")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
