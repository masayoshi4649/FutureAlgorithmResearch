"""21種類の入口信号について、基準再現と未来打切り監査を保存する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

import signal_variants


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
CUTOFF_SECONDS = (65 * 60 + 17, 125 * 60 + 31, 245 * 60 + 11)


def digest(path: Path) -> str:
    """機能: 読取元の変更がないことを確認するためSHA256を計算する。

    引数: path (Path) は読取対象ファイル。
    返り値: SHA256の16進文字列 (str)。
    """
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1048576):
            result.update(chunk)
    return result.hexdigest()


def load_inputs() -> tuple[dict, dict, list[Path]]:
    """機能: 保存済み入力と監査済み方向状態を読取専用で読み込む。

    引数: なし。
    返り値: 入力、元方向状態、参照ファイル一覧 (tuple[dict, dict, list[Path]])。
    """
    paths = [ROOT / "work/wave_v16" / f"入力_{name}.pkl" for name in ("development", "holdout")]
    states_path = ROOT / "work/wave_v17/主方向状態.pkl"
    inputs = {}
    for path in paths:
        with path.open("rb") as stream:
            part = pickle.load(stream)
        assert not set(inputs).intersection(part), "保存入力のキーが重複しています"
        inputs.update(part)
    with states_path.open("rb") as stream:
        states = pickle.load(stream)
    assert len(inputs) == 20 and set(inputs) == set(states)
    paths += [states_path, OUT / "signal_variants.py", Path(__file__).resolve()]
    paths += [ROOT / "candle_1min" / symbol / f"{session}.csv" for session, symbol in sorted(inputs)]
    return inputs, states, paths


def truncate_inputs(inputs: dict, elapsed: float) -> dict:
    """機能: セッション開始から指定時間より未来の入力行を物理的に除く。

    引数: inputs (dict) は全入力、elapsed (float) は開始からの打切り秒数。
    返り値: 原本行対応の全配列を先頭切断した入力 (dict)。
    """
    result = {}
    for key, ready in inputs.items():
        count = int(np.searchsorted(ready["time_s"], ready["start"] + elapsed, side="right"))
        assert count > 0
        result[key] = {
            name: value[:count].copy()
            if isinstance(value, np.ndarray) and len(value) == len(ready["seq"]) else value
            for name, value in ready.items() if name != "families"
        }
    return result


def array_digest(states: dict) -> str:
    """機能: 全セルの方向配列を一定のキー順でハッシュ化する。

    引数: states (dict) は (セッション, 銘柄) 別の方向配列。
    返り値: キー・長さ・方向列を含むSHA256 (str)。
    """
    result = hashlib.sha256()
    for key, values in sorted(states.items()):
        result.update(json.dumps([*key, len(values)], ensure_ascii=False).encode("utf-8"))
        result.update(values.tobytes())
    return result.hexdigest()


def run_audit() -> dict:
    """機能: 全候補の基準再現・未来打切り・入出力不変性を検査して保存する。

    引数: なし。
    返り値: 監査結果と全比較記録 (dict)。audit_signals.jsonへ同じ内容を保存する。
    """
    started = time.perf_counter()
    inputs, original_states, paths = load_inputs()
    source_hashes = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    specs = signal_variants.variant_specs()
    assert len(specs) == 21 and specs[0]["id"] == "S00"
    assert specs[0]["change_count"] == 0
    assert all(spec["change_count"] == 1 for spec in specs[1:])
    full = signal_variants.build_all(inputs, original_states)
    baseline_records = []
    for key, values in full["S00"].items():
        assert values.dtype == np.int8
        assert np.array_equal(values, -original_states[key]["M3"]), key
        baseline_records.append({"セッション": key[0], "銘柄": key[1], "比較行数": len(values), "完全一致": True})
    # ----------------------------------------
    # 元配列を切るだけでなく、打切り後に公開済み足の抽出・EMA・方向確認を最初からやり直す。
    records = []
    for elapsed in CUTOFF_SECONDS:
        cut = truncate_inputs(inputs, elapsed)
        cut_original = {
            key: {name: values[:len(cut[key]["seq"])].copy() for name, values in states.items()}
            for key, states in original_states.items()
        }
        for spec in specs:
            partial = signal_variants.build_one(spec, cut, cut_original)
            for key, values in partial.items():
                assert np.array_equal(values, full[spec["id"]][key][:len(values)]), (spec["id"], key, elapsed)
                records.append({
                    "信号ID": spec["id"], "セッション": key[0], "銘柄": key[1],
                    "開始後秒": elapsed, "比較行数": len(values), "完全一致": True,
                })
    groups = {}
    state_records = []
    for signal_id, data in full.items():
        signature = array_digest(data)
        groups.setdefault(signature, []).append(signal_id)
        state_records.append({
            "信号ID": signal_id, "状態SHA256": signature,
            "非中立行数": sum(int(np.count_nonzero(values)) for values in data.values()),
            "基準からの変更行数": sum(int(np.count_nonzero(values != full["S00"][key])) for key, values in data.items()),
        })
    hashes_after = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    assert source_hashes == hashes_after, "監査中に読取元ファイルが変更されました"
    result = {
        "合格": True, "API取得数": 0, "新規バックテスト数": 0,
        "再現コマンド": "python work/wave_v19/audit_signals.py",
        "候補数": len(specs), "異なる状態配列数": len(groups),
        "同一状態の候補": [items for items in groups.values() if len(items) > 1],
        "入力セル数": len(inputs), "基準比較行数": sum(item["比較行数"] for item in baseline_records),
        "基準完全一致": True, "打切り開始後秒": list(CUTOFF_SECONDS),
        "未来打切りケース数": len(records), "未来打切り比較状態値数": sum(item["比較行数"] for item in records),
        "未来打切り全一致": True, "読取元の監査前後SHA256一致": True,
        "公開条件": "確定１分足は足開始120秒後に公開。公開済み相手M1に候補別の追加遅延を適用し、現在以下の公開時刻だけ参照する。",
        "板フィルタの監査範囲": "S19/S20はwave_v17で因果性監査済みの保存M2を使用。本監査ではM2自体を再抽出せず、切断後のM2先頭配列だけを入口フィルタへ渡す。",
        "注文の監査範囲": "新規方向の再現性監査。注文の次原本行への繰越と約定処理は別のエンジン監査の対象。",
        "基準比較": baseline_records, "状態集計": state_records,
        "未来打切り": records, "読取元SHA256": source_hashes,
        "実行秒": round(time.perf_counter() - started, 3),
    }
    (OUT / "audit_signals.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    audited = run_audit()
    print(json.dumps({key: value for key, value in audited.items()
                      if key not in ("基準比較", "状態集計", "未来打切り", "読取元SHA256")}, ensure_ascii=False, indent=2))
