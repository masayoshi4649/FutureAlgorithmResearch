"""二市場の片側未来を切断・改変し、共同状態と実注文の過去部分を照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from account_parts import study, ROOT
from adapters import check
from independent_account import save
from real_signals import load_material


HERE = Path(__file__).resolve().parent


def variant(r: dict, f: dict, cut: int, truncate: bool, move_clock: bool) -> tuple[dict, dict]:
    """機能: 一市場だけ原本seqの後半を切る、又は価格・板・品質・時計を改変する。

    引数: r/f(dict)、cut(int)、truncate/move_clock(bool)。返り値: 新しいready/book(tuple)。
    """
    if truncate:
        return tuple({name: value[:cut].copy() if isinstance(value, np.ndarray) else value for name, value in source.items()} for source in (r, f))
    rr, ff = r.copy(), f.copy()
    for changed in (rr, ff):
        for name in ("last", "bid", "ask", "mid"):
            if name in changed:
                changed[name] = changed[name].copy()
                changed[name][cut:] *= .8
        if move_clock:
            changed["time_s"] = changed["time_s"].copy()
            changed["time_s"][cut:] += 120.
    for name, value in (("best_ofi", -1000.), ("valid", False), ("reset", True)):
        ff[name] = ff[name].copy()
        ff[name][cut:] = value
    return rr, ff


def main() -> None:
    """機能: 固定10設定×3場について、両方向の片側未来を原本順で検査する。

    引数: なし。返り値: なし(None)。切断prefixに人工返済を足さない。
    """
    fixed = study.load(HERE.parent / "事前固定.json")
    assert all(study.digest(ROOT / name) == expected for name, expected in fixed["SHA256"].items())
    selected = study.load(HERE.parent / "前半選定.json")
    wanted = [r["id"] for r in selected["代表"]] + ["S" + ident[1:] for ident in selected["主3"]]
    by_id = {c["id"]: c for c in fixed["条件"]}
    configs = [by_id[ident] for ident in wanted]
    ready, book, sync, meta = load_material()
    sessions = [fixed["全29"][index] for index in (0, 3, 28)]
    checks = signal_checks = seq_cases = opens = pending = 0
    for session in sessions:
        keys = [(session, symbol) for symbol in ("TOPIX", "NK225")]
        rr0, ff0 = {key: ready[key] for key in keys}, {key: book[key] for key in keys}
        ss = {session: sync[session]}
        full_entry = study.signals.build(rr0, ff0, ss, 5, 30)
        full_out = {(c["id"], key): study.engine.simulate(*study.arguments(c, key, rr0, ff0, full_entry, meta)) for c in configs for key in keys}
        for changed_key in keys:
            r = ready[changed_key]
            midpoint = len(r["seq"]) // 2
            clock = r["time_s"][midpoint]
            first = int(np.searchsorted(r["time_s"], clock, side="left"))
            next_seq = min(first + 1, len(r["seq"]) - 1)
            for cut, seq_mode in ((first, False), (next_seq, True)):
                assert cut > 0
                for truncate in (True, False):
                    rr, ff = rr0.copy(), ff0.copy()
                    rr[changed_key], ff[changed_key] = variant(rr0[changed_key], ff0[changed_key], cut, truncate, not seq_mode)
                    new_entry = study.signals.build(rr, ff, ss, 5, 30)
                    before_grid = ss[session]["grid"] < r["time_s"][cut]
                    for ident in full_entry:
                        for key in keys:
                            for field in ("states", "valid", "pulse", "own_source", "peer_source"):
                                np.testing.assert_array_equal(full_entry[ident][key][field][before_grid], new_entry[ident][key][field][before_grid])
                                signal_checks += 1
                    for c in configs:
                        for key in keys:
                            out = study.engine.simulate(*study.arguments(c, key, rr, ff, new_entry, meta))
                            baseline = full_out[(c["id"], key)]
                            own_cut = cut if key == changed_key else int(np.searchsorted(ready[key]["time_s"], r["time_s"][cut], side="left"))
                            for output_index in (0, 1, 3):
                                column = 2 if output_index == 1 else 0
                                before = baseline[output_index][baseline[output_index][:, column] < own_cut]
                                after = out[output_index][out[output_index][:, column] < own_cut]
                                np.testing.assert_array_equal(after, before)
                            np.testing.assert_allclose(out[2][:own_cut], baseline[2][:own_cut], atol=1.e-4, rtol=0)
                            if truncate and key == changed_key:
                                check(dict(time_s=rr[key]["time_s"], seq=rr[key]["seq"], bid=ff[key]["bid"], ask=ff[key]["ask"]), key[1], *out[:3], False)
                                opens += int(out[4][0] != 0)
                                pending += int(out[4][1] != 0)
                            checks += 1
                    seq_cases += int(seq_mode)
        print(f"二市場の片側未来・注文prefix照合完了: {session}", flush=True)
    save(HERE / "二市場実経路の片側未来切断と注文監査.json", dict(合格=True, 固定SHA256=fixed["SHA256"],
        実設定数=len(configs), 二市場場数=len(sessions), 片側改変切断数=checks, 原本seq切断数=seq_cases,
        過去共同状態配列比較数=signal_checks, 切断時未返済数=opens, 切断時未発注執行待ち数=pending,
        設定ID=wanted, 場=sessions, 配列末尾で人工返済しない=True,
        限界="一方だけの価格・板・品質・時計改変と原本seq切断で過去部分が不変。同時計途中seq切断も含む。受信共通時計がないため銘柄間実受信因果までは証明しない。",
        原本取得=0, API取得=0, 実注文=0))
    print(json.dumps(dict(合格=True, 片側改変切断数=checks, 切断時未返済数=opens), ensure_ascii=False))


if __name__ == "__main__":
    main()
