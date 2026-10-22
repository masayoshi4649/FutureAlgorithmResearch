"""利益の部分返済を補充信用へ変える核の人工検査。実市場の金融再生はしない。"""

import copy
import json
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit_recycle_artificial')
import engine139
import recycle139


def fixture(kind='extreme', partial=True):
    """
    機能: 利益の出た部分返済と、その後の新支持を持つ人工系列を作る。
    引数: kind(str)は極値更新又は押し戻り、partial(bool)は元親途中返済の有無。
    返り値: tupleは原行時刻・気配・ATR・二市場特徴・時計区分・元通知。
    """
    n = 620
    times = np.arange(n, dtype=float) + 1.
    mark = np.full(n, 100.)
    mark[20:80] = 101.
    mark[80:] = 103.
    if kind == 'extreme':
        mark[205:] = 103.5
    else:
        mark[160:205] = 102.5
        mark[205:] = 102.8
    quotes = dict(bid=mark.copy(), ask=mark + .1, quote_valid=np.ones(n, bool))
    market = np.zeros((n, 12))
    market[:, 4:8] = .5
    market[:, 8] = times - .1
    market[:, 11] = 1.
    core = [[1, 0, 1, 1, 5, quotes['ask'][1], 1, 1, 0, times[1], times[0], 1]]
    if partial:
        core.append([140, 139, 1, -1, 2, quotes['bid'][140], 12, 0, 0, times[140], times[139], 1])
    core.append([600, 599, 1, -1, 3 if partial else 5, quotes['bid'][600], 93, 0, 0, times[600], times[599], 1])
    return times, quotes, np.ones(n), market, np.ones(n, np.int64), np.asarray(core, float)


def config(mode='extreme', rounds=1):
    """
    機能: 未消化段が残る状況で補充の起動を検査する固定条件を作る。
    引数: mode(str)、rounds(int)は再追加機構と回数。
    返り値: dictは人工用条件。実市場から係数を選ばない。
    """
    return dict(initial=2, target=5, increments=[2, 1], steps=[.25, 10.], fill_last=False,
                support_hold=15., min_after_initial=30., exit_activation=[0.],
                recycle_rounds=rounds, cooldown=60., recycle_step=.25, recycle_mode=mode,
                retrace_r=.25, recovery_r=.25, fee_tenths=418, multiplier=1000., risk_floor=1.)


def run(data, cfg, old=False):
    """
    機能: 人工系列だけを新旧の核へ接続する。
    引数: data(tuple)、cfg(dict)、old(bool)は人工入力、条件、旧対照の指定。
    返り値: ndarrayは人工注文。
    """
    return (engine139 if old else recycle139).replay(*data, cfg)


def account(orders, data, cfg):
    """
    機能: 人工約定を独立に数量・費用配賦・補充信用で検算する。
    引数: orders(ndarray)、data(tuple)、cfg(dict)は人工出力と設定。
    返り値: dictは再追加回数・信用発生量・使用量・最大保有。
    """
    times, quotes, _, _, _, original = data
    tickets = {}
    credit = earned = used = maximum = held = cycles = 0
    last_parent = int(original[-1, 0])
    for row in orders:
        i, decision, _, side, quantity = map(int, row[:5])
        price, reason, new, uid, fee = row[5:]
        uid, fee, new = int(uid), int(fee), int(new)
        assert decision < i and quotes['quote_valid'][i]
        assert abs(price - quotes['ask' if side > 0 else 'bid'][i]) < 1e-7
        assert fee == quantity * cfg['fee_tenths'] // 10
        if new:
            assert uid not in tickets
            if reason == 1393.:
                cycles += 1
                assert i < last_parent and credit >= quantity
                assert tickets[0]['qty'] > 0
                credit -= quantity
                used += quantity
            tickets[uid] = dict(qty=quantity, price=price, side=side, fee=fee)
            held += quantity
        else:
            ticket = tickets[uid]
            assert ticket['qty'] >= quantity and ticket['side'] == -side
            opening = ticket['fee'] * quantity // ticket['qty']
            ticket['fee'] -= opening
            net = ticket['side'] * (price - ticket['price']) * quantity * cfg['multiplier'] - opening - fee
            ticket['qty'] -= quantity
            held -= quantity
            if uid > 0 and net > 0. and i < last_parent:
                credit += quantity
                earned += quantity
        maximum = max(maximum, held)
        assert 0 <= held <= cfg['target'] <= 10 and credit == earned - used
    assert held == 0 and all(t['qty'] == 0 and t['fee'] == 0 for t in tickets.values())
    assert cycles <= cfg['recycle_rounds']
    return dict(cycles=cycles, earned=earned, used=used, maximum=maximum)


def main():
    """
    機能: 新極値・押し戻り・部分利確・信用不足・未来不変等を人工系列で検査する。
    引数: なし。
    返り値: None。人工検査記録だけを保存する。
    """
    checks = []
    for mode in ('extreme', 'pullback'):
        data = fixture(mode)
        cfg = config(mode)
        new = run(data, cfg)
        old = run(data, cfg, old=True)
        result = account(new, data, cfg)
        assert result['cycles'] == 1 and np.count_nonzero(old[:, 6] == 1393.) == 0
        assert all(new[new[:, 6] == 1393., 0] > 140)
        checks.append(dict(name='元親部分返済後・通常段未消化でも補充_' + mode, **result))

        changed = list(copy.deepcopy(data))
        changed[1]['bid'][350:] += 50.
        changed[1]['ask'][350:] += 50.
        changed[-1][-1, 5] = changed[1]['bid'][600]
        later = run(tuple(changed), cfg)
        np.testing.assert_array_equal(new[new[:, 0] < 350], later[later[:, 0] < 350])
        checks.append(dict(name='未来価格変更の過去不変_' + mode, passed=True))

        mirror = list(copy.deepcopy(data))
        mirror[1]['bid'] = 300. - data[1]['ask']
        mirror[1]['ask'] = 300. - data[1]['bid']
        mirror[3][:, 4:8] *= -1.
        mirror[-1][:, 3] *= -1.
        mirror[-1][:, 5] = 300. - data[-1][:, 5]
        mirrored = run(tuple(mirror), cfg)
        expected = new.copy()
        expected[:, 3] *= -1.
        expected[:, 5] = 300. - new[:, 5]
        np.testing.assert_allclose(mirrored, expected, rtol=0, atol=1e-10)
        account(mirrored, tuple(mirror), cfg)
        checks.append(dict(name='買い売り反射_' + mode, passed=True))

    data = fixture('pullback')
    zero = run(data, config('extreme'))
    assert np.count_nonzero(zero[:, 6] == 1393.) == 0
    checks.append(dict(name='最高値更新必須の対照は押し戻りだけで発火しない', passed=True))

    data = list(fixture('extreme'))
    data[1]['bid'][80:205] = 101.12
    data[1]['ask'][80:205] = 101.22
    data[-1][1, 5] = 101.12
    result = account(run(tuple(data), config()), tuple(data), config())
    assert result['earned'] == 0 and result['cycles'] == 0
    checks.append(dict(name='手数料前の微益を補充信用にしない', **result))

    data = fixture('extreme')
    cfg = config()
    cfg.update(initial=5, increments=[], steps=[])
    result = account(run(data, cfg), data, cfg)
    assert result['earned'] == 0 and result['cycles'] == 0
    checks.append(dict(name='初回玉の利益は補充信用へ入れない', **result))

    data = fixture('extreme', partial=False)
    result = account(run(data, config()), data, config())
    assert result['earned'] == 0 and result['cycles'] == 0
    checks.append(dict(name='含み益だけでは補充しない', **result))

    data = fixture('extreme')
    cfg = config()
    cfg.update(initial=1, increments=[3, 1])
    result = account(run(data, cfg), data, cfg)
    assert result['earned'] > 0 and result['cycles'] == 0
    checks.append(dict(name='初回玉が全滅したら追加しない', **result))

    # ----------------------------------------
    # 二枚追撃の一枚だけを利益返済し、残玉がある段階で再追加する。
    data = list(fixture('pullback', partial=False))
    mark = data[1]['bid']
    mark[80:110] = 104.
    mark[110:140] = 103.4
    mark[140:205] = 102.8
    mark[205:260] = 103.2
    mark[260:300] = 105.5
    mark[300:320] = 104.9
    mark[320:380] = 104.4
    mark[380:405] = 104.7
    mark[405:440] = 106.8
    mark[440:460] = 106.2
    mark[460:520] = 105.7
    mark[520:] = 106.
    data[1]['ask'] = mark + .1
    data[-1][-1, 5] = mark[600]
    data = tuple(data)
    for rounds in (1, 3):
        cfg = config('pullback', rounds)
        cfg.update(exit_activation=[0., 1.5], exit_width=[.5], profit_take=1)
        output = run(data, cfg)
        result = account(output, data, cfg)
        assert result['cycles'] == rounds
        first_recycle = output[output[:, 6] == 1393.][0]
        pre = output[output[:, 0] < first_recycle[0]]
        entered = pre[(pre[:, 8] == 1) & (pre[:, 7] == 1), 4].sum()
        closed = pre[(pre[:, 8] == 1) & (pre[:, 7] == 0), 4].sum()
        assert entered > closed > 0
        checks.append(dict(name=f'部分利確中の補充と回数上限{rounds}', **result))

    # ----------------------------------------
    # 新規発注済みでも、同じ次行に元親の全返済が来たら補充を取り消す。
    data = list(fixture('extreme'))
    output = run(tuple(data), config())
    recycle = output[output[:, 6] == 1393.][0]
    stop = int(recycle[0])
    data[-1][-1, 0] = stop
    data[-1][-1, 1] = stop - 1
    data[-1][-1, 5] = data[1]['bid'][stop]
    data[-1][-1, 9:11] = [data[0][stop], data[0][stop - 1]]
    output = run(tuple(data), config())
    assert np.count_nonzero(output[:, 6] == 1393.) == 0
    account(output, tuple(data), config())
    checks.append(dict(name='元親全返済が同時約定予定の補充に優先', passed=True))

    # ----------------------------------------
    # 補充停止なら旧核と同値。人工気配欠測では次の正常行まで約定を待つ。
    for mode in ('extreme', 'pullback'):
        data = fixture(mode)
        cfg = config(mode, 0)
        np.testing.assert_array_equal(run(data, cfg), run(data, cfg, old=True))
        checks.append(dict(name='再追加回数ゼロは旧核同値_' + mode, passed=True))

    data = list(fixture('extreme'))
    cfg = config()
    original_output = run(tuple(data), cfg)
    recycle = original_output[original_output[:, 6] == 1393.][0]
    fill = int(recycle[0])
    data[1]['quote_valid'][fill:fill + 2] = False
    output = run(tuple(data), cfg)
    changed = output[output[:, 6] == 1393.][0]
    assert changed[0] == fill + 2 and changed[1] == recycle[1]
    account(output, tuple(data), cfg)
    checks.append(dict(name='気配欠測中は補充信用を使用せず次正常行へ待機', passed=True))

    data = list(fixture('extreme'))
    data[3][141:, 8] = data[0][140]
    output = run(tuple(data), config())
    assert np.count_nonzero(output[:, 6] == 1393.) == 0
    checks.append(dict(name='利確以後の新しい相手観測がなければ補充しない', passed=True))

    for cap in (5, 10):
        data = fixture('extreme')
        cfg = config(rounds=3)
        cfg.update(target=cap, increments=[cap - 2, 1], fill_last=False)
        output = run(data, cfg)
        result = account(output, data, cfg)
        assert result['maximum'] == cap and result['cycles'] == 1
        checks.append(dict(name=f'保有上限{cap}枚の枠内で部分返済と補充を実行', **result))

    report = dict(passed=True, checks=checks, checks_count=len(checks), financial_replays=0, API=0,
                  scope='人工生成価格のみ。実市場入力は開いていない。')
    path = HERE / 'recycle_artificial139_v2.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
