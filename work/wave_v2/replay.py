"""凍結候補を保存済み履歴と以前取得したスナップショットで再生する。通信は行わない。"""

import hashlib
import json

import pandas as pd

import research_v2 as r


def cached_data() -> dict:
    """機能: 前回の一度限りの取得物から確定足を読み込む。

    引数: なし。返り値: 現在データの再利用用対応表 (dict)。新しい独立評価ではない。
    """
    directory = r.OUT.parent/"wave_research"/"現在セッション固定"
    meta = json.loads((directory/"取得記録.json").read_text(encoding="utf-8"))
    cutoff = pd.Timestamp(meta["cutoff"])
    status = json.loads((directory/"status.json").read_text(encoding="utf-8"))
    ids = {item["code"]: item["sessionId"] for item in status["current"]}
    data = {}
    for symbol in r.SYMBOLS:
        frames = {}
        for minutes in (1, 5):
            path = directory/f"{symbol}_{minutes}min.json"
            record = next(item for item in meta["requests"] if item["name"]==path.name)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==record["sha256"]
            payload = json.loads(path.read_text(encoding="utf-8"))
            df = pd.DataFrame(payload["data"])
            df["time"] = pd.to_datetime(df.time)
            df = df[df.closed & (df.time+pd.Timedelta(minutes=minutes)<=cutoff)]
            frames[minutes] = df.set_index("time").sort_index()
        z = r.price_features(frames[1], frames[5], r.TICKS[symbol])
        data[(ids[symbol], symbol)] = (frames[1], z)
    return data


def main() -> None:
    """機能: 固定コード・入力ハッシュを確認して結果を完全再現し、旧取得物を再利用評価する。

    引数: なし。返り値: なし (None)。外部通信はゼロ。
    """
    fixed = json.loads((r.OUT/"固定設定.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((r.OUT/"research_v2.py").read_bytes()).hexdigest()==fixed["code_sha256"]
    for path, digest in fixed["input_sha256"].items():
        assert hashlib.sha256((r.ROOT/path).read_bytes()).hexdigest()==digest, path
    cfg = r.Config(**fixed["config"])
    trades, targets, cells = r.evaluate(r.load_data(), cfg)
    for name, value in (("取引", trades), ("指定波", targets), ("集計", cells)):
        expected = json.loads((r.OUT/f"比較_採用{name}.json").read_text(encoding="utf-8"))
        assert json.loads(json.dumps(value, default=str))==expected, name
    assert len(targets)==4 and all(t["passed"] for t in targets)
    assert all(t["closed"] for t in trades)
    current_trades, _, current_cells = r.evaluate(cached_data(), cfg)
    r.save_json(r.OUT/"再利用_取引.json", current_trades)
    r.save_json(r.OUT/"再利用_集計.json", current_cells)
    result = dict(記録時刻=pd.Timestamp.now(tz="Asia/Tokyo").isoformat(), 固定設定=cfg.key,
                  履歴取引数=len(trades), 全履歴取引返済済み=True, 指定４波合格=True,
                  入力とコードハッシュ=True, 結果完全一致=True, 今回の通信回数=0,
                  再利用データ="前回取得の2026-09-23 00:28締切。既知データの再利用であり独立な答え合わせではない。",
                  再利用集計=current_cells)
    r.save_json(r.OUT/"再現性検証.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
