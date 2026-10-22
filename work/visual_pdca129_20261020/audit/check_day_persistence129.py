"""日中の逆行持続時計を独立した人工通知・全行会計で検査する。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
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
sys.path.insert(0, str(PREV))
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_day_persistence129")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def load(path, name):
    """
    機能: 他担当の数値核を変更せず人工専用名で読む。
    引数: path(Path)、name(str)は数値源と識別名。
    返り値: moduleは読込モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture(qty=5, reflected=False, retry=False, seconds=60, partial=False):
    """
    機能: 10秒目から両市場が小逆行する独立人工と紙上の通常返済を作る。
    引数: qty/seconds(int)、reflected/retry/partial(bool)は数量、上下、再参加と部分返済。
    返り値: listは第一巡day129の十五引数。
    """
    n = 500
    times = np.arange(n, dtype=float)
    price = np.full(n, 100.5)
    price[10:] = 99.
    if retry:
        price[seconds+50:seconds+100] = 100.5
    bid, ask = price-.5, price+.5
    good = np.ones(n, bool)
    market = np.zeros((n, 12))
    market[:, :2] = price[:, None]
    market[:, 2:4] = 4.
    market[:, 4:8] = .2
    market[:, 8] = times-.01
    market[:, 9] = times-30.
    market[:, 10] = times-30.01
    market[:, 11] = 1.
    feed = [[0., -1., 0., 1., qty, 100.5, 20., 1., 0., 4.]]
    if partial:
        take = 2 if qty == 5 else 5
        feed.append([40., 39., 0., -1., take, 99., 7., 0., 0., 4.])
        feed.append([450., 449., 0., -1., qty-take, 99., 9., 0., 0., 4.])
    else:
        feed.append([450., 449., 0., -1., qty, 99., 9., 0., 0., 4.])
    feed = np.array(feed, float)
    if reflected:
        price = 200.-price
        bid, ask = 200.-ask, 200.-bid
        market[:, :2] = 200.-market[:, :2]
        market[:, 4:8] *= -1.
        feed[:, 3] *= -1.
        feed[:, 5] = 200.-feed[:, 5]
    return [times, price, bid, ask, good, feed, 499., qty*2, market,
            np.array([0., .5, 0., 0., .75, .5]), np.full(n, 4.),
            np.full((n, 15), np.nan), 1, .25, retry]


def account(args, out):
    """
    機能: 人工注文のFIFO、現金、全行気配時価と数量を核とは独立に確認する。
    引数: args(list)、out(tuple[ndarray,...])は入力と十配列。
    返り値: dictは片道費用も含む保存注文会計。
    """
    times, price, bid, ask, good = args[:5]
    orders, trades, curve = out[:3]
    inventory, cash, realized = 0, 0., 0.
    lots, done = [], []
    rate, mult = (418, 1000) if args[7] == 10 else (110, 10)
    fees = 0
    markbid, markask = np.nan, np.nan
    valid = good & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    normal = np.flatnonzero(valid)
    for i in range(len(times)):
        if valid[i]:
            markbid, markask = bid[i], ask[i]
        for order in orders[orders[:, 0] == i]:
            row, source, cid, side, qty = map(int, order[:5])
            assert source < row
            if order[6] != 93:
                assert row == normal[np.searchsorted(normal, source, side="right")]
            assert order[5] == (ask[row] if side > 0 else bid[row])
            cash -= side*qty*order[5]
            inventory += side*qty
            fees += qty*rate//10
            assert abs(inventory) <= args[7]
            if order[7]:
                lots.append([cid, side, qty, order[5]])
            else:
                left = qty
                while left:
                    lot = lots[0]
                    assert lot[0] == cid and lot[1]*side == -1
                    take = min(left, lot[2])
                    gain = lot[1]*take*(order[5]-lot[3])
                    realized += gain
                    done.append(gain)
                    left -= take
                    lot[2] -= take
                    if not lot[2]:
                        lots.pop(0)
        liquidation = inventory*(markbid if inventory > 0 else markask) if inventory else 0.
        assert np.isclose(curve[i, 0], cash+liquidation)
        assert np.isclose(curve[i, 1], realized)
        assert curve[i, 2] == max(inventory, 0) and curve[i, 3] == max(-inventory, 0)
    assert inventory == 0
    assert np.isclose(trades[:, 10].sum(), realized)
    assert np.isclose(cash, realized)
    return dict(raw_points=realized, gross_yen=realized*mult, fees=fees, net_yen=realized*mult-fees)


def main():
    """
    機能: 連続時計の境界、他出口の優先、未来非参照と旧互換を人工だけで確認する。
    引数: なし。
    返り値: None。独立証拠を新規保存し、実市場は読まない。
    """
    sources = [WORK/name for name in ("day129.py", "day129b.py", "run_day129b.py", "日中第二巡条件.json")]
    sources += [PREV/"bbo_order_kernel126.py", Path(__file__)]
    before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old = load(WORK/"day129.py", "日中連続129旧").simulate.py_func
    module = load(WORK/"day129b.py", "日中連続129新")
    new = module.simulate.py_func
    tests = []

    def check(name, action):
        """
        機能: 一項目の成功・失敗を記録する。
        引数: name(str)、action(callable)は項目名と検査。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=name, 合格=True))
        except Exception as exc:
            tests.append(dict(確認=name, 合格=False, 詳細=type(exc).__name__+": "+str(exc)))

    for qty in (5, 10):
        for reflected in (False, True):
            for retry in (False, True):
                def compatible(qty=qty, reflected=reflected, retry=retry):
                    """
                    機能: 持続0秒の全十配列が第一巡と同値であることを確認する。
                    引数: qty(int)、reflected/retry(bool)は人工条件。
                    返り値: None。
                    """
                    args = fixture(qty, reflected, retry, partial=True)
                    a, b = old(*args), new(*args, 0.)
                    assert len(a) == len(b) == 10
                    for x, y in zip(a, b):
                        np.testing.assert_array_equal(x, y)
                    account(args, b)
                check(f"0秒全十配列同値_{qty}_{reflected}_{retry}", compatible)

            for seconds in (60, 120):
                for retry in (False, True):
                    for partial in (False, True):
                        def sustained(qty=qty, reflected=reflected, seconds=seconds, retry=retry, partial=partial):
                            """
                            機能: 連続成立、再参加時計の初期化と通常部分返済を別期待行で確認する。
                            引数: qty/seconds(int)、reflected/retry/partial(bool)は条件。
                            返り値: None。
                            """
                            args = fixture(qty, reflected, retry, seconds, partial)
                            out = new(*args, seconds)
                            forced = out[0][out[0][:, 6] == 75]
                            expected = [[seconds+11, seconds+10]]
                            if retry:
                                expected.append([2*seconds+101, 2*seconds+100])
                            np.testing.assert_array_equal(forced[:, :2], expected)
                            assert len(out[0][out[0][:, 7] == 1]) == 1+int(retry)
                            if partial:
                                np.testing.assert_array_equal(out[0][out[0][:, 6] == 7, :2], [[41, 40]])
                            np.testing.assert_array_equal(out[6][out[6][:, 1] == 15, 12], [seconds]*(1+int(retry)))
                            account(args, out)
                        check(f"連続と再参加と部分_{qty}_{reflected}_{seconds}_{retry}_{partial}", sustained)

                for fault in ("回復", "気配", "市場", "相手価格", "相手時計", "16秒空白", "15秒境界"):
                    def reset(qty=qty, reflected=reflected, seconds=seconds, fault=fault):
                        """
                        機能: 一行の解除・未知・時間空白で以前の経過を足さないことを確認する。
                        引数: qty/seconds(int)、reflected(bool)、fault(str)は人工条件。
                        返り値: None。
                        """
                        args = fixture(qty, reflected)
                        if fault == "回復":
                            args[8][40, 1] = 100.5 if not reflected else 99.5
                        elif fault == "気配":
                            args[4][40] = False
                        elif fault == "市場":
                            args[8][40, 11] = 0.
                        elif fault == "相手価格":
                            args[8][40, 1] = np.nan
                        elif fault == "相手時計":
                            args[8][40, 8] = np.nan
                        else:
                            delta = 15. if fault == "16秒空白" else 14.
                            args[0][40:] += delta
                            args[8][40:, 8:11] += delta
                            args[6] += delta
                        expected = 40+seconds if fault == "16秒空白" else 10+seconds-14 if fault == "15秒境界" else 41+seconds
                        out = new(*args, seconds)
                        np.testing.assert_array_equal(out[0][out[0][:, 6] == 75, :2], [[expected+1, expected]])
                        account(args, out)
                    check(f"連続解除_{qty}_{reflected}_{seconds}_{fault}", reset)

                def priority(qty=qty, reflected=reflected, seconds=seconds):
                    """
                    機能: 元損切り・通常終了・場終了は連続時計を待たないことを確認する。
                    引数: qty/seconds(int)、reflected(bool)は条件。
                    返り値: None。
                    """
                    args = fixture(qty, reflected)
                    if not reflected:
                        args[2][30:] = 95.
                        args[3][30:] = 96.
                    else:
                        args[2][30:] = 104.
                        args[3][30:] = 105.
                    out = new(*args, seconds)
                    np.testing.assert_array_equal(out[0][out[0][:, 6] == 32, :2], [[31, 30]])
                    account(args, out)
                    args = fixture(qty, reflected)
                    args[5][-1, :2] = [30, 29]
                    out = new(*args, seconds)
                    np.testing.assert_array_equal(out[0][-1, [0, 1, 6]], [31, 30, 9])
                    account(args, out)
                    args = fixture(qty, reflected)
                    args[6] = 30.
                    out = new(*args, seconds)
                    np.testing.assert_array_equal(out[0][-1, [0, 6]], [30, 93])
                    account(args, out)
                check(f"旧出口が確認待ちに優先_{qty}_{reflected}_{seconds}", priority)

    def same_time():
        """
        機能: 同じ価格時計内の複数行を経過秒に加算しない。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        args[0][30:41] = 30.
        args[8][30:41, 8] = 29.99
        out = new(*args, 60.)
        np.testing.assert_array_equal(out[0][out[0][:, 6] == 75, :2], [[71, 70]])
        account(args, out)
    check("同価格時計で時間を水増ししない", same_time)

    def committed():
        """
        機能: 返済判断後に相手価格が戻っても注文を取消さず次正常気配で返済する。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        args[4][71:74] = False
        args[8][71:, 1] = 110.
        args[2][74:] = 97.
        args[3][74:] = 98.
        out = new(*args, 60.)
        np.testing.assert_array_equal(out[0][out[0][:, 6] == 75, :2], [[74, 70]])
        account(args, out)
    check("判断後の回復は返済を遡及取消さない", committed)

    def future_and_prefix():
        """
        機能: 将来の資料変更と接頭切断が確定済み注文・時価へ影響しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args = fixture(retry=True)
        out = new(*args, 60.)
        altered = deepcopy(args)
        for col in (1, 2, 3):
            altered[col][200:] += 30.
        altered[8][200:, :2] += 30.
        later = new(*altered, 60.)
        np.testing.assert_array_equal(out[2][:200], later[2][:200])
        np.testing.assert_array_equal(out[0][out[0][:, 0] < 200], later[0][later[0][:, 0] < 200])
        prefix = deepcopy(args)
        for k in (0, 1, 2, 3, 4, 8, 10, 11):
            prefix[k] = prefix[k][:200]
        prefix[5] = prefix[5][prefix[5][:, 0] < 200]
        shorter = new(*prefix, 60.)
        np.testing.assert_array_equal(shorter[2], out[2][:200])
        np.testing.assert_array_equal(shorter[0], out[0][out[0][:, 0] < 200])
    check("未来毒化と接頭切断の因果性", future_and_prefix)

    def runner():
        """
        機能: 日中接続の旧十五引数と追加一引数及び四固定条件を構文比較する。
        引数: なし。
        返り値: None。
        """
        trees = [ast.parse((WORK/name).read_text(encoding="utf-8")) for name in ("run_day129.py", "run_day129b.py")]
        calls = [next(x for x in ast.walk(tree) if isinstance(x, ast.Call) and
                      isinstance(x.func, ast.Attribute) and x.func.attr == "simulate") for tree in trees]
        assert len(calls[0].args) == 15 and len(calls[1].args) == 16
        for a, b in zip(calls[0].args, calls[1].args[:15]):
            assert ast.dump(a, include_attributes=False) == ast.dump(b, include_attributes=False)
        assert ast.unparse(calls[1].args[-1]) == "config['withdrawal_persistence_seconds']"
        configs = json.loads((WORK/"日中第二巡条件.json").read_text(encoding="utf-8-sig"))
        assert [(c["withdrawal_width"], c["allow_reentry"], c["withdrawal_persistence_seconds"]) for c in configs] == [
            (.25, False, 60.), (.25, True, 60.), (.25, False, 120.), (.25, True, 120.)]
    check("接続は連続秒引数だけ追加し四条件固定", runner)

    def compiled():
        """
        機能: 専用キャッシュによるPythonとJITの全十配列を照合する。
        引数: なし。
        返り値: None。
        """
        for seconds in (0., 60., 120.):
            for reflected in (False, True):
                args = fixture(qty=10, reflected=reflected, retry=True, seconds=int(seconds), partial=True)
                for a, b in zip(new(*args, seconds), module.simulate(*args, seconds)):
                    np.testing.assert_array_equal(a, b)
    check("専用JITとPython全十配列同値", compiled)
    after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assert before == after
    result = dict(passed=all(x["合格"] for x in tests), cases=len(tests), tests=tests,
                  source_hashes=before, financial_replays=0, original_market_reads=0, API=0)
    target = HERE/f"日中持続確認の独立人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), passed=result["passed"], cases=len(tests),
                         failures=[x for x in tests if not x["合格"]]), ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
