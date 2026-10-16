"""場停止の境界だけを、実商品の会計検査から切り分けて確認する。"""

from __future__ import annotations

from pathlib import Path
import hashlib
import importlib
import json
import sys

import numpy as np

HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 場清算閾値の等号・直前直後・不可逆停止を小人工で確認する。
    引数: なし。
    返り値: None。境界分離のため料金ゼロの純 kernel を使い、商品成績とは呼ばない。
    """
    private = HERE / "完成三源の私有複製"
    sys.path.insert(0, str(private))
    engine = importlib.import_module("engine")
    proof = {"全合格": False, "確認数": 0, "料金の扱い": "場閾値の等号を二進で厳密に分離する純kernelだけ料金0。実商品の料金は別の2240確認で検査済み。", "読取": {"NPZ": 0, "原入力": 0, "金融結果": 0, "API": 0}, "境界": []}
    checks = 0
    for side in (1, -1):
        for kind, limit, line in (("損失", -5.0, -50000.0), ("利益", 15.0, 150000.0)):
            for delta in (-0.0625, 0.0, 0.0625):
                seq = np.arange(100, 106, dtype=np.int64)
                times = np.array([1000., 1001., 1002., 1003., 1004., 1700.])
                b = np.full(6, 3999.75)
                a = np.full(6, 4000.25)
                entry = 4000.25 if side == 1 else 3999.75
                quote = entry + side * (limit + delta)
                if side == 1:
                    b[2:] = quote
                    a[2:] = quote + 0.5
                else:
                    a[2:] = quote
                    b[2:] = quote - 0.5
                candidates = np.array([[0, 0, side, 0, 0], [3, 1, side, 0, 1]], dtype=float)
                value = engine._run(seq, times, b, a, np.ones(6, dtype=bool), np.ones(6, dtype=bool), candidates,
                                    0., 1400., 1700., np.empty((0, 2)), 10, 0.5, 1000., 0, 1, 0, 0.00125, 0.00375)
                orders, legs, parents, pubs, execution, controls, curve, counts, final = value
                crosses = delta <= 0 if kind == "損失" else delta >= 0
                expected_reason = 161 if kind == "損失" else 162
                selected = controls[controls[:, 2] == expected_reason]
                assert (len(selected) == 1) == crosses
                assert curve[0, 12] == 50000.0 and curve[0, 13] == 150000.0
                assert curve[2, 1] == line + delta * 10000.0
                if crosses:
                    assert selected[0, 0] == 2
                    assert selected[0, 8] == line + delta * 10000.0
                    assert orders[1, 0] == 3 and orders[1, 1] == 2 and orders[1, 9] == expected_reason
                    assert pubs[1, 5] == 0 and pubs[1, 7] == expected_reason
                    assert counts[15] == 1 and final[5] == 1 and counts[2] == 1
                    checks += 5
                else:
                    assert final[5] == 0 and counts[15] == 0
                    checks += 1
                proof["境界"].append({"方向": side, "種別": kind, "線": line, "線との差": delta * 10000., "場停止": bool(crosses)})
                checks += 3
    proof.update(全合格=True, 確認数=checks, core_SHA256=hashlib.sha256((private / "engine.py").read_bytes()).hexdigest(), 独立源_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    output = HERE / "場清算の等号と停止ラッチだけの独立純kernel補完.json"
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"全合格": True, "確認数": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
