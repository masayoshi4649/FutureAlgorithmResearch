"""保存参照価格・準備配列・実経路の未来切断を独立確認する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np
import numba

from adapters import check
from independent_account import save


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
os.environ.setdefault("NUMBA_CACHE_DIR", str(HERE / "cache"))
sys.path.insert(0, str(HERE.parent))
spec = importlib.util.spec_from_file_location("wave74_study", HERE.parent / "study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
numba.config.CACHE_DIR = str(HERE / "cache")


def lag(times: np.ndarray, reset: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 単調時計の過去行と直近切断境界から独立に参照行を求める。

    引数: times/reset(np.ndarray)、seconds(float)。返り値: 行番号(np.ndarray)。
    """
    assert np.all(np.diff(times) >= 0)
    indices = np.arange(len(times))
    boundary = np.maximum.accumulate(np.where(reset, indices, 0))
    rows = np.searchsorted(times, times - seconds, side="right") - 1
    return np.where((rows >= boundary) & (rows < indices), rows, -1)


def direct(r: dict, refs: dict, previous_rows: np.ndarray, reference: int, band: float) -> np.ndarray:
    """機能: API実装を使わず、既知基準と中立帯から全方向を計算する。

    引数: r/refs(dict)、previous_rows(np.ndarray)、reference(int)、band(float)。
    返り値: 方向(np.ndarray[int8])。始値未観測中は値幅も不明なため全方式待機。
    """
    values = r["last"]
    own = refs["ref_open"]
    old = refs["ref_prev"]
    available = (np.arange(len(values)) >= own["known_from_i"]) & np.isfinite(values) & (values > 0)
    def signed(price: float | None, known: int) -> np.ndarray:
        """機能: 1基準との隔たりを同時点の既知条件だけで符号化する。

        引数: price(float|None)、known(int)。返り値: 符号(np.ndarray[int8])。
        """
        if price is None or not np.isfinite(price) or price <= 0:
            return np.zeros(len(values), dtype=np.int8)
        result = np.where(values - price > price * band, 1, np.where(values - price < -price * band, -1, 0))
        return np.where(np.arange(len(values)) >= known, result, 0).astype(np.int8)
    a, b = signed(own["value"], own["known_from_i"]), signed(old["value"], old["known_from_i"])
    if reference == 0:
        result = a
    elif reference == 1:
        result = b
    elif reference == 2:
        result = np.where(a == b, a, 0)
    else:
        past = values[np.maximum(previous_rows, 0)]
        valid = (previous_rows >= 0) & np.isfinite(past) & (past > 0)
        result = np.where(valid & (values - past > past * band), 1, np.where(valid & (values - past < -past * band), -1, 0))
    return np.where(available, result, 0).astype(np.int8)


def reference_audit(ready: dict, features: dict, meta: dict, prepared: dict) -> None:
    """機能: 原本再取得なしに、保存参照の由来・利用開始・価格方向を検査する。

    引数: ready/features/meta/prepared(dict)。返り値: なし(None)。
    """
    assert len(ready) == len(features) == len(meta["references"]) == 58
    sessions = sorted({key[0] for key in ready})
    assert sessions == meta["sessions"] and len(sessions) == 29
    hashes = {}
    for name, expected in meta["input_SHA256"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        assert actual == expected
        hashes[name] = actual
    missing = unavailable_source = weekly = own_points = direction_points = historical_points = 0
    for symbol in ("TOPIX", "NK225"):
        ordered = sorted((key for key in ready if key[1] == symbol), key=lambda key: ready[key]["start"])
        for index, key in enumerate(ordered):
            r, f, p, refs = ready[key], features[key], prepared[key], meta["references"]["|".join(key)]
            times, sequence, n = r["time_s"], r["seq"], len(r["seq"])
            assert np.all(np.diff(sequence) > 0) and np.all(np.diff(times) >= 0)
            np.testing.assert_array_equal(times, f["time_s"])
            np.testing.assert_array_equal(sequence, f["seq"])
            opening, previous = refs["ref_open"], refs["ref_prev"]
            known = opening["known_from_i"]
            assert 0 <= known < n and times[known] >= opening["source_time"] and sequence[known] >= opening["source_seq"]
            if known:
                assert times[known - 1] < opening["source_time"] or sequence[known - 1] < opening["source_seq"]
            assert opening["source_session"] == key[0] and r["start"] <= opening["reference_time"] <= opening["source_time"]
            assert np.isfinite(opening["value"]) and opening["value"] > 0
            assert opening["reference_time"] < r["limit"] + 300.
            if opening["source_raw_has_valid_quote"]:
                assert sequence[opening["source_ready_i"]] == opening["source_seq"]
            own_points += 1
            if index == 0:
                assert previous["value"] is None and previous["known_from_i"] == -1
                missing += 1
            else:
                prior = ordered[index - 1]
                assert previous["source_session"] == prior[0]
                assert previous["source_time"] < r["start"] and previous["saved_end"] <= r["start"]
                assert previous["known_from_i"] == 0 and ready[prior]["start"] <= previous["source_time"] < ready[prior]["limit"] + 300.
                assert previous["saved_end"] == ready[prior]["limit"] + 300.
                assert np.isfinite(previous["value"]) and previous["value"] > 0
                source_i = previous["source_ready_i"]
                if source_i is None:
                    unavailable_source += 1
                else:
                    pr = ready[prior]
                    assert pr["seq"][source_i] == previous["source_seq"] and pr["time_s"][source_i] == previous["source_time"]
                    assert pr["last"][source_i] == previous["value"]
                weekly += int(previous["weekend_gap"])
            quality = f["valid"] & np.isfinite(f["bid"]) & np.isfinite(f["ask"]) & (f["bid"] > 0) & (f["ask"] > f["bid"]) & (f["ask"] - f["bid"] <= 2 * r["tick"] + r["tick"] * 1.e-8)
            np.testing.assert_array_equal(quality, p["quality"])
            reset = f["reset"] | ~quality
            lag30, lag60 = lag(times, reset, 30.), lag(times, reset, 60.)
            np.testing.assert_array_equal(lag30, p["lag30"])
            np.testing.assert_array_equal(lag60, study.engine.historical_rows(times, reset, 60.))
            historical_points += 2 * n
            for reference in range(4):
                for band in (0., .00025):
                    expected = direct(r, refs, lag60, reference, band)
                    np.testing.assert_array_equal(p["direction"][(reference, band)], expected)
                    direction_points += n
    assert missing == 2 and own_points == 58
    save(HERE / "参照基準と全方向配列の独立監査.json", dict(合格=True, 保存場数=29, 口座数=58,
        始値利用可能性検査=own_points, 前値欠測未補完=missing, 前値原本seqが準備配列外=unavailable_source,
        週末越しの過去価格参照=weekly, 過去行検査数=historical_points, 方向符号検査数=direction_points,
        入力SHA256=hashes, engine_SHA256=study.digest(HERE.parent / "engine.py"), study_SHA256=study.digest(HERE.parent / "study.py"),
        限界="本配列検査だけでは準備配列外seqの前値47口座の原本価格を直接確認していない。別資料『前場参照価格の原本末尾による独立監査.json』では全56前値の原本価格・時刻・元序数を直接照合した。受信時計と公式始値/終値の保証はない。",
        原本取得=0, API取得=0, 実注文=0))
    print("58口座の基準・過去行・全方向検査が合格しました", flush=True)


def future_audit(ready: dict, features: dict, meta: dict, prepared: dict) -> None:
    """機能: 固定した実条件の原本行を切断・改変して過去注文を照合する。

    引数: ready/features/meta/prepared(dict)。返り値: なし(None)。
    """
    fixed = study.load(HERE.parent / "事前固定.json")
    assert all(study.digest(ROOT / name) == expected for name, expected in fixed["SHA256"].items())
    wanted = ["A0_E0_B0_W10_P0", "A0_E1_B1_W20_P3", "A1_E1_B0_W05_P4", "A1_E0_B1_W40_P5",
              "A2_E1_B1_W10_P2", "M3_E1_B0_W20_P1", "X0_E0_B0_W10_P0", "K1_E1_B1_W40_P0"]
    configs = {c["id"]: c for c in fixed["条件"]}
    sessions = [meta["sessions"][index] for index in (0, 3, 15, 16, 28)]
    selected_keys = [(session, symbol) for session in sessions for symbol in ("TOPIX", "NK225")]
    cases_count = observed_open = observed_pending = 0
    for config_id in wanted:
        c = configs[config_id]
        for key in selected_keys:
            r, f = ready[key], features[key]
            full = study.engine.simulate(*study.arguments(c, key, ready, features, prepared))
            for cut in sorted({max(2, len(r["seq"]) // 3), max(2, len(r["seq"]) // 2), len(r["seq"]) - 1}):
                rr = {name: value[:cut].copy() if isinstance(value, np.ndarray) else value for name, value in r.items()}
                ff = {name: value[:cut].copy() if isinstance(value, np.ndarray) else value for name, value in f.items()}
                pp = study.prepare({key: rr}, {key: ff}, meta)
                prefix_out = study.engine.simulate(*study.arguments(c, key, {key: rr}, {key: ff}, pp))
                check(dict(time_s=rr["time_s"], seq=rr["seq"], bid=ff["bid"], ask=ff["ask"]), key[1], *prefix_out[:3], False)
                for output_index in (0, 1, 3):
                    column = 2 if output_index == 1 else 0
                    np.testing.assert_array_equal(prefix_out[output_index], full[output_index][full[output_index][:, column] < cut])
                np.testing.assert_allclose(prefix_out[2], full[2][:cut], atol=1.e-4, rtol=0)
                observed_open += int(prefix_out[4][0] != 0)
                observed_pending += int(prefix_out[4][1] != 0)
                changed_r = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in r.items()}
                changed_f = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in f.items()}
                for changed in (changed_r, changed_f):
                    for name in ("last", "bid", "ask", "mid"):
                        if name in changed:
                            changed[name][cut:] *= .75
                changed_f["valid"][cut:] = False
                changed_f["reset"][cut:] = True
                new_prepared = study.prepare({key: changed_r}, {key: changed_f}, meta)
                changed_out = study.engine.simulate(*study.arguments(c, key, {key: changed_r}, {key: changed_f}, new_prepared))
                for output_index in (0, 1, 3):
                    column = 2 if output_index == 1 else 0
                    np.testing.assert_array_equal(prefix_out[output_index], changed_out[output_index][changed_out[output_index][:, column] < cut])
                np.testing.assert_allclose(prefix_out[2], changed_out[2][:cut], atol=1.e-4, rtol=0)
                for field in ("quality", "lag30"):
                    np.testing.assert_array_equal(pp[key][field], new_prepared[key][field][:cut])
                for signal in pp[key]["direction"]:
                    np.testing.assert_array_equal(pp[key]["direction"][signal], new_prepared[key]["direction"][signal][:cut])
                cases_count += 2
        print(f"実経路の未来切断完了: {config_id}", flush=True)
    save(HERE / "保存実経路の未来切断と改変監査.json", dict(合格=True, 固定SHA256=fixed["SHA256"], 条件ID=wanted,
        口座=selected_keys, 未来切断改変数=cases_count, 切断時に未返済玉あり=observed_open,
        切断時に未執行注文あり=observed_pending, 末尾を人工返済としない=True,
        検査="8条件×10口座×3切断位置、prefixと将来価格/品質改変で注文・全決済・休止・清算時価・全方向配列の過去部分一致。", 原本取得=0, API取得=0, 実注文=0))


def main() -> None:
    """機能: 基準準備検査又は凍結後の実経路因果検査を実行する。

    引数: --future(bool)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--future", action="store_true")
    args = parser.parse_args()
    ready, features, meta = study.material()
    prepared = study.prepare(ready, features, meta)
    reference_audit(ready, features, meta, prepared)
    if args.future:
        future_audit(ready, features, meta, prepared)


if __name__ == "__main__":
    main()
