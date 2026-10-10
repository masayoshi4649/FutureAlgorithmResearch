"""人工台帳から金額・枚数・期間下落と事前採否を独立検査する。"""

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
import trade_statistics as statistics


HERE = Path(__file__).resolve().parent
RECORDS: list[dict] = []


def denied(*args: object, **kwargs: object) -> None:
    """機能: 人工検査からの通信を拒否する。

    引数: 任意(object)。返り値: なし(None)、常に例外。
    """
    raise AssertionError('人工台帳検査では通信しません')


def digest(path: Path) -> str:
    """機能: 検査対象の内容指紋を得る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(name: str, actual: object, expected: object) -> None:
    """機能: 独立期待値と比較し、成功・不一致を省略せず残す。

    引数: name(str)、actual/expected(object)。返り値: なし(None)。
    """
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        passed = actual is not None and math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9)
    else:
        passed = actual == expected
    RECORDS.append(dict(検査=name, 合格=bool(passed), 実値=actual, 期待=expected))


def drawdown(points: list[float]) -> float:
    """機能: 時系列の含み込み口座から最大下落を別の逐次式で求める。

    引数: points(list[float])。返り値: 最大下落(float)。
    """
    peak = 0.
    loss = 0.
    for value in points:
        if value > peak:
            peak = value
        if peak - value > loss:
            loss = peak - value
    return loss


def fixture(symbol: str, session_id: str, profits: list[float], risks: list[float] | None = None,
            sides: list[int] | None = None, equity: list[float] | None = None) -> tuple[dict, dict]:
    """機能: 注文器を呼ばず、正の初期リスクを持つ1枚人工台帳を作る。

    引数: symbol/session_id(str)、profits/risks/equity(list[float]|None)、sides(list[int]|None)。
    返り値: 原本時刻と人工結果(tuple[dict,dict])。実相場データは使用しない。
    """
    count = len(profits)
    risks = [2.] * count if risks is None else risks
    sides = [1 if i % 2 == 0 else -1 for i in range(count)] if sides is None else sides
    trades = np.zeros((count, 10), dtype=float)
    path = [0.]
    realized = 0.
    for i, (pnl, risk, side) in enumerate(zip(profits, risks, sides)):
        assert risk > 0 and math.isfinite(risk) and side in (-1, 1)
        entry = 3 * i + 1
        exit_row = entry + 2
        trades[i] = [entry, exit_row, side, 100., 100. + pnl * side, risk, pnl, 1 if pnl < 0 else 2, 3*i, entry]
        path.extend([realized, realized + pnl / 2., realized + pnl])
        realized += pnl
    if equity is not None:
        assert len(equity) >= max(1, count * 3 + 1)
        assert math.isclose(equity[-1], realized)
        path = equity
    curve = np.zeros((len(path), 4), dtype=float)
    curve[:, 1] = path
    ready = dict(symbol=symbol, session=session_id, time_s=np.arange(len(path), dtype=float) * 60.)
    result = dict(trades=trades, curve=curve, stats=np.asarray([realized, drawdown(path), count+3, count+1, 1.]))
    return ready, result


def good(symbol: str = 'TOPIX') -> dict:
    """機能: 最低取引数・活動数・売り数と比率境界に一致する実台帳型集計を作る。

    引数: symbol(str)。返り値: 期間集計(dict)。20取引・6場・17買い3売り・両比率1.2。
    """
    profits = [6., -5.] * 10
    quantities = [4, 4, 3, 3, 3, 3]
    rows = []
    start = 0
    for i, size in enumerate(quantities):
        sides = [1 if j < 17 else -1 for j in range(start, start+size)]
        ready, result = fixture(symbol, f'2026-01-{i+1:02d}_Day', profits[start:start+size], sides=sides)
        rows.append(statistics.session(ready, result))
        start += size
    return statistics.aggregate(rows)


def index_fixture() -> dict:
    """機能: 既定240条件の人工集計を作り、情報比較と採否を分離検査する。

    引数: なし。返り値: 条件別人工集計(dict)。実損益の探索・読取りはしない。
    """
    index = {}
    for spec in design.catalog() + design.supplementary():
        values = {symbol:good(symbol) for symbol in ('TOPIX', 'NK225')}
        for value in values.values():
            value['net_r'] = 39.
        index[spec['id']] = dict(symbols=values)
    for symbol in ('TOPIX', 'NK225'):
        index['I00']['symbols'][symbol]['net_r'] = 40.
        for seed in range(64):
            index[f'I00_R{seed:02d}']['symbols'][symbol]['net_r'] = float(seed)
            index[f'I00_R{seed:02d}']['symbols'][symbol]['net_yen'] = 1. if seed < 32 else 1e6
        for identifier in ('I05', 'I06'):
            index[identifier]['symbols'][symbol]['net_r'] = 45.
    return index


def rejects_nonfinite(index: dict) -> bool:
    """機能: 非有限な比較母集団を合否計算の前に拒否することを調べる。

    引数: index(dict)。返り値: ValueErrorで拒否したか(bool)。
    """
    try:
        assessment.assess(index)
    except ValueError:
        return True
    return False


def accounting_cases() -> None:
    """機能: 全決済・ゼロ・初期R・円倍率・時間と接続下落を直接台帳から検算する。

    引数: なし。返り値: なし(None)、検査明細へ追記。
    """
    for symbol, factor in (('TOPIX', 1000.), ('NK225', 10.)):
        ready, result = fixture(symbol, '2026-01-01_Day', [4., -2., 0., 6.], [2., 4., 2., 3.])
        row = statistics.session(ready, result)
        expected = dict(profit_yen=10*factor, loss_yen=2*factor, net_yen=8*factor,
            profit_units=2, loss_units=1, zero_units=1, trades=4, net_r=3.5,
            long_trades=2, short_trades=2, held_minutes=8., candidates=7, accepted=5, cancelled=1,
            drawdown_yen=2*factor, minimum_yen=0., maximum_yen=8*factor, max_win_yen=6*factor)
        for key, value in expected.items():
            check(f'単場/{symbol}/{key}', row[key], value)
        total = statistics.aggregate([row])
        for key, value in dict(profit_factor=5., average_payoff=2.5, without_max_trade=2*factor,
                               without_max_session=0., active_sessions=1, positive_sessions=1).items():
            check(f'単場期間/{symbol}/{key}', total[key], value)
        # ----------------------------------------
        # 各曲線の当場損益を前場終値へ平行移動し、全時点の口座を直接連結する。
        paths = [([5.], [0., 12., -4., 5.]), ([-8.], [0., 3., -12., -8.]),
                 ([10.], [0., -3., 18., 10.]), ([], [0., 0., 0., 0.])]
        names = ['2026-01-01_Day', '2026-01-01_Night', '2026-01-02_Day', '2026-01-02_Night']
        rows = []
        joined = [0.]
        base = 0.
        for name, (profits, path) in zip(names, paths):
            ready, result = fixture(symbol, name, profits, equity=path)
            rows.append(statistics.session(ready, result))
            joined.extend((base + value)*factor for value in path)
            base += path[-1]
        value = statistics.aggregate([rows[2], rows[3], rows[1], rows[0]])
        check(f'接続DD/{symbol}/原本曲線全時点', value['drawdown_yen'], drawdown(joined))
        check(f'接続DD/{symbol}/具体値', value['drawdown_yen'], 19*factor)
        check(f'接続DD/{symbol}/終値だけでは測れない', value['drawdown_yen'] > 8*factor, True)
        check(f'接続DD/{symbol}/終値', value['net_yen'], 7*factor)
        check(f'接続DD/{symbol}/活動数', value['active_sessions'], 3)
        check(f'接続DD/{symbol}/最大取引除去', value['without_max_trade'], -3*factor)
        check(f'接続DD/{symbol}/最大場除去', value['without_max_session'], -3*factor)


def basic_cases() -> None:
    """機能: 閾値等号・各不足・無取引・集中・比率未定義を拒否することを検査する。

    引数: なし。返り値: なし(None)、検査明細へ追記。
    """
    base = good()
    check('最低値を満たす有効人工20取引', statistics.basic(base)['合格'], True)
    for key, expected in dict(trades=20, active_sessions=6, long_trades=17, short_trades=3,
                              profit_factor=1.2, average_payoff=1.2).items():
        check(f'境界/{key}', base[key], expected)
    fields = dict(trades=19, active_sessions=5, long_trades=2, short_trades=2,
                  net_yen=0., profit_factor=1.199, average_payoff=1.199,
                  without_max_trade=-1., without_max_session=-1.)
    for key, value in fields.items():
        changed = deepcopy(base)
        changed[key] = value
        check(f'不足を拒否/{key}', statistics.basic(changed)['合格'], False)
    for key in ('without_max_trade', 'without_max_session'):
        changed = deepcopy(base)
        changed[key] = 0.
        check(f'大勝ち除去等号/{key}', statistics.basic(changed)['合格'], True)
    for name, pnls in (('無取引', []), ('全損失', [-1.]*24), ('全同値', [0.]*24),
                       ('全利益', [2.]*24), ('単発大勝ち', [100.] + [-1.]*23)):
        rows = []
        for i in range(6):
            ready, result = fixture('TOPIX', f'2026-02-{i+1:02d}_Day', pnls[i*4:(i+1)*4])
            rows.append(statistics.session(ready, result))
        total = statistics.aggregate(rows)
        check(f'不適切な成績/{name}', statistics.basic(total)['合格'], False)
        if name in ('無取引', '全同値', '全利益'):
            check(f'比率未定義/{name}/PF', total['profit_factor'], None)
            check(f'比率未定義/{name}/平均', total['average_payoff'], None)
        if name == '単発大勝ち':
            check('単発大勝ち/PFだけなら通る', total['profit_factor'] >= 1.2, True)
            check('単発大勝ち/最大勝ち除去が拒否', total['without_max_trade'] < 0., True)
    check('空の期間', statistics.basic(statistics.aggregate([]))['合格'], False)
    # ----------------------------------------
    # PFと1枚当たり平均比率は異なり、勝率の高さで後者を代用しない。
    for name, pnls, pf, payoff in (('勝率高い小利大損', [1.]*19+[-2.], 9.5, .5),
                                 ('平均比良い総損失大', [20.]+[-1.]*19, 20/19, 20.)):
        ready, result = fixture('TOPIX', '2026-01-01_Day', pnls)
        total = statistics.aggregate([statistics.session(ready, result)])
        check(f'{name}/PF', total['profit_factor'], pf)
        check(f'{name}/平均比', total['average_payoff'], payoff)
    for numerator, denominator, expected in ((1., 0., None), (0., 0., None), (1., -1., None), (0., 2., 0.),
        (float('inf'), 2., None), (1., float('inf'), None), (float('nan'), 2., None),
        (1., float('nan'), None), (1e308, 1e-308, None)):
        check(f'分母処理/{numerator}/{denominator}', statistics.ratio(numerator, denominator), expected)
    for key in ('profit_factor', 'average_payoff'):
        for label, value in (('未定義', None), ('非数', float('nan')), ('無限大', float('inf'))):
            changed = deepcopy(base)
            changed[key] = value
            check(f'比率不正/{key}/{label}', statistics.basic(changed)['合格'], False)


def assessment_cases() -> None:
    """機能: 両銘柄の積条件、合計R対照、乱数・実行感度と未検証表示を検算する。

    引数: なし。返り値: なし(None)、検査明細へ追記。
    """
    base = index_fixture()
    result = assessment.assess(base)
    for flag in ('基礎候補', '板の比較付加価値', '実行感度', '既知経済目安合格'):
        check(f'合格人工/{flag}', result[flag], True)
    for flag in ('未知での有効性確認', '全体目標達成'):
        check(f'合格人工でも/{flag}', result[flag], False)
    for symbol in ('TOPIX', 'NK225'):
        item = result['成分対照'][symbol]
        check(f'64固定乱数/{symbol}/中央値', item['乱数合計R中央値'], 31.5)
        check(f'64固定乱数/{symbol}/主以上R同値込み', item['主以上合計Rの乱数数'], 24)
        check(f'64固定乱数/{symbol}/主以上円', item['主以上円収支の乱数数'], 32)
        # ----------------------------------------
        # 親指標を壊した銘柄だけでも、相手市場の成績では救済できない。
        for key, replacement in (('trades', 19), ('active_sessions', 5), ('short_trades', 2),
                                 ('profit_factor', None), ('average_payoff', None), ('net_yen', -1.)):
            changed = deepcopy(base)
            changed['I00']['symbols'][symbol][key] = replacement
            check(f'片市場不合格/{symbol}/{key}', assessment.assess(changed)['既知経済目安合格'], False)
        for identifier in ('I01', 'I03', 'I19', 'I04'):
            for difference in (0., 1.):
                changed = deepcopy(base)
                changed[identifier]['symbols'][symbol]['net_r'] = 40. + difference
                check(f'Rは厳密超過/{symbol}/{identifier}/{difference}', assessment.assess(changed)['既知経済目安合格'], False)
        changed = deepcopy(base)
        for seed in range(64):
            changed[f'I00_R{seed:02d}']['symbols'][symbol]['net_r'] = 40.
        check(f'乱数中央値同率を拒否/{symbol}', assessment.assess(changed)['既知経済目安合格'], False)
        for identifier in ('I00_D01', 'I00_D05', 'I00_D15', 'I00_OBS'):
            changed = deepcopy(base)
            changed[identifier]['symbols'][symbol]['average_payoff'] = 1.19
            verdict = assessment.assess(changed)
            check(f'全実行感度必要/{symbol}/{identifier}', verdict['既知経済目安合格'], False)
            check(f'実行不合格と基本を分離/{symbol}/{identifier}', verdict['基礎候補'], True)
    changed = deepcopy(base)
    for identifier in ('I01', 'I03', 'I19', 'I04'):
        for value in changed[identifier]['symbols'].values():
            value['net_yen'] = 1e12
    check('対照の円額が大きくても情報比較はR', assessment.assess(changed)['板の比較付加価値'], True)
    changed = deepcopy(base)
    for identifier in ('I05', 'I06'):
        for value in changed[identifier]['symbols'].values():
            value['net_r'] = -1e6
            value['net_yen'] = -1e12
            value['profit_factor'] = None
    check('相手確認候補の失敗は主と別記', assessment.assess(changed)['既知経済目安合格'], True)
    changed['I00']['symbols']['NK225']['net_yen'] = -1.
    for identifier in ('I05', 'I06'):
        for value in changed[identifier]['symbols'].values():
            value.update(net_r=1e6, net_yen=1e12, profit_factor=2.)
    check('相手確認だけの成功で主を救済しない', assessment.assess(changed)['既知経済目安合格'], False)
    for symbol in ('TOPIX', 'NK225'):
        changed = deepcopy(base)
        changed['I00']['symbols'][symbol]['net_r'] = float('nan')
        check(f'非数Rを拒否/{symbol}', rejects_nonfinite(changed), True)
        changed['I00']['symbols'][symbol]['net_r'] = float('inf')
        check(f'無限Rを拒否/{symbol}', rejects_nonfinite(changed), True)
        changed = deepcopy(base)
        changed['I19']['symbols'][symbol]['net_r'] = -float('inf')
        check(f'負の無限R対照を拒否/{symbol}', rejects_nonfinite(changed), True)
        changed = deepcopy(base)
        changed['I00_R63']['symbols'][symbol]['net_r'] = float('nan')
        check(f'非数の乱数1件を拒否/{symbol}', rejects_nonfinite(changed), True)


def design_cases() -> None:
    """機能: 実装の条件数と比較対象が設計の固定値に対応することを調べる。

    引数: なし。返り値: なし(None)、検査明細へ追記。
    """
    main, random = design.catalog(), design.supplementary()
    ids = {spec['id'] for spec in main + random}
    check('主48条件', len(main), 48)
    check('補助192条件', len(random), 192)
    check('全ID一意240', len(ids), 240)
    check('基礎条件の固定値', design.rules()['基礎条件'], dict(各銘柄決済数下限=20,
        各銘柄活動セッション下限=6, 各銘柄ロングショート各下限=3, 各銘柄収支正=True,
        利益損失比下限=1.2, 平均利益平均損失比下限=1.2,
        最大勝ち取引除外収支非負=True, 最大黒字セッション除外収支非負=True))
    check('円倍率は銘柄別', design.rules()['円倍率'], statistics.FACTORS)
    for identifier in ('I00', 'I01', 'I03', 'I19', 'I04', 'I00_D01', 'I00_D05', 'I00_D15', 'I00_OBS'):
        check(f'固定採否対象存在/{identifier}', identifier in ids, True)


def main() -> None:
    """機能: 人工だけを実行し、合否・非有限反例・実装指紋を保存する。

    引数: なし。返り値: なし(None)。不一致時は保存後に非0終了する。
    """
    socket.create_connection = denied
    socket.socket.connect = denied
    urllib.request.urlopen = denied
    names = ('trade_statistics.py', 'assessment.py', 'design.py')
    before = {name:digest(HERE/name) for name in names}
    accounting_cases()
    basic_cases()
    assessment_cases()
    design_cases()
    after = {name:digest(HERE/name) for name in names}
    check('検査前後の対象ソース不変', after, before)
    failures = [row for row in RECORDS if not row['合格']]
    result = dict(全合格=not failures, 人工検査数=len(RECORDS), 不合格数=len(failures),
        実相場損益計算数=0, 原本参照数=0, 現在API取得数=0,
        検査実装SHA256=digest(Path(__file__)), 対象実装SHA256=before, 対象実装不変=before==after,
        SHA256=dict(before, **{'check_assessment.py':digest(Path(__file__))}),
        独立式='1枚人工返済から金額・枚数・初期Rを算出。セッション曲線全時点を別式で連結しDD検算。売買エンジン・実成果を読まない。',
        不合格=failures, 検査=RECORDS)
    (HERE/'check_assessment.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    lines = ['# 集計と採否の人工検査', '',
        f'人工 {len(RECORDS)} 検査、合格 {len(RECORDS)-len(failures)}、不合格 {len(failures)}。実相場の損益は計算していない。', '',
        '利益・損失・同値の枚数、銘柄別円倍率、取引ごとの固定初期R、全時点を連結した含み込み最大下落を独立検算した。',
        '20取引・6活動場・各方向3・PF/平均比1.2の等号と不足、最大勝ち/最大黒字場除去、全損失・無取引・単発大勝ちを検査した。',
        '主案は両市場の基本条件と全4実行感度が必要。R対照は同値を認めず、円額との混同や相手候補による救済を認めないことを確認した。', '',
        '## 不一致', '']
    lines += [f'- {row["検査"]}: 実値 {row["実値"]}、期待 {row["期待"]}。' for row in failures] or ['なし。']
    lines += ['', '非有限入力の検査は保存値・呼出しに対する防御検査であり、実台帳に非有限値が存在したとの意味ではない。',
        '入力が有限という上流契約だけで集計関数の誤入力を合格にしない。比率の分母0は未定義であり、全勝を無限PFとして合格させない。',
        '旧ファイル・原本・現在データは変更していない。対象3ファイルの実行前後SHAをJSONへ保存した。', '']
    (HERE/'check_assessment.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(全合格=not failures, 人工検査数=len(RECORDS), 不合格=failures), ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
