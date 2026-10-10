"""二市場の同期索引を、別の時計群検索と片側未来改変で独立照合する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np

from dual_fixtures import START, paired_cases, one_side_future, cut_one_side
from independent_account import save
from sync_oracle import asof, asof_fast


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("wave75_input_core", HERE.parent / "inputs/core.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def compare(got: tuple, expected: tuple) -> None:
    """機能: 同期行と欠測NaNを含む古さを別計算に一致確認する。

    引数: got/expected(tuple)。返り値: なし(None)。
    """
    np.testing.assert_array_equal(got[0], expected[0])
    np.testing.assert_allclose(got[1], expected[1], atol=1.e-6, rtol=0, equal_nan=True)


def synthetic() -> dict:
    """機能: 片側停止・全空・同時計・未来改変を含む同期の人工検査を行う。

    引数: なし。返り値: 検査件数(dict)。
    """
    cases = paired_cases()
    calls = future_checks = 0
    for name, markets in cases.items():
        start = markets["NK225"]["start"]
        grid = np.arange(start + 300., markets["NK225"]["limit"] - 300., 15.)
        for delay in (1, 5, 15, 60):
            targets = grid - delay
            for symbol, data in markets.items():
                slow = asof(targets, data["time_s"], data["valid"], data["reset"])
                fast = asof_fast(targets, data["time_s"], data["valid"], data["reset"])
                compare(fast, slow)
                got = core.asof_indices(targets, data["time_s"], data["valid"], data["reset"])
                compare(got, slow)
                if name in ("全空", "片側だけ前日データ") or name == "片市場全欠測" and symbol == "TOPIX":
                    if name != "片側だけ前日データ" or symbol == "TOPIX":
                        assert np.all(got[0] == -1)
                calls += 1
                for cutoff in (start + 900., start + 1800., start + 2700.):
                    for changed in (one_side_future(markets, symbol, cutoff), cut_one_side(markets, symbol, cutoff)):
                        altered = changed[symbol]
                        new = core.asof_indices(targets, altered["time_s"], altered["valid"], altered["reset"])
                        earlier = targets <= cutoff
                        compare((new[0][earlier], new[1][earlier]), (got[0][earlier], got[1][earlier]))
                        future_checks += 1
    times = np.array([10., 10., 11., 11., 20., 20., 30.])
    good, reset = np.ones(7, bool), np.zeros(7, bool)
    targets = np.array([10., 11., 12., 20., 21., 30., 31., 40., 41., np.nan, np.inf])
    compare(core.asof_indices(targets, times, good, reset), asof_fast(targets, times, good, reset))
    first_bad = good.copy()
    first_bad[2] = False
    assert core.asof_indices(np.array([12.]), times, first_bad, reset)[0][0] == -1
    reset[4] = True
    assert core.asof_indices(np.array([21.]), times, good, reset)[0][0] == -1
    later = good.copy()
    later[1::2] = False
    reset[:] = False
    compare(core.asof_indices(targets, times, later, reset), core.asof_indices(targets, times, good, reset))
    return dict(人工二市場経路数=len(cases), 同期比較数=calls + 4, 片側未来切断及び改変数=future_checks,
        検査=["厳密な過去", "同時計先頭のみ", "先頭無効を救済しない", "reset不採用", "古さ境界", "片側停止", "片側全欠測", "全空", "日跨ぎ", "片側だけ前日", "非有限cutoff", "同時計後続改変", "片側未来改変", "片側未来切断"])


def main() -> None:
    """機能: 保存29場の同期・入力fingerprintを人工検査に続いて独立照合する。

    引数: --fresh30(bool)。返り値: なし(None)。原本・現在APIを読み込まない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh30", action="store_true")
    cli = parser.parse_args()
    artificial = synthetic()
    suffix = "_fresh30" if cli.fresh30 else ""
    metadata_path = HERE.parent / f"inputs/同期入力仕様{suffix}.json"
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    max_age = meta["max_cutoff_age_seconds"]
    merged = []
    checked_hashes = {}
    for kind in ("ready", "features"):
        material = {}
        for name in meta["input_paths"][kind]:
            payload = (ROOT / name).read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            assert digest == meta["input_SHA256"][name]
            checked_hashes[name] = digest
            new = pickle.loads(payload)
            assert not set(material) & set(new)
            material.update(new)
        merged.append(material)
    ready, features = merged
    assert len(ready) == len(features) == 58 and set(ready) == set(features)
    raw_sync = (HERE.parent / f"inputs/sync{suffix}.pkl").read_bytes()
    assert hashlib.sha256(raw_sync).hexdigest() == meta["sync_SHA256"]
    sync = pickle.loads(raw_sync)
    assert sorted(sync) == sorted({key[0] for key in ready}) == meta["sessions"] and len(sync) == 29
    arrays = points = same_clock_refs = 0
    for session, shared in sync.items():
        start, limit = ready[(session, "TOPIX")]["start"], ready[(session, "TOPIX")]["limit"]
        assert ready[(session, "NK225")]["start"] == start and ready[(session, "NK225")]["limit"] == limit
        expected_grid = np.arange(start + 300., limit - 300., 15.)
        np.testing.assert_array_equal(shared["grid"], expected_grid)
        for delay in (1, 5, 15, 60):
            both = np.ones(len(expected_grid), bool)
            for symbol in ("TOPIX", "NK225"):
                r, f = ready[(session, symbol)], features[(session, symbol)]
                np.testing.assert_array_equal(r["seq"], f["seq"])
                np.testing.assert_array_equal(r["time_s"], f["time_s"])
                assert np.all(np.diff(r["seq"]) > 0) and np.all(np.diff(r["time_s"]) >= 0)
                result = asof_fast(expected_grid - delay, r["time_s"], f["valid"], f["reset"], max_age)
                compare((shared["indices"][delay][symbol], shared["observation_age"][delay][symbol]), result)
                np.testing.assert_allclose(shared["actual_age"][delay][symbol], result[1] + delay, atol=1.e-6, rtol=0, equal_nan=True)
                valid = result[0] >= 0
                rows = result[0][valid]
                assert np.all(r["time_s"][rows] < expected_grid[valid] - delay)
                assert np.all(result[1][valid] > 0) and np.all(result[1][valid] <= max_age)
                assert np.all(rows == 0) or np.all((rows == 0) | (r["time_s"][np.maximum(rows - 1, 0)] < r["time_s"][rows]))
                both &= valid
                same_clock_refs += int(np.sum((rows + 1 < len(r["time_s"])) & (r["time_s"][np.minimum(rows + 1, len(r["time_s"]) - 1)] == r["time_s"][rows])))
                arrays += 1
                points += len(result[0])
            np.testing.assert_array_equal(both, shared["both_available"][delay])
    name = "二市場同期fresh30と片側未来改変の独立監査.json" if cli.fresh30 else "二市場同期と片側未来改変の独立監査.json"
    save(HERE / name, dict(合格=True, **artificial, 最大cutoff古さ秒=max_age,
        保存場数=29, 保存口座数=58, 同期配列比較数=arrays, 同期点比較数=points,
        同時計後続行がある先頭参照数=same_clock_refs, 同期仕様SHA256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        sync_SHA256=meta["sync_SHA256"], 入力SHA256=checked_hashes,
        限界="CurrentPriceTime代理時計上の厳密過去と同時計先頭を確認した。最終約定時計と板受信時計は同じとは限らず、実受信順の銘柄間因果は保証していない。",
        原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, 同期配列比較数=arrays, 同期点比較数=points, **artificial), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
