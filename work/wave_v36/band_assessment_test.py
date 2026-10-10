"""実損益を使わず、固定主仮説の採否境界と対照の解釈を確認する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import band_assessment as assessment
import band_design as design


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night',
    '2026-09-23_Day', '2026-09-23_Night', '2026-09-24_Day', '2026-09-24_Night',
    '2026-09-25_Day', '2026-09-25_Night', '2026-09-28_Day', '2026-09-28_Night', '2026-09-29_Day']


def fixture() -> tuple:
    """機能: 全13/後7・両銘柄で基礎合格する人工値を作る。

    引数: なし。返り値: 主条件索引・session明細・乱数64・反転 (tuple)。実データを読まない。
    """
    rows = [dict(session=session, symbol=symbol, cycles=2, net_yen=100.,
        two_largest_cycle_profits=[50., 20.]) for session in SESSIONS for symbol in assessment.SYMBOLS]
    index = {}
    for identifier in [assessment.PRIMARY, *assessment.CONTROLS.values(), 'Q034__C080', 'Q034__C120']:
        value = dict(id=identifier, wave_passes=8)
        for period, count in (('all_symbols', 13), ('symbols', 7)):
            value[period] = {symbol: dict(net_yen=100. * count, gross_profit_yen=200. * count,
                gross_loss_yen=100. * count, profit_units=2. * count, loss_units=2. * count,
                drawdown_yen=100.) for symbol in assessment.SYMBOLS}
        index[identifier] = value
    sessions = {name: deepcopy(rows) for name in index}
    for name in ('Q007__V000', 'Q016__V000'):
        for period in assessment.PERIODS:
            for symbol in assessment.SYMBOLS:
                index[name][period][symbol]['net_yen'] -= 50.
                index[name][period][symbol]['drawdown_yen'] += 10.
    randoms = []
    for seed in range(64):
        item = deepcopy(index[assessment.PRIMARY]); item['id'] = f'Q034__R{seed:03d}'
        for period in assessment.PERIODS:
            for symbol in assessment.SYMBOLS:
                item[period][symbol]['net_yen'] -= 100.
                item[period][symbol]['drawdown_yen'] += 20.
        randoms.append(item)
    reverse = deepcopy(randoms[0]); reverse['id'] = 'Q034__REV'
    return index, sessions, randoms, reverse


def main() -> None:
    """機能: 基礎・比較・乱数・感度・波・監査未完の人工検査後に判定実装を固定する。

    引数: なし。返り値: なし (None)。実損益・API・保存ライブは使用しない。
    """
    results = []
    def confirm(name: str, expression: bool) -> None:
        """機能: 人工境界の期待結果を確認する。

        引数: name (str)、expression (bool)。返り値: なし (None)。
        """
        assert expression, name
        results.append(dict(検査=name, 一致=True))
    def reject(name: str, call) -> None:
        """機能: 欠損・重複・非有限入力が拒否されることを確認する。

        引数: name (str)、call (callable)。返り値: なし (None)。
        """
        try:
            call()
        except (AssertionError, KeyError, TypeError):
            confirm(name, True)
            return
        raise AssertionError('不正を受理: ' + name)
    index, sessions, randoms, reverse = fixture()
    main_value = index[assessment.PRIMARY]
    row7 = [r for r in sessions[assessment.PRIMARY] if r['symbol'] == 'TOPIX' and r['session'] in SESSIONS[6:]]
    metric = main_value['symbols']['TOPIX']
    confirm('基礎の金額比と一枚比を別計算', assessment.basic(metric, row7, True)['金額比'] == 2.
        and assessment.basic(metric, row7, True)['一枚平均比'] == 2.)
    altered = deepcopy(metric); altered['profit_units'] = 100.
    confirm('金額比が良くても一枚比不足は不合格', not assessment.basic(altered, row7, True)['合格'])
    altered = deepcopy(metric); altered['gross_loss_yen'] = 0.
    confirm('損失比未定義は未確認', assessment.basic(altered, row7, True)['金額比'] is None
        and not assessment.basic(altered, row7, True)['合格'])
    for field, amount in (('net_yen', 0.), ('gross_profit_yen', metric['gross_loss_yen'])):
        altered = deepcopy(metric); altered[field] = amount
        confirm(field + 'のゼロ又は比1境界を通さない', not assessment.basic(altered, row7, True)['合格'])
    altered_rows = deepcopy(row7)
    for row in altered_rows[:4]:
        row['cycles'] = 0
    confirm('後7の稼働3は不合格', not assessment.basic(metric, altered_rows, True)['合格'])
    altered_rows[3]['cycles'] = 2
    confirm('後7の稼働4は合格', assessment.basic(metric, altered_rows, True)['合格'])
    full_rows = [r for r in sessions[assessment.PRIMARY] if r['symbol'] == 'TOPIX']
    altered_rows = deepcopy(full_rows)
    for row in altered_rows[:7]:
        row['cycles'] = 0
    confirm('全13の稼働6は不合格', not assessment.basic(main_value['all_symbols']['TOPIX'], altered_rows, False)['合格'])
    altered_rows[6]['cycles'] = 2
    confirm('全13の稼働7は合格', assessment.basic(main_value['all_symbols']['TOPIX'], altered_rows, False)['合格'])
    for field in ('two_largest_cycle_profits', 'net_yen'):
        altered_rows = deepcopy(row7)
        altered_rows[0][field] = [701., 10.] if field == 'two_largest_cycle_profits' else 701.
        confirm(field + '最大勝ち依存を拒否', not assessment.basic(metric, altered_rows, True)['合格'])
        altered_rows[0][field] = [700., 10.] if field == 'two_largest_cycle_profits' else 700.
        confirm(field + '除外後0を非負として受理', assessment.basic(metric, altered_rows, True)['合格'])
    reject('明細不足拒否', lambda: assessment.basic(metric, row7[:-1], True))
    reject('明細重複拒否', lambda: assessment.basic(metric, row7[:-1] + [row7[0]], True))
    altered = deepcopy(metric); altered['net_yen'] = float('nan')
    reject('非有限期間値拒否', lambda: assessment.basic(altered, row7, True))

    # ----------------------------------------
    # 純価格・全出来高との追加価値と、旧方式との交換を区別する。
    confirm('対照完全同値を追加価値と呼ばない', assessment.relation(main_value, main_value)['関係'] == '同値')
    confirm('両市場の対応同時改善を受理', assessment.relation(main_value, index['Q007__V000'])['同時改善'])
    mixed = deepcopy(index['Q007__V000']); mixed['symbols']['NK225']['net_yen'] += 100.
    confirm('一市場だけの優位で全体合格にしない', assessment.relation(main_value, mixed)['関係'] == '交換又は混在')
    only_one = deepcopy(main_value); only_one['symbols']['TOPIX']['drawdown_yen'] += 1.
    confirm('全セル非劣位かつ1項目厳密改善', assessment.relation(main_value, only_one)['同時改善'])
    random_check = assessment.random_comparison(main_value, randoms, reverse)
    confirm('人工64方向対照を受理', random_check['合格'])
    reject('乱数63本拒否', lambda: assessment.random_comparison(main_value, randoms[:-1], reverse))
    reject('乱数ID重複拒否', lambda: assessment.random_comparison(main_value, randoms[:-1] + [randoms[0]], reverse))
    equal = [{**deepcopy(main_value), 'id': r['id']} for r in randoms]
    confirm('乱数中央値完全同値を優位としない', not assessment.random_comparison(main_value, equal, reverse)['合格'])
    one = deepcopy(equal)
    for item in one:
        item['symbols']['TOPIX']['drawdown_yen'] += 1.
    confirm('乱数全4セル非劣位かつ全体1項目の厳密改善', assessment.random_comparison(main_value, one, reverse)['合格'])
    bad = deepcopy(randoms)
    for item in bad:
        item['symbols']['NK225']['net_yen'] += 101.
    confirm('乱数より1セル劣れば不合格', not assessment.random_comparison(main_value, bad, reverse)['合格'])
    confirm('全反転完全同値を拒否', not assessment.random_comparison(main_value, randoms, main_value)['合格'])
    dominant = deepcopy(main_value)
    for period in assessment.PERIODS:
        for symbol in assessment.SYMBOLS:
            dominant[period][symbol]['net_yen'] += 1.
    confirm('全反転優位を拒否', not assessment.random_comparison(main_value, randoms, dominant)['合格'])

    # ----------------------------------------
    # 主仮説・感度・波・監査完了の全条件を別々に落とす。
    judged = assessment.assess(index, sessions, SESSIONS, True, random_check)
    confirm('全人工基準通過時だけ既知比較の候補', judged['既知比較の採用候補'] and not judged['未知での有効性確認'])
    confirm('監査未完を完成扱いしない', not assessment.assess(index, sessions, SESSIONS, False, random_check)['既知比較の採用候補'])
    confirm('方向対照未完を完成扱いしない', not assessment.assess(index, sessions, SESSIONS, True, {'完了': False})['既知比較の採用候補'])
    altered_index = deepcopy(index); altered_index[assessment.PRIMARY]['wave_passes'] = 7
    confirm('指定7波を8波合格にしない', not assessment.assess(altered_index, sessions, SESSIONS, True, random_check)['既知比較の採用候補'])
    altered_index = deepcopy(index); altered_index['Q034__C080']['symbols']['TOPIX']['net_yen'] = -1.
    confirm('時計感度の赤字を隠さない', not assessment.assess(altered_index, sessions, SESSIONS, True, random_check)['既知比較の採用候補'])
    altered_index = deepcopy(index); altered_index['Q007__V000'] = deepcopy(main_value)
    confirm('純価格同値なら追加価値不合格', not assessment.assess(altered_index, sessions, SESSIONS, True, random_check)['既知比較の採用候補'])
    altered_index = deepcopy(index); altered_index['Q016__V000'] = deepcopy(main_value)
    confirm('全出来高同値なら追加価値不合格', not assessment.assess(altered_index, sessions, SESSIONS, True, random_check)['既知比較の採用候補'])
    altered_index = deepcopy(index); altered_index['H019__V000'] = dominant
    confirm('旧H019劣位だけで別原理を一律棄却しない', assessment.assess(altered_index, sessions, SESSIONS, True, random_check)['既知比較の採用候補'])
    altered_index = deepcopy(index); altered_index['Q089__V000'] = dominant
    altered_index[assessment.PRIMARY]['symbols']['TOPIX']['net_yen'] = -1.
    confirm('別ID好成績へ主仮説を差替えない', not assessment.assess(altered_index, sessions, SESSIONS, True, random_check)['既知比較の採用候補'])
    reject('主仮説欠損を代替IDで補わない', lambda: assessment.assess({k: v for k, v in index.items() if k != assessment.PRIMARY}, sessions, SESSIONS, True, random_check))
    reject('期間順序変更拒否', lambda: assessment.assess(index, sessions, SESSIONS[::-1], True, random_check))

    conditions = design.conditions()
    confirm('主91診断273の全364直積', len(conditions) == 364 and len({r['id'] for r in conditions}) == 364
        and sum(r['primary'] for r in conditions) == 91)
    proxy = {s['id']: s for s in design.catalog()}
    main_params = proxy['Q034']['params']
    confirm('対応対照の価格窓分岐相手は同一', all(
        proxy[name]['params'][key] == main_params[key] for name in ('Q007', 'Q016')
        for key in main_params if key not in ('proxy', 'volume_threshold')))
    extras = design.supplementary_conditions()
    confirm('乱数64と全反転1を主とは別に固定', len(extras) == 65 and len({r['id'] for r in extras}) == 65
        and {r['random_seed'] for r in extras if r.get('random_seed') is not None} == set(range(64))
        and sum(r.get('reverse_direction', False) for r in extras) == 1)
    result = dict(全検査合格=True, 検査数=len(results), 検査=results,
        新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False)
    (HERE / 'band_assessment_test.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    files = ['band_assessment.py', 'band_assessment_test.py', 'band_assessment_test.json',
             'band_design.py', '採否と反証の事前規則.md']
    fixed = dict(主仮説=assessment.PRIMARY, 主条件数=91, 診断条件数=273, 全条件数=364, 別補助条件数=65,
        主仮説の事後差替=False, 比較対照=assessment.CONTROLS,
        乱数中央値='全4セル非劣位、全体で最低1項目厳密改善。各セル厳密改善とは異なる。',
        入力完備='集合・元台帳・全seed/反転ID・波8実体・再集計は完備guardが検査する。判定関数単体は監査済み入力を受け取る。',
        人工検査=result, 参照SHA256={'work/wave_v36/' + name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in files},
        新損益読取=False, 売買再生=False, API取得数=0, 現在保存物使用=False)
    path = HERE / 'band_assessment_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == fixed
    else:
        path.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding='utf-8')
    print('判定人工検査', len(results), '件合格。実損益不使用で固定。', flush=True)


if __name__ == '__main__':
    main()
