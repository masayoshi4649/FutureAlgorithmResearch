"""通信も再選択もせず、凍結設定と保存スナップショットの再現性を検証する。"""

import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd

from evaluate_current import load_current
from research import Config, HOLDOUT, OUT, ROOT, TRAIN, evaluate, load_sessions, write_json


def main() -> None:
    """機能: 元データ・凍結コード・現在取得物のハッシュと全イベント一致を検証する。

    引数: なし。返り値: なし (None)。不一致なら例外で停止する。
    """
    frozen_path = OUT/"凍結設定.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    assert hashlib.sha256((OUT/"research.py").read_bytes()).hexdigest()==frozen["code_sha256"]
    for name, digest in frozen["input_sha256"].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, name
    directory = OUT/"現在セッション固定"
    capture = json.loads((directory/"取得記録.json").read_text(encoding="utf-8"))
    assert capture["frozen_sha256"]==hashlib.sha256(frozen_path.read_bytes()).hexdigest()
    for item in capture["requests"]:
        assert item["ok"]
        assert hashlib.sha256((directory/item["name"]).read_bytes()).hexdigest()==item["sha256"]
    cfg = Config(**frozen["config"])
    cases = [("開発_採用条件", load_sessions(TRAIN, cfg.timeframe)),
             ("未使用日", load_sessions(HOLDOUT, cfg.timeframe)),
             ("現在", load_current(cfg.timeframe)[0])]
    verified = []
    for name, data in cases:
        records, rows = evaluate(data, cfg)
        for suffix, value in (("イベント", records), ("集計", rows)):
            expected = json.loads((OUT/f"{name}_{suffix}.json").read_text(encoding="utf-8"))
            actual = json.loads(json.dumps(value, default=str))
            assert actual==expected, f"{name}_{suffix} の再現結果が一致しません"
        verified.append(dict(区分=name, イベント数=len(records), 完全一致=True))
    result = dict(検証時刻=pd.Timestamp.now(tz="Asia/Tokyo").isoformat(), 結果=verified,
                  元データハッシュ=True, 凍結設定ハッシュ=True, コードハッシュ=True, 取得物ハッシュ=True,
                  実行環境=dict(Python=platform.python_version(), NumPy=np.__version__, pandas=pd.__version__),
                  通信回数=0)
    write_json(OUT/"再現性検証.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
