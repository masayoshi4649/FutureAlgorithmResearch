"""実保存二市場の片側未来と原本seqを切断し、途中管理と実注文を照合する。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from numba.core.caching import NullCache
import numpy as np

from account_parts import study, ROOT
from adapters import check
from engine_synthetic import engine
from independent_account import save
import model_oracle as oracle


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("wave76_future_input", HERE.parent / "inputs/core.py")
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)
study.signals.confirmation._cache = NullCache()
study.signals.pulses._cache = NullCache()


def variant(r: dict, f: dict, snap: dict, cut: int, truncate: bool, move_clock: bool) -> tuple:
    """機能: 一市場だけの未来価格・板・品質・時計を変更し、原本seq途中も切断する。

    引数: r/f/snap(dict)、cut(int)、truncate/move_clock(bool)。返り値: 三入力(tuple)。
    """
    if truncate:
        return tuple({name: a[:cut].copy() if isinstance(a, np.ndarray) else a for name, a in source.items()}
            for source in (r, f, snap))
    rr, ff, ss = r.copy(), f.copy(), snap.copy()
    for output in (rr, ff):
        for field in ("last", "bid", "ask", "mid"):
            if field in output:
                output[field] = output[field].copy()
                output[field][cut:] *= .8
    if move_clock:
        rr["time_s"] = rr["time_s"].copy()
        rr["time_s"][cut:] += 120.
        ss["time_s"] = rr["time_s"].copy()
    for field, value in (("valid", False), ("reset", True), ("best_ofi", -1000.)):
        ff[field] = ff[field].copy()
        ff[field][cut:] = value
    ss["valid"] = ss["valid"].copy()
    ss["valid"][cut:] = False
    for field in core.SNAPSHOT_FIELDS:
        ss[field] = ss[field].copy()
        ss[field][cut:] *= -.8
    return rr, ff, ss


def slice_state(state: dict, rows: np.ndarray) -> dict:
    """機能: 共同状態と入場・保有確認の過去格子だけを抜き出す。

    引数: state(dict)、rows(ndarray[bool])。返り値: 過去共同状態(dict)。
    """
    out = {}
    for field, value in state.items():
        if field == "management":
            out[field] = {s: {k: a[rows] for k, a in arrays.items()} for s, arrays in value.items()}
        elif field == "entry":
            out[field] = {s: a[rows] for s, a in value.items()}
        else:
            out[field] = value[rows]
    return out


def main() -> None:
    """機能: 固定10設定×3場で片側未来変更・同時計seq途中・注文prefixを検査する。

    引数: なし。返り値: なし(None)。配列末尾の人工返済を許さない。
    """
    fixed = study.load(HERE.parent / "事前固定.json")
    assert all(study.digest(ROOT / p) == expected for p, expected in fixed["SHA256"].items())
    selected = study.load(HERE.parent / "前半選定.json")
    ids = [r["id"] for r in selected["代表"]]
    for ident in selected["主3"]:
        rep = next(r for r in selected["代表"] if r["id"] == ident)
        ids.append(rep["controls"][5])
    ids.append(selected["基準"])
    ids = list(dict.fromkeys(ids))
    configs = [c for c in fixed["条件"] if c["id"] in ids]
    assert len(configs) == len(ids)
    ready, book, saved_state, full_maps, all_legacy, meta = study.material(5)
    snapshots = study.load(HERE.parent / "inputs/snapshots.pkl")
    sessions = [fixed["全29"][i] for i in (0, 3, 28)]
    checks = arrays = opens = pending = reservations = seq_cases = 0
    for session in sessions:
        keys = [(session, s) for s in ("TOPIX", "NK225")]
        rr0, ff0, ss0 = ({k: source[k] for k in keys} for source in (ready, book, snapshots))
        grid_record = core.session_features(rr0, ff0, ss0, session, 5)
        full_state = study.signals.build({session: grid_record})
        for definition in full_state:
            oracle.compare(full_state[definition][session], saved_state[definition][session])
        baseline_legacy = {k: all_legacy[k] for k in keys}
        maps = {k: study.signals.mapping(grid_record["grid"], rr0[k]) for k in keys}
        originals = {(c["id"], k): engine.simulate(*study.arguments(c, k, rr0, ff0, full_state, maps, baseline_legacy, meta))
            for c in configs for k in keys}
        for changed_key in keys:
            r = ready[changed_key]
            midpoint = len(r["seq"]) // 2
            first = int(np.searchsorted(r["time_s"], r["time_s"][midpoint], side="left"))
            for cut, seq_mode in ((first, False), (first + 1, True)):
                assert 0 < cut < len(r["seq"])
                cutoff = r["time_s"][cut]
                for truncate in (True, False):
                    rr, ff, ss = rr0.copy(), ff0.copy(), ss0.copy()
                    rr[changed_key], ff[changed_key], ss[changed_key] = variant(rr0[changed_key], ff0[changed_key], ss0[changed_key], cut, truncate, not seq_mode)
                    record = core.session_features(rr, ff, ss, session, 5)
                    state = study.signals.build({session: record})
                    before = record["grid"] <= cutoff
                    for ident in full_state:
                        arrays += oracle.compare(slice_state(state[ident][session], before), slice_state(full_state[ident][session], before))
                    maps = {k: study.signals.mapping(record["grid"], rr[k]) for k in keys}
                    legacy = baseline_legacy.copy()
                    if truncate:
                        legacy[changed_key] = dict(baseline_legacy[changed_key])
                        candidates = legacy[changed_key]["candidates"]
                        legacy[changed_key]["candidates"] = candidates[candidates[:, 1] < cut].copy()
                    for c in configs:
                        for key in keys:
                            out = engine.simulate(*study.arguments(c, key, rr, ff, state, maps, legacy, meta))
                            original = originals[(c["id"], key)]
                            own_cut = cut if key == changed_key else int(np.searchsorted(ready[key]["time_s"], cutoff, side="left"))
                            for column, index in ((0, 0), (2, 1), (0, 3)):
                                a = out[index][out[index][:, column] < own_cut]
                                b = original[index][original[index][:, column] < own_cut]
                                np.testing.assert_array_equal(a, b)
                            np.testing.assert_allclose(out[2][:own_cut], original[2][:own_cut], atol=1.e-4, rtol=0)
                            if truncate and key == changed_key:
                                check(dict(time_s=rr[key]["time_s"], seq=rr[key]["seq"], bid=ff[key]["bid"], ask=ff[key]["ask"]), key[1], *out[:3], False)
                                opens += int(out[4][0] != 0)
                                pending += int(out[4][1] != 0)
                                reservations += int(out[4][2] != 0)
                            checks += 1
                    seq_cases += int(seq_mode)
        print(f"共同途中判断の片側未来と注文prefix一致: {session}", flush=True)
    save(HERE / "二市場実経路の片側未来と途中管理注文の独立監査.json", dict(合格=True,
        固定設定数=len(configs), 二市場場数=len(sessions), 片側未来切断改変比較数=checks,
        過去状態確認配列比較数=arrays, 同時計seq途中切断数=seq_cases,
        切断時未返済数=opens, 切断時執行待ち数=pending, 切断時反転予約数=reservations,
        設定ID=ids, 場=sessions, 配列末尾の架空返済なし=True, 固定SHA256=fixed["SHA256"],
        限界="一市場だけの価格・最良OFI・十段snapshot・品質・時計の未来改変と同時計原本seq途中切断。実受信共通時計がなく、代理時計上の因果性を検査した。",
        原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, 注文prefix比較数=checks, 切断時未返済数=opens), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
