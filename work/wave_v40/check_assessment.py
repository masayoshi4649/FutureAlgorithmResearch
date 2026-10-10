"""実相場を使わず、固定281条件の採否と旧統計の接続を人工検算する。"""

from __future__ import annotations

from copy import deepcopy
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
    """機能: 固定281仕様の人工比較集計を作る。

    引数: なし。返り値: spec/symbolsを持つ全条件辞書 (dict)。
    採否境界を独立に動かすためR比較値だけを人工設定し、実成績とは呼ばない。
    """
    rows = {}
    templates = {symbol: good(symbol) for symbol in assessment.SYMBOLS}
    for spec in design.catalog() + design.supplementary():
        values = deepcopy(templates)
        for value in values.values():
            value['net_r'] = 39.
        rows[spec['id']] = dict(spec=deepcopy(spec), symbols=values)
    for symbol in assessment.SYMBOLS:
        rows['B00']['symbols'][symbol]['net_r'] = 40.
        rows['B12']['symbols'][symbol]['net_r'] = 45.
        for identifier in ('B00', 'B01', 'B12'):
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


def comparison_cases() -> None:
    """機能: 主と全対照の厳密超過、乱数中央値、相手を別欄にする接続を検査する。

    引数: なし。返り値: なし (None)。
    """
    base = index_fixture()
    result = assessment.assess(base)
    for field in ('基礎候補', '板の比較付加価値', '実行感度', '窓距離感度', '既知経済目安合格'):
        check('全合格人工/'+field, result[field], True)
    for field in ('未知での有効性確認', '全体目標達成'):
        check('既知合格を過大主張しない/'+field, result[field], False)
    for symbol in assessment.SYMBOLS:
        for identifier, above in (('B00', 24), ('B01', 25), ('B12', 19)):
            group = result['方向乱数'][identifier][symbol]
            check(f'乱数/{identifier}/{symbol}/64件', len(group['全乱数']), 64)
            check(f'乱数/{identifier}/{symbol}/中央値', group['乱数合計R中央値'], 31.5)
            check(f'乱数/{identifier}/{symbol}/同率込みR', group['主以上合計Rの乱数数'], above)
            check(f'乱数/{identifier}/{symbol}/円', group['主以上円収支の乱数数'], 32)
        for field, replacement in dict(trades=19, active_sessions=5, long_trades=2, short_trades=2,
            profit_factor=None, average_payoff=None, without_max_trade=-1., without_max_session=-1., net_yen=0.).items():
            changed = deepcopy(base)
            changed['B00']['symbols'][symbol][field] = replacement
            value = assessment.assess(changed)
            check(f'片市場の主不足/{symbol}/{field}', value['既知経済目安合格'], False)
            check(f'主不足なら近傍も不合格/{symbol}/{field}', value['窓距離感度'], False)
        for identifier in assessment.COMPONENTS:
            for difference in (0., 1.):
                changed = deepcopy(base)
                changed[identifier]['symbols'][symbol]['net_r'] = 40.+difference
                value = assessment.assess(changed)
                check(f'R厳密超過/{identifier}/{symbol}/{difference}', value['板の比較付加価値'], False)
                check(f'R失敗と基本を区別/{identifier}/{symbol}/{difference}', value['基礎候補'], True)
        changed = deepcopy(base)
        for seed in range(64):
            changed[f'B00_R{seed:02d}']['symbols'][symbol]['net_r'] = 40.
        check('乱数中央値同率/'+symbol, assessment.assess(changed)['板の比較付加価値'], False)
        for suffix in assessment.EXECUTION_SUFFIXES:
            changed = deepcopy(base)
            changed['B00_'+suffix]['symbols'][symbol]['average_payoff'] = 1.19
            value = assessment.assess(changed)
            check(f'執行全4必要/{symbol}/{suffix}', value['実行感度'], False)
            check(f'執行不足と基本を区別/{symbol}/{suffix}', value['基礎候補'], True)
        changed = deepcopy(base)
        for seed in range(64):
            changed[f'B12_R{seed:02d}']['symbols'][symbol]['net_r'] = 45.
        value = assessment.assess(changed)
        check('B12自身の乱数群で判定/'+symbol, value['相手確認']['B12'][symbol]['同機会乱数中央値超過'], False)
        check('B12失敗でも主は独立/'+symbol, value['既知経済目安合格'], True)
    changed = deepcopy(base)
    for identifier in ('B10', 'B11', 'B12'):
        for row in changed[identifier]['symbols'].values():
            row.update(net_r=1e6, net_yen=1e9)
    check('独立価格や相手に劣っても別欄', assessment.assess(changed)['既知経済目安合格'], True)
    changed['B00']['symbols']['NK225']['net_yen'] = -1.
    check('相手成功で主を差替えない', assessment.assess(changed)['既知経済目安合格'], False)
    changed = deepcopy(base)
    for identifier in assessment.COMPONENTS:
        for row in changed[identifier]['symbols'].values():
            row['net_yen'] = 1e9
    check('情報比較は円でなくR', assessment.assess(changed)['板の比較付加価値'], True)


def neighbor_cases() -> None:
    """機能: 全8の分母、6/8活動基準、中央値50%・最悪-25%の境界を検査する。

    引数: なし。返り値: なし (None)。平均比と集中回避を近傍へ追加しない。
    """
    base = index_fixture()
    for symbol in assessment.SYMBOLS:
        main = base['B00']['symbols'][symbol]['net_yen']
        changed = deepcopy(base)
        for suffix in assessment.NEIGHBOR_SUFFIXES[:2]:
            changed['B00_'+suffix]['symbols'][symbol]['net_yen'] = -.25*main
        value = assessment.assess(changed)
        check('6/8と最悪等号合格/'+symbol, value['窓距離感度'], True)
        check('不利な2条件も分母へ/'+symbol, value['近傍詳細'][symbol]['近傍数'], 8)
        check('6通過数/'+symbol, value['近傍詳細'][symbol]['活動黒字PF通過数'], 6)
        changed['B00_'+assessment.NEIGHBOR_SUFFIXES[2]]['symbols'][symbol]['net_yen'] = -.25*main
        check('5/8は拒否/'+symbol, assessment.assess(changed)['窓距離感度'], False)
        changed = deepcopy(base)
        for suffix in assessment.NEIGHBOR_SUFFIXES:
            changed['B00_'+suffix]['symbols'][symbol]['net_yen'] = .5*main
        check('中央値50%等号/'+symbol, assessment.assess(changed)['窓距離感度'], True)
        for suffix in assessment.NEIGHBOR_SUFFIXES:
            changed['B00_'+suffix]['symbols'][symbol]['net_yen'] = .5*main-1.
        check('中央値50%未満/'+symbol, assessment.assess(changed)['窓距離感度'], False)
        changed = deepcopy(base)
        changed['B00_A080']['symbols'][symbol]['net_yen'] = -.25*main-1.
        check('最悪-25%未満/'+symbol, assessment.assess(changed)['窓距離感度'], False)
        for field, replacement in dict(trades=19, active_sessions=5, long_trades=2,
                                       short_trades=2, profit_factor=None, net_yen=0.).items():
            changed = deepcopy(base)
            for suffix in assessment.NEIGHBOR_SUFFIXES[:3]:
                changed['B00_'+suffix]['symbols'][symbol][field] = replacement
            check(f'活動又はPF不足を成功にしない/{symbol}/{field}', assessment.assess(changed)['窓距離感度'], False)
        changed = deepcopy(base)
        for suffix in assessment.NEIGHBOR_SUFFIXES:
            changed['B00_'+suffix]['symbols'][symbol].update(average_payoff=None, without_max_trade=-1., without_max_session=-1.)
        check('近傍に未指定の追加基準を課さない/'+symbol, assessment.assess(changed)['窓距離感度'], True)


def malformed_cases() -> None:
    """機能: 必須ID・仕様・必須集計の欠落、重複、非有限値を拒否する。

    引数: なし。返り値: なし (None)。ゼロ活動は例外でなく不合格を確認する。
    """
    base = index_fixture()
    for identifier in base:
        changed = dict(base)
        del changed[identifier]
        check('全条件の欠落拒否/'+identifier, rejected(changed), True)
    for name, replacement in (('空辞書', {}), ('配列', []), ('未入力', None)):
        check('不正入力/'+name, rejected(replacement), True)
    changed = deepcopy(base)
    changed['別名'] = changed['B00']
    check('余計な別名重複を拒否', rejected(changed), True)
    changed = deepcopy(base)
    changed['B02'] = deepcopy(changed['B01'])
    check('同数でもspecID重複を拒否', rejected(changed), True)
    changed = deepcopy(base)
    changed['B00_R63']['spec']['seed'] = 62
    check('乱数seed重複を拒否', rejected(changed), True)
    changed = deepcopy(base)
    changed['B00']['spec']['trial_seconds'] = 60.
    check('主仕様差替えを拒否', rejected(changed), True)
    changed = deepcopy(base)
    del changed['B00']['spec']
    check('仕様欠落を拒否', rejected(changed), True)
    for symbol in assessment.SYMBOLS:
        changed = deepcopy(base)
        del changed['B02']['symbols'][symbol]
        check('市場欠落/'+symbol, rejected(changed), True)
        for field in assessment.AGGREGATE_FIELDS:
            changed = deepcopy(base)
            del changed['B02']['symbols'][symbol][field]
            check(f'必須集計欠落/{symbol}/{field}', rejected(changed), True)
            for label, replacement in (('非数', float('nan')), ('正無限', float('inf')), ('負無限', -float('inf'))):
                changed = deepcopy(base)
                changed['B02']['symbols'][symbol][field] = replacement
                check(f'非有限拒否/{symbol}/{field}/{label}', rejected(changed), True)
        for identifier in ('B00_R63', 'B01_R63', 'B12_R63'):
            changed = deepcopy(base)
            changed[identifier]['symbols'][symbol]['net_r'] = float('nan')
            check(f'乱数末尾の非有限/{symbol}/{identifier}', rejected(changed), True)
        for field, replacement in (('trades', 20.5), ('active_sessions', 14), ('loss_yen', -1.),
                                   ('net_yen', True), ('net_r', '1')):
            changed = deepcopy(base)
            changed['B00']['symbols'][symbol][field] = replacement
            check(f'不正型値/{symbol}/{field}', rejected(changed), True)
    changed = deepcopy(base)
    changed['B00']['symbols'] = {symbol: statistics.aggregate([]) for symbol in assessment.SYMBOLS}
    check('無取引は資料例外にしない', rejected(changed), False)
    check('無取引は候補合格にしない', assessment.assess(changed)['既知経済目安合格'], False)


def main() -> None:
    """機能: 人工だけを検査し、設計と実装の指紋を結果前の証跡へ固定する。

    引数: なし。返り値: なし (None)。不一致は保存したうえ非0終了する。
    """
    socket.create_connection = denied
    socket.socket.connect = denied
    urllib.request.urlopen = denied
    paths = [HERE/'assessment.py', HERE/'design.py', assessment.STATISTICS_PATH, Path(__file__)]
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    statistics_cases()
    comparison_cases()
    neighbor_cases()
    malformed_cases()
    check('主89条件', len(design.catalog()), 89)
    check('補助192条件', len(design.supplementary()), 192)
    check('全281一意', len({s['id'] for s in design.catalog()+design.supplementary()}), 281)
    check('旧統計のファイル位置', str(Path(statistics.__file__).resolve()), str(assessment.STATISTICS_PATH.resolve()))
    after = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    check('対象コード前後不変', after, before)
    failures = [r for r in RECORDS if not r['合格']]
    result = dict(全合格=not failures, 人工検査数=len(RECORDS), 不合格数=len(failures),
        実相場損益計算数=0, 原本参照数=0, 現在API取得数=0, 保存ライブ使用=False,
        旧統計を無変更使用=True, 対象実装不変=before==after, SHA256=before,
        不合格=failures, 検査=RECORDS)
    (HERE/'check_assessment.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    if not failures:
        fixed = dict(損益計算前=True, 判定対象='B00', 主条件数=89, 方向乱数条件数=192, 全条件数=281,
            仕様=design.rules(), 条件=design.catalog()+design.supplementary(),
            入力契約='全281のID→spec/symbols。非有限と集合不正は拒否、比率Noneと無取引は基礎不合格。',
            採用式='主基礎 AND 情報R厳密超過 AND 全4執行基礎 AND 全8近傍の固定条件。',
            相手と独立価格は別判定=True, 将来保証又は実装完備を意味しない=True,
            人工検査数=len(RECORDS), SHA256=dict(before, **{'work/wave_v40/check_assessment.json':sha(HERE/'check_assessment.json')}))
        (HERE/'assessment_fixed.json').write_text(json.dumps(fixed, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    lines = ['# 採否と旧統計の人工検査', '',
        f'人工 {len(RECORDS)} 検査、合格 {len(RECORDS)-len(failures)}、不合格 {len(failures)}。新しい実相場損益は計算していない。', '',
        '旧v39のsession・aggregate・basicを無変更で使用し、1枚台帳の金額・枚数・R・期間時価DDを人工で照合した。',
        '主B00の基礎、5対照と乱数中央値のR厳密超過、4執行、8近傍を別々に判定する。',
        '近傍は全8を分母とし、各市場6/8の活動・黒字・PF、全8中央値50%と最悪−25%の等号／不足を検査した。',
        '主不合格は近傍や相手確認で救済しない。B12と独立価格B10/B11は別欄で、最良条件への差替えはしない。',
        '比率Noneと無取引は正常な不合格。NaN/無限、全条件の欠落、別名重複・仕様/seed差替えは資料不正として拒否する。',
        '辞書化する前に上書きされた重複は採否だけでは見えないため、読込み側の資料一覧でもID一意性を検査する。', '',
        '## 不一致', '']
    lines += [str(row) for row in failures] or ['なし。']
    (HERE/'check_assessment.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=not failures, 人工検査数=len(RECORDS), 不合格=failures), ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
