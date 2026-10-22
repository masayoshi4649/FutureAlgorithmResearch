"""強逆流時の古い再試験準備破棄を独立人工で確認する。"""

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(HERE))
from check_retest129 import fixture, load, check_night_account
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_retest_discard129")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def main():
    """
    機能: 旧0～5互換、候補だけの破棄、新準備の段階、未知・次行・未来と接続を検査する。
    引数: なし。
    返り値: None。人工だけを売買核へ渡し、新しい指紋付き証拠を保存する。
    """
    paths = [WORK/name for name in ("night_retest129b.py", "night_retest129c.py",
                                    "run_retest129c.py", "第七巡条件.json", "features129.py")]
    paths.append(Path(__file__))
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    old = load(WORK/"night_retest129b.py", "準備破棄129旧").simulate.py_func
    module = load(WORK/"night_retest129c.py", "準備破棄129新")
    new = module.simulate.py_func
    tests = []

    def check(name, action):
        """
        機能: 一件の成否を記録する。
        引数: name(str)、action(callable)は確認名と処理。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=name, 合格=True))
        except Exception as exc:
            tests.append(dict(確認=name, 合格=False, 詳細=type(exc).__name__+": "+str(exc)))

    for top in (False, True):
        for reflected in (False, True):
            for confirm in range(6):
                def compatible(top=top, reflected=reflected, confirm=confirm):
                    """
                    機能: 旧確認を指定したときに全配列が前巡核と同一と確認する。
                    引数: top/reflected(bool)、confirm(int)は人工条件。
                    返り値: None。
                    """
                    args = fixture(top=top, reflected=reflected, confirm=confirm)
                    for mode in ((0, 1) if confirm < 4 else (1,)):
                        for a, b in zip(old(*args, mode), new(*args, mode)):
                            np.testing.assert_array_equal(a, b)
                        check_night_account(args, new(*args, mode))
                check(f"旧確認{confirm}互換_{top}_{reflected}", compatible)

    for reflected in (False, True):
        sign = -1 if reflected else 1

        def discard(reflected=reflected, sign=sign):
            """
            機能: 発注可能候補での強逆流を破棄し、翌行に旧段階で入らないことを確認する。
            引数: reflected(bool)、sign(int)は上下。
            返り値: None。
            """
            args = fixture(prices=[110.5, 113., 111., 112., 112., 112., 112., 112., 112., 112.],
                           reflected=reflected, confirm=6)
            args[7][3, [5, 7]] = -sign
            out = new(*args, 1)
            assert len(out[0]) == 0
            args[-1][10] = 5
            before = old(*args, 1)
            np.testing.assert_array_equal(before[0][0, :2], [5, 4])
            check_night_account(args, before)
        check(f"候補の強逆流は古い段階を破棄_{reflected}", discard)

        def new_stages(reflected=reflected, sign=sign):
            """
            機能: 新しい準備を翌行から許すが全段階をもう一度要求することを確認する。
            引数: reflected(bool)、sign(int)は上下。
            返り値: None。
            """
            args = fixture(prices=[110.5, 113., 111., 112., 112., 113., 111., 112., 112., 112., 112., 112.],
                           reflected=reflected, confirm=6)
            args[7][3, [5, 7]] = -sign
            out = new(*args, 1)
            np.testing.assert_array_equal(out[0][0, :2], [8, 7])
            check_night_account(args, out)
        check(f"翌行の新準備では三段階を再試験_{reflected}", new_stages)

        for fault in ("気配幅", "気配乖離", "距離", "自己30", "相手30", "相手5", "相手20", "市場未知", "準備秒未達"):
            def not_candidate(fault=fault, reflected=reflected, sign=sign):
                """
                機能: 強逆流以外の発注資格が未達なら古い準備を破棄しないことを確認する。
                引数: fault(str)、reflected(bool)、sign(int)は人工条件。
                返り値: None。
                """
                args = fixture(prices=[110.5, 113., 111., 112., 112., 112., 112., 112., 112., 112.],
                               reflected=reflected, confirm=6)
                args[7][3, [5, 7]] = -sign
                if fault == "気配幅":
                    args[2][3] -= 2.
                    args[3][3] += 2.
                elif fault == "気配乖離":
                    args[2][3] += 3.*sign
                    args[3][3] += 3.*sign
                elif fault == "距離":
                    args[-1][13] = .5
                    if sign > 0:
                        args[3][4] = 112.
                    else:
                        args[2][4] = 88.
                elif fault in ("自己30", "相手30"):
                    args[7][3, 4 if fault == "自己30" else 6] = 0.
                elif fault in ("相手5", "相手20"):
                    args[6][3, 10 if fault == "相手5" else 11] = 0.
                elif fault == "市場未知":
                    args[7][3, 11] = 0.
                else:
                    args[0][1:4] = [20., 40., 59.]
                    args[0][4] = 60.
                out = new(*args, 1)
                np.testing.assert_array_equal(out[0][0, :2], [5, 4])
                check_night_account(args, out)
            check(f"未候補の{fault}では破棄しない_{reflected}", not_candidate)

        for row in (0, 1, 2):
            def incomplete(row=row, reflected=reflected, sign=sign):
                """
                機能: 準備・進行・戻りの途中での強逆流だけでは段階を消さない。
                引数: row(int)、reflected(bool)、sign(int)は人工条件。
                返り値: None。
                """
                args = fixture(reflected=reflected, confirm=6)
                args[7][row, [5, 7]] = -sign
                out = new(*args, 1)
                np.testing.assert_array_equal(out[0][0, :2], [4, 3])
                check_night_account(args, out)
            check(f"段階{row}は発注候補に至らず破棄しない_{reflected}", incomplete)

        for own, peer in ((-.25, -1.), (-1., -.25), (-.25000001, -.25000001),
                          (np.nan, -1.), (-1., np.inf), (-np.inf, -1.), (-1., .1)):
            def edge(own=own, peer=peer, reflected=reflected, sign=sign):
                """
                機能: 有限双方の厳密強逆流だけを破棄し、境界・片側・未知は通す。
                引数: own/peer(float)、reflected(bool)、sign(int)は条件。
                返り値: None。
                """
                args = fixture(prices=[110.5, 113., 111., 112., 112., 112., 112., 112., 112.],
                               reflected=reflected, confirm=6)
                args[7][3, 5] = own*sign
                args[7][3, 7] = peer*sign
                out = new(*args, 1)
                reject = np.isfinite(own) and np.isfinite(peer) and own < -.25 and peer < -.25
                assert bool(len(out[0])) == (not reject)
                if not reject:
                    np.testing.assert_array_equal(out[0][0, :2], [4, 3])
                check_night_account(args, out)
            check(f"強逆流厳密境界_{own}_{peer}_{reflected}", edge)

        def after_order(reflected=reflected, sign=sign):
            """
            機能: 発注判断済みの注文は後の強逆流や不利gapで取消さない。
            引数: reflected(bool)、sign(int)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected, confirm=6)
            args[7][4:, [5, 7]] = -sign
            args[4][4:6] = False
            args[2][6:] += 20.*sign
            args[3][6:] += 20.*sign
            out = new(*args, 1)
            np.testing.assert_array_equal(out[0][0, :2], [6, 3])
            check_night_account(args, out)
        check(f"発注後強逆流の遡及取消しなし_{reflected}", after_order)

    def future():
        """
        機能: 将来の強逆流と再試験の変更が過去注文へ影響しないと確認する。
        引数: なし。
        返り値: None。
        """
        args = fixture(confirm=6)
        a = new(*args, 1)
        changed = deepcopy(args)
        changed[7][5:, [5, 7]] = -100.
        changed[6][5:, 10:12] *= -1.
        b = new(*changed, 1)
        np.testing.assert_array_equal(a[0][a[0][:, 0] < 5], b[0][b[0][:, 0] < 5])
        np.testing.assert_array_equal(a[2][:5], b[2][:5])
    check("未来の破棄条件による先読みなし", future)

    def runner():
        """
        機能: 接続全引数が前巡と同じで、二対照の確認番号だけを追加変更したと確認する。
        引数: なし。
        返り値: None。
        """
        calls = []
        exits = []
        for name in ("run_retest129b.py", "run_retest129c.py"):
            tree = ast.parse((WORK/name).read_text(encoding="utf-8"))
            call = next(x for x in ast.walk(tree) if isinstance(x, ast.Call) and
                        isinstance(x.func, ast.Attribute) and x.func.attr == "simulate")
            calls.append([ast.dump(x, include_attributes=False) for x in call.args])
        assert calls[0] == calls[1]
        for name in ("night_retest129b.py", "night_retest129c.py"):
            tree = ast.parse((WORK/name).read_text(encoding="utf-8"))
            func = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "simulate")
            loop = next(x for x in func.body if isinstance(x, ast.For))
            selected = [x for x in loop.body if isinstance(x, ast.If) and
                        ast.unparse(x.test) in ("pending and good and (i > pending_source)", "position and good")]
            assert len(selected) == 2
            exits.append([ast.dump(x, include_attributes=False) for x in selected])
        assert exits[0] == exits[1]
        before = json.loads((WORK/"第六巡条件.json").read_text(encoding="utf-8-sig"))
        after = json.loads((WORK/"第七巡条件.json").read_text(encoding="utf-8-sig"))
        assert [(x["id"], x["price_source"], x["entry_confirm"]) for x in after] == [
            ("NV24", "last", 6), ("NV25", "mid", 6)]
        for a, b in zip(before, after):
            for key, value in a.items():
                if key not in ("id", "name", "entry_confirm"):
                    assert b[key] == value
    check("出口と接続を維持し二対照の確認番号だけ変更", runner)

    def compiled():
        """
        機能: 破棄・新準備・未知の分岐でPythonとJITの全出力を比較する。
        引数: なし。
        返り値: None。
        """
        for reflected in (False, True):
            for value in (1., -1., np.nan):
                args = fixture(prices=[110.5, 113., 111., 112., 112., 113., 111., 112., 112., 112., 112., 112.],
                               reflected=reflected, confirm=6)
                args[7][3, [5, 7]] = value*(-1 if reflected else 1)
                for a, b in zip(new(*args, 1), module.simulate(*args, 1)):
                    np.testing.assert_array_equal(a, b)
    check("専用JITとPythonの破棄と再形成が同値", compiled)
    assert hashes == {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result = dict(passed=all(x["合格"] for x in tests), cases=len(tests), tests=tests,
                  source_hashes=hashes, financial_replays=0, original_market_reads=0, API=0)
    target = HERE/f"強逆流による準備破棄の独立人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), passed=result["passed"], cases=len(tests),
                         failures=[x for x in tests if not x["合格"]]), ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
