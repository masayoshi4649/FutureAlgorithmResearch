"""価格改善と開始基準の追加15条件を、注文から独立再構築して解釈する。"""

import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROUND = WORK/'round2'
ROOT = WORK.parents[1]
SPEC = importlib.util.spec_from_file_location('原因診断90の読取第二段', HERE/'独立選定と原因診断.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def verify_periods(independent, official, ident):
    """
    機能: 独立復元した全親の期間会計を保存された集計と照合する。
    引数: independent/official(dict)、ident(str)。
    返り値: None。不整合なら停止する。
    """
    fields = ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'winning_campaigns', 'losing_campaigns',
              'winning_lots', 'losing_lots', 'lots', 'profit_share', 'average_win', 'average_loss', 'payoff',
              'active_sessions', 'positive_sessions', 'losing_sessions', 'no_trade_sessions',
              'positive_session_rate', 'worst_session')
    for name, rows in independent.items():
        for symbol, row in rows.items():
            reference = official[name][symbol]
            for field in fields:
                if row[field] is None:
                    assert reference[field] is None
                else:
                    assert abs(row[field]-reference[field]) < R.TOLERANCE, (ident, name, symbol, field)
            assert row['best_day'] == reference['best_day']
            for field in ('profit', 'loss', 'net', 'campaigns'):
                assert abs(row['without_best_day'][field]-reference['without_best_day'][field]) < R.TOLERANCE


def main():
    """
    機能: 全15完了後に第一段と追加段の会計、源稼働、残る損失原因を検証する。
    引数: なし。
    返り値: None。reviewの追加資料だけに保存する。
    """
    fixed = R.read(ROUND/'事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert R.digest(ROOT/relative) == expected, relative
    configs = {config['id']: config for config in fixed['条件']}
    assert len(configs) == 15
    assert all((ROUND/'results'/f'{ident}.json').exists() for ident in configs)
    comparison = R.read(WORK/'analysis/比較結果.json')
    assert comparison['条件数'] == 42
    accounts, records, results, periods = {}, {}, {}, {}
    for ident in configs:
        results[ident] = R.read(ROUND/'results'/f'{ident}.json')
        path = ROUND/'ledgers'/f'{ident}.pkl'
        assert R.digest(path) == results[ident]['ledger_SHA256']
        records[ident] = R.read(path)
        accounts[ident] = {key: R.parents_from_orders(key, ledger) for key, ledger in records[ident].items()}
        periods[ident] = {name: {symbol: R.aggregate(accounts[ident], symbol, sessions) for symbol in R.SYMBOLS}
                         for name, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']), ('後14', fixed['後14'])]}
        verify_periods(periods[ident], results[ident]['periods'], ident)
    eligible = {ident: periods[ident] for ident, config in configs.items() if config['improve_limit']}
    assert len(eligible) == 13
    selection = R.choose(eligible)
    assert selection['id'] == comparison['selected']
    assert selection['level'] == comparison['selection_proof']['level']
    assert set(selection['eligible_ids']) == set(comparison['selection_proof']['eligible_ids'])

    # ----------------------------------------
    single_controls = {}
    compared = [index for index in range(17) if index not in (2, 16)]
    for ident in ('J10_Q', 'J8_Q'):
        old = R.read(WORK/'ledgers'/f"{configs[ident]['base_id']}.pkl")
        for key, ledger in records[ident].items():
            assert np.array_equal(ledger['orders'], old[key]['orders'])
            assert np.array_equal(ledger['trades'], old[key]['trades'])
            assert ledger['curve_SHA256'] == old[key]['curve_SHA256']
        single_controls[ident] = dict(全合格=True, 対応第一段=configs[ident]['base_id'], 口座数=60,
                                     説明='QはO06新規価格だけの変更で、O06枠ゼロのJ2単独は全会計が不変。')
    for key, ledger in records['M82_Q'].items():
        for source, single in ((0, 'J8_Q'), (1, 'O2_Q')):
            actual = ledger['orders'][ledger['orders'][:, 3] == source]
            expected = records[single][key]['orders']
            assert np.array_equal(actual[:, compared], expected[:, compared])
            assert ledger['source_curve_column_SHA256'][source] == records[single][key]['source_curve_column_SHA256'][source]
        row = R.totals(accounts['M82_Q'][key])
        left, right = R.totals(accounts['J8_Q'][key]), R.totals(accounts['O2_Q'][key])
        for field in ('profit', 'loss', 'net', 'gross', 'fees', 'campaigns', 'lots'):
            assert abs(row[field]-left[field]-right[field]) < R.TOLERANCE
    single_controls['M82_Q'] = dict(全合格=True, 源口座数=120, 注文及び源別時価指紋同量一致=True,
                                   利益損失を日別源別で相殺しない=True)

    # ----------------------------------------
    differences = {}
    for ident in ('G82_C_Q', 'G82_C_A', 'G82_C_QA', 'G82_E_QA', 'G82_X_QA'):
        baseline_id = 'M82_Q' if configs[ident]['improve_limit'] else 'M82'
        baseline = accounts.get(baseline_id)
        if baseline is None:
            old = R.read(WORK/'ledgers'/f'{baseline_id}.pkl')
            baseline = {key: R.parents_from_orders(key, ledger) for key, ledger in old.items()}
        delta = {key: R.difference(parents, baseline[key]) for key, parents in accounts[ident].items()}
        differences[ident] = {name: {symbol: {field: sum(item[field] for key, item in delta.items()
                                     if key[0] in sessions and key[1] == symbol)
                                     for field in next(iter(delta.values()))}
                              for symbol in R.SYMBOLS}
                             for name, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']), ('後14', fixed['後14'])]}
        for name, rows in differences[ident].items():
            for symbol, row in rows.items():
                for field, value in row.items():
                    assert abs(value-comparison['differences'][ident][name][symbol][field]) < R.TOLERANCE

    # ----------------------------------------
    scaled = {}
    preserved = [index for index in range(17) if index not in (2, 5, 9, 16)]
    for symbol in R.SYMBOLS:
        count, fees_extra = 0, 0.
        for key in accounts['D_C_QA']:
            if key[1] != symbol:
                continue
            full, small = records['D_C_QA'][key]['orders'], records['G82_C_QA'][key]['orders']
            assert np.array_equal(full[:, preserved], small[:, preserved])
            assert np.array_equal(full[:, 5], small[:, 5]*5)
            fees_extra += float(full[:, 9].sum()-small[:, 9].sum()*5)
            count += len(full)
        full = periods['D_C_QA']['全30'][symbol]
        small = periods['G82_C_QA']['全30'][symbol]
        assert abs(full['net']-5*small['net']+fees_extra) < R.TOLERANCE
        scaled[symbol] = dict(全合格=True, 比較注文数=count, 数量比=5,
            注文価格時刻理由同一=True, 倍率差を除く追加手数料=fees_extra,
            全枠純損益=full['net'], 固定小枠純損益=small['net'],
            説明='J2が両条件で稼働しない場合、全枠と固定小枠は同じO06経路の数量差であり、配分の高度な違いを示す結果ではない。')

    # ----------------------------------------
    prices = R.read(ROOT/'work/wave_v83/prepared/inputs.pkl')
    grids = R.read(ROOT/'work/wave_v77/inputs/grids_delay1.pkl')
    entries = R.read(ROOT/'work/wave_v77/prepared/signals_delay1.pkl')
    states = {session: R.state(grids[session], entries[session], fixed['条件'][0]) for session in fixed['全30']}
    timelines = {key: R.timeline(record, states[key[0]]) for key, record in prices.items()}
    initial_stop, source_activity = {}, {}
    for ident, by_key in accounts.items():
        initial_stop[ident], source_activity[ident] = {}, {}
        for symbol in R.SYMBOLS:
            counters = dict(range_parents=0, price_outside_quote=0, price_stop_domain_at_entry=0,
                            outside_and_stop=0, stopped_on_first_next_row=0,
                            outside_and_first_row_stop=0)
            selected, examples = [], []
            for key, parents in by_key.items():
                if key[1] != symbol:
                    continue
                record = prices[key]
                for parent in parents:
                    if parent['source'] != 1:
                        continue
                    selected.append(parent)
                    row, side = parent['entry_row'], parent['side']
                    bid, ask, current_price = record['bid'][row], record['ask'][row], record['price'][row]
                    if configs[ident]['improve_limit']:
                        assert parent['entry_price'] == (ask if side==1 else bid)
                    outside = current_price < bid-1e-9 or current_price > ask+1e-9
                    stop_domain = side*(current_price-parent['entry_price']) <= -8*record['tick']
                    next_stop = parent['exit_decision_row'] == row+1 and parent['exit_reason'] == 6
                    counters['range_parents'] += 1
                    counters['price_outside_quote'] += int(outside)
                    counters['price_stop_domain_at_entry'] += int(stop_domain)
                    counters['outside_and_stop'] += int(outside and stop_domain)
                    counters['stopped_on_first_next_row'] += int(next_stop)
                    counters['outside_and_first_row_stop'] += int(outside and next_stop)
                    if stop_domain or next_stop:
                        example = dict(session=key[0], parent_id=parent['parent_id'], side=side,
                            entry_time=R.stamp(parent['entry_time']), entry_price=parent['entry_price'],
                            current_price=float(current_price), bid=float(bid), ask=float(ask),
                            actual_parent_net=parent['net'], outside=bool(outside),
                            stop_domain_at_entry=bool(stop_domain), first_next_row_stop=bool(next_stop),
                            exit_decision_time=R.stamp(parent['exit_decision_time']), exit_time=R.stamp(parent['exit_time']))
                        examples.append(example)
            initial_stop[ident][symbol] = dict(counts=counters, range_totals=R.totals(selected),
                examples=sorted(examples, key=lambda example: example['actual_parent_net'])[:5])
            source_activity[ident][symbol] = {}
            for source, name in enumerate(('J2', 'O06')):
                chosen = [parent for key, parents in by_key.items() if key[1]==symbol for parent in parents if parent['source']==source]
                active = sum(any(parent['source']==source for parent in parents) for key, parents in by_key.items() if key[1]==symbol)
                source_activity[ident][symbol][name] = dict(R.totals(chosen), active_sessions=active,
                    maximum_entry_quantity=max((parent['quantity'] for parent in chosen), default=0))

    # ----------------------------------------
    worst = {}
    representatives = list(dict.fromkeys((fixed['主'], 'G82_C_QA', 'M82_Q', selection['id'])))
    for ident in representatives:
        worst[ident] = {}
        for symbol in R.SYMBOLS:
            keys = sorted((key for key in accounts[ident] if key[1]==symbol),
                          key=lambda key: (sum(parent['net'] for parent in accounts[ident][key]), key[0]))[:3]
            cases = []
            for key in keys:
                parent = min(accounts[ident][key], key=lambda parent: parent['net'], default=None)
                if parent is None:
                    cases.append(dict(session=key[0], symbol=symbol, no_trade=True))
                else:
                    case = R.diagnosis(key, parent, records[ident][key], prices[key], timelines[key], states[key[0]])
                    case['session_totals'] = R.totals(accounts[ident][key])
                    cases.append(case)
            worst[ident][symbol] = cases
    both80 = [ident for ident in configs if all(periods[ident]['全30'][symbol]['profit_share'] is not None
              and periods[ident]['全30'][symbol]['profit_share'] >= .8 and periods[ident]['全30'][symbol]['net'] > 0
              and periods[ident]['全30'][symbol]['campaigns'] >= 20 and periods[ident]['全30'][symbol]['active_sessions'] >= 8
              for symbol in R.SYMBOLS)]
    all_positive = [ident for ident in configs if all(periods[ident]['全30'][symbol]['all_sessions_profitable'] for symbol in R.SYMBOLS)]
    assert set(both80) == {ident for ident in comparison['both80'] if ident in configs}
    assert set(all_positive) == {ident for ident in comparison['all_sessions_positive'] if ident in configs}
    proof = dict(全合格=True, 追加条件数=15, 独立参考選定=selection, 主=fixed['主'],
        会計口座数=900, 独立復元親数=sum(len(parents) for rows in accounts.values() for parents in rows.values()),
        対照一致=single_controls, G82差額分解=differences,
        主と固定小枠の量差だけの検査=scaled, 源別実稼働=source_activity,
        新規時価格と気配の不一致及び即損切り=initial_stop,
        最悪3セッションと最大損失親=worst, 独立期間会計=periods,
        両商品金額80=both80, 全30両商品全黒字=all_positive,
        注意=['Qは約定仮定の修正であり予測性能の向上ではない。Aは待機していた間の基準価格を更新する戦略変更。',
              '源別親の利益と損失を別々に足し、日別相殺から金額利益率を作らない。',
              '全原板時価の再構築は別の全会計監査で確認する。ここでは注文・親会計と源別曲線指紋の非干渉を独立確認。',
              '新規直後のCurrentPriceと気配の不一致は事後診断であり、注文条件へ遡って使わない。',
              '全30場は既知。無取引を勝ちに含めず活動場・親数・最大利益日除外を別に評価する。'],
        凍結SHA一致=True, 全期間既知=True, API取得=0, 実注文=0, 凍結変更=0,
        SHA256={str(path.relative_to(ROOT)): R.digest(path) for path in
            [Path(__file__), HERE/'独立選定と原因診断.py', ROUND/'事前固定.json', WORK/'analysis/比較結果.json',
             *[ROUND/'results'/f'{ident}.json' for ident in configs]]})
    target = HERE/'追加15条件の独立会計と源稼働及び残る損失原因.json'
    target.write_text(json.dumps(R.clean(proof), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(主=fixed['主'], 独立参考選定=selection['id'], 口座=900,
                         独立親=proof['独立復元親数'], 両80=both80, 全日黒字=all_positive,
                         主源稼働=source_activity[fixed['主']]), ensure_ascii=False))


if __name__ == '__main__':
    main()
