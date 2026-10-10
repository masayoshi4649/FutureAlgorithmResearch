"""独立損切り・利益保護・順行追加・次行返済を人工原本順で監査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

from adapters import check
from independent_account import CAP, POINT, HERE, fee, near, save


ROOT = HERE.parents[2]
ENGINE_PATH = HERE.parent / "engine.py"
os.environ["NUMBA_CACHE_DIR"] = str(HERE / "cache")


def load_engine(path: Path, name: str) -> object:
    """機能: 凍結前の被検査コードを読み取り、監査領域にだけコンパイル結果を保存する。

    引数: path(Path)、name(str)。返り値: 読み込んだモジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


engine = load_engine(ENGINE_PATH, "wave77_audit_engine")
old = load_engine(ROOT / "work/wave_v76/engine.py", "wave77_audit_baseline76")


def fixture(delta: list[float], symbol: str, side: int, policy: int, allocation: int = 0,
            trail_ticks: float = 20., hold: float = 0.) -> list:
    """機能: 方向対称の約定・返済気配を持つ人工原本と共同状態を生成する。

    引数: delta(list[float])、symbol(str)、side/policy/allocation(int)、trail_ticks/hold(float)。
    返り値: simulate引数(list)。deltaは有利方向の返済気配変化を呼値で表す。
    """
    n = len(delta)
    tick = .5 if symbol == "TOPIX" else 5.
    base = 4000. if symbol == "TOPIX" else 60000.
    liquidation = base + side * np.asarray(delta) * tick
    bid = liquidation if side == 1 else liquidation - tick
    ask = liquidation + tick if side == 1 else liquidation
    times = 300. + np.arange(n) * 5.
    event = np.zeros(n, dtype=np.int8); event[0] = side
    entry = ask[0] if side == 1 else bid[0]
    return [times, bid.copy(), ask.copy(), np.ones(n, dtype=bool), np.zeros(n, dtype=bool), event,
        np.arange(n, dtype=np.int32), times.copy(), np.ones(n, dtype=bool), np.full(n, side, dtype=np.int8),
        np.zeros(n, dtype=bool), np.zeros(n, dtype=bool), np.full(n, entry-10*tick), np.full(n, entry+10*tick),
        tick, 0., 1200., CAP[symbol], POINT[symbol], 41.8 if symbol == "TOPIX" else 11.,
        10*tick, trail_ticks*tick, hold, policy, allocation, 300.]


def quote_data(args: list) -> dict:
    """機能: 原本気配だけを独立全玉会計へ渡す。

    引数: args(list)。返り値: time_s/seq/bid/ask辞書(dict)。
    """
    return dict(time_s=args[0], seq=np.arange(len(args[0])), bid=args[1], ask=args[2])


def risk_check(args: list, result: tuple, symbol: str) -> int:
    """機能: リスク証跡の全料金込み予測値と初回予算を、過去注文だけで再構成する。

    引数: args(list)、result(tuple)、symbol(str)。返り値: 超過追加数(int)。
    将来の追加実約定を判断時リスクの価格に流用しない。
    """
    orders, _, _, stats, records = result
    excess = 0
    for record in records:
        row, cid, phase, budget, stop, projected, quantity, side = record
        row, cid, phase, quantity, side = map(int, (row, cid, phase, quantity, side))
        entries = [o for o in orders if int(o[2]) == cid and int(o[7]) == 1 and int(o[0]) <= row]
        assert entries
        first = entries[0]
        initial_risk = args[20]
        if args[23] == 4:
            g = int(args[6][int(first[1])])
            reference = args[12][g] if side == 1 else args[13][g]
            initial_risk = side * (first[5] - reference)
        near(budget, first[4] * max(initial_risk, 0.) * POINT[symbol] + 2 * fee(symbol, int(first[4])), "初回リスク予算")
        amount = sum(int(o[4]) for o in entries)
        cost = sum(o[4] * o[5] for o in entries)
        paid = sum(fee(symbol, int(o[4])) for o in entries)
        if phase == 0:
            extra = quantity - amount
            assert extra > 0 and quantity <= CAP[symbol]
            price = args[2][row] if side == 1 else args[1][row]
            cost += extra * price
            paid += fee(symbol, extra)
            assert args[9][int(args[6][row])] == side and -projected <= budget + 1.e-6
        else:
            assert phase == 1 and amount == quantity
            assert any(int(o[0]) == row and int(o[6]) == 11 for o in entries)
            excess += -projected > budget + 1.e-6
        independent = side * (stop * quantity - cost) * POINT[symbol] - paid - fee(symbol, quantity)
        near(projected, independent, "全玉stop時net")
    assert stats[6] == excess
    return excess


def inspect(args: list, symbol: str, label: str, exit_row: int | None = None,
            exit_reason: int | None = None, expected_quantities: list[int] | None = None) -> tuple:
    """機能: 注文・建値明細・全曲線・cap・統計と指定した因果成立点を照合する。

    引数: args(list)、symbol/label(str)、exit_row/exit_reason(int|None)、expected_quantities(list[int]|None)。
    返り値: 新再生器の結果(tuple)。未返済の人工経路では末尾清算を要求しない。
    """
    result = engine.simulate(*args)
    orders, trades, curve, stats, _ = result
    account = check(quote_data(args), symbol, orders, trades, curve, require_flat=not bool(stats[0]))
    assert stats.shape == (7,)
    assert stats[3] == account["max_long"] and stats[4] == account["max_short"]
    assert stats[5] == sum(o[6] == 11 and o[7] == 1 for o in orders)
    quantity = sum(int(o[3] * o[4]) for o in orders)
    assert stats[2] == abs(quantity) and stats[0] == np.sign(quantity)
    if exit_reason is not None:
        exits = orders[orders[:, 7] == 0]
        assert len(exits) == 1 and int(exits[0, 6]) == exit_reason, (label, exits)
        if exit_row is not None:
            assert int(exits[0, 1]) == exit_row and int(exits[0, 0]) == exit_row + 1, (label, exits)
    if expected_quantities is not None:
        assert [int(o[4]) for o in orders if o[7] == 1] == expected_quantities, (label, orders)
    risk_check(args, result, symbol)
    return result


def prefix(args: list, cut: int) -> list:
    """機能: 人工原本と同じ境界の共同格子を切断し、予定場末を保存末尾へ変えない。

    引数: args(list)、cut(int)。返り値: 切断引数(list)。
    """
    out = [a.copy() if isinstance(a, np.ndarray) else a for a in args]
    for index in range(14):
        out[index] = out[index][:cut]
    return out


def future_check(args: list, symbol: str) -> dict:
    """機能: 各seq切断と未来気配・共同状態の変更で過去注文・料金・時価が不変か確認する。

    引数: args(list)、symbol(str)。返り値: 比較数と未返済数(dict)。
    """
    full = engine.simulate(*args)
    comparisons = open_ends = 0
    n = len(args[0])
    for cut in sorted(set([1, 2, 3, n//2, n-1])):
        if not 0 < cut < n:
            continue
        short = engine.simulate(*prefix(args, cut))
        np.testing.assert_array_equal(short[0], full[0][full[0][:, 0] < cut])
        np.testing.assert_array_equal(short[1], full[1][full[1][:, 2] < cut])
        np.testing.assert_array_equal(short[2], full[2][:cut])
        np.testing.assert_array_equal(short[4], full[4][full[4][:, 0] < cut])
        check(quote_data(prefix(args, cut)), symbol, *short[:3], require_flat=False)
        open_ends += bool(short[3][0])
        changed = [a.copy() if isinstance(a, np.ndarray) else a for a in args]
        changed[1][cut:] += 10000.
        changed[2][cut:] += 10000.
        changed[3][cut:] = False
        changed[4][cut:] = True
        changed[5][cut:] *= -1
        changed[9][cut:] *= -1
        changed[10][cut:] = True
        changed[11][cut:] = True
        changed[12][cut:] -= 1000.
        changed[13][cut:] += 1000.
        mutant = engine.simulate(*changed)
        np.testing.assert_array_equal(mutant[0][mutant[0][:, 0] < cut], short[0])
        np.testing.assert_array_equal(mutant[1][mutant[1][:, 2] < cut], short[1])
        np.testing.assert_array_equal(mutant[2][:cut], short[2])
        np.testing.assert_array_equal(mutant[4][mutant[4][:, 0] < cut], short[4])
        comparisons += 2
    return dict(comparisons=comparisons, open_ends=open_ends)


def legacy_check(args: list) -> None:
    """機能: 従来policy0一括新規の注文・決済・曲線を旧76 M0と完全一致で検査する。

    引数: args(list)。返り値: なし(None)。
    """
    zeros = np.zeros(len(args[7]), dtype=bool)
    old_args = args[:7] + [args[14], args[15], args[16], args[17], args[18], args[19], args[21], 2*args[14],
        args[7], args[8], args[9], zeros, zeros, args[10], args[11], 0, args[22], args[25], 30.]
    before = old.simulate(*old_args)
    after = engine.simulate(*args)
    np.testing.assert_array_equal(after[0][:, :8], before[0])
    np.testing.assert_array_equal(after[1][:, :11], before[1])
    np.testing.assert_array_equal(after[2], before[2])
    np.testing.assert_array_equal(after[3][:2], before[4][:2])


def main() -> None:
    """機能: 全policy・二商品両方向・追加・滑り・停止・同時計・未来切断を検査する。

    引数: なし。返り値: なし(None)。新P/Lは読まず人工の成立点だけを採点する。
    """
    digest = hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()
    cases, baseline_count = [], 0
    for symbol in CAP:
        for side in (1, -1):
            for policy in range(1, 6):
                a = fixture([0, 0, -9, -10, -10], symbol, side, policy)
                inspect(a, symbol, "初期stop", 2, 1)
                cases.append((symbol, a))
            a = fixture([0, 0, 6, 3, 12, 8, 7], symbol, side, 1, trail_ticks=2)
            inspect(a, symbol, "利益が乗る前のtrail待機", 5, 2); cases.append((symbol, a))
            a = fixture([0, 0, 6, 2, 2], symbol, side, 2)
            inspect(a, symbol, "半R後の料金込み保護", 3, 2); cases.append((symbol, a))
            a = fixture([0, 0, 21, 15, 10, 9], symbol, side, 3)
            inspect(a, symbol, "二R後の一R保護", 4, 2); cases.append((symbol, a))
            a = fixture([0, 0, 6, 7, 12, 25, 26, 30, 31, 20, 19], symbol, side, 2, 1, 10)
            scaled = [2, 3, 5] if symbol == "TOPIX" else [4, 6, 10]
            r = inspect(a, symbol, "順行2割3割5割", 9, 2, scaled)
            assert any(t[10] < 0 for t in r[1]) and sum(r[1][:, 10]) > 0
            cases.append((symbol, a))
            a = fixture([0, 0, 6, 100, 99], symbol, side, 2, 1, 10)
            r = inspect(a, symbol, "既発注追加のslip超過", 3, 8, scaled[:2]); assert r[3][6] == 1
            cases.append((symbol, a))
            a = fixture([0, 0, 6, -10, -11], symbol, side, 2, 1, 10)
            r = inspect(a, symbol, "追加約定同時のstop優先", 3, 2, scaled[:2]); assert len(r[4]) == 1
            cases.append((symbol, a))
            a = fixture([0, 0, 6, 7, -10, -11], symbol, side, 2, 1, 10)
            a[9][:] = 0
            inspect(a, symbol, "逆支持なら追加なし", 4, 2, scaled[:1]); cases.append((symbol, a))
            a = fixture([0, 0, -9, -10], symbol, side, 1)
            a[10 if side == 1 else 11][2] = True
            inspect(a, symbol, "stopは反対合意より優先", 2, 1); cases.append((symbol, a))
            a = fixture([0, 0, 3, 2], symbol, side, 1)
            a[10 if side == 1 else 11][2] = True
            inspect(a, symbol, "既知の反対合意", 2, 6); cases.append((symbol, a))
            a = fixture([0, 20, 19], symbol, side, 4)
            inspect(a, symbol, "構造stop幅の実約定後超過", 1, 8); cases.append((symbol, a))
            a = fixture([0, -10, -11], symbol, side, 4)
            inspect(a, symbol, "構造線を越えた新規fill", 1, 8); cases.append((symbol, a))
            a = fixture([0, 0, -9, -10], symbol, side, 1, hold=10)
            a[0] = a[7] = np.array([300., 305., 840., 845.]); a[16] = 900.
            inspect(a, symbol, "場末はholdとstopより優先", 2, 4); cases.append((symbol, a))
            a = fixture([0, 0, 0, -9, -10], symbol, side, 1, hold=10)
            inspect(a, symbol, "holdはstopより優先", 3, 3); cases.append((symbol, a))
            a = fixture([0, 0, 6, 7, 0, 0], symbol, side, 2, 1, 10)
            a[0] = a[7] = np.array([300., 305., 595., 600., 840., 845.]); a[16] = 900.
            inspect(a, symbol, "場末で追加fill失効", 4, 4, scaled[:1]); cases.append((symbol, a))
            a = fixture([0.] * 76, symbol, side, 5)
            a[9][:] = 0
            inspect(a, symbol, "300秒停滞後30秒確認", 67, 9); cases.append((symbol, a))
            b = [x.copy() if isinstance(x, np.ndarray) else x for x in a]
            b[10 if side == 1 else 11][67] = True
            inspect(b, symbol, "反対合意と停滞の同時成立", 67, 6); cases.append((symbol, b))
            b = [x.copy() if isinstance(x, np.ndarray) else x for x in a]
            b[8][64] = False
            inspect(b, symbol, "欠測は停滞時計を破棄", 71, 9); cases.append((symbol, b))
            a = fixture([0, 0, 0, -9, -10], symbol, side, 1)
            a[1][1] = a[2][1] = np.nan
            r = inspect(a, symbol, "新規は次有効行まで待つ", 3, 1); assert r[0][0, 0] == 2
            cases.append((symbol, a))
            a = fixture([0, 0, -9, -10], symbol, side, 1)
            a[0][1] = a[0][0]; a[7][1] = a[7][0]
            r = inspect(a, symbol, "同時計でも次seq", 2, 1); assert r[0][0, 0] == 1
            cases.append((symbol, a))
            rng = np.random.default_rng(470 + CAP[symbol] + side)
            for _ in range(5):
                delta = np.cumsum(rng.normal(0, 3, 100)); delta[:2] = 0
                a = fixture(delta.tolist(), symbol, side, 0, trail_ticks=10, hold=60)
                a[5][:] = 0; a[5][::40] = side
                a[3][10:13] = False; a[4][21] = True
                a[1][7] = a[2][7] = np.nan
                a[25] = 30.
                inspect(a, symbol, "旧一括M0対照")
                legacy_check(a); baseline_count += 1
    # ----------------------------------------
    # 全人工成立点について、将来原本と共同証拠が過去を変えないか別に検査する。
    comparisons = open_ends = 0
    for symbol, args in cases:
        counts = future_check(args, symbol)
        comparisons += counts["comparisons"]; open_ends += counts["open_ends"]
    assert digest == hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest(), "検査途中のengine変更"
    save(HERE / "独立損切り利益保護と追加リスクの人工監査.json", dict(合格=True,
        人工経路数=len(cases), 旧一括基準完全一致人工経路数=baseline_count,
        未来変更切断比較数=comparisons, 切断未返済数=open_ends, engine_SHA256=digest,
        検査範囲=["二商品両方向", "初期損切り", "利益追従待機", "料金込み建値保護", "段階保護",
            "構造線と約定後超過", "停滞確認と欠測reset", "順行追加と保有cap", "追加滑り超過",
            "追加fill同時stop", "場末追加失効", "次有効行", "同時計seq", "全料金配賦", "全行清算曲線"],
        限界="共同状態を人工的に与えたengineの検査。二市場実受信因果、実入力特徴、将来収益性は別。",
        原本取得=0, API取得=0, 実注文=0, 新利益結果閲覧=0))
    print(json.dumps(dict(合格=True, 人工経路数=len(cases), 旧基準人工一致数=baseline_count,
        未来比較数=comparisons, 未返済切断数=open_ends, SHA256=digest), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
