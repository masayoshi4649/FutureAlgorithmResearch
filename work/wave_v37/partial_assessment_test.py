"""実損益を読まず、固定主案の採否・欠落拒否・境界を人工値で検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import partial_assessment as assessment
import partial_design as design


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAMES = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night',
    '2026-09-23_Day', '2026-09-23_Night', '2026-09-24_Day', '2026-09-24_Night',
    '2026-09-25_Day', '2026-09-25_Night', '2026-09-28_Day', '2026-09-28_Night', '2026-09-29_Day']


def rebuild(value: dict, rows: list[dict]) -> None:
    """機能: 人工明細の変更を全13/後7の集計へ正しく反映する。

    引数: value (dict)、rows (list[dict])。返り値: なし (None)。実データは使わない。
    """
    for period, names in (('all_symbols', NAMES), ('symbols', NAMES[6:])):
        for symbol in assessment.SYMBOLS:
            part = [r for r in rows if r['symbol'] == symbol and r['session'] in names]
            for key in assessment.SUM_FIELDS:
                value[period][symbol][key] = sum(r[key] for r in part)


def fixture() -> tuple[dict, dict]:
    """機能: 全427条件・全26明細を人工値だけで生成する。

    引数: なし。返り値: summary索引と明細索引 (tuple[dict,dict])。
    """
    index, sessions = {}, {}
    for spec in design.catalog() + design.supplementary():
        identifier = spec['id']
        is_main = spec['policy']['id'] == design.PRIMARY_POLICY and spec['random_seed'] is None
        profit, dd = (300., 80.) if is_main else (200., 120.) if spec['random_seed'] is not None else (250., 100.)
        value = dict(id=identifier, wave_passes=8,
            **{p: {s: {'drawdown_yen': dd} for s in assessment.SYMBOLS} for p in assessment.PERIODS})
        rows = [dict(id=identifier, session=session, symbol=symbol,
            net_yen=profit-100., gross_profit_yen=profit, gross_loss_yen=100.,
            profit_units=1, loss_units=1, zero_units=0, cycles=2, cycle_wins=1, cycle_losses=1,
            cycle_profit_yen=profit, cycle_loss_yen=100., maximum_trade_profit=profit,
            reductions=1 if is_main else 0, restorations=1 if is_main else 0)
            for session in NAMES for symbol in assessment.SYMBOLS]
        rebuild(value, rows)
        index[identifier], sessions[identifier] = value, rows
    return index, sessions


def main() -> None:
    """機能: 人工の合否境界と資料不足を検査し、規則と実装を結果前に固定する。

    引数: なし。返り値: なし (None)。実損益・売買再生・APIは使用しない。
    """
    results = []
    def check(name: str, expression: bool) -> None:
        """機能: 人工の期待値との一致を記録する。

        引数: name (str)、expression (bool)。返り値: なし (None)。
        """
        assert expression, name
        results.append(dict(検査=name, 一致=True))
    def reject(name: str, call) -> None:
        """機能: 不正な資料や数値が明示的に拒否されることを確認する。

        引数: name (str)、call (callable)。返り値: なし (None)。
        """
        try:
            call()
        except (AssertionError, KeyError, TypeError):
            check(name, True)
            return
        raise AssertionError('不正受理: ' + name)

    index, sessions = fixture()
    main_value = index[assessment.PRIMARY]
    judged = assessment.assess(index, sessions, NAMES, True)
    check('全人工条件で候補・未知未確認', judged['既知比較の採用候補'] and not judged['未知での有効性確認'])
    provisional = assessment.assess(index, sessions, NAMES, False)
    check('監査未完でも経済条件を区別', provisional['経済目安合格'] and not provisional['既知比較の採用候補'])
    check('監査完了だけで変わるのは二項目', {k for k in judged if judged[k] != provisional[k]} == {'監査完了', '既知比較の採用候補'})
    row7 = [r for r in sessions[assessment.PRIMARY] if r['symbol'] == 'TOPIX' and r['session'] in NAMES[6:]]
    metric = main_value['symbols']['TOPIX']
    basic = assessment.basic(metric, row7, NAMES[6:], True)
    check('元組PFと平均元組勝敗比独立計算', basic['比率']['元組PF'] == basic['比率']['平均元組勝敗比'] == 3.)
    varied = deepcopy(metric); varied['cycle_wins'] = 70
    varied['cycles'] = 77
    check('高PFでも小勝ち多数の平均元組比を区別', assessment.ratios(varied)['元組PF'] == 3.
        and assessment.ratios(varied)['平均元組勝敗比'] < 1.)
    varied = deepcopy(metric); varied['profit_units'] = 70
    check('脚枚数比と元組比を混同しない', assessment.ratios(varied)['一枚平均勝敗比'] < 1.
        and assessment.ratios(varied)['平均元組勝敗比'] == 3.)
    varied = deepcopy(metric); varied['cycle_loss_yen'] = 0.; varied['cycle_losses'] = 0
    check('無損失PFを無限大合格としない', assessment.ratios(varied)['元組PF'] is None
        and assessment.ratios(varied)['平均元組勝敗比'] is None)
    for field in ('net_yen', 'cycle_profit_yen'):
        value, rows = deepcopy(metric), deepcopy(row7)
        for r in rows: r[field] = 0. if field == 'net_yen' else r['cycle_loss_yen']
        value[field] = sum(r[field] for r in rows)
        check(field + 'の0又は1境界は不合格', not assessment.basic(value, rows, NAMES[6:], True)['合格'])
    for field in ('maximum_trade_profit', 'net_yen'):
        rows = deepcopy(row7)
        rows[0][field] = metric['net_yen']
        value = deepcopy(metric)
        if field == 'net_yen':
            rows[1]['net_yen'] -= sum(r['net_yen'] for r in rows) - metric['net_yen']
        check(field + '除外0境界を受理', assessment.basic(value, rows, NAMES[6:], True)['合格'])
        rows[0][field] += 1.
        if field == 'net_yen': rows[1]['net_yen'] -= 1.
        check(field + '除外赤字を拒否', not assessment.basic(value, rows, NAMES[6:], True)['合格'])
        check(field + '感度では除外失敗を表示だけにする', assessment.basic(value, rows, NAMES[6:], False)['合格'])
    reject('明細数不足', lambda: assessment.basic(metric, row7[:-1], NAMES[6:], True))
    reject('明細重複', lambda: assessment.basic(metric, row7[:-1]+row7[:1], NAMES[6:], True))
    varied = deepcopy(metric); varied['net_yen'] += 1.
    reject('期間明細不一致', lambda: assessment.basic(varied, row7, NAMES[6:], True))
    for invalid in (float('nan'), float('inf'), True):
        reject('非有限又は真偽数値の拒否_' + str(invalid), lambda invalid=invalid: assessment.finite(invalid))

    # ----------------------------------------
    # 4セル比較は銘柄の円を合算せず、1項目の悪化も交換として残す。
    check('全同値を同時改善としない', assessment.relation(main_value, main_value)['完全同値'])
    reference = deepcopy(main_value); reference['symbols']['TOPIX']['drawdown_yen'] += 1.
    check('全セル非劣位かつ1項目改善で同時改善', assessment.relation(main_value, reference)['同時改善'])
    reference['all_symbols']['NK225']['net_yen'] += 1.
    check('一市場の悪化は交換', assessment.relation(main_value, reference)['関係'] == '交換又は混在')
    reference = deepcopy(main_value); reference['symbols']['NK225']['net_yen'] += 1.
    check('単純対照の厳密支配を識別', assessment.relation(main_value, reference)['対照が厳密支配'])
    randoms = [index[r['id']] for r in design.supplementary()]
    check('64中央値全セル優位', assessment.random_comparison(main_value, randoms)['合格'])
    reject('乱数63不足', lambda: assessment.random_comparison(main_value, randoms[:-1]))
    reject('乱数ID重複', lambda: assessment.random_comparison(main_value, randoms[:-1]+randoms[:1]))
    bad_randoms = deepcopy(randoms); bad_randoms[-1]['id'] = '別seed'
    reject('本数だけ同じ別seed拒否', lambda: assessment.random_comparison(main_value, bad_randoms))
    equal = [dict(deepcopy(main_value), id=r['id']) for r in randoms]
    check('64中央値同値は情報優位としない', not assessment.random_comparison(main_value, equal)['合格'])
    for r in equal: r['symbols']['TOPIX']['drawdown_yen'] += 1.
    check('64中央値も全体1厳密改善', assessment.random_comparison(main_value, equal)['合格'])
    for r in equal: r['symbols']['NK225']['net_yen'] += 1.
    check('64中央値一市場悪化は不合格', not assessment.random_comparison(main_value, equal)['合格'])

    # ----------------------------------------
    # 固定主案・7感度・8波・全427集合の各ゲートを単独に破る。
    altered = deepcopy(index); altered[assessment.PRIMARY]['wave_passes'] = 7
    check('指定7波では不採用', not assessment.assess(altered, sessions, NAMES, True)['既知比較の採用候補'])
    for variant in assessment.VARIANTS:
        altered, rows = deepcopy(index), deepcopy(sessions)
        identifier = 'H019__' + design.PRIMARY_POLICY + '__' + variant
        for r in rows[identifier]:
            if r['symbol'] == 'NK225' and r['session'] in NAMES[6:]: r['net_yen'] = -1.
        rebuild(altered[identifier], rows[identifier])
        check(variant + '後7赤字を他変形で救済しない', not assessment.assess(altered, rows, NAMES, True)['既知比較の採用候補'])
    for field in ('reductions', 'restorations'):
        altered, rows = deepcopy(index), deepcopy(sessions)
        for r in rows[assessment.PRIMARY]:
            if r['symbol'] == 'TOPIX' and r['session'] in NAMES[6:]: r[field] = 0
        rebuild(altered[assessment.PRIMARY], rows[assessment.PRIMARY])
        check(field + '片市場後7不発火は支持しない', not assessment.assess(altered, rows, NAMES, True)['既知比較の採用候補'])
    altered = deepcopy(index); altered[assessment.CONTROLS['元A0']] = dict(deepcopy(main_value), id=assessment.CONTROLS['元A0'])
    check('元A0同値では代替改善未達', not assessment.assess(altered, sessions, NAMES, True)['既知比較の採用候補'])
    for label in ('減量のみ', '固定コア', '通常半分利確型小数量', '120秒復元'):
        altered = deepcopy(index); identifier = assessment.CONTROLS[label]
        altered[identifier] = dict(deepcopy(main_value), id=identifier)
        altered[identifier]['symbols']['TOPIX']['net_yen'] += 1.
        check(label + '厳密支配で追加価値を支持しない', not assessment.assess(altered, sessions, NAMES, True)['既知比較の採用候補'])
    altered = deepcopy(index); identifier = assessment.CONTROLS['固定コア']
    altered[identifier] = dict(deepcopy(main_value), id=identifier)
    check('対照同値は非支配だが同値を明記', '固定コア' in assessment.assess(altered, sessions, NAMES, True)['単純対照と同値の項目'])
    altered, rows = deepcopy(index), deepcopy(sessions)
    for r in rows[assessment.PRIMARY]: r['net_yen'] = -1.
    rebuild(altered[assessment.PRIMARY], rows[assessment.PRIMARY])
    check('他426好成績でも主を差替えない', not assessment.assess(altered, rows, NAMES, True)['既知比較の採用候補'])
    absent = {k:v for k,v in index.items() if k != assessment.PRIMARY}
    reject('主仮説欠損', lambda: assessment.assess(absent, sessions, NAMES, True))
    missing_random = {k:v for k,v in index.items() if k != design.supplementary()[0]['id']}
    reject('補助1不足', lambda: assessment.assess(missing_random, sessions, NAMES, True))
    absent = deepcopy(sessions); absent[assessment.PRIMARY] = absent[assessment.PRIMARY][:-1]
    reject('26入力1不足', lambda: assessment.assess(index, absent, NAMES, True))
    reject('期間順序反転', lambda: assessment.assess(index, sessions, NAMES[::-1], True))
    reject('真偽以外の監査完了', lambda: assessment.assess(index, sessions, NAMES, 1))
    check('309主54診断64補助の一意集合', len(design.catalog()) == 363 and
        sum(r['role']=='main' for r in design.catalog()) == 309 and len(index)==427)
    result = dict(全検査合格=True, 検査数=len(results), 検査=results, 新損益読取=False,
        売買再生=False, API取得数=0, 現在保存物使用=False)
    (HERE/'partial_assessment_test.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    files = ('partial_assessment.py', 'partial_assessment.md', 'partial_assessment_test.py',
        'partial_assessment_test.json', 'partial_design.py')
    fixed = dict(規則=assessment.rules(), 人工検査=result,
        参照SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/name for name in files)},
        新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False)
    path = HERE/'partial_assessment_fixed.json'
    if path.exists(): assert json.loads(path.read_text(encoding='utf-8')) == fixed
    else: path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('採否の人工検査', len(results), '件合格。全427の固定主案判定を結果前固定。', flush=True)


if __name__ == '__main__':
    main()
