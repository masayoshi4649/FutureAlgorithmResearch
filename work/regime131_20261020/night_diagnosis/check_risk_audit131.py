"""固定リスク配分の監査を、売買核に依存しない手計算例で確認する。"""

import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

from audit_risk131 import audit_one, independent_phases, PHASES, reference
from check_portfolio_audit131 import curve

HERE = Path(__file__).resolve().parent


def fixture(symbol, risk, budget, quantity):
    """
    機能: 既存買いの部分返済と、指定枚数の追加売りの手計算例を作る。
    引数: symbol(str)、risk/budget(float)、quantity(int)は商品・初期幅・予算・正解枚数。
    返り値: tupleは独立監査への入力一式。売買判断核は利用しない。
    """
    top = symbol == "TOPIX"
    scale, mult, tick = (1., 1000., .5) if top else (10., 10., 10.)
    unit = scale*mult
    charges = {1: 41, 2: 83, 3: 125, 4: 167, 5: 209} if top else {
        q: q*11 for q in range(1, 11)}
    f5, f2, f3, fq = charges[5], charges[2], charges[3], charges[quantity]
    corefee, extrafee = f5+f2+f3, 2*fq
    corenet, extranet = 14*unit-corefee, -8*quantity*unit-extrafee
    start = datetime(2026, 9, 21, 8, 45, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()
    times = start+2700.+120*np.arange(14)
    bid = scale*np.array([100., 100., 101., np.nan, 102., 103., 104., np.nan,
                          105., 106., 107., 108., 109., 110.])
    ready = dict(start=start, limit=times[9], time_s=times, atr=np.full(14, risk),
                 symbol=symbol, session="2026-09-21_Day", tick=tick)
    quotes = dict(bid=bid, ask=bid+scale, quote_valid=np.isfinite(bid))
    phase = independent_phases(ready)
    history = np.zeros((14, 15))
    history[:, [6, 7, 10, 11]] = -1.
    co = np.array([
        [1, 0, 7, 1, 5, 101*scale, 80, 1, f5, times[1], times[0], 5],
        [4, 2, 7, -1, 2, 102*scale, 70, 0, f2, times[4], times[2], 5],
        [8, 6, 7, -1, 3, 105*scale, 70, 0, f3, times[8], times[6], 5],
    ])
    eo = np.array([
        [1, 0, 1000000, -1, quantity, 100*scale, 82, 1, fq, times[1], times[0], 5],
        [10, 9, 1000000, 1, quantity, 108*scale, 93, 0, fq, times[10], times[9], 5],
    ])
    ct = np.array([[7, 1, 8, 1, 5, 101*scale, 103.8*scale, 14*unit, corefee, corenet,
                    np.nan, np.nan, np.nan, 5, -1, 80, 70]])
    et = np.array([[1000000, 1, 10, -1, quantity, 100*scale, 108*scale,
                    -8*quantity*unit, extrafee, extranet, risk, 0., -8*scale,
                    5, 1, 82, 93]])
    longs = np.array([0, 5, 5, 5, 3, 3, 3, 3, 0, 0, 0, 0, 0, 0.])
    shorts = quantity*np.array([0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0.])
    coreeq = np.array([0, -5*unit-2*f5, -2*f5, -2*f5,
                       5*unit-corefee, 8*unit-corefee, 11*unit-corefee, 11*unit-corefee,
                       corenet, corenet, corenet, corenet, corenet, corenet])
    corecash = np.array([0, -f5, -f5, -f5, 2*unit-f5-f2, 2*unit-f5-f2,
                         2*unit-f5-f2, 2*unit-f5-f2, corenet, corenet, corenet,
                         corenet, corenet, corenet])
    extraeq = np.array([0]+[-j*quantity*unit-extrafee for j in [1, 2, 2, 3, 4, 5, 5, 6, 7]]
                       +[extranet]*4)
    extracash = np.array([0]+[-fq]*9+[extranet]*4)
    totalcurve = curve(coreeq+extraeq, longs-shorts, corecash+extracash)
    orders = np.concatenate((co, eo))
    orders = orders[np.argsort(orders[:, 0], kind="stable")]
    arrays = dict(core_orders=co, core_trades=ct, extra_orders=eo, extra_trades=et,
                  extra_curve=curve(extraeq, -shorts, extracash, True),
                  orders=orders, trades=np.concatenate((ct, et)), curve=totalcurve,
                  long_quantity=longs, short_quantity=shorts)
    config = dict(id="リスク配分人工", schedule=0, style=0, budget_ticks=budget)
    net = corenet+extranet
    summary = dict(profit=corenet, loss=-extranet, net=net,
                   gross=14*unit-8*quantity*unit, fees=corefee+extrafee,
                   entries=2, quantity=5+quantity, parent_wins=1, parent_losses=1,
                   max_quantity=max(5, quantity), max_long=5, max_short=quantity,
                   max_gross_quantity=5+quantity, max_drawdown=totalcurve[-1, 3],
                   deadline_entries=1, activation_time=times[0],
                   components={"旧核": dict(entries=1, profit=corenet, loss=0., net=corenet,
                                            gross=14*unit, fees=corefee),
                               "追加": dict(entries=1, profit=0., loss=-extranet, net=extranet,
                                            gross=-8*quantity*unit, fees=extrafee)},
                   phases={name: dict(entries=2 if i == 5 else 0, net=net if i == 5 else 0.)
                           for i, name in enumerate(PHASES)},
                   phase_equity_changes={name: net if i == 5 else 0. for i, name in enumerate(PHASES)},
                   direction={"買い": dict(entries=1, net=corenet),
                              "売り": dict(entries=1, net=extranet)})
    return arrays, ready, quotes, history, phase, config, summary, co[:, :8].copy()


def main():
    """
    機能: 商品・整数切捨て・上下限の手計算例と不正記録の検出を検査する。
    引数: なし。
    返り値: None。時刻付き人工証拠を保存する。
    """
    cases = [
        ("TOPIX", 4., 8., 5), ("TOPIX", 10., 8., 2),
        ("TOPIX", 21., 8., 1), ("TOPIX", 10., 12., 3),
        ("TOPIX", 10., 16., 4), ("TOPIX", 10., 24., 5),
        ("TOPIX", 6.6, 8., 3), ("TOPIX", 6.7, 8., 2),
        ("NK225", 80., 8., 10), ("NK225", 290., 8., 2),
        ("NK225", 290., 12., 4), ("NK225", 290., 16., 5),
        ("NK225", 290., 24., 8), ("NK225", 1000., 8., 1),
    ]
    passed = []
    for symbol, risk, budget, quantity in cases:
        result = audit_one(*fixture(symbol, risk, budget, quantity))
        passed.append(dict(symbol=symbol, risk=risk, budget=budget, quantity=quantity, net=result["net"]))
    # ----------------------------------------
    # 全会計が合っていても数量計画だけ誤った記録と、その他の会計不正を拒否する。
    wrong = []
    args = list(fixture("TOPIX", 10., 8., 3))
    try:
        audit_one(*args)
    except AssertionError as exc:
        assert "追加枚数" in str(exc)
        wrong.append(dict(case="会計一致でも数量式が誤り", detected=str(exc)))
    else:
        raise AssertionError("固定リスクの数量誤りを見逃した")
    for label, name, place, value in [
        ("部分返済の料金切捨て", "core_orders", (1, 8), 84.),
        ("追加売り在庫の消失", "short_quantity", (2,), 0.),
        ("欠測行で清算価値を書換え", "curve", (3, 0), 0.),
        ("追加の手数料を片道にする", "extra_trades", (0, 8), 83.),
        ("旧親の平均返済価格誤り", "core_trades", (0, 6), 105.),
    ]:
        args = copy.deepcopy(fixture("TOPIX", 10., 8., 2))
        args[0][name][place] = value
        try:
            audit_one(*args)
        except AssertionError as exc:
            wrong.append(dict(case=label, detected=str(exc)))
        else:
            raise AssertionError("不正保存値を拒否しなかった:"+label)
    forbidden = ("baseline131", "participation131", "participation_risk131",
                 "engine131", "run_portfolio131", "run_risk131")
    assert not any(name in sys.modules for name in forbidden)
    target = HERE / ("リスク配分会計監査の独立手計算_"+str(time.time_ns())+".json")
    proof = dict(passed=True, financial_replays=0, core_replays=0,
                 checks=len(passed)+len(wrong), valid_cases=passed, corruptions=wrong,
                 checker=reference(HERE / "audit_risk131.py"),
                 predecessor_checker=reference(HERE / "audit_portfolio131.py"),
                 test_source=reference(Path(__file__).resolve()), old_source_changes=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(target.as_posix(), "人工", proof["checks"], "合格", flush=True)


if __name__ == "__main__":
    main()
