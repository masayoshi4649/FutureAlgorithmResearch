"""次原行BBO核の開発者人工検査。実市場と金融入力は読まない。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import core126


HERE = Path(__file__).resolve().parent


def fixture(bids: list[float], *, entry: int = 1, exit_row: int = 5,
            good: list[bool] | None = None, quantity: int = 5,
            reflected: bool = False, policy: list[float] | None = None) -> tuple:
    """
    機能: Last影通知と約定可能BBOを独立に合成する。
    引数: bids(list[float])、entry/exit_row/quantity(int)、good/policy(list|None)、reflected(bool)。
    返り値: tupleは核の返却配列。各新規を当行気配で先読み約定させない。
    """
    bid = np.asarray(bids, dtype=float)
    ask = bid+1.
    side = -1 if reflected else 1
    if reflected:
        bid, ask = 200.-ask, 200.-bid
    price = (bid+ask)/2.
    n = len(bid)
    time = np.arange(n, dtype=float)*301.
    feed = np.array([[entry,entry-1,0,side,quantity,price[entry],20.,1.,0.,4.],
                     [exit_row,exit_row-1,0,-side,quantity,price[exit_row],9.,0.,0.,4.]], dtype=float)
    market = np.full((n,12), np.nan)
    market[:,11] = 0.
    qok = np.ones(n,dtype=bool) if good is None else np.asarray(good,dtype=bool)
    pars = np.array(policy if policy is not None else [0.,.5,0.,0.], dtype=float)
    runner = getattr(core126.simulate, 'py_func', core126.simulate)
    result = runner(time,price,bid,ask,qok,feed,time[-1]+1000.,quantity*2,market,pars)
    return result, time, bid, ask, qok


def check_cash(value: tuple) -> None:
    """
    機能: 注文から実在庫と全行清算額を独立に作り、FIFO決済と照合する。
    引数: value(tuple)は人工核返却値と元合成価格。
    返り値: None。不一致では例外を送出する。
    """
    result,time,bid,ask,qok = value
    orders,trades,curve,stats,cycles = result[:5]
    cash = 0.; inventory = 0
    for i in range(len(time)):
        for order in orders[orders[:,0] == i]:
            row,source,cid,side,qty = order[:5].astype(int)
            assert source < row and qok[row]
            expected = ask[row] if side > 0 else bid[row]
            assert order[5] == expected
            inventory += side*qty
            cash -= side*qty*order[5]
        if qok[i]: markbid,markask = bid[i],ask[i]
        liquidation = inventory*markbid if inventory > 0 else inventory*markask if inventory < 0 else 0.
        assert np.isclose(curve[i,0],cash+liquidation)
        assert curve[i,2] == max(0,inventory) and curve[i,3] == max(0,-inventory)
    assert inventory == 0 and stats[9] == 0.
    assert np.isclose(cash,trades[:,10].sum()) and np.isclose(cash,cycles[:,3].sum())
    assert np.isclose(cash,stats[0])


def main() -> None:
    """
    機能: 次行待機・欠測・取消競合・実建値予算・売買反射を人工だけで確認する。
    引数: なし。
    返り値: None。開発者確認JSONを新所有域へ保存する。
    """
    checks = []
    for quantity in (5,10):
        for reflected in (False,True):
            value = fixture([100,100,100,101,102,103,104],quantity=quantity,reflected=reflected)
            check_cash(value)
            orders = value[0][0]
            assert orders[:,0].tolist() == [2.,6.]
            assert orders[:,1].tolist() == [1.,5.]
            assert value[0][2][5,3 if reflected else 2] == quantity
            checks.append('新規と返済が各々次原行まで実保有を維持')
            # ----------------------------------------
            # 不適格原行は飛ばすが、その間に影が撤回した新規は復活させない。
            value = fixture([100,100,100,101,102,103,104],entry=1,exit_row=2,
                good=[True,True,False,True,True,True,True],quantity=quantity,reflected=reflected)
            check_cash(value)
            assert not len(value[0][0])
            checks.append('正常気配待ち中の影撤回による新規取消')
            value = fixture([100,100,100,101,102,103,104],entry=1,exit_row=2,
                quantity=quantity,reflected=reflected)
            check_cash(value)
            assert value[0][0][:,0].tolist() == [2.,3.]
            checks.append('同原行は前行予約の実約定が先、当行影撤回は次原行返済')
            # ----------------------------------------
            # Last影の出口より前でも、実建値とBBOで一リスクを越せば返済する。
            value = fixture([110,110,110,105,106,108,109],entry=1,exit_row=5,
                quantity=quantity,reflected=reflected)
            check_cash(value)
            assert value[0][0][-1,6] == 32. and value[0][0][-1,0] == 4.
            checks.append('実建値からの一ATR予算を次原行へ予約')
    proof = dict(passed=True,checks=checks,count=len(checks),market_reads=0,financial_runs=0,
        scope='開発者の合成確認。独立監査・原版同値・実市場成績ではない。',
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (HERE/'core126.py',HERE/'bbo_order_kernel126.py',Path(__file__))})
    target = HERE/'次原行と実建値予算の開発者純人工.json'
    assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,count=len(checks),market_reads=0,financial_runs=0),ensure_ascii=False))


if __name__ == '__main__':
    main()
