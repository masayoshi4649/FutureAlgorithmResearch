"""数量配分の順位・同時保有上限・再入場・固定型の比例性を独立検算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

OUT = Path(__file__).resolve().parent
WORK = OUT.parent.parent
METHODS = ['M3_逆_A03', 'M3_逆_A00', 'M2_逆_A00', 'M2_逆_A01']
CAPS = {'TOPIX': 10, 'NK225': 20}
MULT = {'TOPIX': 1000., 'NK225': 10.}
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
CHECKS = 0


def read(name: str) -> object:
    """機能: 保存した日本語JSONを読む。

    引数: name (str)。返り値: JSON内容 (object)。
    """
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def compare(actual: object, expected: object, label: str) -> None:
    """機能: 独立計算値と保存値が一致するか検査する。

    引数: actual/expected (object)、label (str)。返り値: なし (None)。
    """
    global CHECKS
    if expected is None or actual is None or isinstance(expected, (str, bool)):
        assert actual == expected, (label, actual, expected)
    else:
        assert np.isclose(actual, expected, rtol=1e-10, atol=1e-5), (label, actual, expected)
    CHECKS += 1


def ratio(a: float, b: float) -> float | None:
    """機能: 正の分母だけで比率を求める。

    引数: a/b (float)。返り値: 比率または欠損 (float|None)。
    """
    return float(a/b) if b > 1e-8 else None


def profit_fields(profit: np.ndarray, qty: np.ndarray) -> dict:
    """機能: 約定価格差から利益・損失・累計数量を求める。

    引数: profit/qty (ndarray)。返り値: 損益指標 (dict)。
    """
    positive, negative = profit > 1e-6, profit < -1e-6
    p, l = float(profit[positive].sum()), float(-profit[negative].sum())
    w, d, z = [int(qty[mask].sum()) for mask in [positive, negative, ~(positive | negative)]]
    return dict(gross_profit_yen=p, gross_loss_yen=l, net_yen=p-l,
                profit_units=w, loss_units=d, zero_units=z, unit_balance=w-d, closed_units=w+d+z,
                money_ratio=ratio(p,l), unit_ratio=ratio(w,d), avg_profit_per_unit=ratio(p,w),
                avg_loss_per_unit=ratio(l,d), unit_payoff=ratio(p/w,l/d) if w and d else None)


def reconstruct(block: dict, ready: dict, symbol: str) -> tuple[dict, np.ndarray, dict]:
    """機能: 表示配分の元約定から全原本行の在庫・時価と再入場を再構成する。

    引数: block/ready (dict)、symbol (str)。返り値: 集計、資産曲線、検査件数 (tuple)。
    """
    trades, cycles, config = block['trades'], block['cycles'], block['config']
    assert trades.shape[1] == 11 and cycles.shape[1] == 10
    qty, side = trades[:,3], trades[:,2]
    entries, exits = trades[:,6].astype(int), trades[:,7].astype(int)
    assert np.all(qty >= 1) and np.equal(qty, np.floor(qty)).all()
    assert np.all(entries < exits) and len(np.unique(trades[:,1])) == len(trades)
    assert np.isin(side, [-1,1]).all() and np.all(trades[:,8] == 0)
    assert not np.any(np.isin(trades[:,9], [3,4,5,6,7]))
    prices, times, count = ready['last'], ready['time_s'], len(ready['last'])
    point_profit = qty*side*(trades[:,5]-trades[:,4])
    np.testing.assert_allclose(point_profit, trades[:,10], atol=1e-8, rtol=1e-12)
    out = profit_fields(point_profit*MULT[symbol], qty)
    signed = qty*side
    cash_delta = np.bincount(entries, weights=-signed*trades[:,4], minlength=count)
    cash_delta += np.bincount(exits, weights=signed*trades[:,5], minlength=count)
    inventory = []
    for direction in [1,-1]:
        mask = side == direction
        delta = np.bincount(entries[mask], weights=qty[mask], minlength=count)
        delta -= np.bincount(exits[mask], weights=qty[mask], minlength=count)
        position = np.cumsum(delta)
        assert position.min(initial=0) >= 0 and position.max(initial=0) <= CAPS[symbol]
        assert position[-1] == 0
        inventory.append(position)
    long, short = inventory
    assert np.all((long == 0) | (short == 0))
    gross, net = long+short, long-short
    equity = (np.cumsum(cash_delta) + net*prices)*MULT[symbol]
    peaks = np.maximum.accumulate(np.r_[0., equity])[1:]
    compare(equity[-1], out['net_yen'], '区間末の現金と純損益')
    gains, risks = [], []
    previous_exit, reentry = -1, 0
    for campaign in cycles:
        mask = trades[:,0] == campaign[0]
        first, last = int(entries[mask].min()), int(exits[mask].max())
        compare(first, campaign[1], '組開始行')
        compare(last, campaign[2], '組終了行')
        gain = float(point_profit[mask].sum())
        compare(gain, campaign[3], '組の全脚損益')
        risk = config['initial_qty']*config['stop_atr']*campaign[5]
        compare(risk, campaign[4], '組の初期損失予算')
        compare(gross[first:last+1].max(initial=0), campaign[6], '組の最大総保有')
        compare(abs(net[first:last+1]).max(initial=0), campaign[7], '組の最大純保有')
        if previous_exit >= 0:
            assert first > previous_exit and gross[previous_exit] == 0
            assert times[first]-times[previous_exit] >= 300-1e-8
            reentry += 1
        previous_exit = last
        gains.append(gain*MULT[symbol])
        risks.append(risk*MULT[symbol])
    gains, risks = np.asarray(gains), np.asarray(risks)
    compare(gains.sum(), out['net_yen'], '組損益合計')
    orders = block['orders']
    assert np.all(orders[:,1] < orders[:,0]), '注文条件は約定前に決める'
    for order in orders[orders[:,7] == 1]:
        row = int(order[0])
        if int(order[6]) == 20:
            compare(order[4], config['initial_qty'], '初回枚数')
        elif int(order[6]) == 22:
            before = gross[row]-order[4]
            compare(order[4], min(config['add_qty'], CAPS[symbol]-before), '追加は空き枠まで')
        else:
            raise AssertionError(('未知の新規理由', order))
    tick = .25 if symbol == 'TOPIX' else 5.
    np.testing.assert_allclose(trades[:,4:6]/tick, np.round(trades[:,4:6]/tick), rtol=1e-12, atol=1e-8)
    out.update(drawdown_yen=float((peaks-equity).max(initial=0)), min_equity_yen=float(equity.min(initial=0)),
               max_equity_yen=float(equity.max(initial=0)), max_long=int(long.max(initial=0)),
               max_short=int(short.max(initial=0)), max_gross=int(gross.max(initial=0)), max_net=int(abs(net).max(initial=0)),
               cycles=len(cycles), cycle_wins=int((gains>1e-6).sum()), cycle_losses=int((gains < -1e-6).sum()),
               cycle_profit_yen=float(gains[gains>1e-6].sum()), cycle_loss_yen=float(-gains[gains < -1e-6].sum()),
               net_r=float(np.sum(gains/risks)), order_count=len(orders), reversals=0,
               cover_profit_yen=0., cover_loss_yen=0.)
    diagnostic = dict(全行再構成数=count, 返済行数=len(trades), 返済後の再入場数=reentry,
                      累計返済枚数が同時保有上限超=out['closed_units'] > CAPS[symbol],
                      risk=risks.tolist())
    return out, equity, diagnostic


def aggregate(rows: list[dict]) -> dict:
    """機能: 保存区間の独立合算で週指標と最大下落を求める。

    引数: rows (list[dict])。返り値: 週指標 (dict)。
    """
    additive = ['gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units',
                'unit_balance','closed_units','cycles','cycle_wins','cycle_losses','cycle_profit_yen',
                'cycle_loss_yen','net_r','order_count','reversals','cover_profit_yen','cover_loss_yen']
    result = {key: sum(row[key] for row in rows) for key in additive}
    p,l,w,d = [result[key] for key in ['gross_profit_yen','gross_loss_yen','profit_units','loss_units']]
    result.update(money_ratio=ratio(p,l), unit_ratio=ratio(w,d), avg_profit_per_unit=ratio(p,w),
                  avg_loss_per_unit=ratio(l,d), unit_payoff=ratio(p/w,l/d) if w and d else None,
                  positive_sessions=sum(r['net_yen']>0 for r in rows), active_sessions=sum(r['cycles']>0 for r in rows),
                  session_count=len(rows))
    cp,cl,cw,cd = [result[key] for key in ['cycle_profit_yen','cycle_loss_yen','cycle_wins','cycle_losses']]
    result.update(cycle_pf=ratio(cp,cl), cycle_payoff=ratio(cp/cw,cl/cd) if cw and cd else None)
    offsets = np.r_[0., np.cumsum([r['net_yen'] for r in rows])[:-1]]
    highs = [offset+r['max_equity_yen'] for offset,r in zip(offsets,rows)]
    lows = [offset+r['min_equity_yen'] for offset,r in zip(offsets,rows)]
    losses = [max([0.]+highs[:j])-low for j,low in enumerate(lows)]
    result['drawdown_yen'] = max([0.] + losses + [r['drawdown_yen'] for r in rows])
    for key in ['max_long','max_short','max_gross','max_net']:
        result[key] = max(r[key] for r in rows)
    return result


def check_dict(actual: dict, expected: dict, label: str) -> None:
    """機能: 独立指標の全項目を集計に照合する。

    引数: actual/expected (dict)、label (str)。返り値: なし (None)。
    """
    for field, value in expected.items():
        compare(actual[field], value, f'{label}:{field}')


def main() -> None:
    """機能: 全配分の順位と表示台帳の会計・上限・再入場・固定比例性を監査する。

    引数: なし。返り値: なし (None)。売買条件の変更や追加探索はしない。
    """
    started = time.time()
    complete = read('探索完了記録.json')
    assert complete['合格']
    weekly, sessions = read('全配分の週合計.json'), read('全配分のセッション集計.json')
    report, selections = read('allocation_report_data.json'), read('配分選択.json')
    assert len(weekly) == 327 and len(sessions) == 3270
    by_week = {r['allocation_id']: r for r in weekly}
    by_session = {(r['allocation_id'],r['session'],r['symbol']): r for r in sessions}
    grouped = {aid: [by_session[(aid,s,r['symbol'])] for s in SESSIONS] for aid,r in by_week.items()}
    ranking_rows, qualification = [], {}
    for method in METHODS:
        for symbol, cap in CAPS.items():
            actual = [r for r in weekly if r['method_id'] == method and r['symbol'] == symbol]
            expected = ([(i,a) for i in range(1,cap) for a in range(1,cap-i+1)]+[(cap,0)]
                        if method.endswith('A03') else [(i,0) for i in range(1,cap+1)])
            assert sorted((r['initial_qty'],r['add_qty']) for r in actual) == sorted(expected)
            ranks = []
            for r in actual:
                derived = aggregate(grouped[r['allocation_id']])
                check_dict(r, derived, r['allocation_id'])
                removed = derived['net_yen']-max(row['net_yen'] for row in grouped[r['allocation_id']])
                eligible = (round(derived['net_yen'],6)>0 and round(derived['money_ratio'] or 0.,10)>1
                            and round(derived['unit_payoff'] or 0.,10)>1 and derived['positive_sessions'] >= 6
                            and round(removed,6)>0)
                score = min(derived['money_ratio'] or 0., derived['unit_payoff'] or 0.)
                recovery = derived['net_yen']/derived['drawdown_yen'] if derived['drawdown_yen'] else 0.
                check_dict(r['selection'], dict(eligible=eligible,score=score,recovery=recovery,
                                               best_session_removed_net=removed), '選択資格')
                qualification[r['allocation_id']] = eligible
                if eligible:
                    ranks.append((-round(score,10),-round(recovery,10),r['initial_qty'],r['add_qty'],r['allocation_id']))
            chosen = min(ranks)[-1] if ranks else None
            greatest = min(actual, key=lambda r:(-round(r['net_yen'],6),r['initial_qty'],r['add_qty']))['allocation_id']
            saved = next(s for s in selections if s['method_id']==method and s['symbol']==symbol)
            check_dict(saved, dict(selected_id=chosen,max_net_id=greatest,candidate_count=len(actual),
                                  eligible_count=len(ranks)), '配分順位')
            variant = next(m for m in report['methods'] if m['id']==method)['variants'][symbol]
            compare(variant['selected']['allocation_id'], chosen or greatest, '表示する代表')
            compare(variant['max_net']['allocation_id'], greatest, '表示する最大収支')
            compare(variant['selected_is_reference'], chosen is None, '該当なしの表示')
            for key in ['selected','max_net']:
                item = variant[key]
                expected_row = by_week[item['allocation_id']]
                assert item['week'] == {k:v for k,v in expected_row.items() if k not in ['selection','initial_risk']}
                assert item['sessions'] == grouped[item['allocation_id']]
                assert item['selection'] == expected_row['selection']
                compare(item['config']['initial_qty'],expected_row['initial_qty'],'表示初回枚数')
                compare(item['config']['add_qty'],expected_row['add_qty'],'表示追加枚数')
                compare(item['config']['position_cap'],cap,'表示同時保有上限')
            ranking_rows.append(dict(method_id=method,symbol=symbol,selected=chosen,max_net=greatest,
                                     eligible_count=len(ranks),candidate_count=len(actual)))
    # ----------------------------------------
    # 表示配分だけ全原本行の在庫・時価を独立再構成する。
    raw = pickle.loads((OUT / '表示配分の生台帳.pkl').read_bytes())
    inputs = {}
    for stage in ['development','holdout']:
        inputs.update(pickle.loads((WORK / 'wave_v16' / f'入力_{stage}.pkl').read_bytes()))
    raw_rows, raw_closed, reentries, repeated_cells = 0,0,0,0
    rebuilt, raw_risks = {}, {}
    for key, block in raw.items():
        aid, session, symbol = key
        result, equity, extra = reconstruct(block, inputs[(session,symbol)], symbol)
        check_dict(by_session[key], result, f'原本再構成:{key}')
        rebuilt[key] = result
        raw_risks.setdefault(aid,[]).extend(extra['risk'])
        raw_rows += extra['全行再構成数']
        raw_closed += extra['返済行数']
        reentries += extra['返済後の再入場数']
        repeated_cells += int(extra['累計返済枚数が同時保有上限超'])
    for aid, risks in raw_risks.items():
        symbol = by_week[aid]['symbol']
        rows = [rebuilt[(aid,s,symbol)] for s in SESSIONS]
        check_dict(by_week[aid], aggregate(rows), f'原本週:{aid}')
        derived_risk = dict(count=len(risks),min_yen=min(risks),median_yen=float(np.median(risks)),
                            max_yen=max(risks),mean_yen=float(np.mean(risks)))
        check_dict(by_week[aid]['initial_risk'],derived_risk,f'初期予算:{aid}')
        for method in report['methods']:
            for variant in method['variants'].values():
                for key in ['selected','max_net']:
                    if variant[key]['allocation_id'] == aid:
                        check_dict(variant[key]['risk'],derived_risk,f'表示初期予算:{aid}')
    # ----------------------------------------
    # 固定型90配分すべての約定経路と一枚あたり会計を直接比較する。
    fixed = pickle.loads((OUT / '固定型全配分の生台帳.pkl').read_bytes())
    assert len(fixed) == 900
    fixed_prices, fixed_sessions = 0, 0
    fixed_invariants = ['money_ratio','unit_ratio','unit_payoff','avg_profit_per_unit','avg_loss_per_unit',
                        'cycles','cycle_wins','cycle_losses','net_r','order_count','reversals']
    fixed_linear = ['gross_profit_yen','gross_loss_yen','net_yen','drawdown_yen','min_equity_yen',
                    'max_equity_yen','profit_units','loss_units','zero_units','unit_balance','closed_units',
                    'max_long','max_short','max_gross','max_net','cycle_profit_yen','cycle_loss_yen']
    for method in METHODS[1:]:
        for symbol,cap in CAPS.items():
            for session in SESSIONS:
                base_id = f'{method}__{symbol}__I01_A00'
                base = fixed[(base_id,session,symbol)]
                for initial in range(1,cap+1):
                    aid = f'{method}__{symbol}__I{initial:02d}_A00'
                    block = fixed[(aid,session,symbol)]
                    a,b = block['trades'],base['trades']
                    assert a.shape == b.shape
                    np.testing.assert_array_equal(a[:,[0,1,2,4,5,6,7,8,9]],b[:,[0,1,2,4,5,6,7,8,9]])
                    np.testing.assert_allclose(a[:,[3,10]],b[:,[3,10]]*initial,atol=1e-8,rtol=1e-12)
                    current, baseline = by_session[(aid,session,symbol)], by_session[(base_id,session,symbol)]
                    for field in fixed_invariants:
                        compare(current[field],baseline[field],f'固定型不変:{aid}:{field}')
                    for field in fixed_linear:
                        compare(current[field],baseline[field]*initial,f'固定型比例:{aid}:{field}')
                    fixed_prices += len(a)
                    fixed_sessions += 1
    sources = read('探索前の固定記録.json')['ソースSHA256']
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value for path,value in sources.items())
    output = dict(合格=True, 全配分数=len(weekly), 全区間集計数=len(sessions), 順位一致数=len(ranking_rows),
                  数値等照合数=CHECKS, 表示生台帳セル数=len(raw), 表示配分数=len(raw_risks),
                  独立再構成原本行数=raw_rows, 独立返済行数=raw_closed,
                  全同時保有上限内=True, 全セッション末在庫ゼロ=True, 次行以降注文=True,
                  返済後再入場数=reentries, 累計返済枚数が同時保有上限を超える表示セル数=repeated_cells,
                  固定型全配分数=90, 固定型経路一致セル数=fixed_sessions, 固定型返済経路一致行数=fixed_prices,
                  固定型結論='固定型の全枚数で約定価格・時刻・方向・理由は完全一致。損益・下落額は枚数比例、損益比・一枚平均・件数は不変。小数10桁丸め後の同点規則で最小1枚を代表とし、丸め差による偽の最適化なし。',
                  入力原本不変=True, 追加条件探索数=0, 現在API取得数=0,
                  表示データSHA256=hashlib.sha256((OUT/'allocation_report_data.json').read_bytes()).hexdigest(),
                  順位=ranking_rows, 経過秒=time.time()-started)
    (OUT/'audit_allocation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
