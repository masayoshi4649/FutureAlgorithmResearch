"""固定代表と追加対照の既往原本順注文に、切断と未来変更を加えて検査する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json

import numba
import numpy as np

from account_parts import HERE, study
from independent_account import save


def compare_prefix(actual: tuple, full: tuple, count: int) -> int:
    """機能: 注文・全建値決済・全玉時価・追加リスクの確定済み範囲を比較する。

    引数: actual/full(tuple)、count(int)。返り値: 比較配列数(int)。
    """
    expected = (full[0][full[0][:, 0] < count], full[1][full[1][:, 2] < count],
                full[2][:count], full[4][full[4][:, 0] < count])
    outputs = (actual[0][actual[0][:, 0] < count], actual[1][actual[1][:, 2] < count],
               actual[2][:count], actual[4][actual[4][:, 0] < count])
    for a, b in zip(outputs, expected):
        assert np.array_equal(a, b, equal_nan=True), (count, a.shape, b.shape)
    return 4


def cut_args(args: tuple, count: int) -> tuple:
    """機能: 既知の時計・場終了予定を維持し、原本行と共同格子を途中までに切る。

    引数: args(tuple)、count(int)。返り値: 同じAPIの途中引数(tuple)。
    """
    out = list(args)
    grid_end = int(np.searchsorted(args[7], args[0][count - 1], side="right"))
    for index in range(7):
        out[index] = args[index][:count].copy()
    for index in range(7, 14):
        out[index] = args[index][:grid_end].copy()
    assert not np.any(out[6] >= grid_end)
    return tuple(out)


def future_args(args: tuple, count: int, mode: int) -> tuple:
    """機能: 既知範囲を保存し、未来の気配又は共同判断だけを敵対的に変更する。

    引数: args(tuple)、count/mode(int)。返り値: 未来改変引数(tuple)。
    """
    out = list(args)
    if mode == 0:
        for index in (1, 2, 3, 4, 5, 6):
            out[index] = args[index].copy()
        tail = len(args[0]) - count
        level = 1000 * args[14] + (np.arange(tail) % 17) * 70 * args[14]
        out[1][count:] = level
        out[2][count:] = level + args[14]
        out[3][count:] = np.arange(tail) % 3 != 0
        out[4][count:] = np.arange(tail) % 4 == 0
        out[5][count:] = np.where(np.arange(tail) % 2, -1, 1)
        out[6][count:] = -1
    else:
        grid_end = int(np.searchsorted(args[7], args[0][count - 1], side="right"))
        for index in range(8, 14):
            out[index] = args[index].copy()
        out[8][grid_end:] = False
        out[9][grid_end:] *= -1
        out[10][grid_end:] = True
        out[11][grid_end:] = True
        out[12][grid_end:] = 1.
        out[13][grid_end:] = 1e9
    return tuple(out)


def one_case(case: tuple, materials: tuple, catalog: dict) -> dict:
    """機能: 一設定一口座を保存台帳と照合後、実注文前後で切断・未来改変する。

    引数: case(tuple)、materials(tuple)、catalog(dict)。返り値: 検査計数(dict)。
    """
    ident, key, ledger = case
    args = study.arguments(catalog[ident], key, *materials)
    full = study.engine.simulate(*args)
    for name, index in (("orders", 0), ("trades", 1), ("stats", 3), ("risk_events", 4)):
        assert np.array_equal(full[index], ledger[name], equal_nan=True), (ident, key, name)
    assert hashlib.sha256(full[2].tobytes()).hexdigest() == ledger["curve_hash"]
    n = len(args[0]); cuts = {max(1, n // 2)}
    orders = full[0]
    for subset in (orders[orders[:, 7] == 1], orders[orders[:, 7] == 0],
                   orders[(orders[:, 7] == 1) & (orders[:, 9] > 0)]):
        for row in subset[:2]:
            for field in (0, 1):
                count = int(row[field]) + 1
                if 0 < count < n:
                    cuts.add(count)
    comparisons = 0; open_count = 0; pending = 0
    for count in sorted(cuts):
        prefix = study.engine.simulate(*cut_args(args, count))
        comparisons += compare_prefix(prefix, full, count)
        open_count += int(prefix[3][2] > 0)
        pending += int(prefix[3][1] > 0)
        for mode in (0, 1):
            changed = study.engine.simulate(*future_args(args, count, mode))
            comparisons += compare_prefix(changed, full, count)
    return dict(id=ident, session=key[0], symbol=key[1], 切断地点数=len(cuts),
                検査数=len(cuts) * 3, 配列照合数=comparisons, 切断未返済数=open_count,
                切断発注待ち数=pending, 実追加注文数=int(np.count_nonzero((orders[:, 7] == 1) & (orders[:, 9] > 0))))


def main() -> None:
    """機能: 固定代表と追加対照の既往3場及び実追加例を6並列で検査・保存する。

    引数: なし。返り値: なし(None)。追加Nightの再生は実行しない。
    """
    numba.config.CACHE_DIR = str(HERE / "cache")
    fixed = study.load(HERE.parent / "事前固定.json")
    selected = study.load(HERE.parent / "前半選定.json")
    ids = [selected["基準"]] + [r["id"] for r in selected["代表"]]
    ids += ["Q1_P2_R20_T20_H30_A1", "P1_P2_R20_T20_H60_A1"]
    catalog = {c["id"]: c for c in fixed["条件"]}
    materials = study.material(5)
    sessions = ("2026-09-21_Day", "2026-09-22_Night", "2026-10-09_Day")
    jobs = []
    for ident in ids:
        ledger = study.load(HERE.parent / "ledgers" / f"{ident}.pkl")
        keys = [k for k in sorted(ledger) if k[0] in sessions]
        if catalog[ident]["allocation"] == 1:
            added = [k for k in sorted(ledger) if k not in keys and
                     np.any((ledger[k]["orders"][:, 7] == 1) & (ledger[k]["orders"][:, 9] > 0))]
            if added:
                keys.append(added[0])
        assert all(k[0] in fixed["全29"] and k[0] not in fixed["追加1"] for k in keys)
        jobs += [(ident, key, ledger[key]) for key in keys]
    first = one_case(jobs[0], materials, catalog)
    rows = [first]
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks = [pool.submit(one_case, job, materials, catalog) for job in jobs[1:]]
        for task in as_completed(tasks):
            rows.append(task.result())
    rows.sort(key=lambda r: (r["id"], r["session"], r["symbol"]))
    proof = dict(合格=True, 条件数=len(ids), 口座数=len(rows),
        **{field: sum(r[field] for r in rows) for field in (
            "切断地点数", "検査数", "配列照合数", "切断未返済数", "切断発注待ち数", "実追加注文数")},
        条件=ids, 検査口座=rows, engine_SHA256=study.digest(HERE.parent / "engine.py"),
        範囲="基準・固定代表3・追加P2対照2、既往3場の両商品。追加のある対照は既往の実追加1口座も検査。",
        方式="入口判断後・約定直後、返済判断後・約定直後、実追加判断後・約定直後と場途中を切断。未来の気配・有効性・新規候補、又は共同状態・構造線を別々に改変。確定済注文/全決済/全玉時価/リスク証跡は全配列厳密一致。",
        限界="注文器の因果検査。生データ→格子及び格子→共同信号は別監査を併読。真の受信時計の因果保証ではない。",
        原本取得=0, API取得=0, 実注文=0, 新Night再生回数=0)
    save(HERE / "固定代表と追加対照の実注文未来不変監査.json", proof)
    print(json.dumps({k: v for k, v in proof.items() if k not in ("検査口座", "条件")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
