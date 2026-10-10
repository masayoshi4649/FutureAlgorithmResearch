"""初期6だけの条件選択と運用期間の分離を、人工値だけで検査する。"""

from copy import deepcopy
import json
from pathlib import Path

import conditional_assessment as audit
import conditional_design as design


def synthetic() -> tuple:
    """機能: 840条件の人工26行・8波を作り、初期6の選択材料を分離する。

    引数: なし。返り値: summaries/details/waves/training (tuple)。実相場の損益は使わない。
    """
    summaries, details, waves, training = [], {}, {}, {}
    for spec in design.catalog():
        extra = 10. if spec['exit_mode_id'] == 'B00' else 5. if spec['exit_mode_id'] == 'MIN' else 0.
        net, dd = 100. + extra, 100. - 2 * extra
        rows = []
        for i, session in enumerate(design.SESSIONS):
            for symbol in audit.SYMBOLS:
                rows.append({'id': spec['id'], 'session': session, 'symbol': symbol,
                    'completed_at': 100. + i, 'complete': True, 'net_yen': net, 'net_r': net / 100.,
                    'gross_profit_yen': 200. + extra, 'gross_loss_yen': 100.,
                    'profit_units': 1, 'loss_units': 1, 'zero_units': 0, 'closed_units': 2,
                    'cycles': 1, 'opening_orders': 1, 'long_unit_minutes': 50., 'short_unit_minutes': 30.,
                    'drawdown_yen': dd, 'min_equity_yen': -40., 'max_equity_yen': 110.,
                    'retracements': [{'final_yen': net, 'peak_yen': 150., 'retracement_yen': 150. - net,
                        'retracement_r': (150. - net) / 100., 'positive_peak': True}]})
        details[spec['id']] = rows
        summaries.append({'id': spec['id'], 'spec': spec, **audit.period_values(rows)})
        if spec['role'] == 'primary':
            training[spec['id']] = [r for r in rows if r['session'] in design.SESSIONS[:6]]
        waves[spec['id']] = [{'method': spec['id'], 'wave': wave['id'], 'symbol': symbol,
            'session': wave['session'], '開始': wave['start'], '終了': wave['end'], '波方向': wave['side'],
            '正方向ネット保有分': 30., '正方向ネット20分目安達成': True}
            for wave in design.waves() for symbol in audit.SYMBOLS]
    return summaries, details, waves, training


def main() -> None:
    """機能: 選択の順序・同値・欠損拒否・後半不使用と採用限定を検査する。

    引数: なし。返り値: なし (None)。新相場再生と成績読取は行わない。
    """
    summaries, details, waves, training = synthetic()
    selected = audit.select_training(training, 106.)
    assert selected['selected_exit_mode_id'] == 'B00' and selected['全初期行数'] == 2016
    result = audit.assess(summaries, details, waves, selected)
    assert result['主条件採用目安ID'] == ['H019__B00__V000']
    policy = result['H019運用policy']['セッション']
    assert {r['id'] for r in policy if r['session'] in design.SESSIONS[:6]} == {'H019__A0__V000'}
    assert result['H019運用policy']['全13と後7']['all_symbols']['TOPIX']['net_yen'] == 1370.
    cases = [{'検査': '全840・主168の初期選択と初期A0/後半B00の接続', '一致': True}]

    tie = deepcopy(training)
    for name, rows in tie.items():
        base = training[name.split('__')[0] + '__A0__V000']
        tie[name] = [{**deepcopy(r), 'id': name} for r in base]
    assert audit.select_training(tie, 106.)['selected_exit_mode_id'] == 'A0'
    cases.append({'検査': '完全同値では既存A0で取引を継続', '一致': True})
    tie = deepcopy(training)
    for signal in design.SIGNAL_IDS:
        tie[f'{signal}__B01__V000'] = [{**deepcopy(r), 'id': f'{signal}__B01__V000'} for r in training[f'{signal}__B00__V000']]
    assert audit.select_training(tie, 106.)['selected_exit_mode_id'] == 'B00'
    assert audit.select_training(dict(reversed(list(tie.items()))), 106.) == audit.select_training(tie, 106.)
    cases.append({'検査': '候補順に依存せず同点ID順を固定', '一致': True})
    changed = deepcopy(training)
    for name, rows in changed.items():
        if '__B00__' in name:
            for row in rows:
                if row['symbol'] == 'NK225':
                    row['drawdown_yen'] = 1000.
    assert audit.select_training(changed, 106.)['selected_exit_mode_id'] == 'MIN'
    cases.append({'検査': '片銘柄の中央値DD悪化を無視せず常時MINも選択可能', '一致': True})

    def reject(label, function) -> None:
        """機能: 破損・未来混入の人工資料を拒否させる。

        引数: label (str)、function (callable)。返り値: なし (None)。
        """
        try:
            function()
        except (AssertionError, KeyError, TypeError, ValueError):
            cases.append({'検査': label, '一致': True})
        else:
            raise AssertionError(label)

    name = next(iter(training))
    for label, mutation in (
        ('初期候補1件欠落', lambda r: r.pop(name)),
        ('後半区間混入', lambda r: r[name].append(deepcopy(details[name][-1]))),
        ('初期区間重複', lambda r: r[name].__setitem__(1, deepcopy(r[name][0]))),
        ('未完了セッション', lambda r: r[name][0].__setitem__('complete', False)),
        ('開始時刻後の完了資料', lambda r: r[name][0].__setitem__('completed_at', 107.)),
        ('診断候補を混入', lambda r: r.__setitem__('H019__B00__C080', deepcopy(r[name]))),
        ('非有限R', lambda r: r[name][0].__setitem__('net_r', float('nan'))),
    ):
        damaged = deepcopy(training); mutation(damaged)
        reject(label, lambda d=damaged: audit.select_training(d, 106.))
    changed = deepcopy(details)
    for identifier, rows in changed.items():
        for row in rows:
            if row['session'] in design.SESSIONS[6:]:
                row['net_r'] = -1e9 if '__B00__' in identifier else 1e9
    unchanged = {name: [r for r in changed[name] if r['session'] in design.SESSIONS[:6]] for name in training}
    assert audit.select_training(unchanged, 106.) == selected
    cases.append({'検査': '後半全候補の成績改変で選択不変', '一致': True})
    altered = deepcopy(selected); altered['selected_exit_mode_id'] = 'B01'
    reject('後付け選択固定の変更', lambda: audit.assess(summaries, details, waves, altered))
    lost = deepcopy(waves)
    lost['H019__B00__V000'][0]['正方向ネット保有分'] = 19.99
    lost['H019__B00__V000'][0]['正方向ネット20分目安達成'] = False
    assert audit.assess(summaries, details, lost, selected)['主条件採用目安ID'] == []
    cases.append({'検査': 'policy初期A0の波達成で選択Bの波喪失を隠さない', '一致': True})
    reject('全840の1件欠落', lambda: audit.assess(summaries[:-1], details, waves, selected))
    output = {'全検査合格': True, '人工検査件数': len(cases), '検査': cases,
        '全840仕様一致': True, '新PnL参照': False, '売買再生': False, 'API取得数': 0, '現在保存物使用': False,
        '設計実装SHA256': design.digest(Path(design.__file__)), '判定実装SHA256': design.digest(Path(audit.__file__))}
    (design.HERE / 'conditional_assessment_test.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('人工選択・判定検査:', len(cases), '全合格')


if __name__ == '__main__':
    main()
