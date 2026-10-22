"""価格予算の保存・失効・上下対称を架空原行だけで検査する。"""

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
sys.path.insert(0, str(WORK))
sys.path.insert(0, str(HERE))
from check_exit130 import fixture, account, prior_fixture
import night_activity130
import night_budget130
import run_budget130

os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_budget_author")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def tape(prices=None, times=None, reflected=False, top=True):
    """
    機能: 三つの候補を別の原行で形成する固定幅4の架空入力を作る。
    引数: prices/times(list|None)、reflected/top(bool)は価格・時計・方向・商品。
    返り値: listは旧核の十六引数。
    """
    if prices is None:
        prices = [110.5, 113., 111., 112., 111.5, 113., 111., 112.5,
                  111.5, 113., 111., 112., 112., 120., 120., 115., 115., 115., 115.]
    if times is None:
        times = [0., 20., 40., 60., 61., 81., 101., 121., 122., 142., 162., 182.,
                 183., 184., 185., 186., 187., 188., 189.]
    args = fixture(top=top)
    n = len(prices)
    args[0] = np.array(times, float)
    args[1] = np.array(prices, float)
    args[2], args[3] = args[1]-.5, args[1]+.5
    args[4] = np.ones(n, bool)
    args[5] = np.full(n, 4.)
    args[6] = np.tile(args[6][0], (n, 1))
    args[7] = np.tile(args[7][0], (n, 1))
    args[6][:, 9] = args[0]-60.
    args[6][:, 14] = args[0]-120.
    args[7][:, 0] = args[1]
    args[7][:, 8:11] = args[0][:, None]-1.
    args[9] = args[0][-2]
    if reflected:
        reflect(args)
    return args


def reflect(args):
    """
    機能: 価格と方向情報を対称反転する。
    引数: args(list)は架空入力で、直接変更する。
    返り値: None。
    """
    args[1] = 500.-args[1]
    args[2], args[3] = 500.-args[3], 500.-args[2]
    args[6][:, [0, 1, 8]] = 500.-args[6][:, [0, 1, 8]]
    previous_high = args[6][:, 3].copy()
    args[6][:, 3] = 500.-args[6][:, 4]
    args[6][:, 4] = 500.-previous_high
    args[6][:, [6, 7, 10, 11, 13]] *= -1
    args[7][:, 0] = args[1]
    args[7][:, 4:8] *= -1


def activity(args, reflected=False):
    """
    機能: 最初の候補だけ不適格な活動を作る。
    引数: args(list)、reflected(bool)は入力と方向。
    返り値: ndarray[N,4]は活動列。
    """
    side = -1. if reflected else 1.
    result = np.tile([side, 20., -7.*side, 1.], (len(args[0]), 1))
    result[3, 3] = 0.
    return result


def run(args, activities, budget=1, retest=1, style=0, activity_mode=1, compiled=False):
    """
    機能: 架空資料だけを新核へ渡す。
    引数: args(list)、activities(ndarray|None)、各mode(int)、compiled(bool)は実行指定。
    返り値: tuple[ndarray,...]は注文・返済・時価。
    """
    target = night_budget130.simulate if compiled else night_budget130.simulate.py_func
    return target(*args, retest, style, activities, activity_mode, budget)


def main():
    """
    機能: 旧互換、方向別の保存予算、リセット、未来・約定順を人工検査する。
    引数: なし。
    返り値: None。作者証拠のみ保存し実相場の金融再生は行わない。
    """
    sources = run_budget130.sources()
    frozen = {name: hashlib.sha256((WORK/name).read_bytes()).hexdigest()
              for name in ("night_activity130.py", "run_activity130.py")}
    checks = []

    def check(name, action):
        """
        機能: 一件の確認と反例を保存する。
        引数: name(str)、action(callable)は検査名と内容。
        返り値: None。
        """
        try:
            action()
            checks.append(dict(確認=name, 合格=True))
        except Exception as error:
            checks.append(dict(確認=name, 合格=False, 詳細=f"{type(error).__name__}: {error}"))

    def same(left, right):
        """
        機能: 全配列を厳密照合する。
        引数: left/right(tuple[ndarray,...])は対象。
        返り値: None。
        """
        for a, b in zip(left, right):
            np.testing.assert_array_equal(a, b)

    for reflected in (False, True):
        for top in (False, True):
            for confirm in range(7):
                def compatibility(reflected=reflected, top=top, confirm=confirm):
                    """
                    機能: 確認全枝・出口全枝でbudget0互換と全適格時のbudget1同値を確認する。
                    引数: reflected/top(bool)、confirm(int)は入力条件。
                    返り値: None。
                    """
                    args = prior_fixture(top=top, reflected=reflected, confirm=confirm)
                    good = activity(args, reflected)
                    good[:, 3] = 1.
                    for retest in ((0, 1) if confirm < 4 else (1,)):
                        for style in range(4):
                            for mode in (0, 1):
                                data = good if mode else None
                                expected = night_activity130.simulate.py_func(*args, retest, style, data, mode)
                                same(expected, run(args, data, 0, retest, style, mode))
                                if mode:
                                    same(expected, run(args, data, 1, retest, style, mode))
                    # 活動不適格・未知の旧取消経路もbudget0ならそのまま。
                    bad = good.copy()
                    bad[3:9] = np.nan
                    retest = 1
                    same(night_activity130.simulate.py_func(*args, retest, 0, bad, 1),
                         run(args, bad, 0, retest))
                check(f"旧確認{confirm}全枝互換_反転{reflected}_商品{top}", compatibility)

            def reject_then_equal(reflected=reflected, top=top):
                """
                機能: 不利な二番目を捨て、最初のBBOと等値の三番目だけを許す。
                引数: reflected/top(bool)は条件。
                返り値: None。
                """
                args = tape(reflected=reflected, top=top)
                data = activity(args, reflected)
                original = run(args, data, 0)
                modified = run(args, data, 1)
                assert tuple(original[0][0, :2]) == (8, 7)
                assert tuple(modified[0][0, :2]) == (12, 11)
                assert modified[0][0, 5] == (args[3] if not reflected else args[2])[12]
                account(args, modified)
                for style in range(4):
                    account(args, run(args, data, 1, style=style))
            check(f"不利は拒否し初回同値は許可_反転{reflected}_商品{top}", reject_then_equal)

        def favorable(reflected=reflected):
            """
            機能: 最初より好条件の候補は許し、好条件の見送りで予算を狭めない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = tape()
            args[1][6], args[1][7] = 110.75, 111.75
            args[2], args[3] = args[1]-.5, args[1]+.5
            if reflected:
                reflect(args)
            data = activity(args, reflected)
            result = run(args, data)
            assert tuple(result[0][0, :2]) == (8, 7)
            account(args, result)
            data[7, 3] = 0.
            result = run(args, data)
            assert tuple(result[0][0, :2]) == (12, 11)
            account(args, result)
        check(f"好条件可と好条件再見送りで予算を変更しない_反転{reflected}", favorable)

        def no_worse_update(reflected=reflected):
            """
            機能: 二番目の不利な見送りを新しい価格基準へ更新しない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = tape()
            args[1][11] = 112.25
            args[2], args[3] = args[1]-.5, args[1]+.5
            args[6][12:, 5] = 0.
            if reflected:
                reflect(args)
            data = activity(args, reflected)
            data[7, 3] = 0.
            out = run(args, data)
            assert len(out[0]) == 0
            account(args, out)
        check(f"不利な後続価格へ更新しない_反転{reflected}", no_worse_update)

        def bbo_not_last(reflected=reflected):
            """
            機能: 同じ自己価格でも判断側気配の悪化を予算超過として扱う。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = tape()
            args[2][3], args[3][3] = 111.75, 112.25
            args[1][7] = 112.
            args[2][7], args[3][7] = 111.5, 112.5
            args[2][11], args[3][11] = 111.75, 112.25
            if reflected:
                reflect(args)
            out = run(args, activity(args, reflected))
            assert tuple(out[0][0, :2]) == (12, 11)
            account(args, out)
        check(f"自己価格でなく実発注側気配を比較_反転{reflected}", bbo_not_last)

        for value in (108.999999, 109., 109.000001, np.nan, np.inf):
            def boundary(reflected=reflected, value=value):
                """
                機能: 元固定線−.25Rの等号で解除し、他資料の未知には依存しない。
                引数: reflected(bool)、value(float)は自己価格。
                返り値: None。
                """
                args = tape()
                args[1][4] = value
                args[4][4] = False
                args[5][4] = np.nan
                args[6][4] = np.nan
                args[7][4] = np.nan
                args[0][7:] += 20.
                args[9] = args[0][-2]
                args[6][8:, 5] = 0.
                if reflected:
                    reflect(args)
                out = run(args, activity(args, reflected))
                if np.isfinite(value) and value <= 109.:
                    assert tuple(out[0][0, :2]) == (8, 7)
                else:
                    assert len(out[0]) == 0
                account(args, out)
            check(f"保存境界の厳密解除_反転{reflected}_{value}", boundary)

        def original_level(reflected=reflected):
            """
            機能: 後続履歴の帯や現在幅で最初の失効線を書き換えない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = tape()
            args[1][4] = 110.5
            args[6][4, 3] = 120.
            args[5][4] = 100.
            args[0][7:] += 20.
            args[9] = args[0][-2]
            args[6][8:, 5] = 0.
            if reflected:
                reflect(args)
            assert len(run(args, activity(args, reflected))[0]) == 0
        check(f"保存境界と固定幅を後続資料で更新しない_反転{reflected}", original_level)

        def quiet_reset(reflected=reflected):
            """
            機能: 米開始の禁止時間に入れば価格予算を解除して新工程を許す。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = tape(reflected=reflected)
            args[0][4] = 100.
            args[0][5:] += 1340.
            args[0][7:] += 20.
            args[10] = 100.
            args[15][7] = 10.
            args[9] = args[0][-2]
            args[6][8:, 5] = 0.
            out = run(args, activity(args, reflected))
            assert tuple(out[0][0, :2]) == (8, 7)
            account(args, out)
        check(f"既知の禁止時間で予算を解除_反転{reflected}", quiet_reset)

        def pending_gap(reflected=reflected):
            """
            機能: 等値候補の判断後に不利へ飛んでも予算値で約定したことにしない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = tape(reflected=reflected)
            data = activity(args, reflected)
            side = -1 if reflected else 1
            args[4][12] = False
            for col in (1, 2, 3):
                args[col][13:] += side*20.
            data[12:] = np.nan
            out = run(args, data)
            assert tuple(out[0][0, :2]) == (13, 11)
            quoted = args[3] if side > 0 else args[2]
            assert out[0][0, 5] == quoted[13] and side*(quoted[13]-quoted[3]) > 0
            account(args, out)
        check(f"発注後不利gapは取消せず次正常BBO約定_反転{reflected}", pending_gap)

        def opposite_separate(reflected=reflected):
            """
            機能: 一方向の予算を逆方向へ流用しない。
            引数: reflected(bool)は全体の反転。
            返り値: None。
            """
            args = tape()
            args[1][4:12] = [112.5, 110., 112., 111., 111., 106., 106., 111.]
            args[2], args[3] = args[1]-.5, args[1]+.5
            args[6][4:, 3:5] = [123., 113.]
            args[6][4:, [6, 7, 10, 11, 13]] *= -1.
            args[7][4:, 4:8] *= -1.
            args[6][8:, 5] = 0.
            data = activity(args)
            data[4:, 0] *= -1.
            data[4:, 2] *= -1.
            if reflected:
                reflect(args)
                data[:, 0] *= -1.
                data[:, 2] *= -1.
            out = run(args, data)
            same(out, run(args, data, 0))
            assert tuple(out[0][0, :2]) == (8, 7)
            assert out[0][0, 3] == (1 if reflected else -1)
            account(args, out)
        check(f"逆方向は別予算_反転{reflected}", opposite_separate)

        def retained_after_entry(reflected=reflected):
            """
            機能: 一度許可して返済した後も元境界の有効な方向の予算を保持する。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            prices = [110.5, 113., 111., 112., 111.5, 113., 110.75, 111.75, 111.75,
                      119., 115., 115., 111.5, 113., 111., 112.5, 112.5, 120., 115., 115., 115.]
            times = [0.,20.,40.,60.,61.,81.,101.,121.,122.,123.,124.,125.,
                     500.,520.,540.,560.,561.,562.,563.,564.,565.]
            args = tape(prices, times, reflected)
            args[6][16:, 5] = 0.
            data = activity(args, reflected)
            out = run(args, data)
            old_out = run(args, data, 0)
            entered = out[0][out[0][:, 7] == 1]
            old_entered = old_out[0][old_out[0][:, 7] == 1]
            assert len(entered) == 1 and tuple(entered[0, :2]) == (8, 7)
            assert len(old_entered) == 2 and tuple(old_entered[1, :2]) == (16, 15)
            account(args, out)
        check(f"一度約定と返済後も保存予算を維持_反転{reflected}", retained_after_entry)

        for blocker in ("30秒支持", "相手5分", "未知", "気配", "距離"):
            def noncandidate(reflected=reflected, blocker=blocker):
                """
                機能: 発注候補に至らない未知活動を初回予算へ保存しない。
                引数: reflected(bool)、blocker(str)は不足資格。
                返り値: None。
                """
                args = tape()
                if blocker == "30秒支持":
                    args[7][3, 4] = 0.
                elif blocker == "相手5分":
                    args[6][3, 10] = 0.
                elif blocker == "未知":
                    args[6][3, 0] = np.nan
                elif blocker == "気配":
                    args[2][3] -= 1.
                    args[3][3] += 1.
                elif blocker == "距離":
                    args[15][13] = .625
                    args[1][3], args[2][3], args[3][3] = 112.5, 112., 113.
                    args[1][5], args[2][5], args[3][5] = 112., 111.5, 112.5
                if reflected:
                    reflect(args)
                data = activity(args, reflected)
                out = run(args, data)
                same(out, run(args, data, 0))
                assert len(out[0]) > 0
                account(args, out)
            check(f"未候補の活動不適格では記録しない_{blocker}_反転{reflected}", noncandidate)

    for retest in (0, 1):
        def future(retest=retest):
            """
            機能: 未来の価格・活動を改変しても過去の全注文と曲線が不変と確認する。
            引数: retest(int)は入口。
            返り値: None。
            """
            args = tape()
            args[15][10] = 3.
            data = activity(args)
            original = run(args, data, retest=retest)
            for cut in (2, 3, 6, 7, 10, 11, 12, 14):
                changed = deepcopy(args)
                changed_data = data.copy()
                changed_data[cut+1:] = np.nan
                for j in (1, 2, 3):
                    changed[j][cut+1:] -= 30.
                changed[6][cut+1:] = np.nan
                updated = run(changed, changed_data, retest=retest)
                np.testing.assert_array_equal(original[0][original[0][:, 0] <= cut],
                                              updated[0][updated[0][:, 0] <= cut])
                np.testing.assert_array_equal(original[1][original[1][:, 1] <= cut],
                                              updated[1][updated[1][:, 1] <= cut])
                np.testing.assert_array_equal(original[2][:cut+1], updated[2][:cut+1])
        check(f"未来改変で過去保存予算と売買不変_再試験{retest}", future)

    for budget in (0, 1):
        for reflected in (False, True):
            def compiled(budget=budget, reflected=reflected):
                """
                機能: 専用キャッシュのJITと逐次実行の全配列を比較する。
                引数: budget(int)、reflected(bool)は条件。
                返り値: None。
                """
                args = tape(reflected=reflected)
                data = activity(args, reflected)
                same(run(args, data, budget), run(args, data, budget, compiled=True))
                if budget == 0:
                    same(run(args, None, 0, activity_mode=0),
                         run(args, None, 0, activity_mode=0, compiled=True))
            check(f"JIT全出力一致_予算{budget}_反転{reflected}", compiled)

    def trend_counterexample():
        """
        機能: 予算で損失だけでなく後続トレンドの利益も消す反例を保存する。
        引数: なし。
        返り値: None。
        """
        args = tape()
        args[1][8:] = [112.5, 118., 119., 120., 121., 122., 123., 124., 125., 126., 126.]
        args[2], args[3] = args[1]-.5, args[1]+.5
        args[6][8:, 5] = 0.
        data = activity(args)
        original = run(args, data, 0)
        blocked = run(args, data)
        assert original[2][-1, 0] > 0 and blocked[2][-1, 0] == 0 and len(blocked[0]) == 0
        account(args, original)
        account(args, blocked)
    check("同方向へ伸び続ける後続勝ちも削る反例", trend_counterexample)

    assert frozen == {name: hashlib.sha256((WORK/name).read_bytes()).hexdigest() for name in frozen}
    assert sources == run_budget130.sources()
    passed = all(c["合格"] for c in checks)
    output = HERE/f"価格予算の作者人工_{time.time_ns()}.json"
    output.write_text(json.dumps(dict(passed=passed, checks=checks, sources=sources, frozen=frozen,
        author_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0, API=0, scope="架空原行のみ。利益・損失双方を削る反例も含む。",
    ), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=passed, checks=len(checks), path=str(output),
        failures=[c for c in checks if not c["合格"]]), ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
