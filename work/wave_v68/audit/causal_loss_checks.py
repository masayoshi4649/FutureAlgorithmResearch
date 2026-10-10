"""損失低減の全条件を切断・未来変更し、過去の実注文と影時計が不変か検査する。"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK))
import risk_replay as risk


def clipped(ready: dict, count: int) -> dict:
    """機能: 原本行へ対応する配列だけを途中まで切り出す。

    引数: ready(dict)、count(int)。返り値: 切断入力(dict)。
    """
    n = len(ready["last"])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and v.ndim and len(v) == n else v
            for k, v in ready.items()}


def prefix(left: tuple, right: tuple, count: int) -> None:
    """機能: 切断／未来変更以前の注文、枠、予算、影計画を全件照合する。

    引数: left/right(tuple)、count(int)。返り値: なし(None)。
    """
    for a, b in zip(left[:3], right[:3]):
        for name, row_column in (("orders", 0), ("trades", 7), ("cycles", 2),
                ("prepare_events", 1), ("entry_preparations", 1), ("slot_events", 0),
                ("adjustment_events", 0), ("budget_events", 0), ("branch_events", 0), ("risk_events", 0)):
            if name in a:
                x, y = a[name], b[name]
                np.testing.assert_array_equal(x[x[:, row_column] < count], y[y[:, row_column] < count], err_msg=name)
        for name in ("curve", "atr_curve", "plans", "execution_plans", "control_curve", "slot_curve", "branch_curve"):
            if name in a:
                np.testing.assert_array_equal(a[name][:count], b[name][:count], err_msg=name)


def main() -> None:
    """機能: 全38条件を同じ原本で切断・未来変更し監査結果を保存する。

    引数: --ids(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="")
    args = parser.parse_args()
    chosen = set(args.ids.split(",")) if args.ids else None
    socket.socket.connect = risk.base_replay.prior.previous.deny
    socket.create_connection = risk.base_replay.prior.previous.deny
    risk.base_replay.integration.reference.initialize()
    inputs, _, _ = risk.previous.load_inputs()
    models = {k: risk.base_replay.gate.model(r) for k, r in inputs.items()}
    key = ("2026-10-07_Night", "TOPIX")
    ready = inputs[key]
    ema = risk.ema_columns(key, ready, models)
    variants = {v["id"]: v for v in risk.base_replay.catalog()}
    columns = {base: risk.previous.columns_for(variants[base], key, ready, models) for base in ("E01", "R01")}
    n = len(ready["last"])
    cut, change = int(n * .37), int(n * .73)
    records = []
    fingerprints = {p.name: sha256(p.read_bytes()).hexdigest() for p in
                    (WORK / "loss_engine.py", WORK / "loss_shadow.py", WORK / "risk_replay.py")}
    for variant in risk.catalog():
        if chosen is not None and variant["id"] not in chosen:
            continue
        cols, valid = columns[variant["base"]]
        full = risk.play(variant, ready, cols, valid, ema)
        partial = risk.play(variant, clipped(ready, cut), tuple(v[:cut].copy() for v in cols),
                            valid[:cut].copy(), tuple(v[:cut].copy() for v in ema))
        prefix(full, partial, cut)
        del partial
        edited = clipped(ready, n)
        edited["last"][change:] += ready["tick"] * (37 + np.arange(n - change))
        edited["atr"][change:] *= 3.0
        changed_columns = [v.copy() for v in cols]
        for c in (0, 1, 3, 6):
            changed_columns[c][change:] = np.where(changed_columns[c][change:] == 1, -1, 1)
        for c in (2, 4, 7):
            changed_columns[c][change:] = np.arange(change, n)
        altered_valid = valid.copy()
        altered_valid[change:] = True
        altered_ema = [v.copy() for v in ema]
        altered_ema[0][change:] = np.where(altered_ema[0][change:] == 1, -1, 1)
        altered_ema[1][change:] = np.arange(change, n)
        future = risk.play(variant, edited, tuple(changed_columns), altered_valid, tuple(altered_ema))
        prefix(full, future, change)
        records.append(dict(条件=variant["id"], 対象=list(key), 切断行=cut, 未来変更行=change,
                            切断一致=True, 未来変更一致=True))
        del full, future
        print(variant["id"], "切断・未来変更一致", flush=True)
    assert fingerprints == {p.name: sha256(p.read_bytes()).hexdigest() for p in
                            (WORK / "loss_engine.py", WORK / "loss_shadow.py", WORK / "risk_replay.py")}
    packet = dict(全合格=True, 検査数=len(records), 記録=records, 実装SHA256=fingerprints,
                  注記="保存済み公開指標から実注文生成までの未来参照を検査。既知データ選択による過適合を否定しない。")
    suffix = "_一部" if chosen is not None else ""
    (HERE / ("損失制御の因果検査" + suffix + ".json")).write_text(
        json.dumps(packet, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(全合格=True, 検査数=len(records)), ensure_ascii=False))


if __name__ == "__main__":
    main()
