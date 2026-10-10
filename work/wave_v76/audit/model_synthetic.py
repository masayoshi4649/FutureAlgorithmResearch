"""短期共同状態・両側更新確認・発火・写像を人工入力で独立検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys

import numba
from numba.core.caching import NullCache
import numpy as np

from confirmation_oracle import confirmed_progress
from independent_account import save
import model_oracle as oracle


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("wave76_audit_signals", HERE.parent / "signals.py")
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)
numba.config.CACHE_DIR = str(HERE / "cache")
# ----------------------------------------
# 被検査器が設定する共用キャッシュへ監査用モジュール名を書き込まない。
model.confirmation._cache = NullCache()
model.pulses._cache = NullCache()


def market(direction: int, size: int) -> dict:
    """機能: 明確な板偏り・フロー・短期価格方向の人工特徴を作る。

    引数: direction/size(int)。返り値: 一市場特徴(dict)。
    """
    current = dict(valid=np.ones(size, bool), index=np.arange(size, dtype=np.int32),
        best_imbalance=np.full(size, .3 * direction), depth_imbalance=np.full(size, .4 * direction))
    windows = {}
    for length in (5, 15, 30, 60):
        windows[length] = dict(source_valid=np.ones(size, bool), valid=np.ones(size, bool),
            missing_ofi=np.zeros(size, bool), nonzero_ofi_count=np.full(size, 10, dtype=np.int32),
            ofi_ratio=np.full(size, .5 * direction), mid_change_bp=np.full(size, 2. * direction),
            bid_change_ticks=np.full(size, direction, dtype=float), ask_change_ticks=np.full(size, direction, dtype=float))
    return dict(current=current, windows=windows)


def cases() -> dict:
    """機能: 無活動・少数証拠・欠測・矛盾・参照停止・格子gapを区別した事例を作る。

    引数: なし。返り値: 名前から二市場特徴への対応(dict)。
    """
    n = 60
    baseline = dict(grid=np.arange(n, dtype=float) * 5. + 300.,
        markets={s: market(1, n) for s in ("TOPIX", "NK225")})
    out = {"両市場上方向": baseline,
        "両市場下方向": dict(grid=baseline["grid"].copy(), markets={s: market(-1, n) for s in ("TOPIX", "NK225")}),
        "両市場不一致": dict(grid=baseline["grid"].copy(), markets={"TOPIX": market(1, n), "NK225": market(-1, n)})}
    for name in ("既知無活動", "少数OFI", "OFI欠測", "始終同じ参照行", "片側表示板欠測",
            "双方参照停止", "片側だけ参照停止", "途中欠測", "途中反対", "格子欠落", "合意なしから再合意"):
        value = deepcopy(baseline)
        if name == "既知無活動":
            for m in value["markets"].values():
                for w in m["windows"].values():
                    w["valid"][:] = False
                    w["nonzero_ofi_count"][:] = 0
                    w["ofi_ratio"][:] = np.nan
        elif name == "少数OFI":
            for m in value["markets"].values():
                for w in m["windows"].values():
                    w["nonzero_ofi_count"][:] = 2
        elif name == "OFI欠測":
            for w in value["markets"]["TOPIX"]["windows"].values():
                w["missing_ofi"][:] = True
        elif name == "始終同じ参照行":
            for w in value["markets"]["TOPIX"]["windows"].values():
                w["source_valid"][:] = False
        elif name == "片側表示板欠測":
            value["markets"]["TOPIX"]["current"]["valid"][:] = False
        elif name in ("双方参照停止", "片側だけ参照停止"):
            symbols = ("TOPIX", "NK225") if name == "双方参照停止" else ("TOPIX",)
            for s in symbols:
                value["markets"][s]["current"]["index"][:] = 0
        elif name == "途中欠測":
            value["markets"]["TOPIX"]["current"]["valid"][[2, 7, 21]] = False
        elif name == "途中反対":
            for s in ("TOPIX", "NK225"):
                for field in ("best_imbalance", "depth_imbalance"):
                    value["markets"][s]["current"][field][12:] *= -1
                for w in value["markets"][s]["windows"].values():
                    for field in ("ofi_ratio", "mid_change_bp", "bid_change_ticks", "ask_change_ticks"):
                        w[field][12:] *= -1
        elif name == "格子欠落":
            value["grid"][3:] += 5.
        elif name == "合意なしから再合意":
            for s in ("TOPIX", "NK225"):
                for field in ("best_imbalance", "depth_imbalance"):
                    value["markets"][s]["current"][field][9:12] = 0.
                for w in value["markets"][s]["windows"].values():
                    for field in ("ofi_ratio", "mid_change_bp", "bid_change_ticks", "ask_change_ticks"):
                        w[field][9:12] = 0.
        out[name] = value
    out["全空"] = dict(grid=np.array([], dtype=float), markets={s: market(1, 0) for s in ("TOPIX", "NK225")})
    return out


def main() -> None:
    """機能: 人工全状態・入口・確認・片側未来・銘柄交換を独立検査する。

    引数: なし。返り値: なし(None)。損益結果を参照しない。
    """
    sha = hashlib.sha256((HERE.parent / "signals.py").read_bytes()).hexdigest()
    state_checks = future_checks = swap_checks = confirmation_checks = map_checks = 0
    fixtures = cases()
    for name, session in fixtures.items():
        grid = session["grid"]
        for definition in model.definitions():
            got = model.joint(definition, session)
            expected = oracle.joint(definition, session)
            state_checks += oracle.compare(got, expected)
            if name in ("既知無活動", "少数OFI") and definition["kind"] in ("F", "FD"):
                assert got["valid"].all() and not got["strong"].any()
                assert got["management"][15]["loss_long"][3:].all()
            if name in ("双方参照停止", "片側だけ参照停止"):
                assert not got["entry"][10].any()
                assert not any(a.any() for a in got["management"][15].values())
            for condition in (got["strong"] == 1, got["strong"] == -1, ~got["support_long"]):
                for seconds in (10., 15., 30.):
                    a = oracle.confirmation(grid, condition, got["valid"], got["source_top"], got["source_nk"], seconds)
                    b = confirmed_progress(grid, np.ones(len(grid)), condition & got["valid"],
                        got["source_top"], got["source_nk"], seconds)
                    np.testing.assert_array_equal(a, b)
                    confirmation_checks += 1
            reversed_session = dict(grid=grid, markets={"TOPIX": session["markets"]["NK225"], "NK225": session["markets"]["TOPIX"]})
            swapped = model.joint(definition, reversed_session)
            for field in ("strong", "valid", "disagreement", "support_long", "support_short"):
                np.testing.assert_array_equal(swapped[field], got[field])
                swap_checks += 1
            for symbol in ("TOPIX", "NK225"):
                for cut in (5, 15, 35):
                    if cut >= len(grid):
                        continue
                    changed = deepcopy(session)
                    current = changed["markets"][symbol]["current"]
                    current["valid"][cut:] = False
                    current["index"][cut:] += 1000
                    current["best_imbalance"][cut:] *= -1
                    current["depth_imbalance"][cut:] *= -1
                    for w in changed["markets"][symbol]["windows"].values():
                        w["source_valid"][cut:] = False
                        w["ofi_ratio"][cut:] *= -1
                    altered = model.joint(definition, changed)
                    oracle.compare({k: ({s: {f: a[:cut] for f, a in v.items()} for s, v in values.items()}
                        if k == "management" else {s: a[:cut] for s, a in values.items()} if k == "entry" else values[:cut])
                        for k, values in altered.items()},
                        {k: ({s: {f: a[:cut] for f, a in v.items()} for s, v in values.items()}
                        if k == "management" else {s: a[:cut] for s, a in values.items()} if k == "entry" else values[:cut])
                        for k, values in got.items()})
                    future_checks += 1
        for times in (np.arange(0., 900., 1.), np.arange(0., 900., 19.), np.repeat(np.arange(0., 900., 5.), 3), np.array([])):
            np.testing.assert_array_equal(model.mapping(grid, {"time_s": times}), oracle.mapping(grid, times))
            map_checks += 1
    assert hashlib.sha256((HERE.parent / "signals.py").read_bytes()).hexdigest() == sha
    save(HERE / "短期共同状態と更新確認と発火の人工独立監査.json", dict(合格=True,
        人工二市場経路数=len(fixtures), 入口定義数=16, 状態確認配列比較数=state_checks,
        異なる独立確認器同士の比較数=confirmation_checks, 片側未来改変数=future_checks,
        銘柄交換配列比較数=swap_checks, 原本写像比較数=map_checks, signals_SHA256=sha,
        分離="無活動・少数OFIは観測有効な支持なし。欠測・始終同一行は無効。合意なしの中立又は不一致は10秒再準備に含む。",
        限界="モデル人工特徴を検査。実受信の共通時計なしの制約は解消しない。",
        原本取得=0, API取得=0, 実注文=0, 損益閲覧=0))
    print(f"人工{len(fixtures)}経路・未来{future_checks}比較の共同状態が独立一致しました", flush=True)


if __name__ == "__main__":
    main()
