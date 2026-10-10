"""人工の元組だけで採否3段階と不正資料の拒否を検査する。"""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import adaptive_assessment as audit
import adaptive_design as design

HERE = Path(__file__).resolve().parent


def fixture() -> tuple:
    """機能: 実相場を使わず全974件の完全な人工資料を生成する。

    引数: なし。返り値: index、sessions、names、4台帳 (tuple)。
    """
    names = [f'人工{i:02d}' for i in range(13)]
    index, sessions, ledgers = {}, {}, {identifier: [] for identifier in audit.PAIRED_IDS}
    for spec in design.catalog() + design.supplementary():
        identifier = spec['id']
        profits = [6., 5., -1., -1.]
        if identifier == audit.SIGNAL:
            profits = [6., 1., -1., -1.]
        elif identifier == audit.CLOCK:
            profits = [2., 5., -1., -1.]
        elif identifier == audit.REVERSE or spec['branch_seed'] is not None:
            profits = [2., 1., -1., -1.]
        rows = []
        for name in names:
            for symbol in audit.SYMBOLS:
                factor, q0 = (1000., 5) if symbol == 'TOPIX' else (10., 10)
                risk = 100.
                money = [p * risk * factor for p in profits]
                gains = sum(max(v, 0.) for v in money)
                losses = sum(max(-v, 0.) for v in money)
                row = dict(id=identifier, session=name, symbol=symbol, net_yen=sum(money),
                    gross_profit_yen=gains, gross_loss_yen=losses, profit_units=2 * q0,
                    loss_units=2 * q0, zero_units=0, cycles=4, cycle_wins=2, cycle_losses=2,
                    cycle_profit_yen=gains, cycle_loss_yen=losses, reductions=2, restorations=2,
                    maximum_trade_profit=max(money), drawdown_yen=2 * risk * factor,
                    net_r=sum(profits), signal_choices=1, timer_choices=1)
                rows.append(row)
                if identifier in ledgers:
                    cycles = [[c + 1, c * 100 + 10, c * 100 + 60, p * risk, risk, 20., q0, q0, 1, 2]
                        for c, p in enumerate(profits)]
                    branches = [[20, 1, 1, 1, -1, 19, 1, 3, 1, -1],
                        [120, 2, 1, 2, 1, 119, 1, 2, 1, -1]] if identifier == audit.PRIMARY else []
                    ledgers[identifier].append(dict(session=name, symbol=symbol,
                        config=dict(point_value=factor), cycles=cycles, branch_events=branches))
        summaries = {}
        for period in audit.PERIODS:
            part_names = audit.names_for(period, names)
            summaries[period] = {}
            for symbol in audit.SYMBOLS:
                part = [r for r in rows if r['symbol'] == symbol and r['session'] in part_names]
                value = {field: sum(r[field] for r in part) for field in audit.SUM_FIELDS}
                for field in ('net_r', 'signal_choices', 'timer_choices'):
                    value[field] = sum(r[field] for r in part)
                value['drawdown_yen'] = max(r['drawdown_yen'] for r in part)
                summaries[period][symbol] = value
        sessions[identifier] = rows
        index[identifier] = dict(id=identifier, spec=spec, wave_passes=8, **summaries)
    return index, sessions, names, ledgers


def rejected(callable_value: object) -> bool:
    """機能: 不正な人工資料が例外で拒否されることを確かめる。

    引数: callable_value (Callable)。返り値: 拒否されたか (bool)。
    """
    try:
        callable_value()
    except (AssertionError, KeyError, ValueError, TypeError):
        return True
    return False


def main() -> None:
    """機能: 正常例と判定境界・欠落・分岐混同を人工で検査して保存する。

    引数: なし。返り値: なし (None)。実相場の売買を実行しない。
    """
    index, sessions, names, ledgers = fixture()
    records = []

    def check(name: str, condition: bool) -> None:
        """機能: 日本語の試験名と成否を記録する。

        引数: name (str)、condition (bool)。返り値: なし (None)。
        """
        assert condition, name
        records.append(dict(検査=name, 一致=True))

    baseline = audit.assess(index, sessions, names, ledgers)
    check('全974人工を保持し3経済段階が成立', all(baseline[k] for k in ('基礎候補', '十四感度頑健性', '分岐の利益付加価値', '経済目安合格')))
    check('監査前は採用へ昇格しない', not baseline['既知比較の採用候補'])
    verified = audit.assess(index, sessions, names, ledgers, True)
    check('監査後の変更は2フラグだけ', {k for k in baseline if baseline[k] != verified[k]} == {'監査完了', '既知比較の採用候補'})
    check('Pareto同時改善なしでも主案経済3段階を満たせる', not verified['A0全セル同時改善'] and verified['既知比較の採用候補'])
    check('同条件のB01公開時計を参照', audit.CLOCK.endswith('B06_T120_GB01_F50_N1__R1__V000'))
    check('全補助系統を別々に保持', len(verified['成分符号対照']) == 11)

    alternate = deepcopy(index)
    alternate['H019__A0__R1__V000']['symbols']['TOPIX']['drawdown_yen'] -= 1
    changed = audit.assess(alternate, sessions, names, ledgers)
    check('A0に対するDD微差を隠さず候補は別判定', changed['対応比較']['A0']['関係'] == '対照優位' and changed['経済目安合格'])

    sensitive_index, sensitive_sessions = deepcopy(index), deepcopy(sessions)
    sensitive_id = 'H019__' + design.PRIMARY_POLICY + '__R1__E080'
    for row in sensitive_sessions[sensitive_id]:
        unit = row['gross_profit_yen'] / 11.
        row.update(gross_profit_yen=unit, cycle_profit_yen=unit, net_yen=-unit, maximum_trade_profit=unit / 2.)
    for period in audit.PERIODS:
        for symbol in audit.SYMBOLS:
            part_rows = [r for r in sensitive_sessions[sensitive_id]
                if r['symbol'] == symbol and r['session'] in audit.names_for(period, names)]
            for field in audit.SUM_FIELDS:
                sensitive_index[sensitive_id][period][symbol][field] = sum(r[field] for r in part_rows)
    sensitivity_failed = audit.assess(sensitive_index, sensitive_sessions, names, ledgers, True)
    check('感度失敗は基礎候補を消さず頑健性と採用だけ未達', sensitivity_failed['基礎候補']
        and not sensitivity_failed['十四感度頑健性'] and not sensitivity_failed['既知比較の採用候補'])

    selected = index[audit.PRIMARY]
    rows = sessions[audit.PRIMARY]
    part = [r for r in rows if r['symbol'] == 'TOPIX' and r['session'] in names[6:]]
    value = selected['symbols']['TOPIX']
    check('元組基礎正常', audit.basic(value, part, names[6:], True)['合格'])
    for name, field, number in (('無減量', 'reductions', 0), ('無復元', 'restorations', 0)):
        artificial, artificial_rows = deepcopy(selected), deepcopy(rows)
        for row in artificial_rows:
            row[field] = number
        for period in audit.PERIODS:
            for symbol in audit.SYMBOLS:
                artificial[period][symbol][field] = number
        check(name + 'を基礎候補へしない', not audit.base_candidate(artificial, artificial_rows, names)['基礎候補'])
    artificial = deepcopy(selected); artificial['wave_passes'] = 7
    check('指定波不足を基礎候補へしない', not audit.base_candidate(artificial, rows, names)['基礎候補'])
    for field in ('cycle_losses', 'loss_units'):
        artificial = deepcopy(value); artificial[field] = 0
        ratio = audit.ratios(artificial)
        key = '平均元組勝敗比' if field == 'cycle_losses' else '一枚平均勝敗比'
        check('分母なし_' + field, ratio[key] is None)
    artificial = deepcopy(part); artificial[0]['maximum_trade_profit'] = value['net_yen'] + 1
    check('最大1勝ち組依存を拒否', not audit.basic(value, artificial, names[6:], True)['合格'])
    check('空の対応差は不作動', audit.samples([]) == dict(件数=0, 合計=0, 平均=None, 中央値=None, 改善数=0, 悪化数=0, 同値数=0, 最大正差=0., 最大正差除外=0.))

    # ----------------------------------------
    # 分岐のない口座や同値の復元方式を、選択の成功にしない。
    empty_index, empty_ledgers = deepcopy(index), deepcopy(ledgers)
    for row in empty_ledgers[audit.PRIMARY]: row['branch_events'] = []
    for identifier in audit.PAIRED_IDS:
        for k, row in enumerate(empty_ledgers[identifier]):
            row['cycles'] = deepcopy(ledgers[audit.PRIMARY][k]['cycles'])
        for period in audit.PERIODS:
            for symbol in audit.SYMBOLS:
                empty_index[identifier][period][symbol]['net_r'] = index[audit.PRIMARY][period][symbol]['net_r']
    for period in audit.PERIODS:
        for symbol in audit.SYMBOLS:
            empty_index[audit.PRIMARY][period][symbol]['signal_choices'] = 0
            empty_index[audit.PRIMARY][period][symbol]['timer_choices'] = 0
    check('全無分岐は付加価値未確認', not audit.branch_evidence(empty_index, empty_ledgers, names)['利益付加価値支持'])
    single_index, single_ledgers = deepcopy(index), deepcopy(ledgers)
    for row in single_ledgers[audit.PRIMARY]: row['branch_events'] = row['branch_events'][:1]
    for identifier in (audit.SIGNAL, audit.REVERSE):
        for row in single_ledgers[identifier]: row['cycles'][1][3] = 500.
        for period in audit.PERIODS:
            for symbol in audit.SYMBOLS:
                single_index[identifier][period][symbol]['net_r'] += 4. * len(audit.names_for(period, names))
    for period in audit.PERIODS:
        for symbol in audit.SYMBOLS:
            single_index[audit.PRIMARY][period][symbol]['timer_choices'] = 0
    check('片分岐しか働かない場合は選択有効としない', not audit.branch_evidence(single_index, single_ledgers, names)['利益付加価値支持'])
    same_index, same_ledgers = deepcopy(index), deepcopy(ledgers)
    for identifier in audit.PAIRED_IDS:
        for k, row in enumerate(same_ledgers[identifier]): row['cycles'] = deepcopy(ledgers[audit.PRIMARY][k]['cycles'])
        for period in audit.PERIODS:
            for symbol in audit.SYMBOLS:
                same_index[identifier][period][symbol]['net_r'] = index[audit.PRIMARY][period][symbol]['net_r']
    check('分岐しても両方式同値なら付加価値未確認', not audit.branch_evidence(same_index, same_ledgers, names)['利益付加価値支持'])
    reflected = deepcopy(ledgers)
    for rows_to_reflect in reflected.values():
        for row in rows_to_reflect:
            for cycle in row['cycles']: cycle[8] *= -1
            for branch in row['branch_events']: branch[4] *= -1
    check('保有方向と根拠を反射しても相対分類と差は同じ', audit.branch_pairs(reflected, names) == audit.branch_pairs(ledgers, names))
    one_bad_index, one_bad_ledgers = deepcopy(index), deepcopy(ledgers)
    for identifier in (audit.PRIMARY, audit.CLOCK):
        for row in one_bad_ledgers[identifier]: row['cycles'][1][3] = 50.
    for period in audit.PERIODS:
        for symbol in audit.SYMBOLS:
            for identifier in (audit.PRIMARY, audit.CLOCK):
                one_bad_index[identifier][period][symbol]['net_r'] -= 4.5 * len(audit.names_for(period, names))
    check('片層の利益だけでは分岐付加価値を通さない', not audit.branch_evidence(one_bad_index, one_bad_ledgers, names)['利益付加価値支持'])
    high_random = deepcopy(index)
    for spec in design.supplementary():
        if spec['branch_seed'] is not None:
            for symbol in audit.SYMBOLS:
                high_random[spec['id']]['symbols'][symbol]['net_r'] = index[audit.PRIMARY]['symbols'][symbol]['net_r']
    check('乱数中央値と同じなら支持未達', not audit.branch_evidence(high_random, ledgers, names)['利益付加価値支持'])

    # ----------------------------------------
    # 資料不足と、損益から状態を作る不正な差替えを拒否する。
    for label, mutate in (
        ('主台帳欠落', lambda x: x.pop(audit.PRIMARY)),
        ('台帳26未満', lambda x: x[audit.CLOCK].pop()),
        ('台帳重複', lambda x: x[audit.CLOCK].__setitem__(0, deepcopy(x[audit.CLOCK][1]))),
        ('元組欠落', lambda x: x[audit.SIGNAL][0]['cycles'].pop()),
        ('R差替', lambda x: x[audit.CLOCK][0]['cycles'][0].__setitem__(4, 200.)),
        ('初回時刻差替', lambda x: x[audit.CLOCK][0]['cycles'][0].__setitem__(1, 11)),
        ('B01未来公開', lambda x: x[audit.PRIMARY][0]['branch_events'][0].__setitem__(5, 21)),
        ('分類と方向不一致', lambda x: x[audit.PRIMARY][0]['branch_events'][0].__setitem__(7, 2)),
        ('減量前分岐', lambda x: x[audit.PRIMARY][0]['branch_events'][0].__setitem__(0, 9)),
        ('同組2回分岐', lambda x: x[audit.PRIMARY][0]['branch_events'].append(deepcopy(x[audit.PRIMARY][0]['branch_events'][0]))),
        ('選択後の固定方式と不一致', lambda x: x[audit.CLOCK][0]['cycles'][1].__setitem__(3, 501.)),
        ('無分岐組の経済差', lambda x: x[audit.REVERSE][0]['cycles'][2].__setitem__(3, -101.)),
        ('反対選択不一致', lambda x: x[audit.PRIMARY][0]['branch_events'][0].__setitem__(3, 2)),
        ('非有限元組', lambda x: x[audit.PRIMARY][0]['cycles'][0].__setitem__(3, math.nan)),
    ):
        corrupted = deepcopy(ledgers); mutate(corrupted)
        check(label + 'を拒否', rejected(lambda: audit.branch_pairs(corrupted, names)))
    for label, mutate in (
        ('主結果欠落', lambda x: x.pop(audit.PRIMARY)),
        ('補助seed欠落', lambda x: x.pop(design.supplementary()[0]['id'])),
        ('spec主案差替', lambda x: x[audit.PRIMARY]['spec'].__setitem__('primary', False)),
        ('元組R集計改竄', lambda x: x[audit.PRIMARY]['symbols']['TOPIX'].__setitem__('net_r', 0.)),
        ('分岐数改竄', lambda x: x[audit.PRIMARY]['symbols']['TOPIX'].__setitem__('signal_choices', 0)),
    ):
        corrupted = deepcopy(index); mutate(corrupted)
        check(label + 'を拒否', rejected(lambda: audit.assess(corrupted, sessions, names, ledgers)))
    for v in (True, None, math.nan, math.inf, -math.inf):
        check('数値境界拒否_' + repr(v), rejected(lambda: audit.finite(v)))

    result = dict(全合格=True, 人工検査数=len(records), 検査=records, 新実相場損益=False,
        実装SHA256=hashlib.sha256((HERE / 'adaptive_assessment.py').read_bytes()).hexdigest(),
        検査SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        設計SHA256=hashlib.sha256((HERE / 'adaptive_design.py').read_bytes()).hexdigest())
    (HERE / 'adaptive_assessment_test.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(f'人工{len(records)}件の採否検査に合格。新損益なし。')


if __name__ == '__main__':
    main()
