"""実相場を使わず、固定260条件の採否と旧統計の接続を人工検算する。"""

from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import json
import math
from pathlib import Path
import socket
import urllib.request

import numpy as np

import assessment
import design


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
statistics = assessment.statistics
RECORDS: list[dict] = []


def denied(*args: object, **kwargs: object) -> None:
    """機能: 人工検査からの通信を拒否する。

    引数: 任意 (object)。返り値: なし (None)、常に例外を送出する。
    """
    raise AssertionError('人工検査では通信しません')


def sha(path: Path) -> str:
    """機能: 読取り対象の内容指紋を得る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(name: str, actual: object, expected: object) -> None:
    """機能: 人工の期待値と比較して全検査を残す。

    引数: name (str)、actual/expected (object)。返り値: なし (None)。
    """
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        passed = actual is not None and math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9)
    else:
        passed = actual == expected
    RECORDS.append(dict(検査=name, 合格=bool(passed), 実値=actual, 期待=expected))


def rejected(index: object) -> bool:
    """機能: 不正な資料が明示的なValueErrorで拒否されるかを調べる。

    引数: index (object)。返り値: 拒否した場合True (bool)。
    """
    try:
        assessment.assess(index)
    except ValueError:
        return True
    return False


def fixture(symbol: str, name: str, pnls: list[float], risks: list[float] | None = None,
            sides: list[int] | None = None, equity: list[float] | None = None) -> tuple[dict, dict]:
    """機能: 注文器を呼ばず、1枚の返済台帳と人工時価を作る。

    引数: symbol/name (str)、pnls/risks/equity (list[float]|None)、sides (list[int]|None)。
    返り値: 時刻入力と人工結果 (tuple[dict,dict])。実相場の参照はない。
    """
    count = len(pnls)
    risks = [2.] * count if risks is None else risks
    sides = [1 if i % 2 == 0 else -1 for i in range(count)] if sides is None else sides
    trades = np.zeros((count, 10), dtype=float)
    realized, path = 0., [0.]
    for i, (pnl, risk, side) in enumerate(zip(pnls, risks, sides)):
        assert risk > 0 and side in (-1, 1)
        trades[i] = [3*i+1, 3*i+3, side, 100., 100.+pnl*side, risk, pnl, 1 if pnl < 0 else 2, 3*i, 3*i+1]
        path.extend([realized, realized+pnl/2, realized+pnl])
        realized += pnl
    path = path if equity is None else equity
    assert len(path) >= 3*count+1 and math.isclose(path[-1], realized)
    peak = loss = 0.
    for value in path:
        peak = max(peak, value)
        loss = max(loss, peak-value)
    curve = np.zeros((len(path), 4), dtype=float)
    curve[:, 1] = path
    ready = dict(symbol=symbol, session=name, time_s=np.arange(len(path), dtype=float)*60.)
    result = dict(trades=trades, curve=curve, stats=np.asarray([realized, loss, count+3, count+1, 1.]))
    return ready, result


def good(symbol: str) -> dict:
    """機能: 最低基準の等号を満たす20取引・6場の人工集計を得る。

    引数: symbol (str)。返り値: 旧aggregateが計算した期間値 (dict)。
    """
    pnls, rows, offset = [6., -5.]*10, [], 0
    for number, count in enumerate((4, 4, 3, 3, 3, 3)):
        sides = [1 if i < 17 else -1 for i in range(offset, offset+count)]
        ready, result = fixture(symbol, f'2026-01-{number+1:02d}_Day', pnls[offset:offset+count], sides=sides)
        rows.append(statistics.session(ready, result))
        offset += count
    return statistics.aggregate(rows)


def index_fixture() -> dict:
    """機能: 固定260仕様の人工比較集計を作る。

    引数: なし。返り値: spec/symbolsを持つ全条件辞書 (dict)。
    境界を独立に検査するためR等を人工設定する。実相場の成績ではない。
    """
    rows = {}
    templates = {symbol: good(symbol) for symbol in assessment.SYMBOLS}
    for spec in design.catalog() + design.supplementary():
        values = deepcopy(templates)
        for value in values.values():
            value['net_r'] = 39.
        rows[spec['id']] = dict(spec=deepcopy(spec), symbols=values)
    for symbol in assessment.SYMBOLS:
        rows['F01']['symbols'][symbol]['net_r'] = 40.
        rows['F02']['symbols'][symbol]['net_r'] = 45.
        for identifier in ('F01', 'F02', 'F03'):
            for seed in range(64):
                value = rows[f'{identifier}_R{seed:02d}']['symbols'][symbol]
                value['net_r'] = float(seed)
                value['net_yen'] = 1. if seed < 32 else 1e6
    return rows


def statistics_cases() -> None:
    """機能: 旧session/aggregate/basicを人工台帳と別の曲線接続式で確認する。

    引数: なし。返り値: なし (None)、検査一覧へ追記する。
    """
    for symbol, factor in (('TOPIX', 1000.), ('NK225', 10.)):
        ready, result = fixture(symbol, '2026-01-01_Day', [4., -2., 0., 6.], [2., 4., 2., 3.])
        row = statistics.session(ready, result)
        expected = dict(profit_yen=10*factor, loss_yen=2*factor, net_yen=8*factor, profit_units=2,
            loss_units=1, zero_units=1, trades=4, net_r=3.5, drawdown_yen=2*factor,
            max_win_yen=6*factor, long_trades=2, short_trades=2, held_minutes=8.)
        for field, number in expected.items():
            check(f'台帳/{symbol}/{field}', row[field], number)
        value = statistics.aggregate([row])
        for field, number in dict(profit_factor=5., average_payoff=2.5, without_max_trade=2*factor,
                                  without_max_session=0., active_sessions=1).items():
            check(f'単場集計/{symbol}/{field}', value[field], number)
        # ----------------------------------------
        # 当場時価を前場実現額へ足し、全時点の下落を別式で走査する。
        scenarios = [([5.], [0., 12., -4., 5.]), ([-8.], [0., 3., -12., -8.]),
                     ([10.], [0., -3., 18., 10.]), ([], [0., 0., 0., 0.])]
        rows, joined, base = [], [0.], 0.
        for number, (pnls, path) in enumerate(scenarios):
            ready, result = fixture(symbol, f'2026-01-{number+1:02d}_Day', pnls, equity=path)
            rows.append(statistics.session(ready, result))
            joined.extend((base+p)*factor for p in path)
            base += path[-1]
        peak = maximum = 0.
        for point in joined:
            peak = max(peak, point)
            maximum = max(maximum, peak-point)
        total = statistics.aggregate(list(reversed(rows)))
        check(f'全時価DD/{symbol}', total['drawdown_yen'], maximum)
        check(f'全時価DD具体値/{symbol}', total['drawdown_yen'], 19*factor)
        check(f'全時価最終収支/{symbol}', total['net_yen'], 7*factor)
        check(f'最大勝ち取引除去/{symbol}', total['without_max_trade'], -3*factor)
        check(f'最大勝ち場除去/{symbol}', total['without_max_session'], -3*factor)
    for name, pnls in (('無取引', []), ('全敗', [-1.]*24), ('全勝', [2.]*24),
                       ('全同値', [0.]*24), ('1勝依存', [100.]+[-1.]*23)):
        rows = []
        for number in range(6):
            ready, result = fixture('TOPIX', f'2026-02-{number+1:02d}_Day', pnls[number*4:(number+1)*4])
            rows.append(statistics.session(ready, result))
        total = statistics.aggregate(rows)
        check(f'基本不合格/{name}', statistics.basic(total)['合格'], False)
        if name in ('無取引', '全勝', '全同値'):
            check(f'分母0を未定義/{name}', total['profit_factor'], None)
        if name == '1勝依存':
            check('1勝依存はPFだけなら良い', total['profit_factor'] > 1.2, True)
            check('1勝依存は最大勝ち除去で拒否', total['without_max_trade'] < 0, True)
    value = good('TOPIX')
    check('20決済6場両方向3と比率1.2等号', statistics.basic(value)['合格'], True)
    for field, replacement in dict(trades=19, active_sessions=5, long_trades=2, short_trades=2,
        net_yen=0., profit_factor=1.199, average_payoff=1.199, without_max_trade=-1., without_max_session=-1.).items():
        changed = deepcopy(value)
        changed[field] = replacement
        check('基本不足/'+field, statistics.basic(changed)['合格'], False)
    for field in ('profit_factor', 'average_payoff'):
        for label, replacement in (('未定義', None), ('非数', float('nan')), ('無限', float('inf'))):
            changed = deepcopy(value)
            changed[field] = replacement
            check('基本不正/'+field+'/'+label, statistics.basic(changed)['合格'], False)


def hypothesis(index: dict, identifier: str) -> dict:
    """機能: 全260入力を検査して指定仮説だけを取り出す。

    引数: index (dict)、identifier (str)。返り値: 一仮説の判定 (dict)。
    """
    return assessment.assess(index)['仮説別'][identifier]


def comparison_cases() -> None:
    """機能: 主副の独立、R厳密超過、全乱数、4執行への接続を検査する。

    引数: なし。返り値: なし (None)、人工検査を追記する。
    """
    base = index_fixture()
    frozen = deepcopy(base)
    result = assessment.assess(base)
    check('入力集計を書き換えない', base, frozen)
    check('主仮説を固定', result['主仮説'], 'F01')
    check('副仮説を固定', result['副仮説'], 'F02')
    check('主副以外を採用欄へ増やさない', sorted(result['仮説別']), ['F01', 'F02'])
    check('全主68を省略しない', set(result['全主条件の基礎']), {s['id'] for s in design.catalog()})
    for field in ('未知での有効性確認', '全体目標達成'):
        check('既知合格を未知へ広げない/'+field, result[field], False)
    check('経済判定を実装完備と呼ばない', result['実装監査完了を意味しない'], True)
    for identifier in ('F01', 'F02'):
        group = result['仮説別'][identifier]
        for field in ('基礎候補', '板の比較付加価値', '実行感度', '窓距離感度', '既知経済目安合格'):
            check('全合格人工/'+identifier+'/'+field, group[field], True)
        for symbol in assessment.SYMBOLS:
            prefix = identifier+'/'+symbol+'/'
            main_r = base[identifier]['symbols'][symbol]['net_r']
            for field, replacement in dict(trades=19, active_sessions=5, long_trades=2, short_trades=2,
                profit_factor=None, average_payoff=None, without_max_trade=-1., without_max_session=-1., net_yen=0.).items():
                changed = deepcopy(base)
                changed[identifier]['symbols'][symbol][field] = replacement
                value = hypothesis(changed, identifier)
                check(prefix+'主又は副の不足/'+field, value['既知経済目安合格'], False)
                check(prefix+'不足を近傍で救済しない/'+field, value['窓距離感度'], False)
                other = 'F02' if identifier == 'F01' else 'F01'
                check(prefix+'他仮説は独立/'+field, hypothesis(changed, other)['既知経済目安合格'], True)
            for control in assessment.COMPONENTS[identifier]:
                for difference in (0., 1.):
                    changed = deepcopy(base)
                    changed[control]['symbols'][symbol]['net_r'] = main_r+difference
                    value = hypothesis(changed, identifier)
                    check(prefix+f'対照Rの同点以上/{control}/{difference}', value['板の比較付加価値'], False)
                    check(prefix+f'対照失敗と基礎を分ける/{control}/{difference}', value['基礎候補'], True)
                    check(prefix+f'対照失敗を全体へ伝達/{control}/{difference}', value['既知経済目安合格'], False)
            changed = deepcopy(base)
            for seed in range(64):
                changed[f'{identifier}_R{seed:02d}']['symbols'][symbol]['net_r'] = main_r
            value = hypothesis(changed, identifier)
            check(prefix+'乱数中央値同点は失敗', value['板の比較付加価値'], False)
            for seed in range(64):
                changed[f'{identifier}_R{seed:02d}']['symbols'][symbol]['net_r'] = float(np.nextafter(main_r, -np.inf))
            check(prefix+'乱数中央値の直上は成功', hypothesis(changed, identifier)['板の比較付加価値'], True)
            for suffix in assessment.EXECUTION_SUFFIXES:
                changed = deepcopy(base)
                changed[identifier+'_'+suffix]['symbols'][symbol]['average_payoff'] = 1.19
                value = hypothesis(changed, identifier)
                check(prefix+'4執行の1失敗/'+suffix, value['実行感度'], False)
                check(prefix+'執行失敗を全体へ伝達/'+suffix, value['既知経済目安合格'], False)
                check(prefix+'執行失敗と基礎は別/'+suffix, value['基礎候補'], True)
            changed = deepcopy(base)
            for control in assessment.COMPONENTS[identifier]:
                changed[control]['symbols'][symbol]['net_yen'] = 1e9
            check(prefix+'情報比較は円でなくR', hypothesis(changed, identifier)['板の比較付加価値'], True)
    # ----------------------------------------
    # 各乱数母集団と、採否に使わない比較欄の接続を検査する。
    for symbol in assessment.SYMBOLS:
        for identifier, above in (('F01', 24), ('F02', 19), ('F03', 25)):
            group = result['方向乱数'][identifier][symbol]
            prefix = f'乱数/{identifier}/{symbol}/'
            check(prefix+'全64', [r['id'] for r in group['全乱数']], [f'{identifier}_R{i:02d}' for i in range(64)])
            check(prefix+'合計R中央値', group['乱数合計R中央値'], 31.5)
            check(prefix+'円中央値', group['乱数円収支中央値'], 500000.5)
            check(prefix+'同率を含む上位数', group['主以上合計Rの乱数数'], above)
            check(prefix+'円とRを混同しない', group['主以上円収支の乱数数'], 32)
        for identifier, parent in (('F01','F00'),('F02','F01'),('F03','F18'),('F04','F03'),('F10','F01'),('F16','F02')):
            changed = deepcopy(base)
            changed[identifier]['symbols'][symbol].update(net_r=91., net_yen=4321., drawdown_yen=789., candidates=43, trades=28)
            group = assessment.assess(changed)['旧観測と品質と相手確認'][identifier][symbol]
            check(f'比較親/{identifier}/{symbol}', group['比較相手'], parent)
            for output, field in (('合計R差','net_r'),('円収支差','net_yen'),('最大下落差','drawdown_yen'),('候補数差','candidates'),('実取引数差','trades')):
                expected = changed[identifier]['symbols'][symbol][field]-changed[parent]['symbols'][symbol][field]
                check(f'比較差/{identifier}/{symbol}/{field}', group[output], expected)
    changed = deepcopy(base)
    for identifier in ('F10', 'F16'):
        for row in changed[identifier]['symbols'].values():
            row.update(net_r=1e6, net_yen=1e9)
    check('相手だけ優秀でも主を差替えない', assessment.assess(changed)['主仮説'], 'F01')
    changed['F01']['symbols']['NK225']['net_yen'] = -1.
    result = assessment.assess(changed)
    check('副と相手の成功で主不合格を救済しない', result['仮説別']['F01']['既知経済目安合格'], False)
    check('主不合格でも副は別に残す', result['仮説別']['F02']['既知経済目安合格'], True)


def neighbor_cases() -> None:
    """機能: 主副別の全8分母と6/8・50%・最悪-25%を検査する。

    引数: なし。返り値: なし (None)。旧基準に条件を追加しない。
    """
    base = index_fixture()
    for identifier in ('F01', 'F02'):
        for symbol in assessment.SYMBOLS:
            prefix = identifier+'/'+symbol+'/'
            main = base[identifier]['symbols'][symbol]['net_yen']
            changed = deepcopy(base)
            for suffix in assessment.NEIGHBOR_SUFFIXES[:2]:
                changed[identifier+'_'+suffix]['symbols'][symbol]['net_yen'] = -.25*main
            value = hypothesis(changed, identifier)
            check(prefix+'6/8と最悪等号', value['窓距離感度'], True)
            check(prefix+'悪い2近傍も分母', value['近傍詳細'][symbol]['近傍数'], 8)
            check(prefix+'通過数は6', value['近傍詳細'][symbol]['活動黒字PF通過数'], 6)
            changed[identifier+'_'+assessment.NEIGHBOR_SUFFIXES[2]]['symbols'][symbol]['net_yen'] = -.25*main
            check(prefix+'5/8は失敗', hypothesis(changed, identifier)['窓距離感度'], False)
            changed = deepcopy(base)
            for suffix in assessment.NEIGHBOR_SUFFIXES:
                changed[identifier+'_'+suffix]['symbols'][symbol]['net_yen'] = .5*main
            check(prefix+'中央値50%等号', hypothesis(changed, identifier)['窓距離感度'], True)
            for suffix in assessment.NEIGHBOR_SUFFIXES:
                changed[identifier+'_'+suffix]['symbols'][symbol]['net_yen'] = float(np.nextafter(.5*main, -np.inf))
            check(prefix+'中央値50%直下', hypothesis(changed, identifier)['窓距離感度'], False)
            changed = deepcopy(base)
            changed[identifier+'_A080']['symbols'][symbol]['net_yen'] = float(np.nextafter(-.25*main, -np.inf))
            check(prefix+'最悪-25%直下', hypothesis(changed, identifier)['窓距離感度'], False)
            for field, replacement in dict(trades=19, active_sessions=5, long_trades=2, short_trades=2, profit_factor=None, net_yen=0.).items():
                changed = deepcopy(base)
                for suffix in assessment.NEIGHBOR_SUFFIXES[:3]:
                    changed[identifier+'_'+suffix]['symbols'][symbol][field] = replacement
                check(prefix+'近傍活動不足/'+field, hypothesis(changed, identifier)['窓距離感度'], False)
            changed = deepcopy(base)
            for suffix in assessment.NEIGHBOR_SUFFIXES:
                changed[identifier+'_'+suffix]['symbols'][symbol].update(average_payoff=None, without_max_trade=-1., without_max_session=-1.)
            check(prefix+'近傍へ未指定の基準を追加しない', hypothesis(changed, identifier)['窓距離感度'], True)


def malformed_cases() -> None:
    """機能: 全260条件の集合・仕様・数値の不正を人工で拒否させる。

    引数: なし。返り値: なし (None)。正常な無活動は例外でなく不合格。
    """
    base = index_fixture()
    for identifier in base:
        changed = dict(base)
        del changed[identifier]
        check('全条件欠落/'+identifier, rejected(changed), True)
    for name, replacement in (('空辞書', {}), ('配列', []), ('未入力', None)):
        check('不正入力/'+name, rejected(replacement), True)
    changed = deepcopy(base)
    changed['別名'] = changed['F01']
    check('余分な別名重複', rejected(changed), True)
    changed = deepcopy(base)
    changed['F02'] = deepcopy(changed['F01'])
    check('同数でもspec重複', rejected(changed), True)
    changed = deepcopy(base)
    changed['別名'] = changed.pop('F00')
    check('同数のID置換', rejected(changed), True)
    changed = deepcopy(base)
    changed['F01_R63']['spec']['seed'] = 62
    check('乱数seed重複', rejected(changed), True)
    changed = deepcopy(base)
    changed['F01']['spec']['trial_seconds'] = 60.
    check('主仕様差替え', rejected(changed), True)
    changed = deepcopy(base)
    del changed['F01']['spec']
    check('仕様欠落', rejected(changed), True)
    for symbol in assessment.SYMBOLS:
        changed = deepcopy(base)
        del changed['F04']['symbols'][symbol]
        check('市場欠落/'+symbol, rejected(changed), True)
        for field in sorted(assessment.AGGREGATE_FIELDS):
            changed = deepcopy(base)
            del changed['F04']['symbols'][symbol][field]
            check(f'必須項目欠落/{symbol}/{field}', rejected(changed), True)
            for label, replacement in (('非数', float('nan')), ('正無限', float('inf')), ('負無限', -float('inf')), ('真偽', True), ('文字', '1')):
                changed = deepcopy(base)
                changed['F04']['symbols'][symbol][field] = replacement
                check(f'必須項目不正/{symbol}/{field}/{label}', rejected(changed), True)
            if field not in assessment.RATIO_FIELDS:
                changed = deepcopy(base)
                changed['F04']['symbols'][symbol][field] = None
                check(f'非比率のNone拒否/{symbol}/{field}', rejected(changed), True)
        for identifier in ('F01_R63', 'F02_R63', 'F03_R63'):
            changed = deepcopy(base)
            changed[identifier]['symbols'][symbol]['net_r'] = float('nan')
            check(f'乱数末尾非有限/{symbol}/{identifier}', rejected(changed), True)
        for field in assessment.COUNT_FIELDS:
            changed = deepcopy(base)
            changed['F01']['symbols'][symbol][field] = 3.5
            check(f'件数小数/{symbol}/{field}', rejected(changed), True)
        for field in assessment.NONNEGATIVE_FIELDS:
            changed = deepcopy(base)
            changed['F02']['symbols'][symbol][field] = -1.
            check(f'非負項目が負/{symbol}/{field}', rejected(changed), True)
        for field in ('active_sessions', 'positive_sessions'):
            changed = deepcopy(base)
            changed['F01']['symbols'][symbol][field] = 14
            check(f'13場超過/{symbol}/{field}', rejected(changed), True)
    for identifier in ('F01', 'F02'):
        changed = deepcopy(base)
        changed[identifier]['symbols'] = {symbol: statistics.aggregate([]) for symbol in assessment.SYMBOLS}
        check('無取引は資料不正でない/'+identifier, rejected(changed), False)
        check('無取引は採用しない/'+identifier, hypothesis(changed, identifier)['既知経済目安合格'], False)


def numeric_inheritance() -> None:
    """機能: 旧固定の数値・統計・近傍述語との接続を原文と人工で照合する。

    引数: なし。返り値: なし (None)。旧結果の損益は読まない。
    """
    previous = ROOT/'work/wave_v40/assessment.py'
    old_tree = ast.parse(previous.read_text(encoding='utf-8'))
    new_tree = ast.parse((HERE/'assessment.py').read_text(encoding='utf-8'))
    expressions = []
    for tree in (old_tree, new_tree):
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'neighbor_activity')
        expressions.append([ast.dump(node, include_attributes=False) for node in function.body[1:]])
    check('旧近傍述語と構文同一', expressions[1], expressions[0])
    expected = dict(決済数=20, 活動場数=6, 買い決済数=3, 売り決済数=3, PF=1.2, 平均勝負比=1.2,
        最大勝ち取引除外収支下限=0., 最大勝ち場除外収支下限=0., 近傍活動黒字PF合格数=6,
        近傍全数=8, 近傍収支中央値比下限=.5, 近傍最悪収支比下限=-.25)
    check('旧数値を変更しない', design.rules()['数値基準'], expected)
    check('設計と採否の5成分対応', design.COMPONENTS, assessment.COMPONENTS)
    check('設計と採否の4執行対応', design.EXECUTION_SUFFIXES, assessment.EXECUTION_SUFFIXES)
    check('設計と採否の8近傍対応', tuple(row[0] for row in design.SENSITIVITIES), assessment.NEIGHBOR_SUFFIXES)


def main() -> None:
    """機能: 人工だけで採否を検算し、結果前の実装・設計指紋を固定する。

    引数: なし。返り値: なし (None)。不一致は記録して非0終了する。
    """
    socket.create_connection = denied
    socket.socket.connect = denied
    urllib.request.urlopen = denied
    paths = [HERE/'assessment.py', HERE/'design.py', assessment.STATISTICS_PATH, Path(__file__),
             ROOT/'work/wave_v40/assessment.py', ROOT/'work/wave_v40/assessment_fixed.json']
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    statistics_cases()
    comparison_cases()
    neighbor_cases()
    malformed_cases()
    numeric_inheritance()
    check('主68条件', len(design.catalog()), 68)
    check('補助192条件', len(design.supplementary()), 192)
    check('全260一意', len({s['id'] for s in design.catalog()+design.supplementary()}), 260)
    check('旧統計ファイル位置', str(Path(statistics.__file__).resolve()), str(assessment.STATISTICS_PATH.resolve()))
    after = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    check('対象コード前後不変', after, before)
    failures = [row for row in RECORDS if not row['合格']]
    result = dict(全合格=not failures, 人工検査数=len(RECORDS), 不合格数=len(failures),
        実相場損益計算数=0, 新損益読取=False, 原本参照数=0, 現在API取得数=0, 保存ライブ使用=False,
        旧統計を無変更使用=True, 対象実装不変=before==after, SHA256=before, 不合格=failures, 検査=RECORDS)
    # ----------------------------------------
    # 集合比較だけに使ったsetを保存可能な配列へ変換し、非有限値の混入を禁止する。
    data = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2,
                      default=lambda value: sorted(value) if isinstance(value, set) else str(value))
    (HERE/'check_assessment.json').write_text(data, encoding='utf-8')
    if not failures:
        fixed = dict(損益計算前=True, 新損益読取=False, 判定対象=['F01','F02'], 主仮説='F01', 副仮説='F02',
            主条件数=68, 方向乱数条件数=192, 全条件数=260,
            仕様=design.rules(), 条件=design.catalog()+design.supplementary(),
            入力契約='全260のID→spec/symbols。非有限と集合不正は拒否、比率Noneと無取引は基礎不合格。',
            採用式='各仮説を独立に、基礎 AND 情報R厳密超過 AND 全4執行基礎 AND 全8近傍の固定条件で評価。',
            副案や相手確認は主案の不合格を救済しない=True, 将来保証又は実装完備を意味しない=True,
            人工検査数=len(RECORDS), SHA256=dict(before, **{'work/wave_v42/check_assessment.json':sha(HERE/'check_assessment.json')}))
        (HERE/'assessment_fixed.json').write_text(json.dumps(fixed, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    lines = ['# 採否と旧統計の人工検査', '',
        f'人工 {len(RECORDS)} 検査、合格 {len(RECORDS)-len(failures)}、不合格 {len(failures)}。新損益・原本・現在データは読んでいない。', '',
        '旧統計を無変更で用い、1枚の金額・枚数・R・含み込みDDと最大勝ち除外を人工台帳で照合した。',
        'F01とF02は独立判定。各5対照と64乱数中央値へのR厳密超過、全4執行、全8近傍を別々に検査した。',
        '近傍は全8を分母として6以上、全8中央値50%以上・最悪−25%以上。境界等号と直下を区別する。',
        '活動不足・比率未定義・集中依存を見逃さず、副案・相手・良い近傍で主案を差し替えない。',
        '近傍へ平均勝負比や最大勝ち除外の新たな採否条件は追加しない。数値基準は旧版のまま。',
        '全260 IDの各欠落、同数のID置換、別名重複、仕様・seed差替え、必須集計欠落、NaN/無限/型不正を拒否した。',
        '辞書化前に上書きされた重複や数値相互の会計整合は、この集計入力だけでは再構成できない。資料読込と独立会計の検査を別途要する。', '', '## 不一致', '']
    lines += [str(row) for row in failures] or ['なし。']
    (HERE/'check_assessment.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=not failures, 人工検査数=len(RECORDS), 不合格=failures), ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()


