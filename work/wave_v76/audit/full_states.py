"""全十六条件・二十九場の共同状態を、損益を見ずに独立照合する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

from independent_account import save
from input_oracle import digest
import model_oracle as oracle
from model_synthetic import model


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(path: Path) -> object:
    """機能: 固定入力又は保存状態を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。損益は読み取らない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """機能: 三遅延の全強方向・弱支持・確認・発火と原本写像を照合する。

    引数: --delay(int、0は三遅延)。返り値: なし(None)。選定結果を使わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=int, choices=(0, 1, 5, 15), default=0)
    args = parser.parse_args()
    signals_sha = digest(HERE.parent / "signals.py")
    meta = load(HERE.parent / "inputs/入力と即時板特徴の仕様.json")
    grids = load(HERE.parent / "inputs/grids.pkl")
    ready = {}
    for path in meta["input_paths"]["ready"]:
        assert digest(ROOT / path) == meta["input_SHA256"][path]
        ready.update(load(ROOT / path))
    for delay in ((1, 5, 15) if args.delay == 0 else (args.delay,)):
        path = HERE.parent / "prepared" / f"signals_delay{delay}.pkl"
        prepared = load(path) if path.exists() else None
        array_checks = state_points = map_checks = 0
        expected_counts = []
        for definition in model.definitions():
            for session, value in sorted(grids[delay].items()):
                got = model.joint(definition, value)
                expected = oracle.joint(definition, value)
                array_checks += oracle.compare(got, expected)
                if prepared is not None:
                    oracle.compare(prepared[definition["id"]][session], expected)
                state_points += len(value["grid"])
                expected_counts.append(dict(条件=definition["id"], セッション=session, 格子数=len(value["grid"]),
                    有効数=int(expected["valid"].sum()), 買合意=int((expected["strong"] == 1).sum()),
                    売合意=int((expected["strong"] == -1).sum()), 不一致=int(expected["disagreement"].sum()),
                    瞬時入口数=int(np.count_nonzero(expected["entry"][0])),
                    十秒確認入口数=int(np.count_nonzero(expected["entry"][10]))))
        maps = {}
        for key, r in sorted(ready.items()):
            g = grids[delay][key[0]]["grid"]
            actual, expected = model.mapping(g, r), oracle.mapping(g, r["time_s"])
            np.testing.assert_array_equal(actual, expected)
            rows = np.flatnonzero(expected >= 0)
            assert np.all(g[expected[rows]] <= r["time_s"][rows])
            assert np.all(r["time_s"][rows] - g[expected[rows]] <= 10.)
            map_checks += 1
            maps["|".join(key)] = hashlib.sha256(expected.tobytes()).hexdigest()
        if prepared is not None:
            stored_counts = load(HERE.parent / "prepared" / f"入口状態_delay{delay}.json")
            assert stored_counts["signals_SHA256"] == signals_sha
            assert stored_counts["保存SHA256"] == digest(path)
            assert sorted(stored_counts["集計"], key=lambda r: (r["条件"], r["セッション"])) == sorted(expected_counts, key=lambda r: (r["条件"], r["セッション"]))
        assert digest(HERE.parent / "signals.py") == signals_sha
        save(HERE / f"全短期共同状態と支持確認の独立監査_delay{delay}.json", dict(合格=True,
            遅延=delay, 定義数=16, 場数=29, 条件場数=16 * 29, 全共同状態点数=state_points,
            状態確認配列数=array_checks, 原本写像口座数=map_checks,
            保存状態照合=prepared is not None, 保存状態SHA256=digest(path) if prepared is not None else None,
            signals_SHA256=signals_sha, 入力SHA256=meta["hashes"], 写像指紋=maps,
            分離="中立と不一致を保存上は区別。両方とも合意なしとして有効10秒再準備。無活動OFIは既知支持なし、真の欠測は確認停止。",
            限界="代理時計上の既知保存入力の照合。実受信因果・将来利益の証明ではない。",
            原本取得=0, API取得=0, 実注文=0, 損益閲覧=0))
        print(f"遅延{delay}秒の全{state_points:,}状態・支持・発火が独立一致しました", flush=True)


if __name__ == "__main__":
    main()
