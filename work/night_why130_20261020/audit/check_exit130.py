"""旧入口互換と新出口の因果順・部分返済会計を人工素材だけで独立検査する。"""

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
PRIOR = ROOT / "work/visual_pdca129_20261020"
sys.path.insert(0, str(PRIOR / "audit"))
from check_retest129 import fixture as prior_fixture

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit_exit130_independent")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def load(path, name):
    """
    機能: 凍結旧核又は検査対象を別名で読み込む。
    引数: path(Path)、name(str)は数値源とモジュール名。
    返り値: moduleは読込対象。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture(moves=None, top=True, reflected=False, quantity=None):
    """
    機能: 独立した固定線110・幅4・判断3・新規4の人工入力を作る。
    引数: moves(list|None)は新規後の清算損益幅、top/reflected(bool)、quantity(int|None)。
    返り値: listは核の十六引数。時刻は受信時刻の主張を持たない架空値。
    """
    moves = [2., 1., 1.5, 5., 2.5, 2., 1.5, 1.5, 1.5, 1.5] if moves is None else moves
    price = np.array([110.5, 113., 111., 112., 111.5] + [112.5+x for x in moves])
    n = len(price)
    times = np.r_[[0., 20., 40., 60., 61.], 62.+np.arange(n-5)]
    bid, ask = price-.5, price+.5
    history = np.zeros((n, 15))
    history[:, [0, 1, 2, 3, 4, 8]] = [104., 105., 2., 110., 100., 103.]
    history[:, 5] = .5
    history[4:, 5] = 0.
    history[:, [6, 7, 10, 11, 13]] = 1.
    history[:, 9] = times-60.
    history[:, 14] = times-120.
    market = np.zeros((n, 12))
    market[:, 0] = price
    market[:, 1] = 200.
    market[:, 2:4] = 4.
    market[:, 4:8] = .2
    market[:, 8:11] = times[:, None]-1.
    market[:, 11] = 1.
    if reflected:
        price = 200.-price
        bid, ask = 200.-ask, 200.-bid
        history[:, [0, 1, 8]] = 200.-history[:, [0, 1, 8]]
        previous_high = history[:, 3].copy()
        history[:, 3] = 200.-history[:, 4]
        history[:, 4] = 200.-previous_high
        history[:, [6, 7, 10, 11, 13]] *= -1.
        market[:, 0] = price
        market[:, 4:8] *= -1.
    qty, multiplier, fee = (5, 1000., 418) if top else (10, 10., 110)
    if quantity is not None:
        qty = quantity
    parameters = np.array([2., 1., 1., .75, 0., 300., .25, 900., .35, .25,
                           6., 2., 0., 1.e9])
    return [times, price, bid, ask, np.ones(n, bool), np.full(n, 4.),
            history, market, 0., times[-2], 1.e9, .5, qty, multiplier, fee, parameters]


def account(args, outputs):
    """
    機能: 全注文と各部分返済から親会計・配賦・全行時価を独立再計算する。
    引数: args(list)は架空原行、outputs(tuple)は検査対象の三配列。
    返り値: dictは親別損益。異なる場合は例外を送出する。
    """
    times, _, bid, ask, qok = args[:5]
    quantity, multiplier, fee = args[12:15]
    orders, trades, curve = outputs
    good = qok & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    inventory, entry, entry_row, parent_id = 0, 0., -1, -1
    cash, paid, gross_total = 0., 0, 0.
    entry_fees, allocated = 0, 0
    last_bid, last_ask = np.nan, np.nan
    parents = {}
    exits = 0
    for i in range(len(times)):
        if good[i]:
            last_bid, last_ask = bid[i], ask[i]
        for order in orders[orders[:, 0] == i]:
            fill, decision, cid, side, qty = map(int, order[:5])
            assert 0 <= decision < fill and good[fill]
            assert not good[decision+1:fill].any()
            assert order[5] == (ask[i] if side > 0 else bid[i])
            cost = qty*fee//10
            cash -= cost
            paid += cost
            if order[7]:
                assert inventory == 0 and qty == quantity
                assert cid not in parents
                inventory, entry, entry_row, parent_id = side*qty, order[5], fill, cid
                entry_fees, allocated = cost, 0
                parents[cid] = dict(gross=0., fees=cost, entryqty=qty, exitqty=0, parts=0)
            else:
                assert cid == parent_id and inventory*side < 0 and abs(inventory) >= qty
                direction = 1 if inventory > 0 else -1
                value = direction*(order[5]-entry)*qty*multiplier
                cash += value
                gross_total += value
                part = entry_fees-allocated if abs(inventory) == qty else entry_fees*qty//quantity
                allocated += part
                expected_fee = part+cost
                movement = direction*((bid if direction > 0 else ask)[entry_row:i+1]-entry)
                movement = movement[good[entry_row:i+1]]
                trade = trades[exits]
                assert tuple(trade[:9]) == (
                    entry_row, i, direction, qty, entry, order[5], value, expected_fee, value-expected_fee
                )
                np.testing.assert_allclose(trade[9:11],
                    [max(0., max(movement)), min(0., min(movement))], rtol=0, atol=1e-12)
                assert trade[12] == order[6] and trade[14] == cid
                parents[cid]["gross"] += value
                parents[cid]["fees"] += cost
                parents[cid]["exitqty"] += qty
                parents[cid]["parts"] += 1
                inventory += side*qty
                if inventory == 0:
                    assert allocated == entry_fees
                exits += 1
            assert abs(inventory) <= quantity
        unrealized = 0. if inventory == 0 else (
            (last_bid if inventory > 0 else last_ask)-entry
        )*inventory*multiplier
        np.testing.assert_allclose(curve[i], [cash+unrealized, inventory, paid, cash], rtol=0, atol=1e-9)
    assert inventory == 0 and exits == len(trades)
    assert abs(sum(trades[:, 6])-gross_total) < 1e-8
    assert sum(trades[:, 7]) == paid
    assert abs(sum(trades[:, 8])-cash) < 1e-8
    for cid, parent in parents.items():
        assert parent["entryqty"] == parent["exitqty"]
        parent["net"] = parent["gross"]-parent["fees"]
        assert abs(sum(trades[trades[:, 14] == cid, 8])-parent["net"]) < 1e-8
    return parents


def main():
    """
    機能: 旧互換・閾値・部分会計・時間順・未来不変・JITを独立人工で確認する。
    引数: なし。
    返り値: None。実市場データ・APIを参照せず指紋付き証跡を作る。
    """
    sources = [WORK/"night_exit130.py", PRIOR/"night_retest129c.py",
               PRIOR/"audit/check_retest129.py", Path(__file__)]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    old = load(sources[1], "出口130旧").simulate.py_func
    module = load(sources[0], "出口130独立")
    new = module.simulate.py_func
    tests = []

    def check(name, action):
        """
        機能: 一件の検査と失敗反例を保存する。
        引数: name(str)、action(callable)は検査内容。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=name, 合格=True))
        except Exception as error:
            tests.append(dict(確認=name, 合格=False, 詳細=f"{type(error).__name__}: {error}"))

    for top in (False, True):
        for reflected in (False, True):
            for confirm in range(7):
                def compatible(top=top, reflected=reflected, confirm=confirm):
                    """
                    機能: 入口確認0〜6の旧出力と無改修出口を照合する。
                    引数: top/reflected(bool)、confirm(int)。
                    返り値: None。
                    """
                    args = prior_fixture(top=top, reflected=reflected, confirm=confirm)
                    for retest in ((0, 1) if confirm < 4 else (1,)):
                        prior = old(*args, retest)
                        current = new(*args, retest, 0)
                        np.testing.assert_array_equal(prior[0], current[0])
                        np.testing.assert_array_equal(prior[1], current[1][:, :14])
                        np.testing.assert_array_equal(prior[2], current[2])
                        account(args, current)
                check(f"旧確認{confirm}_商品{top}_反転{reflected}", compatible)

    for top in (False, True):
        for reflected in (False, True):
            for style in range(4):
                def base(top=top, reflected=reflected, style=style):
                    """
                    機能: 固定人工経路の全注文行と残数量を確認する。
                    引数: top/reflected(bool)、style(int)は条件。
                    返り値: None。
                    """
                    args = fixture(top=top, reflected=reflected)
                    out = new(*args, 1, style)
                    account(args, out)
                    np.testing.assert_array_equal(out[0][0, :2], [4, 3])
                    if style in (2, 3):
                        np.testing.assert_array_equal(out[0][:, :2], [[4, 3], [7, 6], [11, 10]])
                        np.testing.assert_array_equal(out[0][:, 4],
                                                      [args[12], args[12]//2, args[12]-args[12]//2])
                        assert list(out[0][:, 6]) == [1., 76., 70.]
                        assert len(set(out[0][:, 2])) == 1
                        assert (out[1][:, 11] == 4.).all()
                    else:
                        np.testing.assert_array_equal(out[0][:, :2], [[4, 3], [11, 10]])
                check(f"全行会計と期待注文_商品{top}_反転{reflected}_出口{style}", base)

            def loser(top=top, reflected=reflected):
                """
                機能: 部分利益が出ても残玉込みの親が赤字になる反例を検査する。
                引数: top/reflected(bool)は条件。
                返り値: None。
                """
                args = fixture([2., 1., 1., -5., -5., -5., -5., -5., -5.],
                               top=top, reflected=reflected)
                out = new(*args, 1, 2)
                parents = account(args, out)
                assert out[1][0, 6] > 0 and parents[0]["net"] < 0
                assert parents[0]["net"] == (-13417. if top else -420.)
                if top:
                    np.testing.assert_array_equal(out[1][:, 7], [166., 251.])
                else:
                    np.testing.assert_array_equal(out[1][:, 7], [110., 110.])
                assert list(out[0][:, 6]) == [1., 76., 32.]
                assert out[1][0, 14] == out[1][1, 14] == 0.
            check(f"半利確でも親赤字と費用残額_商品{top}_反転{reflected}", loser)

    for reflected in (False, True):
        sign = -1 if reflected else 1
        for peak in (1.999999, 2., 2.000001):
            for drawdown in (.999999, 1., 1.000001):
                def boundary(peak=peak, drawdown=drawdown, reflected=reflected):
                    """
                    機能: 0.5R起動と0.25R戻りの厳密境界を確認する。
                    引数: peak/drawdown(float)、reflected(bool)。
                    返り値: None。
                    """
                    args = fixture([peak, peak-drawdown]+[peak-drawdown]*7, reflected=reflected)
                    out = new(*args, 1, 2)
                    partial = out[0][out[0][:, 6] == 76]
                    expected = peak >= 2. and drawdown >= 1.
                    assert len(partial) == int(expected)
                    if expected:
                        np.testing.assert_array_equal(partial[0, :2], [7, 6])
                    account(args, out)
                check(f"半返済境界_{peak}_{drawdown}_{reflected}", boundary)

        def continuous(reflected=reflected):
            """
            機能: 1R未満の順行から床を上げ、後の回復勝ちを消す反例も保存する。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture([3., -1., -2., 5., 2., 2., 2., 2., 2.], reflected=reflected)
            baseline, changed = new(*args, 1, 0), new(*args, 1, 1)
            np.testing.assert_array_equal(changed[0][1, :2], [7, 6])
            assert changed[1][0, 8] < 0 and baseline[1][0, 8] > 0
            account(args, baseline)
            account(args, changed)
        check(f"起動前連続床と回復を消す反例_{reflected}", continuous)

        for kind in ("停止", "終端", "静観", "旧方向撤退"):
            def priority(kind=kind, reflected=reflected, sign=sign):
                """
                機能: 部分条件と同時に元の全返済条件が成立した場合の優先を確認する。
                引数: kind(str)、reflected(bool)、sign(int)。
                返り値: None。
                """
                args = fixture([2., 1., 1.]+[1.]*6, reflected=reflected)
                reason = {"停止": 32., "終端": 93., "静観": 94., "旧方向撤退": 72.}[kind]
                if kind == "停止":
                    args[2][6:] -= 5.*sign
                    args[3][6:] -= 5.*sign
                elif kind == "終端":
                    args[9] = args[0][6]
                elif kind == "静観":
                    args[10] = args[0][6]+.2
                    args[15][7] = .5
                else:
                    args[7][6, [5, 7]] = -sign
                    args[15][11] = 0.
                out = new(*args, 1, 2)
                assert out[0][1, 6] == reason and out[0][1, 4] == args[12]
                assert not (out[0][:, 6] == 76).any()
                account(args, out)
            check(f"全返済優先_{kind}_{reflected}", priority)

        def pending_gap(reflected=reflected, sign=sign):
            """
            機能: 部分返済の判断後に欠測と損切り超過が生じても後続正常行で約定させる。
            引数: reflected(bool)、sign(int)は方向。
            返り値: None。
            """
            args = fixture([2., 1., 1., -8., -8., -8., -8., -8., -8.],
                           reflected=reflected)
            args[4][7] = False
            args[7][7:, 11] = 0.
            out = new(*args, 1, 2)
            np.testing.assert_array_equal(out[0][:, :2], [[4, 3], [8, 6], [9, 8]])
            assert out[0][1, 6] == 76 and out[1][0, 6] < 0
            account(args, out)
        check(f"発注後欠測と悪化を遡及取消ししない_{reflected}", pending_gap)

        def unobserved_peak(reflected=reflected):
            """
            機能: 正常でない気配を最高利益へ含めず、部分返済を起動しない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture([100., 1., 0., 0., 0., 0., 0., 0., 0.], reflected=reflected)
            args[4][5] = False
            out = new(*args, 1, 2)
            assert not (out[0][:, 6] == 76).any()
            account(args, out)
        check(f"未知気配ピークを利用しない_{reflected}", unobserved_peak)

        def fixed_width(reflected=reflected):
            """
            機能: 部分返済後のATR変更で固定幅と過去利益を取り直さない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            baseline = new(*args, 1, 3)
            args[5][5:] = 100.
            args[6][5:, :] = np.nan
            args[7][5:, :] = np.nan
            args[1][5:] = np.nan
            current = new(*args, 1, 3)
            for left, right in zip(baseline, current):
                np.testing.assert_array_equal(left, right)
            account(args, current)
        check(f"保有中の資料未知でも固定幅保護継続_{reflected}", fixed_width)

        def same_clock(reflected=reflected):
            """
            機能: 同じ価格時計でも原行を混同せず、部分返済は判断より後へ出す。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            args[0][5:8] = args[0][5]
            out = new(*args, 1, 2)
            np.testing.assert_array_equal(out[0][1, :2], [7, 6])
            account(args, out)
        check(f"同時計の原行順_{reflected}", same_clock)

        def cooldown(reflected=reflected, sign=sign):
            """
            機能: 部分返済で親を終わらせず、全返済後の休止と全再準備を要求する。
            引数: reflected(bool)、sign(int)は方向。
            返り値: None。
            """
            args = fixture([2., 1., 1., -5., -5., 1., -1.5, -.5, -.5, -.5, -.5, -.5],
                           reflected=reflected)
            args[0][10:] = [366., 386., 406., 426., 427., 428., 429.]
            args[9] = 428.
            args[6][:, 5] = .5
            out = new(*args, 1, 2)
            entries = out[0][out[0][:, 7] == 1]
            np.testing.assert_array_equal(entries[:, :2], [[4, 3], [14, 13]])
            assert list(entries[:, 2]) == [0., 1.]
            assert out[0][2, 0] == 9 and out[0][2, 4] == 3
            account(args, out)
        check(f"半返済では休止開始せず残玉と親を維持_{reflected}", cooldown)

    def one_unit():
        """
        機能: 一枚の建玉ではゼロ枚の部分返済を発注しない。
        引数: なし。
        返り値: None。
        """
        args = fixture(quantity=1)
        out = new(*args, 1, 2)
        assert not (out[0][:, 6] == 76).any()
        account(args, out)
    check("一枚の数量境界", one_unit)

    for style in range(4):
        def future(style=style):
            """
            機能: 未来の価格・履歴・短期情報を変えても過去の注文・部分会計が変わらない。
            引数: style(int)は出口。
            返り値: None。
            """
            args = fixture()
            before_out = new(*args, 1, style)
            for cutoff in (3, 4, 6, 7, 9):
                changed = deepcopy(args)
                changed[1][cutoff+1:] += 30.
                changed[2][cutoff+1:] += 30.
                changed[3][cutoff+1:] += 30.
                changed[5][cutoff+1:] = 90.
                changed[6][cutoff+1:] = np.nan
                changed[7][cutoff+1:] = np.nan
                after_out = new(*changed, 1, style)
                np.testing.assert_array_equal(before_out[0][before_out[0][:, 0] <= cutoff],
                                              after_out[0][after_out[0][:, 0] <= cutoff])
                np.testing.assert_array_equal(before_out[1][before_out[1][:, 1] <= cutoff],
                                              after_out[1][after_out[1][:, 1] <= cutoff])
                np.testing.assert_array_equal(before_out[2][:cutoff+1], after_out[2][:cutoff+1])
                account(changed, after_out)
        check(f"将来改変で過去接頭辞不変_{style}", future)

    for style in range(4):
        def compiled(style=style):
            """
            機能: 専用キャッシュのJITとPython実行が人工配列全列で同じであると確認する。
            引数: style(int)は出口。
            返り値: None。
            """
            args = fixture(top=style % 2 == 0, reflected=style % 2 == 1)
            for expected, actual in zip(new(*args, 1, style), module.simulate(*args, 1, style)):
                np.testing.assert_array_equal(expected, actual)
        check(f"JIT全配列一致_{style}", compiled)

    def entry_unchanged():
        """
        機能: 新旧の入口節が構文木として同じであることを確認する。
        引数: なし。
        返り値: None。
        """
        old_source, new_source = [p.read_text(encoding="utf-8-sig") for p in sources[:2][::-1]]
        marker = "        if not position and not pending and t >= ready_after"
        end = "        if quiet or terminal:"
        chunks = [s[s.index(marker):s.index(end, s.index(marker))] for s in (old_source, new_source)]
        old_chunk, new_chunk = chunks
        new_chunk = new_chunk.replace("                        pending_quantity = quantity\n", "")
        assert ast.dump(ast.parse("if True:\n"+old_chunk)) == ast.dump(ast.parse("if True:\n"+new_chunk))
    check("入口構文同値_数量予約のみ追加", entry_unchanged)

    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    assert before == after, "検査中に数値源が変更された"
    passed = all(t["合格"] for t in tests)
    destination = HERE/f"連続床と半返済の独立人工_{time.time_ns()}.json"
    destination.write_text(json.dumps(dict(
        passed=passed, tests=tests, sources=after, financial_replays=0, api_calls=0,
        説明="架空入力だけ。設定と仮説の採否は未固定、金融上の有効性は未検査"
    ), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=passed, count=len(tests), path=str(destination),
                          failures=[t for t in tests if not t["合格"]]), ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
