"""固定96仕様と採用/交換判定を人工資料だけで検査する。"""

from copy import deepcopy
import json
from pathlib import Path

import scheduler_assessment as assessment
import scheduler_design as design


def synthetic() -> tuple[list[dict], dict, dict]:
    """機能: 全192の人工集計・26明細・8波を作る。

    引数: なし。返り値: summaries/details/waves (tuple)。実相場損益は使用しない。
    """
    summaries, details, waves = [], {}, {}
    for spec in design.catalog():
        dynamic = spec['dynamic_trail_atr']
        net = 100. + 10. * dynamic
        rows = [{'id': spec['id'], 'session': session, 'symbol': symbol, 'net_yen': net,
                 'opening_orders': 1, 'retracements': [{'final_yen': net}]}
                for session in design.SESSIONS for symbol in assessment.SYMBOLS]
        details[spec['id']] = rows
        summary = {'id': spec['id'], 'spec': spec}
        for period, count in (('all_symbols', 13), ('symbols', 7)):
            gp, gl = (net + 100) * count, 100. * count
            summary[period] = {symbol: {'gross_profit_yen': gp, 'gross_loss_yen': gl, 'net_yen': net * count,
                'drawdown_yen': 200. - 20. * dynamic, 'profit_units': 5 * count, 'loss_units': 5 * count,
                'zero_units': 0, 'cycles': count, 'opening_orders': count, 'long_unit_minutes': 1000., 'short_unit_minutes': 500.,
                'money_ratio': gp / gl, 'average_unit_payoff': gp / gl, 'active_sessions': count,
                'retracement': {'all': {'cycles': count, 'sum_yen': 10. * count, 'sum_r': float(count), 'mean_r': 1., 'median_r': 1., 'mean_yen': 10., 'median_yen': 10.},
                                'positive_peak': {'cycles': count}, 'holding_minutes': 100.}}
                for symbol in assessment.SYMBOLS}
        summaries.append(summary)
        waves[spec['id']] = [{'method': spec['id'], 'wave': wave['id'], 'symbol': symbol,
            'session': wave['session'], '開始': wave['start'], '終了': wave['end'], '波方向': wave['side'],
            '正方向ネット保有分': 30., '正方向ネット20分目安達成': True}
            for wave in design.waves() for symbol in assessment.SYMBOLS]
    return summaries, details, waves


def main() -> None:
    """機能: 全件・境界・欠損拒否を検算し、新損益前の証跡を保存する。

    引数: なし。返り値: なし (None)。
    """
    specs = design.catalog()
    assert len(specs) == 192 and sum(r['role'] == 'primary' for r in specs) == 48
    assert {r['signal_id'] for r in specs} == set(design.SIGNAL_IDS)
    assert {r['id'] for r in specs if r['adoption_target']} == {'H019__AT__SHADOW__V000'}
    assert all(r['entry_delay_seconds'] == 0 and r['observed_fill'] is False for r in specs if r['variant_id'] == 'L300')
    assert len(design.SESSIONS) == 13 and len(design.SESSIONS[6:]) == 7
    summaries, details, waves = synthetic()
    result = assessment.assess(summaries, details, waves)
    assert result['主条件採用目安ID'] == ['H019__AT__SHADOW__V000'] and result['全対応比較数'] == 384
    assert all(sum(b.values()) == 12 for v in result['全12の関係件数'].values() for b in v.values())
    cases = [{'検査': '全192人工資料・採用H019限定・診断昇格なし', '一致': True}]
    baseline = deepcopy(summaries[0])
    for label, net_delta, dd_delta, expected in (
        ('完全同値', 0., 0., '同値'), ('丸め差のみ', 1e-8, -1e-8, '同値'),
        ('収支だけ増', 10., 0., '同時改善'), ('DDだけ減', 0., -10., '同時改善'),
        ('利益を減らしてDDを抑制', -10., -10., 'リスク収益交換'),
        ('利益もDDも増', 10., 10., '収益リスク交換'), ('元の方式に支配される', -10., 10., '旧案が支配')):
        changed = deepcopy(baseline)
        for period in assessment.PERIODS:
            for symbol in assessment.SYMBOLS:
                changed[period][symbol]['net_yen'] += net_delta
                changed[period][symbol]['drawdown_yen'] += dd_delta
        assert assessment.relation(changed, baseline) == expected
        cases.append({'検査': label, '一致': True})
    changed = deepcopy(baseline)
    changed['symbols']['TOPIX']['net_yen'] += 10
    changed['all_symbols']['NK225']['net_yen'] -= 10
    assert assessment.relation(changed, baseline) == '混在'
    cases.append({'検査': '期間と銘柄の良い側だけ選ばない', '一致': True})
    changed = deepcopy(summaries)
    normal = next(row for row in changed if row['id'] == 'H019__AT__NORMAL__V000')
    for period in assessment.PERIODS:
        for symbol in assessment.SYMBOLS:
            normal[period][symbol]['drawdown_yen'] = 1.
    compared = assessment.assess(changed, details, waves)
    assert compared['主条件採用目安ID'] == ['H019__AT__SHADOW__V000']
    assert compared['H019主判定']['At通常比較']['収支DD関係'] == '旧案が支配'
    cases.append({'検査': 'At通常との機構効果を旧A0に対する採用基準へ後付けしない', '一致': True})
    assert len(result['全診断の主条件差']) == 144
    assert all(row['base_id'].endswith('__V000') for row in result['全診断の主条件差'])
    cases.append({'検査': '全144診断の自方式原型差を保存し診断最良を採用しない', '一致': True})
    lost = deepcopy(waves)
    lost['H019__AT__SHADOW__V000'][0]['正方向ネット保有分'] = 19.99
    lost['H019__AT__SHADOW__V000'][0]['正方向ネット20分目安達成'] = False
    assert assessment.assess(summaries, details, lost)['主条件採用目安ID'] == []
    lost['H019__AT__SHADOW__V000'][0]['正方向ネット保有分'] = 20.
    lost['H019__AT__SHADOW__V000'][0]['正方向ネット20分目安達成'] = True
    assert assessment.assess(summaries, details, lost)['主条件採用目安ID'] == ['H019__AT__SHADOW__V000']
    cases.append({'検査': '指定波20分境界と失敗時に別入口へ差替禁止', '一致': True})
    values = deepcopy(baseline['symbols']['TOPIX'])
    rows = deepcopy([r for r in details[baseline['id']] if r['symbol'] == 'TOPIX' and r['session'] in design.SESSIONS[6:]])
    rows[0]['retracements'][0]['final_yen'] = values['net_yen'] + 1
    assert not assessment.basic_checks(values, rows, True)['基礎確認']
    rows[0]['retracements'][0]['final_yen'] = values['net_yen']
    assert assessment.basic_checks(values, rows, True)['基礎確認']
    cases.append({'検査': '最大勝ち組除外の非負境界', '一致': True})
    values['profit_units'] *= 3
    values['average_unit_payoff'] /= 3
    assert not assessment.basic_checks(values, rows, True)['検査']['勝ち負け1枚平均比1超']
    cases.append({'検査': '総PFだけ良く平均枚損益が悪い場合を区別', '一致': True})
    values.update(gross_loss_yen=0., money_ratio=None, average_unit_payoff=None)
    assert not assessment.basic_checks(values, rows, True)['基礎確認']
    cases.append({'検査': '損失ゼロで未定義の比を合格にしない', '一致': True})

    def reject(label, function) -> None:
        """機能: 人工破損が拒否されることを確認する。

        引数: label (str)、function (callable)。返り値: なし (None)。
        """
        try:
            function()
        except (AssertionError, KeyError, TypeError, ValueError):
            cases.append({'検査': label, '一致': True})
        else:
            raise AssertionError(label)

    reject('1候補欠落を拒否', lambda: assessment.assess(summaries[:-1], details, waves))
    duplicate = deepcopy(summaries); duplicate[-1] = duplicate[0]
    reject('同一ID重複を拒否', lambda: assessment.assess(duplicate, details, waves))
    damaged = deepcopy(details); damaged[baseline['id']][1] = damaged[baseline['id']][0]
    reject('26区間の重複を拒否', lambda: assessment.assess(summaries, damaged, waves))
    damaged = deepcopy(waves); damaged['H019__AT__SHADOW__V000'][0]['開始'] = '2099-01-01'
    reject('指定波の時刻変更を拒否', lambda: assessment.assess(summaries, details, damaged))
    damaged = deepcopy(waves); damaged['H019__A0__SHADOW__O000'][0]['method'] = '別候補'
    reject('採用外条件の波ID取り違えも拒否', lambda: assessment.assess(summaries, details, damaged))
    damaged = deepcopy(summaries); damaged[0]['symbols']['TOPIX']['money_ratio'] = 99.
    reject('PF要約の改ざんを拒否', lambda: assessment.assess(damaged, details, waves))
    output = {'全検査合格': True, '人工検査件数': len(cases), '検査': cases, '全192仕様一致': True,
              '新PnL参照': False, '売買再生': False, '現在保存物使用': False, 'API取得数': 0,
              '設計実装SHA256': design.digest(Path(design.__file__)),
              '判定実装SHA256': design.digest(Path(assessment.__file__))}
    (design.HERE / 'scheduler_assessment_test.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('人工検査:', len(cases), '全合格')


if __name__ == '__main__':
    main()
