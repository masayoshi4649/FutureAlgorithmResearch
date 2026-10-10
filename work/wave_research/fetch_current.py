"""凍結済み条件の最終確認用スナップショットを一度だけ取得する。"""

import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

import pandas as pd

from research import OUT, write_json


def fetch_one(item: tuple[str, str], destination: Path) -> dict:
    """機能: 一つの公開範囲内の履歴URLを一度取得してそのまま保存する。

    引数: item (tuple[str, str]) は保存名とURL、destination (Path) は保存先。
    返り値: 取得日時・成否・ハッシュ (dict)。自動再試行はしない。
    """
    name, url = item
    result = dict(name=name, url=url, started_at=pd.Timestamp.now(tz="Asia/Tokyo").isoformat())
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            payload = response.read()
            result["http_status"] = response.status
        (destination/name).write_bytes(payload)
        result.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), ok=True)
    except Exception as exc:
        result.update(ok=False, error=str(exc))
    result["finished_at"] = pd.Timestamp.now(tz="Asia/Tokyo").isoformat()
    return result


def main() -> None:
    """機能: 保存済み評価後に現在セッションを共通締切で一度取得する。

    引数: なし。返り値: なし (None)。同じ保存先での再取得を拒否する。
    """
    frozen_path = OUT/"凍結設定.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256((OUT/"research.py").read_bytes()).hexdigest()
    if digest != frozen["code_sha256"]:
        raise RuntimeError("凍結後に研究コードが変更されています")
    if not (OUT/"未使用日_集計.json").exists():
        raise RuntimeError("未使用日の評価を先に完了してください")
    destination = OUT/"現在セッション固定"
    destination.mkdir(exist_ok=False)
    cutoff = pd.Timestamp.now(tz="Asia/Tokyo").floor("min")
    query = urllib.parse.urlencode({"to": cutoff.isoformat()})
    base = "http://10.10.100.1:8080/api/v1/history"
    items = [("status.json", f"{base}/status")]
    items += [(f"{symbol}_{period}.json", f"{base}/{symbol}/candles/{period}?{query}")
              for symbol in ("NK225", "TOPIX") for period in ("1min", "5min")]
    metadata = dict(cutoff=cutoff.isoformat(), frozen_sha256=hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
                    code_sha256=digest, note="１回の取得工程。各URL１リクエスト、再試行なし。")
    write_json(destination/"取得開始.json", metadata)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(fetch_one, item, destination) for item in items]
        results = [future.result() for future in futures]
    metadata["requests"] = results
    write_json(destination/"取得記録.json", metadata)
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()
