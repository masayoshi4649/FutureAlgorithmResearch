"""新会計を人工例と保存D07に照合する。市場判断や売買条件の再生は行わない。"""

import json
import pickle
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
from accounting import account


def main():
    """部分返済・両方向保有の人工会計と既存25夜の会計を検算する。

    引数: なし。
    返り値: None。検査結果のみ監査JSONへ保存する。
    """
    data = dict(ready=dict(time_s=np.arange(7, dtype=float)), quotes=dict(
        bid=np.array([99, 99, 108, 109, 109, 110, 111.]),
        ask=np.array([101, 101, 110, 111, 111, 112, 113.]), quote_valid=np.ones(7, bool)))
    orders = np.array([
        [1, 0, 1, 1, 2, 101, 1, 1, 0, 0],
        [3, 2, 1, -1, 1, 109, 2, 0, 0, 0],
        [4, 3, 2, -1, 1, 109, 1, 1, 0, 0],
        [5, 4, 2, 1, 1, 112, 2, 0, 0, 0],
    ], float)
    synthetic = account(orders, data, allow_open=True)
    assert synthetic["net"] == 500 and synthetic["unrealized"] == 1000 and synthetic["equity"] == 1500
    assert synthetic["profit"] == 0 and synthetic["loss"] == 300
    assert synthetic["entries"] == 2 and synthetic["quantity"] == 3 and synthetic["max_per_side"] == 2
    verified = []
    for path in sorted((WORK / "inputs").glob("*_Night.pkl")):
        if path.stem == "2026-10-26_Night":
            continue
        with path.open("rb") as stream:
            payload = pickle.load(stream)
        result = account(payload["baseline"], payload["data"], strict_next=False)
        original = json.loads((ROOT / "work/research145_roles/results" / f"{path.stem}.json").read_text(encoding="utf-8"))
        expected = next(row for row in original["rows"] if row["method"] == "D07")
        for key in ("profit", "loss", "net", "entries", "quantity", "parent_count"):
            assert abs(result[key] - expected[key]) < 1e-6, (path.stem, key, result[key], expected[key])
        pre = account(payload["pre"], payload["data"], strict_next=False)
        post = account(payload["post"], payload["data"], strict_next=False)
        for key in ("profit", "loss", "net", "entries", "quantity", "parent_count"):
            assert abs(result[key] - pre[key] - post[key]) < 1e-6
        verified.append({"session": path.stem, "net": result["net"], "pre": pre["net"], "post": post["net"], "all_fields_match": True})
    assert len(verified) == 25
    output = {"new_market_replays": 0, "artificial_case": {key: synthetic[key] for key in ("profit", "loss", "net", "unrealized", "equity", "entries", "quantity", "max_per_side")}, "saved_sessions": verified, "conclusion": "人工部分返済・両方向保有・含み損益、および既存25夜D07の利益損失収支と前後段加算を全確認。"}
    (HERE / "会計の独立照合148.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved_sessions": len(verified), "synthetic_equity": synthetic["equity"], "all_match": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
