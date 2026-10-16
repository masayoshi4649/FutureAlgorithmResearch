"""105の物理約定と全行時価を検算し、改善が利益を捨てた分も分解する。"""

import math

import numpy as np

import common


def inspect(key: tuple[str, str], record: dict, output: dict) -> dict:
    """
    機能: 旧会計に加え、次の正常気配での約定と全行の清算時価を独立計算する。
    引数: key(tuple[str,str])、record/output(dict)は場商品・保存気配・注文結果。
    返り値: dictは手数料後会計。予約の条件そのものの監査は別に行う。
    """
    old = common.module('105の不変会計', common.ROOT/'work/wave_v102/accounting.py')
    result = old.account(key, output)
    n = len(record['seq'])
    bid, ask, times = record['bid'], record['ask'], record['time_s']
    valid = (record['quote_valid'] & np.isfinite(times) & np.isfinite(bid) & np.isfinite(ask)
             & (bid > 0) & (ask > bid))
    normal_rows = np.flatnonzero(valid)
    multiplier, fee_unit, cap = (1000., 41.8, 10) if key[1] == 'TOPIX' else (10., 11., 20)
    changes, long_changes, short_changes = (np.zeros(n) for _ in range(3))
    for order in output['orders']:
        row, decision, direction, quantity = int(order[0]), int(order[1]), int(order[4]), int(order[5])
        assert row > decision and valid[row] and 0 < quantity <= cap
        after = normal_rows[np.searchsorted(normal_rows, decision, side='right'):]
        if not order[7]:
            after = after[times[after] >= order[10]]
        assert len(after) and int(after[0]) == row
        expected = ask[row] if direction == 1 else bid[row]
        assert abs(order[6]-expected) < 1e-8
        assert order[9] == math.floor(quantity*fee_unit+1e-8)
        changes[row] += -direction*quantity*expected*multiplier-order[9]
        held_direction = int(order[15])
        quantity_change = quantity if order[7] else -quantity
        (long_changes if held_direction == 1 else short_changes)[row] += quantity_change
    # ----------------------------------------
    # 非正常行は最後の正常気配で評価し、未知の価格を補完して売買しない。
    cash = np.cumsum(changes)
    longs, shorts = np.cumsum(long_changes), np.cumsum(short_changes)
    assert np.all((longs >= 0) & (shorts >= 0) & (longs <= cap) & (shorts <= cap))
    assert not np.any((longs > 0) & (shorts > 0))
    held = (longs+shorts) > 0
    previous = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    assert np.all(previous[held] >= 0)
    expected_curve = cash.copy()
    selected = previous[held]
    expected_curve[held] += (longs[held]*bid[selected]-shorts[held]*ask[selected])*multiplier
    expected_curve[held] -= np.floor((longs[held]+shorts[held])*fee_unit+1e-8)
    np.testing.assert_allclose(output['curve'], expected_curve, atol=1e-4, rtol=0)
    np.testing.assert_array_equal(output['target_trace'][:, 0], longs)
    np.testing.assert_array_equal(output['target_trace'][:, 1], shorts)
    assert output['target_trace'][:, 2:4].max(initial=0) <= cap
    result['独立全行会計検算'] = True
    return result


def trade_map(output: dict, record: dict) -> dict:
    """
    機能: 条件変更で親番号が変わっても、同じ入口判断を対応させる。
    引数: output/record(dict)は新結果と原行対応。
    返り値: dictは入口原seqと方向を鍵にした実取引の簡潔な記録。
    """
    result = {}
    for trade in output['trades']:
        decision, side = int(trade[15]), int(trade[4])
        key = str(int(record['seq'][decision]))+'|'+str(side)
        assert key not in result
        result[key] = dict(net=float(trade[11]), gross=float(trade[10]),
            entry_row=int(trade[2]), exit_row=int(trade[3]), decision_row=decision,
            entry_price=float(trade[6]), exit_price=float(trade[7]), side=side,
            quantity=int(trade[5]), reason=int(trade[13]))
    return result


def contribution(baseline: dict, changed: dict) -> dict:
    """
    機能: 収支改善を、避けた損失・捨てた利益・出口変化・新しい入口へ分ける。
    引数: baseline/changed(dict)は同じ入口候補系列・実数量の取引対応表。
    返り値: dictは収支差と厳密に一致する四つの寄与。事後の分析専用。
    """
    removed = sorted(set(baseline)-set(changed))
    added = sorted(set(changed)-set(baseline))
    retained = sorted(set(baseline)&set(changed))
    avoided = sum(-baseline[key]['net'] for key in removed if baseline[key]['net'] < 0)
    sacrificed = sum(baseline[key]['net'] for key in removed if baseline[key]['net'] > 0)
    exit_change = sum(changed[key]['net']-baseline[key]['net'] for key in retained)
    new_net = sum(changed[key]['net'] for key in added)
    delta = sum(value['net'] for value in changed.values())-sum(value['net'] for value in baseline.values())
    assert abs(delta-(avoided-sacrificed+exit_change+new_net)) < 1e-5
    for key in retained:
        assert changed[key]['entry_row'] == baseline[key]['entry_row']
        assert changed[key]['quantity'] == baseline[key]['quantity']
        assert changed[key]['entry_price'] == baseline[key]['entry_price']
    return dict(収支変化=delta, 避けた基準損失=avoided, 失った基準利益=sacrificed,
        共通入口の出口変化=exit_change, 新たな入口の収支=new_net,
        消えた基準入口=removed, 新しい入口=added, 共通入口=retained,
        注意='入口消失には条件拒否と、別ポジション保有による見送りがある。すべてを予測改善とは呼ばない。')
