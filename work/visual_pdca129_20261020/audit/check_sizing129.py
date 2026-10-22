"""利益床を使う段階追加を独立した人工通知と会計で検査する。"""

import ast
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
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
os.environ["NUMBA_CACHE_DIR"] = str(HERE/"jit_sizing129")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def fixture(top=True, reflected=False, exit_source=9, width=4.):
    """
    機能: 小順行では追加せず、大順行で段階追加できる人工価格と保存通知を作る。
    引数: top/reflected(bool)、exit_source(int)、width(float)は商品、上下、元出口と幅。
    返り値: listは数量核の十三引数。
    """
    scale = 1. if top else 20.
    bid = np.array([100., 100., 103., 105., 108., 108., 116., 116., 116., 112., 111.5, 111.5])*scale
    ask = bid+.5*scale
    times = np.arange(len(bid), dtype=float)
    side = 1
    if reflected:
        bid, ask = 300.*scale-ask, 300.*scale-bid
        side = -1
    initial, maximum, step = (2, 5, 1) if top else (4, 10, 2)
    mult, fee = (1000., 418) if top else (10., 110)
    entry = ask[1] if side > 0 else bid[1]
    leave = bid[exit_source+1] if side > 0 else ask[exit_source+1]
    orders = np.array([[1., 0., 0., side, maximum, entry, 1., 1.],
                       [exit_source+1., exit_source, 0., -side, maximum, leave, 70., 0.]])
    gross = side*maximum*(leave-entry)*mult
    fees = 2*(maximum*fee//10)
    trades = np.array([[1., exit_source+1., side, maximum, entry, leave, gross, fees,
                        gross-fees, 0., 0., width*scale, 70., 2.]])
    return [times, bid, ask, np.ones(len(times), bool), orders, trades, .5*scale,
            initial, maximum, step, mult, fee, 1]


def audit(args, out):
    """
    機能: FIFO・全行清算価値・注文費用・完結親・各追加予算を独立に確認する。
    引数: args(list)、out(tuple[ndarray,...])は入力と四出力。
    返り値: None。不整合は例外にする。
    """
    times, bid, ask, qok = args[:4]
    orders, parents, curve, events = out
    tick, initial, maximum, step, mult, rate = args[6:12]
    good = qok & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    normal = np.flatnonzero(good)
    cash, realized, fees, inventory = 0., 0., 0, 0
    lots = []
    parent_gross, parent_fee, parent_max, parent_first = {}, {}, {}, {}
    markbid, markask = np.nan, np.nan
    for i in range(len(times)):
        if good[i]:
            markbid, markask = bid[i], ask[i]
        for order in orders[orders[:, 0] == i]:
            row, source, cid, side, qty = map(int, order[:5])
            assert row == normal[np.searchsorted(normal, source, side="right")]
            assert qty > 0 and qty == order[4]
            assert order[5] == (ask[row] if side > 0 else bid[row])
            inventory += side*qty
            assert abs(inventory) <= maximum
            fee = qty*rate//10
            fees += fee
            cash -= fee
            parent_fee[cid] = parent_fee.get(cid, 0)+fee
            parent_gross.setdefault(cid, 0.)
            if order[7]:
                if cid not in parent_first:
                    parent_first[cid] = order.copy()
                    assert qty == initial
                else:
                    assert qty <= step and order[6] == 81.
                lots.append([cid, side, qty, order[5]])
                parent_max[cid] = max(parent_max.get(cid, 0), abs(inventory))
            else:
                left = qty
                while left:
                    lot = lots[0]
                    assert lot[0] == cid and side*lot[1] == -1
                    take = min(left, lot[2])
                    gain = lot[1]*take*(order[5]-lot[3])*mult
                    cash += gain
                    realized += gain
                    parent_gross[cid] += gain
                    left -= take
                    lot[2] -= take
                    if not lot[2]:
                        lots.pop(0)
        unrealized = sum(lot[1]*lot[2]*((markbid if lot[1] > 0 else markask)-lot[3])*mult for lot in lots)
        np.testing.assert_allclose(curve[i], [cash+unrealized, inventory, fees, realized-fees], rtol=0, atol=1.e-6)
    for parent in parents:
        cid = int(parent[0])
        assert parent[4] == initial and parent[5] == parent_max[cid]
        assert parent[8] == parent_gross[cid] and parent[9] == parent_fee[cid]
        assert parent[10] == parent_gross[cid]-parent_fee[cid]
        assert parent[14] == sum(lot[2] for lot in lots if lot[0] == cid)
        added = orders[(orders[:, 2] == cid) & (orders[:, 6] == 81.)]
        assert parent[11] == added[:, 4].sum() and parent[12] == len(added)
    # ----------------------------------------
    # 実装とは別にDecimalで予算の呼値丸めと全費用を求める。
    for event in events[events[:, 1] == 3.]:
        row, cid = int(event[0]), int(event[2])
        side = int(parent_first[cid][3])
        history = orders[(orders[:, 2] == cid) & (orders[:, 0] <= row)]
        entries = history[history[:, 7] == 1.]
        held = int(entries[:, 4].sum())
        qty = min(step, maximum-held)
        cost = float(np.sum(entries[:, 4]*entries[:, 5]))
        paid = int(np.sum(history[:, 4].astype(int)*rate//10))
        step_d = Decimal(str(tick))
        floor_d = Decimal(str(event[3]))
        quoted = ask[row] if side > 0 else bid[row]
        entry_d = (Decimal(str(quoted))+Decimal(side)*step_d)/step_d
        entry_d = entry_d.to_integral_value(rounding=ROUND_CEILING if side > 0 else ROUND_FLOOR)*step_d
        leave_d = (floor_d/step_d).to_integral_value(rounding=ROUND_FLOOR if side > 0 else ROUND_CEILING)*step_d
        leave_d -= Decimal(side)*step_d
        future_fees = qty*rate//10+(held+qty)*rate//10
        projected = side*((held+qty)*float(leave_d)-cost-qty*float(entry_d))*mult-paid-future_fees
        np.testing.assert_allclose(event[4:11], [float(entry_d), float(leave_d), held, qty, paid, future_fees, projected],
                                   rtol=0, atol=1.e-6)
        assert projected >= -1.e-8


def main():
    """
    機能: 追加判断の因果性、0円予算境界、同時出口、未知約定と接続を検査する。
    引数: なし。
    返り値: None。純人工のみ実行し、指紋付き検査資料を保存する。
    """
    paths = [WORK/name for name in ("sizing129.py", "run_sizing129.py", "第五巡条件.json",
                                    "第五巡の変更根拠.json", "register_sizing129.py")]
    paths.append(Path(__file__))
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    spec = importlib.util.spec_from_file_location("数量129独立", WORK/"sizing129.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    run = module.simulate.py_func
    tests = []

    def check(name, action):
        """
        機能: 一件の成否を記録する。
        引数: name(str)、action(callable)は確認名と検査。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=name, 合格=True))
        except Exception as exc:
            tests.append(dict(確認=name, 合格=False, 詳細=type(exc).__name__+": "+str(exc)))

    for top in (False, True):
        for reflected in (False, True):
            def full(top=top, reflected=reflected):
                """
                機能: 全量固定なら元保存注文・親損益がそのまま一致することを確認する。
                引数: top/reflected(bool)は商品と上下。
                返り値: None。
                """
                args = fixture(top, reflected)
                args[7] = args[8]
                args[-1] = 0
                out = run(*args)
                np.testing.assert_array_equal(out[0], args[4])
                np.testing.assert_array_equal(out[1][:, 8:11], args[5][:, 6:9])
                audit(args, out)
            check(f"全量対照は元注文会計同値_{top}_{reflected}", full)

            def reduce(top=top, reflected=reflected):
                """
                機能: 初期四割固定は注文時刻不変で実費用を再計算することを確認する。
                引数: top/reflected(bool)は商品と上下。
                返り値: None。
                """
                args = fixture(top, reflected)
                args[-1] = 0
                out = run(*args)
                assert len(out[0]) == 2 and len(out[1]) == 1
                np.testing.assert_array_equal(out[0][:, :4], args[4][:, :4])
                assert np.all(out[0][:, 4] == args[7])
                assert out[1][0, 8] == args[5][0, 6]*.4
                assert out[1][0, 9] == 2*(args[7]*args[11]//10)
                audit(args, out)
            check(f"四割対照は同時刻と実注文費用_{top}_{reflected}", reduce)

            def staged(top=top, reflected=reflected):
                """
                機能: 小順行で追加せず、床予算が残る順行だけで上限まで段階追加する。
                引数: top/reflected(bool)は商品と上下。
                返り値: None。
                """
                args = fixture(top, reflected)
                out = run(*args)
                additions = out[0][out[0][:, 6] == 81.]
                np.testing.assert_array_equal(additions[:, :2], [[5, 4], [7, 6], [8, 7]])
                assert out[1][0, 5] == args[8] and out[1][0, 12] == 3
                audit(args, out)
            check(f"予算が残る場合だけ段階追加_{top}_{reflected}", staged)

            def rounding(top=top, reflected=reflected):
                """
                機能: 非整数の初期幅による床丸めと注文毎の費用切捨てを確認する。
                引数: top/reflected(bool)は商品と上下。
                返り値: None。
                """
                args = fixture(top, reflected, width=4.1)
                out = run(*args)
                assert len(out[3][out[3][:, 1] == 3.]) > 0
                audit(args, out)
            check(f"呼値未満の床を不利に丸め費用を含める_{top}_{reflected}", rounding)

            for exit_source, count, fill_source in ((4, 0, None), (5, 1, [5, 4])):
                def simultaneous(top=top, reflected=reflected, exit_source=exit_source, count=count, fill_source=fill_source):
                    """
                    機能: 新たな追加判断より出口を優先し、既に予約した追加の当行約定は取り消さない。
                    引数: top/reflected(bool)、exit_source/count(int)、fill_source(list|None)は条件。
                    返り値: None。
                    """
                    args = fixture(top, reflected, exit_source)
                    out = run(*args)
                    adds = out[0][out[0][:, 6] == 81.]
                    assert len(adds) == count
                    if count:
                        np.testing.assert_array_equal(adds[0, :2], fill_source)
                    assert out[0][-1, 1] == exit_source and out[0][-1, 0] == exit_source+1
                    audit(args, out)
                check(f"出口と追加の順序_{top}_{reflected}_{exit_source}", simultaneous)

            def cancelled_wait(top=top, reflected=reflected):
                """
                機能: 気配がない間の追加予約を影終了通知で取り消し、既存玉だけ返済する。
                引数: top/reflected(bool)は商品と上下。
                返り値: None。
                """
                args = fixture(top, reflected, exit_source=6)
                args[3][5:8] = False
                out = run(*args)
                assert len(out[0][out[0][:, 6] == 81.]) == 0
                assert out[0][-1, 0] == 8 and out[0][-1, 1] == 6
                assert out[0][-1, 4] == args[7]
                assert len(out[3][out[3][:, 1] == 4.]) == 1
                audit(args, out)
            check(f"影終了時の未約定追加取消し_{top}_{reflected}", cancelled_wait)

            def unfavorable_gap(top=top, reflected=reflected):
                """
                機能: 一呼値予算を超える未知gapでも予約追加を約定させ赤字を隠さない。
                引数: top/reflected(bool)は商品と上下。
                返り値: None。
                """
                args = fixture(top, reflected, exit_source=5)
                jump = 60.*(1 if top else 20.)*(-1 if reflected else 1)
                args[1][5] += jump
                args[2][5] += jump
                out = run(*args)
                adds = out[0][out[0][:, 6] == 81.]
                assert len(adds) == 1 and adds[0, 0] == 5
                assert out[1][0, 10] < 0.
                audit(args, out)
            check(f"未知gap損失を都合よく除外しない_{top}_{reflected}", unfavorable_gap)

    for multiplier, allowed in ((12., True), (11.999, False)):
        def budget_boundary(multiplier=multiplier, allowed=allowed):
            """
            機能: 全費用後の予定収支が0円なら追加し、わずかでも赤字なら拒否する。
            引数: multiplier(float)、allowed(bool)は厳密境界の人工条件。
            返り値: None。
            """
            args = fixture(exit_source=7)
            args[1][2:] = 106.5
            args[2][2:] = 107.
            args[10] = multiplier
            args[11] = 10
            out = run(*args)
            events = out[3][out[3][:, 1] == 3.]
            assert bool(len(events)) == allowed
            if allowed:
                assert events[0, 10] == 0.
            audit(args, out)
        check(f"全費用後ゼロ境界_{multiplier}", budget_boundary)

    def unused_future_columns():
        """
        機能: 保存tradesの初期幅以外とordersの未来約定情報を毒化しても不変と確認する。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        baseline = run(*args)
        altered = deepcopy(args)
        altered[5][:] = np.nan
        altered[5][:, 11] = args[5][:, 11]
        altered[4][:, [0, 4, 5]] = np.nan
        for a, b in zip(baseline, run(*altered)):
            np.testing.assert_array_equal(a, b)
    check("初期幅以外の未来取引列と約定価格は未使用", unused_future_columns)

    def no_initial_fill():
        """
        機能: 初回未約定のまま影終了した場合は幽霊建玉を作らない。
        引数: なし。
        返り値: None。
        """
        args = fixture(exit_source=5)
        args[3][1:7] = False
        out = run(*args)
        assert len(out[0]) == len(out[1]) == 0 and np.all(out[2] == 0.)
    check("初回未約定の影終了", no_initial_fill)

    def future_prefix():
        """
        機能: 将来の気配と影出口変更や入力切断で過去追加判断が変わらないと確認する。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        original = run(*args)
        altered = deepcopy(args)
        altered[1][8:] += 20.
        altered[2][8:] += 20.
        altered[4][-1, 1] = 10
        result = run(*altered)
        np.testing.assert_array_equal(original[0][original[0][:, 0] < 8], result[0][result[0][:, 0] < 8])
        np.testing.assert_array_equal(original[2][:8], result[2][:8])
        prefix = deepcopy(args)
        for k in range(4):
            prefix[k] = prefix[k][:8]
        prefix[4] = prefix[4][prefix[4][:, 1] < 8]
        shorter = run(*prefix)
        np.testing.assert_array_equal(shorter[0], original[0][original[0][:, 0] < 8])
        np.testing.assert_array_equal(shorter[2], original[2][:8])
        np.testing.assert_array_equal(shorter[3], original[3][original[3][:, 0] < 8])
    check("未来改変と真の接頭切断で過去不変", future_prefix)

    def same_clock():
        """
        機能: 同時計でも注文判断の次の正常原行で約定する。
        引数: なし。
        返り値: None。
        """
        args = fixture()
        args[0][:] = 0.
        out = run(*args)
        assert np.all(out[0][:, 0] > out[0][:, 1])
        np.testing.assert_array_equal(out[0][out[0][:, 6] == 81., :2], [[5, 4], [7, 6], [8, 7]])
        audit(args, out)
    check("同価格時計でも次正常原行", same_clock)

    def runner():
        """
        機能: 数量配分・元判断の固定参照・入力指紋検査と四対照を読む。
        引数: なし。
        返り値: None。
        """
        text = (WORK/"run_sizing129.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        call = next(x for x in ast.walk(tree) if isinstance(x, ast.Call) and
                    isinstance(x.func, ast.Attribute) and x.func.attr == "simulate")
        wanted = ["ready['time_s']", "q['bid']", "q['ask']", "q['quote_valid']", "base_orders", "base_trades",
                  "ready['tick']", "2 if top else 4", "5 if top else 10", "1 if top else 2",
                  "1000.0 if top else 10.0", "418 if top else 110", "config['addition_mode']"]
        assert [ast.unparse(x) for x in call.args] == wanted
        assert 'assert sha(ROOT / saved["path"]) == saved["sha256"]' in text
        assert 'assert sha(ROOT / ref["path"]) == ref["sha256"]' in text
        configs = json.loads((WORK/"第五巡条件.json").read_text(encoding="utf-8-sig"))
        assert [(x["id"], x["base_method"], x["addition_mode"]) for x in configs] == [
            ("NV18", "N36", 0), ("NV19", "N36", 1), ("NV20", "NV02", 0), ("NV21", "NV02", 1)]
        reason = json.loads((WORK/"第五巡の変更根拠.json").read_text(encoding="utf-8-sig"))
        assert reason["extra_input_paths"] == ["work/daynight128_20261020/round5/全条件の会計.json",
                                                "work/visual_pdca129_20261020/round1/全条件の会計.json"]
        registration = (WORK/"register_sizing129.py").read_text(encoding="utf-8")
        assert 'reason.get("extra_input_paths", [])' in registration
        assert "input_references=refs" in registration
    check("接続の数量と四対照及び元判断指紋固定", runner)

    def compiled():
        """
        機能: 専用JITとPythonの全配列一致を確認する。
        引数: なし。
        返り値: None。
        """
        for top in (False, True):
            for reflected in (False, True):
                for mode in (0, 1):
                    args = fixture(top, reflected)
                    args[-1] = mode
                    for a, b in zip(run(*args), module.simulate(*args)):
                        np.testing.assert_array_equal(a, b)
    check("専用JIT全配列一致", compiled)
    assert hashes == {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result = dict(passed=all(x["合格"] for x in tests), cases=len(tests), tests=tests,
                  source_hashes=hashes, financial_replays=0, original_market_reads=0, API=0)
    target = HERE/f"利益床予算による段階追加の独立人工_{time.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), passed=result["passed"], cases=len(tests),
                         failures=[x for x in tests if not x["合格"]]), ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
