"""原E01とGだけの旧R01を、旧28場の保存売買へ独立対応させる。"""

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
os.environ["NUMBA_CACHE_DIR"] = str(HERE / "cache")
import numpy as np


def module(name, path):
    """
    機能: 今回の読取専用実装を一意名で読み込む。
    引数: name (str)、path (Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def read(path):
    """
    機能: 旧台帳の圧縮JSONを読む。
    引数: path (Path)。
    返り値: dict の内容。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def main():
    """
    機能: 元売買と新器の無改修・Gだけを照合し、利益を選抜せず一致記録だけ出す。
    引数: コマンドラインの --all (bool) は全28場指定。
    返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    prepare = module("wave85_audit_prepare", WORK / "prepare.py")
    strategy = module("wave85_strategy", WORK / "strategy.py")
    import numba
    numba.config.CACHE_DIR = str(HERE / "cache")
    inputs, signals, _ = prepare.load_inputs()
    features = strategy.initialize(inputs, signals)
    selected = {("2026-09-21_Day", "TOPIX"), ("2026-09-29_Night", "NK225"),
                ("2026-10-05_Day", "TOPIX"), ("2026-10-08_Night", "NK225")}
    records = []
    code_paths = [WORK / n for n in ("engine.py", "strategy.py", "catalog.py")]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths}
    for model in ("specified", "observed"):
        for mask, old_id in ((0, "E01"), (1, "R01")):
            path = ROOT / "work/wave_v67" / model / (old_id + ".json.gz")
            old = read(path)
            count = 0
            for ledger in old["ledgers"]:
                key = ledger["session"], ledger["symbol"]
                if not args.all and key not in selected:
                    continue
                result, settings = strategy.play(dict(mask=mask), inputs[key], features[key], observed=model == "observed")
                for field in ("orders", "cycles"):
                    np.testing.assert_array_equal(result[field], np.asarray(ledger[field]).reshape(result[field].shape), err_msg=str((model, old_id, key, field)))
                entries = [o for o in ledger["orders"] if o[7] == 1]
                leg_lookup = {(int(o[2]), int(o[0])): j for j, o in enumerate(entries)}
                scale = 1000 if key[1] == "TOPIX" else 10
                raw = [[t["組"], leg_lookup[t["組"], t["新規行"]], t["方向"], t["枚数"], t["建値"], t["返済値"],
                        t["新規行"], t["返済行"], 0, t["理由"], t["利益損失前"] / scale] for t in ledger["trades"]]
                np.testing.assert_array_equal(result["trades"], np.asarray(raw).reshape(result["trades"].shape), err_msg=str(key))
                assert result["stats"][9] == 0
                assert not len(result["guard_events"]) and not len(result["block_events"])
                assert settings == ledger["config"]
                records.append(dict(モデル=model, 旧ID=old_id, 新mask=mask, セッション=key[0], 銘柄=key[1],
                    注文数=len(result["orders"]), 決済数=len(result["trades"]), 組数=len(result["cycles"]), 完全一致=True))
                count += 1
            print(model, old_id, count, "口座で旧注文・決済・組・設定に完全一致", flush=True)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name] for p in code_paths)
    output = dict(全合格=True, 対象="全28場" if args.all else "局所4口座", 口座照合数=len(records), 検査=records,
        実装SHA256=hashes, コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        新改修成績による選抜=False, 注記="原E01と旧R01だけを再生し、新部品の成績は計算しない。全会計の監査は別に実施する。")
    name = "原E01とR01の旧28場完全一致.json" if args.all else "原E01とR01の局所完全一致.json"
    (HERE / name).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(全合格=True, 口座照合数=len(records)), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
