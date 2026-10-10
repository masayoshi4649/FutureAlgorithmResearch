"""統合器の単独機構と同時成立を、人工気配と独立全玉会計で監査する。"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys

import numpy as np

from adapters import check
from independent_account import CAP, HERE, POINT, save


ROOT = HERE.parents[2]
ENGINE_PATH = HERE.parent / "engine.py"
os.environ["NUMBA_CACHE_DIR"] = str(HERE / "cache")


def module(path: Path, name: str) -> object:
    """機能: 被検査器を監査専用名で読み込み、旧成果のキャッシュを書き換えない。

    引数: path(Path)、name(str)。返り値: 読込モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


engine = module(ENGINE_PATH, "wave78_audit_engine")
old = module(ROOT / "work/wave_v77/engine.py", "wave78_audit_old77")


def fixture(delta: list[float] | np.ndarray, symbol: str, side: int, flow: int = 0,
            protection: float = 0., holding: int = 0, rest: int = 0) -> list:
    """機能: 同一呼値数の有利変化から、商品と方向に対称な気配を作る。

    引数: delta(list[float]|ndarray)、symbol(str)、side/flow/holding/rest(int)、protection(float)。
    返り値: 統合器の29引数(list)。最初の注文判断は行0、実約定は行1。
    """
    n = len(delta)
    tick = .5 if symbol == "TOPIX" else 5.
    base = 4000. if symbol == "TOPIX" else 60000.
    liquidation = base + side * np.asarray(delta) * tick
    bid = liquidation if side == 1 else liquidation-tick
    ask = liquidation+tick if side == 1 else liquidation
    time = 300. + np.arange(n)*5.
    event = np.zeros(n, dtype=np.int8); event[0] = side
    return [time, bid.copy(), ask.copy(), np.ones(n, dtype=bool), np.zeros(n, dtype=bool),
        event, np.arange(n, dtype=np.int32), time.copy(), np.ones(n, dtype=bool),
        np.full(n, side, dtype=np.int8), np.zeros(n, dtype=bool), np.zeros(n, dtype=bool),
        np.zeros(n, dtype=bool), np.zeros(n, dtype=bool), tick, 0., 10000., CAP[symbol],
        POINT[symbol], 41.8 if symbol == "TOPIX" else 11., 10*tick,
        np.ones(n, dtype=bool), np.full(n, side, dtype=np.int8), np.arange(n), np.arange(n),
        flow, protection, holding, rest]


def quote_data(args: list) -> dict:
    """機能: 会計器へ原本気配だけを渡す。

    引数: args(list)。返り値: 原本辞書(dict)。
    """
    return dict(time_s=args[0], seq=np.arange(len(args[0])), bid=args[1], ask=args[2])


def inspect(args: list, symbol: str) -> tuple:
    """機能: 注文と決済明細、手数料、全行清算時価を独立会計に照合する。

    引数: args(list)、symbol(str)。返り値: 統合器の五結果(tuple)。
    """
    result = engine.simulate(*args)
    account = check(quote_data(args), symbol, *result[:3], require_flat=not bool(result[3][0]))
    assert result[3].shape == (7,) and result[4].shape[1] == 6
    assert result[3][3] == account["max_long"] and result[3][4] == account["max_short"]
    assert result[3][2] == abs(sum(o[3]*o[4] for o in result[0]))
    return result


def exit_at(result: tuple, row: int, reason: int) -> None:
    """機能: 全返済判断行と次行約定を独立の予定値と比較する。

    引数: result(tuple)、row/reason(int)。返り値: なし(None)。
    """
    exits = result[0][result[0][:, 7] == 0]
    assert len(exits) == 1 and tuple(exits[0, [1, 0, 6]]) == (row, row+1, reason), exits


def cut_args(args: list, count: int) -> list:
    """機能: 未来だけを切り、既知の場終了予定を維持する。

    引数: args(list)、count(int)。返り値: 切断済み引数(list)。
    """
    out = list(args)
    grid_end = int(np.searchsorted(args[7], args[0][count-1], side="right"))
    for k in range(7):out[k] = args[k][:count].copy()
    for k in (*range(7, 14), *range(21, 25)):out[k] = args[k][:grid_end].copy()
    return out


def compare(actual: tuple, full: tuple, count: int) -> None:
    """機能: 確定済み注文・決済・清算時価・管理イベントの全要素一致を要求する。

    引数: actual/full(tuple)、count(int)。返り値: なし(None)。
    """
    for a, b in ((actual[0], full[0][full[0][:, 0] < count]),
                 (actual[1], full[1][full[1][:, 2] < count]), (actual[2], full[2][:count]),
                 (actual[4], full[4][full[4][:, 0] < count])):
        np.testing.assert_array_equal(a, b)


def future_check(args: list, symbol: str) -> int:
    """機能: 注文と管理イベントの前後で切断及び未来改変を行う。

    引数: args(list)、symbol(str)。返り値: 比較回数(int)。
    """
    full = inspect(args, symbol); n = len(args[0]); cuts = {1, 2, 3, n//2, n-1}
    for events in (full[0], full[4]):
        for row in events[:12, 0].astype(int):cuts.update((row, row+1))
    comparisons = 0
    for count in sorted(x for x in cuts if 0 < x < n):
        short = inspect(cut_args(args, count), symbol); compare(short, full, count)
        changed = [v.copy() if isinstance(v, np.ndarray) else v for v in args]
        changed[1][count:] += 10000.; changed[2][count:] += 10000.
        changed[3][count:] = False; changed[4][count:] = True; changed[5][count:] *= -1
        changed[9][count:] *= -1; changed[10][count:] = True; changed[11][count:] = True
        changed[12][count:] = True; changed[13][count:] = True; changed[21][count:] = False
        changed[22][count:] *= -1; changed[23][count:] += 100000; changed[24][count:] += 100000
        mutant = engine.simulate(*changed)
        prefix = (mutant[0][mutant[0][:, 0] < count], mutant[1][mutant[1][:, 2] < count],
            mutant[2][:count], mutant[3], mutant[4][mutant[4][:, 0] < count])
        compare(prefix, full, count); comparisons += 2
    return comparisons


def legacy(args: list) -> None:
    """機能: 全機構無効の注文・明細・曲線を旧wave77基準と完全一致させる。

    引数: args(list)。返り値: なし(None)。
    """
    zeros = np.zeros(len(args[7]), dtype=bool)
    old_args = args[:10]+[zeros, zeros, np.zeros(len(zeros)), np.zeros(len(zeros))]
    old_args += args[14:20]+[args[20], args[20], 1800., 0, 0, 30.]
    current, prior = engine.simulate(*args), old.simulate(*old_args)
    for i in range(4):np.testing.assert_array_equal(current[i], prior[i])


def main() -> None:
    """機能: 二商品・両方向で独立機構、重複条件、休止再開及び未来不変を監査する。

    引数: なし。返り値: なし(None)。新候補の実データ損益は読まない。
    """
    digest = hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()
    cases = []; baseline = 0
    for symbol in CAP:
        for side in (1, -1):
            a = fixture([0, 0, -9, -10, -10], symbol, side)
            exit_at(inspect(a, symbol), 2, 1); legacy(a); baseline += 1; cases.append((symbol, "初期損切り", a))
            for fraction, high in ((.25, 4), (.5, 6)):
                a = fixture([0, 0, high-1, high, 2, 1], symbol, side, protection=fraction)
                result = inspect(a, symbol); exit_at(result, 4, 2)
                assert result[4][0, 0] == 3 and result[4][0, 2] == 21
                assert result[1][0, 10] < 0, "保護線を下回る実約定は赤字のまま"
                cases.append((symbol, "費用込み保護と価格飛び", a))
            for flow in (1, 2):
                a = fixture([0, 0, 2, 3, 2], symbol, side, flow=flow)
                a[(10 if side == 1 else 11) if flow == 1 else (12 if side == 1 else 13)][3:] = True
                exit_at(inspect(a, symbol), 3, 6); cases.append((symbol, "反対合意", a))
            # ----------------------------------------
            # 時間延長は最新の利益・共同支持・新極値を全て満たす時だけ許す。
            steps = np.maximum(0, np.floor((np.arange(1120)*5.-5.)/240.)+2.)
            steps[:2] = 0
            a = fixture(steps, symbol, side, holding=1)
            result = inspect(a, symbol); exit_at(result, 1081, 3)
            assert list(result[4][:, 2]) == [20, 20, 20, 20]
            cases.append((symbol, "利益継続時の最大90分", a))
            for failure in ("共通方向消失", "情報無効", "新高安なし", "同値再接触"):
                b = [v.copy() if isinstance(v, np.ndarray) else v for v in a]
                if failure == "共通方向消失":b[9][361] = 0
                elif failure == "情報無効":b[8][361] = False
                else:
                    b[1][100:] = b[1][99]; b[2][100:] = b[2][99]
                    if failure == "同値再接触":
                        b[1][359] -= side*b[14]; b[2][359] -= side*b[14]
                exit_at(inspect(b, symbol), 361, 3); cases.append((symbol, failure, b))
            b = [v.copy() if isinstance(v, np.ndarray) else v for v in a]; b[27] = 2
            exit_at(inspect(b, symbol), 1081, 3); cases.append((symbol, "固定90分", b))
            b = [v.copy() if isinstance(v, np.ndarray) else v for v in a]; b[16] = b[0][361]+60.
            exit_at(inspect(b, symbol), 361, 4); cases.append((symbol, "場内撤収優先", b))
            # ----------------------------------------
            # 二つの確定損失後、30分の休止と60秒の新しい共同状態を順番に満たす。
            d = np.zeros(440); d[2:8] = -10; d[9:] = -10
            b = fixture(d, symbol, side, flow=1, rest=1)
            b[5][9] = side; b[5][12] = side; b[5][25] = side; b[5][385] = side; b[5][400] = side
            own = 10 if side == 1 else 11; b[own][12] = True
            b[22][:] = 0; b[9][:] = 0
            result = inspect(b, symbol)
            entries = result[0][result[0][:, 7] == 1]
            assert list(entries[:, 1]) == [0., 9., 385.], entries
            records = result[4]; starts = records[records[:, 2] == 22]; resumed = records[records[:, 2] == 23]
            assert len(starts) == len(resumed) == 1
            assert starts[0, 0] == 13 and resumed[0, 0] == 385, records
            assert starts[0, 3] == b[0][13]+1800.
            cases.append((symbol, "連敗後30分と新たな60秒", b))
            c = [v.copy() if isinstance(v, np.ndarray) else v for v in b]
            c[24][:] = 0
            result = inspect(c, symbol)
            assert not np.any(result[4][:, 2] == 23)
            assert len(result[0][result[0][:, 7] == 1]) == 2
            cases.append((symbol, "相手の更新なしでは再開しない", c))
    total = sum(future_check(a, symbol) for symbol, _, a in cases)
    assert hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest() == digest
    proof = dict(合格=True, 人工経路数=len(cases), 旧基準完全一致数=baseline,
        未来切断改変検査数=total, engine_SHA256=digest,
        検査=[dict(商品=s, 内容=name) for s, name, _ in cases],
        実データ新損益参照=0, API取得=0, 実注文=0)
    save(HERE / "統合管理の人工経路と独立会計監査.json", proof)
    print({k: v for k, v in proof.items() if k != "検査"}, flush=True)


if __name__ == "__main__":main()
