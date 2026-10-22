"""利益床内の追加数量を、注文ごとの独立会計で純人工確認する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(TASK))
import sizing129

numba.config.CACHE_DIR = str(HERE/"jit")
CHECKS = []
CASES = []
FIELDS = ("orders", "parents", "curve", "events")


def check(name: str, condition: bool) -> None:
    """
    機能: 人工の期待条件を確認して記録する。
    引数: name(str)、condition(bool)は検査名と成否。
    返り値: None。
    """
    assert condition, name
    CHECKS.append(name)


def same(name: str, left, right) -> None:
    """
    機能: 全配列を同値比較する。
    引数: name(str)、left/right(object)は配列又は数値。
    返り値: None。
    """
    np.testing.assert_array_equal(left, right, err_msg=name)
    CHECKS.append(name)


def fixture(top: bool = True, short: bool = False) -> dict:
    """
    機能: 初期少量から床が上がり、上限まで追加できる毎秒人工を作る。
    引数: top/short(bool)は商品の倍率と売り側か。
    返り値: dictはsimulateの全入力。
    """
    scale = 1. if top else 10.
    bid = np.array([100.,100.,100.,104.,106.,109.,110.,112.,113.,114.,115.]+[114.]*29)*scale
    ask = bid+scale
    side = -1 if short else 1
    first, last = ask[2], bid[31]
    if short:
        bid, ask = 400.*scale-ask, 400.*scale-bid
        first, last = bid[2], ask[31]
    qty = 5 if top else 10
    orders = np.array([[2,1,0,side,qty,first,1,1], [31,30,0,-side,qty,last,70,0]], float)
    trades = np.zeros((1,14))
    trades[0,11] = 4.*scale
    return dict(times=np.arange(len(bid), dtype=float), bid=bid, ask=ask,
        qok=np.ones(len(bid), bool), base_orders=orders, base_trades=trades,
        tick=scale, initial_quantity=2 if top else 4, maximum_quantity=qty,
        step_quantity=1 if top else 2, multiplier=1000. if top else 10.,
        fee_tenths=418 if top else 110)


def audit(value: dict, result: dict) -> None:
    """
    機能: 結果の注文だけからFIFO・全行時価・費用・追加時予算を独立照合する。
    引数: value(dict)は人工入力、result(dict)は被監査出力。
    返り値: None。核の会計関数は呼ばない。
    """
    orders, parents, curve, events = (result[n] for n in FIELDS)
    lots = []
    cash = fees = 0.
    last_bid = last_ask = np.nan
    accounts = {}
    for i in range(len(value["times"])):
        good = value["qok"][i] and np.isfinite(value["bid"][i]) and np.isfinite(value["ask"][i])
        good = good and 0 < value["bid"][i] < value["ask"][i]
        if good:
            last_bid, last_ask = value["bid"][i], value["ask"][i]
        for o in orders[orders[:, 0] == i]:
            row, source, cid, side, qty = map(int, o[:5])
            assert source < row and good and qty > 0
            expected_price = value["ask"][i] if side > 0 else value["bid"][i]
            assert o[5] == expected_price
            fee = qty*value["fee_tenths"]//10
            fees += fee
            cash -= fee
            accounts.setdefault(cid, dict(gross=0., fees=0., entries=0, exits=0, maxqty=0))
            accounts[cid]["fees"] += fee
            if o[7] == 1:
                assert not lots or lots[0][1] == side
                lots.append([cid, side, qty, o[5]])
                accounts[cid]["entries"] += qty
            else:
                remaining = qty
                for lot in lots:
                    if lot[0] != cid or lot[2] == 0:
                        continue
                    assert lot[1] == -side
                    take = min(remaining, lot[2])
                    gross = lot[1]*(o[5]-lot[3])*take*value["multiplier"]
                    cash += gross
                    accounts[cid]["gross"] += gross
                    accounts[cid]["exits"] += take
                    lot[2] -= take
                    remaining -= take
                    if remaining == 0:
                        break
                assert remaining == 0
            lots = [p for p in lots if p[2] > 0]
            held = sum(p[2] for p in lots)
            assert held <= value["maximum_quantity"]
            accounts[cid]["maxqty"] = max(accounts[cid]["maxqty"], held)
        unrealized = sum(p[1]*((last_bid if p[1] > 0 else last_ask)-p[3])*p[2]*value["multiplier"] for p in lots)
        position = sum(p[1]*p[2] for p in lots)
        np.testing.assert_allclose(curve[i], [cash+unrealized, position, fees, cash], rtol=0, atol=1e-7)
        for event in events[(events[:, 0] == i) & (events[:, 1] == 3)]:
            cid = int(event[2])
            mine = [p for p in lots if p[0] == cid]
            side, held = mine[0][1], sum(p[2] for p in mine)
            cost = sum(p[2]*p[3] for p in mine)
            take = min(value["step_quantity"], value["maximum_quantity"]-held)
            tick = value["tick"]
            entry = math.ceil((value["ask"][i]+tick)/tick-1e-10)*tick if side > 0 else math.floor((value["bid"][i]-tick)/tick+1e-10)*tick
            exit_value = math.floor(event[3]/tick+1e-10)*tick-tick if side > 0 else math.ceil(event[3]/tick-1e-10)*tick+tick
            future_fees = take*value["fee_tenths"]//10+(held+take)*value["fee_tenths"]//10
            budget = side*((held+take)*exit_value-cost-take*entry)*value["multiplier"]-accounts[cid]["fees"]-future_fees
            np.testing.assert_allclose(event[4:11], [entry, exit_value, held, take, accounts[cid]["fees"], future_fees, budget],
                                       rtol=0, atol=1e-7)
            assert budget >= 0.
    for parent in parents:
        cid = int(parent[0])
        a = accounts[cid]
        np.testing.assert_allclose(parent[8:11], [a["gross"], a["fees"], a["gross"]-a["fees"]], rtol=0, atol=1e-7)
        assert parent[14] == a["entries"]-a["exits"]
        assert parent[5] == a["maxqty"]
    CHECKS.append("独立FIFO時価費用予算_"+str(len(CASES)))


def run(value: dict, mode: int, *, jit: bool = False) -> dict:
    """
    機能: 純人工を核へ渡し独立会計へ接続する。
    引数: value(dict)、mode(int)、jit(bool)は入力・追加の有無・JITか。
    返り値: dictは4配列。
    """
    method = sizing129.simulate if jit else sizing129.simulate.py_func
    result = dict(zip(FIELDS, method(**value, addition_mode=mode)))
    audit(value, result)
    CASES.append(dict(mode=mode, jit=jit, orders=len(result["orders"]), parents=len(result["parents"])))
    return result


def main() -> None:
    """
    機能: 単純減量、利益床追加、因果順序、未知、上下、費用、未来参照を検査する。
    引数: なし。
    返り値: None。純人工証拠JSONを保存する。市場資料は一切読まない。
    """
    paths = [TASK/"sizing129.py", Path(__file__)]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for top in (True, False):
        for short in (False, True):
            value = fixture(top, short)
            reduced = run(value, 0)
            same("単純減量は同じ入口出口_"+str((top, short)), reduced["orders"][:, :4], value["base_orders"][:, :4])
            same("単純減量の枚数_"+str((top, short)), reduced["orders"][:, 4], [value["initial_quantity"]]*2)
            full = deepcopy(value)
            full["initial_quantity"] = full["maximum_quantity"]
            original = run(full, 0)
            same("元全枚数時の注文完全互換_"+str((top, short)), original["orders"], full["base_orders"])
            result = run(value, 1)
            same("追加行と判断行_"+str((top, short)), result["orders"][result["orders"][:, 6] == 81, :2],
                 [[6,5],[8,7],[9,8]])
            same("最大数量まで段階追加_"+str((top, short)), result["parents"][:, [4,5,11,12]],
                 [[value["initial_quantity"], value["maximum_quantity"],
                   value["maximum_quantity"]-value["initial_quantity"], 3]])
            compiled = run(value, 1, jit=True)
            for field in FIELDS:
                same("JIT一致_"+str((top, short, field)), result[field], compiled[field])
            # ----------------------------------------
            # 元の出口判断と追加判断が同時なら、新たな追加を予約しない。
            altered = deepcopy(value)
            altered["base_orders"][1, :2] = [6,5]
            ending = run(altered, 1)
            same("同時出口優先_"+str((top, short)), ending["orders"][:, 7], [1,0])
            # 前行で予約済みの追加は当行で約定し、その後の出口判断を予約する。
            altered = deepcopy(value)
            altered["base_orders"][1, :2] = [7,6]
            ending = run(altered, 1)
            same("前行追加の遡及取消なし_"+str((top, short)), ending["orders"][:, [0,6]],
                 [[2,1],[6,81],[7,70]])
            # 不明気配で追加未約定のまま出口通知が来たら、予約を取消す。
            altered["qok"][6] = False
            ending = run(altered, 1)
            same("未約定追加は出口で取消_"+str((top, short)), ending["orders"][:, [0,6]], [[2,1],[7,70]])
            check("追加取消証跡_"+str((top, short)), np.sum(ending["events"][:, 1] == 4) == 1)
            # 初回が未約定のまま影が終われば新規は発生しない。
            altered = deepcopy(value)
            altered["qok"][2:5] = False
            altered["base_orders"][1, :2] = [5,3]
            ending = run(altered, 1)
            same("初回未約定の影終了_"+str((top, short)), len(ending["orders"]), 0)
            # 床の丸めを整数以外の幅でも別の数式で確認する。
            altered = deepcopy(value)
            altered["base_trades"][0, 11] *= 1.0625
            run(altered, 1)
            # ----------------------------------------
            # 未来損益・幅以外の保存trades・旧約定値を毒化しても同値。
            poison = deepcopy(value)
            poison["base_trades"][:] = np.nan
            poison["base_trades"][:, 11] = value["base_trades"][:, 11]
            poison["base_orders"][:, [0,4,5]] = 9999999.
            poisoned = run(poison, 1)
            for field in FIELDS:
                same("未来保存列を非参照_"+str((top, short, field)), result[field], poisoned[field])
            cut = 12
            changed = deepcopy(value)
            changed["bid"][cut:] += 50*value["tick"]
            changed["ask"][cut:] += 50*value["tick"]
            changed["base_orders"][1, :2] = [34,33]
            future = run(changed, 1)
            same("未来変更の時価接頭_"+str((top, short)), result["curve"][:cut], future["curve"][:cut])
            same("未来変更の注文接頭_"+str((top, short)), result["orders"][result["orders"][:, 0] < cut],
                 future["orders"][future["orders"][:, 0] < cut])
            prefix = deepcopy(value)
            for key in ("times","bid","ask","qok"):
                prefix[key] = prefix[key][:cut]
            prefix["base_orders"] = prefix["base_orders"][prefix["base_orders"][:, 1] < cut]
            truncated = run(prefix, 1)
            same("真の接頭時価_"+str((top, short)), result["curve"][:cut], truncated["curve"])
            same("真の接頭注文_"+str((top, short)), result["orders"][result["orders"][:, 0] < cut], truncated["orders"])
        # ----------------------------------------
        # 次行の飛び越しで予定予算は破られる。保証された黒字へ捏造しない。
        value = fixture(top)
        value["bid"][6] += 100*value["tick"]
        value["ask"][6] += 100*value["tick"]
        gap = run(value, 1)
        check("次行gapの実損失を隠さない_"+str(top), gap["parents"][0,10] < 0)
        accepted = gap["events"][gap["events"][:,1] == 3]
        check("gap前の予算だけは非負_"+str(top), accepted[0,10] >= 0)
        # 次の別影へ最高順行・床・支払済費用を持ち越さない。
        value = fixture(top)
        scale = value["tick"]
        value["bid"] = np.r_[value["bid"], np.full(30, 114.*scale)]
        value["ask"] = value["bid"]+scale
        value["bid"][34:45] = (np.array([100.,104.,106.,109.,110.,112.,113.,114.,115.,115.,114.])+14.)*scale
        value["bid"][45:] = 128.*scale
        value["ask"] = value["bid"]+scale
        value["times"] = np.arange(len(value["bid"]), dtype=float)
        value["qok"] = np.ones(len(value["bid"]), bool)
        qty = value["maximum_quantity"]
        value["base_orders"] = np.vstack([value["base_orders"],
            [34,33,1,1,qty,value["ask"][34],1,1],
            [56,55,1,-1,qty,value["bid"][56],70,0]])
        value["base_trades"] = np.vstack([value["base_trades"], value["base_trades"]])
        multiple = run(value, 1)
        same("別影ID別の初期と追加_"+str(top), multiple["parents"][:, [0,4,5]],
             [[0,value["initial_quantity"],qty],[1,value["initial_quantity"],qty]])
        same("別影開始直後に旧床で追加しない_"+str(top),
             multiple["orders"][(multiple["orders"][:,2] == 1) & (multiple["orders"][:,6] == 81),1],
             [37,39,40])
        value = fixture(top)
        value["fee_tenths"] = 0
        value["bid"][5] = 108.*scale
        value["ask"][5] = 109.*scale
        zero = run(value, 1)
        accepted = zero["events"][zero["events"][:,1] == 3]
        same("予算ちょうどゼロは許可_"+str(top), accepted[0,10], 0.)
        value = fixture(top)
        value["fee_tenths"] = 10000000
        expensive = run(value, 1)
        same("費用を含むと不足する場合追加禁止_"+str(top), len(expensive["orders"]), 2)
        value = fixture(top)
        value["base_orders"] = np.empty((0,8))
        value["base_trades"] = np.empty((0,14))
        empty = run(value, 1)
        same("無通知は無注文_"+str(top), len(empty["orders"]), 0)
        same("無通知は時価ゼロ_"+str(top), empty["curve"], np.zeros_like(empty["curve"]))
    assert hashes == {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    proof = dict(passed=True, checks=CHECKS, cases=CASES, source_hashes=hashes,
                 financial_replays=0, market_reads=0, API=0)
    path = HERE/f"利益床内追加の純人工_{time.time_ns()}.json"
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(path=str(path), checks=len(CHECKS), cases=len(CASES),
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()), ensure_ascii=True))


if __name__ == "__main__":
    main()
