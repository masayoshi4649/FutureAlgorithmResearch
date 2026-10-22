"""固定突破線の再試験状態を市場データなしで独立監査する。"""

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
PREV = ROOT/"work/daynight128_20261020"
sys.path.insert(0, str(PREV/"audit"))
from check_engines128 import load, night_fixture, check_night_account
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_retest129")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def fixture(prices=None, reflected=False, top=True, confirm=3):
    """
    機能: 固定線110、幅4の順行・戻り・再進行を人工的に作る。
    引数: prices(list|None)、reflected/top(bool)、confirm(int)は人工条件。
    返り値: listは旧夜間核の十六引数。
    """
    prices = prices or [110.5, 113., 111., 112., 112., 117., 114., 114., 114., 114., 114., 114.]
    qty, mult, fee = (5, 1000., 418) if top else (10, 10., 110)
    args = list(night_fixture(prices, qty, mult, fee, reflected))
    args[6][:, 5] = .5
    args[-1][0] = 2.
    args[-1] = np.r_[args[-1], float(confirm), 2., 0., 1.e9]
    return args


def main():
    """
    機能: 旧互換、段階境界、価格時計、欠測、非取消し、将来毒化とJITを確認する。
    引数: なし。
    返り値: None。人工入力だけを売買核へ渡し、指紋付き証拠を新規保存する。
    """
    sources = [PREV/"night5.py", WORK/"night_retest129.py", WORK/"run_retest129.py",
               WORK/"features129.py", WORK/"第四巡条件.json", Path(__file__)]
    before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old = load(PREV/"night5.py", "再試験129旧核").simulate.py_func
    module = load(WORK/"night_retest129.py", "再試験129独立新核")
    new = module.simulate.py_func
    tests = []

    def check(name, action):
        """
        機能: 独立確認の例外も記録する。
        引数: name(str)、action(callable)は確認名と検査。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=name, 合格=True))
        except Exception as exc:
            tests.append(dict(確認=name, 合格=False, 詳細=type(exc).__name__+": "+str(exc)))

    for reflected in (False, True):
        for top in (False, True):
            for confirm in (0, 1, 2, 3):
                def compatible(reflected=reflected, top=top, confirm=confirm):
                    """
                    機能: 再試験無効時の旧全出力を照合する。
                    引数: reflected/top(bool)、confirm(int)は人工条件。
                    返り値: None。
                    """
                    args = fixture(reflected=reflected, top=top, confirm=confirm)
                    for a, b in zip(old(*args), new(*args, 0)):
                        np.testing.assert_array_equal(a, b)
                    check_night_account(args, new(*args, 0))
                check(f"旧互換_上下{reflected}_商品{top}_確認{confirm}", compatible)

            for confirm in (3, 4):
                def stages(reflected=reflected, top=top, confirm=confirm):
                    """
                    機能: 三段階が別原行で成立し次原行で約定することを確かめる。
                    引数: reflected/top(bool)、confirm(int)は人工条件。
                    返り値: None。
                    """
                    args = fixture(reflected=reflected, top=top, confirm=confirm)
                    out = new(*args, 1)
                    assert len(out[1]) == 1
                    assert out[0][0, 1] == 3 and out[0][0, 0] == 4
                    assert out[0][0, 3] == (-1 if reflected else 1)
                    check_night_account(args, out)
                check(f"三段階と次原行_上下{reflected}_商品{top}_確認{confirm}", stages)

        for label, prices, expected in (
            ("進行不足", [110.5, 112.999999, 111., 112., 112., 112., 112., 112., 112.], None),
            ("進行境界一致", [110.5, 113., 111., 112., 112., 112., 112., 112., 112.], 3),
            ("戻り不足", [110.5, 113., 111.000001, 112.000001, 112., 112., 112., 112., 112.], None),
            ("反発不足", [110.5, 113., 111., 111.999999, 111.999999, 111.999999, 111.999999, 111.999999, 111.999999], None),
            ("最低点更新後反発", [110.5, 113., 111., 110., 110.999999, 111., 111., 111., 111., 111.], 5),
            ("取消し境界一致", [110.5, 113., 109., 110., 111., 112., 112., 112., 112.], None),
            ("取消し直前は維持", [110.5, 113., 109.000001, 110.000001, 110.000001, 110.000001, 110.000001, 110.000001, 110.000001], 3),
            ("初回で進行済み", [113., 111., 112., 112., 112., 112., 112., 112., 112.], 2),
            ("戻り省略不可", [110.5, 113., 114., 115., 116., 117., 118., 119., 120.], None),
        ):
            def boundaries(prices=prices, expected=expected, reflected=reflected):
                """
                機能: 固定線からの進行・戻り・取消しと追跡最低点の境界を確認する。
                引数: prices(list)、expected(int|None)、reflected(bool)は人工条件。
                返り値: None。
                """
                args = fixture(prices=prices, reflected=reflected)
                out = new(*args, 1)
                if expected is None:
                    assert len(out[0]) == 0
                else:
                    assert out[0][0, 1] == expected and out[0][0, 0] == expected+1
                check_night_account(args, out)
            check(f"{label}_上下{reflected}", boundaries)

        def fixed_line(reflected=reflected):
            """
            機能: 準備後の履歴帯変更が固定線・幅を変更しないことを確認する。
            引数: reflected(bool)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            baseline = new(*args, 1)
            args[6][1:, 3:5] += 40.
            args[5][1:] = 8.
            out = new(*args, 1)
            assert np.array_equal(out[0], baseline[0])
            assert out[1][0, 11] == 4.
        check(f"固定突破線と準備幅を維持_上下{reflected}", fixed_line)

        for confirm in (3, 4):
            for col in (5, 7):
                for label, value, allowed in (("未知", np.nan, False), ("逆", -1., False), ("零", 0., False)):
                    def confirmation(confirm=confirm, col=col, value=value, reflected=reflected):
                        """
                        機能: 確認4だけが120秒値の未知・逆・零を入口要件から除くことを確認する。
                        引数: confirm/col(int)、value(float)、reflected(bool)は人工条件。
                        返り値: None。
                        """
                        args = fixture(reflected=reflected, confirm=confirm)
                        args[7][:, col] = value * (-1 if reflected else 1)
                        out = new(*args, 1)
                        assert bool(len(out[0])) == (confirm == 4)
                        if len(out[0]):
                            assert out[0][0, 1] == 3
                        check_night_account(args, out)
                    check(f"確認{confirm}_120秒列{col}_{label}_上下{reflected}", confirmation)

            for source, col in (("短期", 4), ("短期", 6), ("相手履歴", 10), ("相手履歴", 11)):
                def required(confirm=confirm, source=source, col=col, reflected=reflected):
                    """
                    機能: 30秒支持と相手5・20分は確認4でも必要なことを確かめる。
                    引数: confirm/col(int)、source(str)、reflected(bool)は条件。
                    返り値: None。
                    """
                    args = fixture(reflected=reflected, confirm=confirm)
                    (args[7] if source == "短期" else args[6])[:, col] = np.nan
                    assert len(new(*args, 1)[0]) == 0
                check(f"確認{confirm}_{source}{col}未知拒否_上下{reflected}", required)

        def same_clock(reflected=reflected):
            """
            機能: 別原行なら同価格時計でも順序を保ち、準備から60秒を要求する。
            引数: reflected(bool)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            args[0][1:8] = 60.
            out = new(*args, 1)
            assert out[0][0, 1] == 3 and out[0][0, 0] == 4
            args = fixture(reflected=reflected)
            args[0][1:8] = 59.
            args[9] = 60.
            assert len(new(*args, 1)[0]) == 0
        check(f"同価格時計と60秒資格_上下{reflected}", same_clock)

        def timeout(reflected=reflected):
            """
            機能: 1800秒超で旧準備を破棄し過去の再試験を流用しない。
            引数: reflected(bool)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            args[0][3:] += 1801.
            args[9] = args[0][-2]
            args[6][3:, 5] = 0.
            assert len(new(*args, 1)[0]) == 0
        check(f"準備期限切れ_上下{reflected}", timeout)

        for where in (1, 2):
            def missing_stage(where=where, reflected=reflected):
                """
                機能: 欠測原行の進行又は戻りを観測済みとして扱わない。
                引数: where(int)、reflected(bool)は欠測行と上下。
                返り値: None。
                """
                args = fixture(prices=[110.5, 113., 111., 112., 112., 112., 112., 112., 112.], reflected=reflected)
                args[4][where] = False
                assert len(new(*args, 1)[0]) == 0
            check(f"欠測行{where}を段階に数えない_上下{reflected}", missing_stage)

        for missing in ("相手資格", "相手履歴", "現在ATR", "自己30秒"):
            def observed_break(missing=missing, reflected=reflected):
                """
                機能: 他の特徴が欠けても観測済み自己価格による固定線破綻は取消す。
                引数: missing(str)、reflected(bool)は欠測種類と上下。
                返り値: None。
                """
                args = fixture(prices=[110.5, 113., 111., 109., 112., 112., 112., 112., 112., 112.],
                               reflected=reflected)
                if missing == "相手資格":
                    args[7][3, 11] = 0.
                elif missing == "相手履歴":
                    args[6][3, 10] = np.nan
                elif missing == "現在ATR":
                    args[5][3] = np.nan
                else:
                    args[7][3, 4] = np.nan
                assert len(new(*args, 1)[0]) == 0
            check(f"{missing}欠測中の固定線破綻取消し_上下{reflected}", observed_break)

        def later_fill(reflected=reflected):
            """
            機能: 判断後の支持消失と不利な次正常気配を理由に予約を取消さない。
            引数: reflected(bool)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            args[4][4:6] = False
            args[6][4:] = np.nan
            args[7][4:] = np.nan
            jump = -20. if reflected else 20.
            args[2][6:] += jump
            args[3][6:] += jump
            out = new(*args, 1)
            assert out[0][0, 1] == 3 and out[0][0, 0] == 6
            check_night_account(args, out)
        check(f"判断後不明と不利気配でも約定_上下{reflected}", later_fill)

        def quiet_cancel(reflected=reflected):
            """
            機能: 既知の米開始静観に入った未約定新規を取消す。
            引数: reflected(bool)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            args[10] = 1150.
            args[0][4:] += 60.
            args[9] = args[0][-2]
            assert len(new(*args, 1)[0]) == 0
        check(f"既知静観の未約定新規取消し_上下{reflected}", quiet_cancel)

        def terminal_cancel(reflected=reflected):
            """
            機能: 場内返済時刻に達した未約定新規を取消す。
            引数: reflected(bool)は上下。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            args[9] = args[0][4]
            assert len(new(*args, 1)[0]) == 0
        check(f"終了境界の未約定新規取消し_上下{reflected}", terminal_cancel)

    def future():
        """
        機能: 将来の価格・支持・帯を毒化しても過去判断と会計が不変であることを確かめる。
        引数: なし。
        返り値: None。
        """
        for mode in (0, 1):
            args = fixture()
            original = new(*args, mode)
            changed = deepcopy(args)
            for k in (1, 2, 3):
                changed[k][6:] += 40.
            changed[6][6:] *= -3.
            changed[7][6:, 4:8] *= -9.
            altered = new(*changed, mode)
            np.testing.assert_array_equal(original[0][original[0][:, 0] < 6], altered[0][altered[0][:, 0] < 6])
            np.testing.assert_array_equal(original[2][:6], altered[2][:6])
    check("未来価格と支持の変更で過去不変", future)

    def unchanged_execution():
        """
        機能: 発注後の約定処理と保有中出口が旧核の構文と完全に同じことを確かめる。
        引数: なし。
        返り値: None。
        """
        blocks = []
        for path in (PREV/"night5.py", WORK/"night_retest129.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            function = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "simulate")
            loop = next(x for x in function.body if isinstance(x, ast.For))
            selected = [x for x in loop.body if isinstance(x, ast.If) and
                        ast.unparse(x.test) in ("pending and good and (i > pending_source)", "position and good")]
            assert len(selected) == 2
            blocks.append([ast.dump(x, include_attributes=False) for x in selected])
        assert blocks[0] == blocks[1]
    check("約定処理と保有出口の構文完全同値", unchanged_execution)

    def runner():
        """
        機能: 接続の旧十六引数同値と再試験一引数、四条件の独立性を照合する。
        引数: なし。
        返り値: None。
        """
        trees = [ast.parse((WORK/name).read_text(encoding="utf-8")) for name in ("run_night129.py", "run_retest129.py")]
        calls = [next(x for x in ast.walk(tree) if isinstance(x, ast.Call) and
                      isinstance(x.func, ast.Attribute) and x.func.attr == "simulate") for tree in trees]
        assert len(calls[0].args) == 16 and len(calls[1].args) == 17
        for oldarg, newarg in zip(calls[0].args, calls[1].args[:16]):
            assert ast.dump(oldarg, include_attributes=False) == ast.dump(newarg, include_attributes=False)
        assert ast.unparse(calls[1].args[-1]) == "config['retest_mode']"
        assert any(isinstance(x, ast.ImportFrom) and x.module == "features129" and
                   [a.name for a in x.names] == ["build"] for x in trees[1].body)
        configs = json.loads((WORK/"第四巡条件.json").read_text(encoding="utf-8-sig"))
        base = json.loads((WORK/"第一巡条件.json").read_text(encoding="utf-8-sig"))[0]
        assert [(x["price_source"], x["entry_confirm"], x["retest_mode"]) for x in configs] == [
            ("last", 3, 1), ("last", 4, 1), ("mid", 3, 1), ("mid", 4, 1)]
        assert [x["id"] for x in configs] == ["NV14", "NV15", "NV16", "NV17"]
        for config in configs:
            for key, value in base.items():
                if key not in ("id", "name", "price_source", "entry_confirm"):
                    assert config[key] == value
    check("第四巡接続と四条件は源と確認のみの差", runner)

    def no_mutation():
        """
        機能: 入力資料を数値核が変更しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        copy = deepcopy(args)
        new(*args, 1)
        for a, b in zip(args, copy):
            np.testing.assert_array_equal(a, b)
    check("入力配列非改変", no_mutation)

    def compiled():
        """
        機能: 独立キャッシュのJITとPythonを上下・確認方式ごとに照合する。
        引数: なし。
        返り値: None。
        """
        for mode, confirm in ((0, 3), (1, 3), (1, 4)):
            for reflected in (False, True):
                args = fixture(reflected=reflected, top=False, confirm=confirm)
                for a, b in zip(new(*args, mode), module.simulate(*args, mode)):
                    np.testing.assert_array_equal(a, b)
    check("専用JITとPythonが全配列一致", compiled)
    after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assert before == after
    result = dict(passed=all(x["合格"] for x in tests), cases=len(tests), tests=tests,
                  sources=before, financial_replays=0, API=0)
    path = HERE/f"再試験入口状態の独立人工_{time.time_ns()}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(path=str(path.relative_to(ROOT)), passed=result["passed"],
                         cases=len(tests), failures=[x for x in tests if not x["合格"]]), ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
