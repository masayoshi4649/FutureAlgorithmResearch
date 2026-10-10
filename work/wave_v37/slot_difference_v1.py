"""保存台帳だけから、元枠の空き区間とA0収支差の恒等式を独立に検算する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

import partial_runner as runner
import chart_slot_design as design

HERE = Path(__file__).resolve().parent
BASELINE = 'H019__A0__V000'


def array(ledger: dict, name: str, width: int) -> np.ndarray:
    """機能: 保存された空台帳も列数を維持して復元する。

    引数: ledger(dict)、name(str)、width(int)。返り値: 台帳(ndarray)。
    """
    return np.asarray(ledger[name], dtype=float).reshape(-1, width)


def decompose(ready: dict, actual: dict, reference: dict, factor: float) -> dict:
    """機能: 元の一枚枠ごとの不保有区間を閉じ、全台帳差へ照合する。

    引数: ready/actual/reference(dict)、factor(float)。返り値: 組別・不保有区間・復元脚診断(dict)。
    復元脚損益は空き区間差と別に保存し、差の足し算へ再加算しない。
    """
    base_events = array(reference, 'slot_events', 11)
    events = array(actual, 'slot_events', 11)
    origins = {}; actual_events = {}
    for ev in base_events:
        key = int(ev[2]), int(ev[3]); event = int(ev[4])
        if event == 1:
            assert key not in origins and ev[8] == 1
            origins[key] = dict(side=int(ev[6]), start_row=int(ev[0]), start_price=float(ev[7]))
        elif event in (4, 5):
            assert key in origins and 'end_row' not in origins[key] and ev[8] == 1
            origins[key].update(end_row=int(ev[0]), end_price=float(ev[7]))
        else:
            raise AssertionError('基準A0に数量調整が混入しています')
    assert all('end_row' in value for value in origins.values())
    for ev in events:
        key = int(ev[2]), int(ev[3])
        assert key in origins
        actual_events.setdefault(key, []).append(ev)
    intervals = []; restored_legs = []; campaigns = {}
    actual_slot_pnl = 0.; baseline_slot_pnl = 0.
    for key, origin in sorted(origins.items()):
        campaign, slot = key; d = origin['side']
        start, finish = origin['start_row'], origin['end_row']
        start_price, finish_price = origin['start_price'], origin['end_price']
        base_pnl = d*(finish_price-start_price)*factor
        baseline_slot_pnl += base_pnl
        part = actual_events.get(key, [])
        initial = [ev for ev in part if ev[4] == 1]
        assert len(initial) <= 1
        held = False; leg_price = 0.; leg_row = -1; restored = False; leg_id = -1
        missing = None if initial else dict(begin_row=start, begin_price=start_price, cause='初回から不保有')
        slot_pnl = 0.; slot_delta = 0.

        def finish_gap(row: int, price: float) -> None:
            """機能: 現在の一つの空き区間を閉じ、元保有との差だけを加算する。

            引数: row(int)、price(float)。返り値: なし(None)。
            """
            nonlocal missing, slot_delta
            assert missing is not None and row >= missing['begin_row']
            value = -d*(price-missing['begin_price'])*factor
            intervals.append(dict(campaign=campaign, slot=slot, direction=d, cause=missing['cause'],
                begin_row=missing['begin_row'], end_row=row, begin_price=missing['begin_price'], end_price=price,
                begin_time=float(ready['time_s'][missing['begin_row']]), end_time=float(ready['time_s'][row]),
                delta_yen=value, avoided_yen=max(0., value), missed_yen=max(0., -value)))
            slot_delta += value; missing = None

        for ev in part:
            row, event, qty, reason = int(ev[0]), int(ev[4]), int(ev[8]), int(ev[9])
            price = float(ev[7]); assert start <= row <= finish and int(ev[6]) == d
            if event == 1:
                assert not held and missing is None and row == start and price == start_price and qty == 1
                held = True; leg_price = price; leg_row = row; leg_id = int(ev[5]); restored = False
            elif event == 3:
                assert not held and missing is not None and qty == 1
                finish_gap(row, price)
                held = True; leg_price = price; leg_row = row; leg_id = int(ev[5]); restored = True
            elif event in (2, 4, 5):
                assert bool(qty) == held
                if held:
                    value = d*(price-leg_price)*factor; slot_pnl += value
                    if restored:
                        restored_legs.append(dict(campaign=campaign, slot=slot, leg=leg_id, direction=d,
                            begin_row=leg_row, end_row=row, begin_price=leg_price, end_price=price,
                            pnl_yen=value, exit_reason=reason))
                    held = False
                    if event == 2:
                        assert missing is None
                        missing = dict(begin_row=row, begin_price=price, cause='悪化減量')
                    elif row < finish or price != finish_price:
                        assert event == 5 and reason == 32 and missing is None
                        missing = dict(begin_row=row, begin_price=price, cause='早期予算終了')
                if event == 4:
                    assert row == finish and price == finish_price
                    if missing is not None:
                        finish_gap(row, price)
                elif event == 5 and row == finish:
                    assert price == finish_price
                    if missing is not None:
                        finish_gap(row, price)
            else:
                raise AssertionError('未知の枠イベントです')
        assert not held
        if missing is not None:
            finish_gap(finish, finish_price)
        np.testing.assert_allclose(slot_delta, slot_pnl-base_pnl, rtol=0, atol=1e-6)
        actual_slot_pnl += slot_pnl
        item = campaigns.setdefault(campaign, dict(campaign=campaign, baseline_yen=0., actual_yen=0., delta_yen=0., slots=0))
        item['baseline_yen'] += base_pnl; item['actual_yen'] += slot_pnl; item['delta_yen'] += slot_delta; item['slots'] += 1
    actual_trades = array(actual, 'trades', 11); base_trades = array(reference, 'trades', 11)
    np.testing.assert_allclose(actual_slot_pnl, actual_trades[:, 10].sum()*factor, rtol=0, atol=1e-6)
    np.testing.assert_allclose(baseline_slot_pnl, base_trades[:, 10].sum()*factor, rtol=0, atol=1e-6)
    for campaign, item in campaigns.items():
        np.testing.assert_allclose(item['actual_yen'], actual_trades[actual_trades[:, 0] == campaign, 10].sum()*factor, rtol=0, atol=1e-6)
        np.testing.assert_allclose(item['baseline_yen'], base_trades[base_trades[:, 0] == campaign, 10].sum()*factor, rtol=0, atol=1e-6)
    by_cause = {}
    for cause in design.rules()['分類']:
        part = [v for v in intervals if v['cause'] == cause]
        by_cause[cause] = dict(intervals=len(part), avoided_yen=sum(v['avoided_yen'] for v in part),
                              missed_yen=sum(v['missed_yen'] for v in part), delta_yen=sum(v['delta_yen'] for v in part))
    net_difference = actual_slot_pnl-baseline_slot_pnl
    np.testing.assert_allclose(sum(v['delta_yen'] for v in intervals), net_difference, rtol=0, atol=1e-6)
    restored_ids = {int(v['leg']) for v in restored_legs}
    expected_restored = actual_trades[np.isin(actual_trades[:, 1], list(restored_ids))]
    restored_net = sum(v['pnl_yen'] for v in restored_legs)
    np.testing.assert_allclose(restored_net, expected_restored[:, 10].sum()*factor, rtol=0, atol=1e-6)
    return dict(全枠会計一致=True, 空き区間恒等式一致=True, 元枠数=len(origins), 元組数=len(campaigns),
        baseline_yen=baseline_slot_pnl, actual_yen=actual_slot_pnl, delta_yen=net_difference,
        分類=by_cause, 組別=list(campaigns.values()), 空き区間=intervals, 復元脚=restored_legs,
        復元脚集計=dict(profit_yen=sum(max(v['pnl_yen'], 0.) for v in restored_legs),
                       loss_yen=-sum(min(v['pnl_yen'], 0.) for v in restored_legs), net_yen=restored_net,
                       units=len(restored_legs), 差の式へ加算=False))


def synthetic() -> dict:
    """機能: 人工台帳で減量・復元・退役・予算終了と小数量の恒等式を検査する。

    引数: なし。返り値: 検査結果(dict)。実相場の再生はしない。
    """
    import partial_engine_audit as tests
    paths = [tests.fixture([100,101,102,101,100,101,103,104,109,106,95], (2,), (4,)),
             tests.fixture([100,101,103,100,103,104,100,99,101,104,100,98,95], (2,6,10), (4,8))]
    count = 0
    for args in paths:
        for observed in (False, True):
            baseline = tests.play(args, tests.POLICIES['A0'], observed_fill=observed)
            for policy in (tests.POLICIES[p.split('__')[1]] for p in design.METHODS):
                result = tests.play(args, policy, observed_fill=observed, good_valid=np.ones(len(args[1]), dtype=np.bool_))
                value = decompose(args[0], result, baseline, 1000.)
                assert value['空き区間恒等式一致']; count += 1
    broken = deepcopy(baseline); broken['trades'][0, 10] += 1
    try:
        decompose(args[0], broken, baseline, 1000.)
    except AssertionError:
        pass
    else:
        raise AssertionError('損益を書き換えた台帳を拒否しませんでした')
    return dict(全合格=True, 人工比較数=count, 破損拒否数=1, 新方針実相場再生=False)


def main() -> None:
    """機能: 固定6方式の保存台帳だけを分解し、全組の収支差へ照合する。

    引数: --prepare(bool)。返り値: なし(None)。売買条件の再生・探索は行わない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true'); args = parser.parse_args()
    runner.save(HERE/'slot_difference_synthetic.json', synthetic())
    if args.prepare:
        return
    assert runner.read(HERE/'主再生の完了.json')['全条件数'] == 363
    frozen = design.prepare(); runner.initialize()
    base_path = HERE/'ledgers'/(BASELINE+'.json.gz')
    references = {(v['session'], v['symbol']): v for v in runner.read(base_path)}
    records = []; hashes = {str(base_path.relative_to(HERE)): runner.digest(base_path)}
    for identifier in design.METHODS:
        path = HERE/'ledgers'/(identifier+'.json.gz'); hashes[str(path.relative_to(HERE))] = runner.digest(path)
        for actual in runner.read(path):
            key = actual['session'], actual['symbol']
            value = decompose(runner.INPUTS[key], actual, references[key], actual['config']['point_value'])
            records.append(dict(id=identifier, session=key[0], symbol=key[1], **value))
    assert len(records) == 156
    for name, sha in hashes.items(): assert runner.digest(HERE/name) == sha
    runner.save(HERE/'slot_difference_details.json.gz', records)
    totals = []
    for identifier in design.METHODS:
        for symbol in ('TOPIX', 'NK225'):
            part = [v for v in records if v['id'] == identifier and v['symbol'] == symbol]
            value = dict(id=identifier, symbol=symbol, 元組数=sum(v['元組数'] for v in part),
                         **{k: sum(v[k] for v in part) for k in ('baseline_yen','actual_yen','delta_yen')})
            value['分類'] = {cause: {k: sum(v['分類'][cause][k] for v in part) for k in ('intervals','avoided_yen','missed_yen','delta_yen')}
                             for cause in design.rules()['分類']}
            value['復元脚集計'] = {k: sum(v['復元脚集計'][k] for v in part) for k in ('profit_yen','loss_yen','net_yen','units')}
            totals.append(value)
    runner.save(HERE/'slot_difference_audit.json', dict(全合格=True, 全156入力=True, 全組恒等式一致=True,
        分解=totals, 固定SHA256=runner.digest(HERE/'chart_slot_fixed.json'), 台帳SHA256=hashes,
        明細SHA256=runner.digest(HERE/'slot_difference_details.json.gz'), API取得数=0, 新売買再生=False))


if __name__ == '__main__':
    main()
