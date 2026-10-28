"""S01運用の診断用に、現在の板・足・アプリ状態を一度だけ固定取得する。"""
import concurrent.futures
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "current_20261027"
CUTOFF = "2026-10-27T15:20:00+09:00"


def fetch(item):
    """読取応答を保存し、取得時刻と内容指紋を返す。

    引数: item(tuple[str,str])は出力名とGET URL。
    返り値: dictは保存先、要求URL、取得時刻、SHA256、サイズ又は失敗理由。
    """
    name, url = item
    path = OUT / name
    assert not path.exists()
    start = datetime.now().astimezone().isoformat()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=120) as response:
            payload = response.read()
        if name.startswith("app_"):
            value = json.loads(payload)
            value.pop("csrf_token", None)
            payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(payload)
        return {"path": str(path), "url": url, "requested_at": start, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    except Exception as exc:
        return {"path": str(path), "url": url, "requested_at": start, "error": f"{type(exc).__name__}: {exc}"}


def main():
    """時刻を固定して資料を取得し、変更不可の目録を保存する。

    引数: なし。返り値: None。GETのみ、発注・設定変更・金融再生なし。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "manifest.json").exists()
    query = urllib.parse.urlencode({"from": "2026-10-27T08:45:00+09:00", "to": CUTOFF})
    jobs = [("app_state.json", "http://10.10.100.1:8090/api/state"),
            ("app_settings.json", "http://10.10.100.1:8090/api/settings"),
            ("history_status.json", "http://10.10.100.1:8080/api/v1/history/status")]
    for symbol in ("NK225", "TOPIX"):
        for suffix, endpoint in (("book.jsonl", "book"), ("candles_1min.json", "candles/1min"), ("candles_5min.json", "candles/5min")):
            jobs.append((symbol + "_" + suffix, f"http://10.10.100.1:8080/api/v1/history/{symbol}/{endpoint}?{query}"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(fetch, jobs))
    (OUT / "manifest.json").write_text(json.dumps({"cutoff_exclusive": CUTOFF, "downloaded_at": datetime.now().astimezone().isoformat(), "files": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cutoff": CUTOFF, "files": len(rows), "errors": [x for x in rows if "error" in x], "bytes": sum(x.get("bytes", 0) for x in rows)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
