"""00154の現在セッションを一度取得し、比較中の入力を固定する。"""
import concurrent.futures
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "current_20261027"
CUTOFF = "2026-10-27T12:08:00+09:00"


def fetch(item):
    """読取APIの応答を保存する。

    引数: item(tuple[str, str])はファイル名とURL。
    返り値: dictはURL、保存名、サイズ、内容指紋。
    """
    name, url = item
    path = OUT / name
    with urllib.request.urlopen(url, timeout=180) as response:
        payload = response.read()
    if name == "app_state.json":
        value = json.loads(payload)
        value.pop("csrf_token", None)
        payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(payload)
    return {"path": str(path), "url": url, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def main():
    """同一終端で原板と足を取得する。

    引数: なし。
    返り値: なし。目録と原応答を保存する。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "manifest.json").exists():
        raise RuntimeError("取得済み。再取得で入力を上書きしません")
    query = urllib.parse.urlencode({"from": "2026-10-27T08:45:00+09:00", "to": CUTOFF})
    jobs = [("app_state.json", "http://10.10.100.1:8090/api/state"), ("history_status.json", "http://10.10.100.1:8080/api/v1/history/status")]
    for symbol in ("NK225", "TOPIX"):
        for suffix, endpoint in (("book.jsonl", "book"), ("candles_1min.json", "candles/1min"), ("candles_5min.json", "candles/5min")):
            jobs.append((symbol + "_" + suffix, f"http://10.10.100.1:8080/api/v1/history/{symbol}/{endpoint}?{query}"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(fetch, jobs))
    manifest = {"cutoff_exclusive": CUTOFF, "downloaded_at": datetime.now().astimezone().isoformat(), "files": rows, "manual_close_confirmed_by_user": True}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cutoff": CUTOFF, "files": len(rows), "bytes": sum(x["bytes"] for x in rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
