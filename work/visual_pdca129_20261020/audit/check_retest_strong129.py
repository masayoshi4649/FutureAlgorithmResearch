"""再試験入口の強逆流拒否だけを独立人工で確認する。"""

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
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_retest_strong129")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def main():
    """
    機能: 旧分岐互換、強逆流の符号・厳密境界・未知、予約後処理と接続を確認する。
    引数: なし。
    返り値: None。金融再生なしで源指紋付き証拠を保存する。
    """
    sources = [WORK/name for name in ("night_retest129.py", "night_retest129b.py",
                                      "run_retest129b.py", "第六巡条件.json", "features129.py")]
    sources.append(Path(__file__))
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old = load(WORK/"night_retest129.py", "強逆流129旧").simulate.py_func
    module = load(WORK/"night_retest129b.py", "強逆流129新")
    new = module.simulate.py_func
    tests = []

    def check(name, action):
        """
        機能: 一件の成否を記録する。
        引数: name(str)、action(callable)は名称と検査。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=name, 合格=True))
        except Exception as exc:
            tests.append(dict(確認=name, 合格=False, 詳細=type(exc).__name__+": "+str(exc)))

    for top in (False, True):
        for reflected in (False, True):
            for confirm in (0, 1, 2, 3, 4):
                def compatible(top=top, reflected=reflected, confirm=confirm):
                    """
                    機能: 新確認5以外では旧全配列と一致することを確かめる。
                    引数: top/reflected(bool)、confirm(int)は人工条件。
                    返り値: None。
                    """
                    args = fixture(top=top, reflected=reflected, confirm=confirm)
                    for mode in ((0, 1) if confirm < 4 else (1,)):
                        before, after = old(*args, mode), new(*args, mode)
                        for a, b in zip(before, after):
                            np.testing.assert_array_equal(a, b)
                        check_night_account(args, after)
                check(f"旧確認{confirm}互換_{top}_{reflected}", compatible)

    values = (-1., -.25000001, -.25, -.24999999, 0., .1, np.nan, np.inf, -np.inf)
    for reflected in (False, True):
        sign = -1 if reflected else 1
        for own in values:
            for peer in values:
                def boundary(own=own, peer=peer, reflected=reflected, sign=sign):
                    """
                    機能: 双方が有限で厳密に逆流幅を超える場合だけ見送ることを独立論理で照合する。
                    引数: own/peer(float)、reflected(bool)、sign(int)は人工条件。
                    返り値: None。
                    """
                    args = fixture(reflected=reflected, confirm=5)
                    args[7][:, 5] = own*sign
                    args[7][:, 7] = peer*sign
                    reject = np.isfinite(own) and np.isfinite(peer) and own < -.25 and peer < -.25
                    out = new(*args, 1)
                    assert bool(len(out[0])) == (not reject)
                    if not reject:
                        assert out[0][0, 1] == 3 and out[0][0, 0] == 4
                    check_night_account(args, out)
                check(f"強逆流境界_上下{reflected}_自己{own}_相手{peer}", boundary)

        for where in ("market11", "own30", "peer30", "peer5", "peer20"):
            def required(where=where, reflected=reflected):
                """
                機能: 120秒の未知を許しても必要な30秒と相手履歴の支持を免除しない。
                引数: where(str)、reflected(bool)は欠落条件と上下。
                返り値: None。
                """
                args = fixture(reflected=reflected, confirm=5)
                args[7][:, [5, 7]] = np.nan
                if where == "market11":
                    args[7][:, 11] = 0.
                elif where in ("own30", "peer30"):
                    args[7][:, 4 if where == "own30" else 6] = 0.
                else:
                    args[6][:, 10 if where == "peer5" else 11] = 0.
                assert len(new(*args, 1)[0]) == 0
            check(f"必要支持を保持_{where}_{reflected}", required)

        def recovery(reflected=reflected, sign=sign):
            """
            機能: 強逆流が消えるまで待ち、解除後に次原行の注文を予約する。
            引数: reflected(bool)、sign(int)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected, confirm=5)
            args[7][3:5, [5, 7]] = -sign
            out = new(*args, 1)
            assert out[0][0, 1] == 5 and out[0][0, 0] == 6
            check_night_account(args, out)
        check(f"強逆流解除後の発火_{reflected}", recovery)

        def after_decision(reflected=reflected, sign=sign):
            """
            機能: 発注後の強逆流と不利な気配gapで予約済み注文を取り消さない。
            引数: reflected(bool)、sign(int)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected, confirm=5)
            args[7][4:, [5, 7]] = -sign
            args[4][4:6] = False
            args[2][6:] += sign*20.
            args[3][6:] += sign*20.
            out = new(*args, 1)
            assert out[0][0, 1] == 3 and out[0][0, 0] == 6
            check_night_account(args, out)
        check(f"判断後逆流の非取消し_{reflected}", after_decision)

        def missing_break(reflected=reflected):
            """
            機能: 相手欠測中の自己境界破綻取消し修正を新確認でも保持する。
            引数: reflected(bool)は上下。
            返り値: None。
            """
            args = fixture(prices=[110.5, 113., 111., 109., 112., 112., 112., 112., 112.],
                           reflected=reflected, confirm=5)
            args[7][3, 11] = 0.
            assert len(new(*args, 1)[0]) == 0
        check(f"欠測中の観測済み自己破綻は取消し_{reflected}", missing_break)

    def future():
        """
        機能: 将来の120秒値の毒化が過去の注文と時価を変えないことを確かめる。
        引数: なし。
        返り値: None。
        """
        args = fixture(confirm=5)
        a = new(*args, 1)
        changed = deepcopy(args)
        changed[7][5:, [5, 7]] = -999.
        b = new(*changed, 1)
        np.testing.assert_array_equal(a[0][a[0][:, 0] < 5], b[0][b[0][:, 0] < 5])
        np.testing.assert_array_equal(a[2][:5], b[2][:5])
    check("将来の強逆流による先読みなし", future)

    def same_exit():
        """
        機能: 前行予約の約定と保有中出口は旧核の構文と同一であることを確かめる。
        引数: なし。
        返り値: None。
        """
        blocks = []
        for name in ("night_retest129.py", "night_retest129b.py"):
            tree = ast.parse((WORK/name).read_text(encoding="utf-8"))
            func = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "simulate")
            loop = next(x for x in func.body if isinstance(x, ast.For))
            selected = [x for x in loop.body if isinstance(x, ast.If) and
                        ast.unparse(x.test) in ("pending and good and (i > pending_source)", "position and good")]
            assert len(selected) == 2
            blocks.append([ast.dump(x, include_attributes=False) for x in selected])
        assert blocks[0] == blocks[1]
    check("約定と出口の構文不変", same_exit)

    def runner():
        """
        機能: 第四巡と同じ引数で確認番号と数値核だけを替えた二対照と確認する。
        引数: なし。
        返り値: None。
        """
        calls = []
        for name in ("run_retest129.py", "run_retest129b.py"):
            tree = ast.parse((WORK/name).read_text(encoding="utf-8"))
            call = next(x for x in ast.walk(tree) if isinstance(x, ast.Call) and
                        isinstance(x.func, ast.Attribute) and x.func.attr == "simulate")
            calls.append([ast.dump(x, include_attributes=False) for x in call.args])
        assert calls[0] == calls[1]
        old_configs = json.loads((WORK/"第四巡条件.json").read_text(encoding="utf-8-sig"))
        new_configs = json.loads((WORK/"第六巡条件.json").read_text(encoding="utf-8-sig"))
        assert [(x["id"], x["price_source"], x["entry_confirm"]) for x in new_configs] == [
            ("NV22", "last", 5), ("NV23", "mid", 5)]
        for item in new_configs:
            base = next(x for x in old_configs if x["price_source"] == item["price_source"] and x["entry_confirm"] == 4)
            for key, value in base.items():
                if key not in ("id", "name", "entry_confirm"):
                    assert item[key] == value
    check("第六巡の接続と二対照", runner)

    def compiled():
        """
        機能: 新確認の有限・未知・拒否についてJITとPythonの全配列一致を確認する。
        引数: なし。
        返り値: None。
        """
        for reflected in (False, True):
            for value in (1., -1., np.nan):
                args = fixture(top=False, reflected=reflected, confirm=5)
                args[7][:, [5, 7]] = value*(-1 if reflected else 1)
                for a, b in zip(new(*args, 1), module.simulate(*args, 1)):
                    np.testing.assert_array_equal(a, b)
    check("新確認の専用JIT一致", compiled)
    assert hashes == {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    result = dict(passed=all(x["合格"] for x in tests), cases=len(tests), tests=tests,
                  source_hashes=hashes, financial_replays=0, original_market_reads=0, API=0)
    target = HERE/f"再試験強逆流拒否の独立人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), passed=result["passed"], cases=len(tests),
                         failures=[x for x in tests if not x["合格"]]), ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
