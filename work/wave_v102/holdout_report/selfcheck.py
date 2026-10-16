"""実損益を読まず、追加合算の小人工会計と正式終端guardだけを確認する。"""

from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 担当集計と不変会計だけを固有名で読む。
    引数: name(str)、path(Path)は名前と位置。
    返り値: objectは読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def row(accounting: object, session: str, symbol: str, net: float, active: bool = True) -> dict:
    """
    機能: 原板及び発注を伴わない、合算欄だけの小人工会計を作る。
    引数: accounting(object)、session/symbol(str)、net(float)、active(bool)。
    返り値: dictは集計構造の人工一口座。実際の約定費用の検証には使わない。
    """
    trades = np.zeros((1 if active else 0, 16), dtype=np.float64)
    columns = ['net', 'quantity', 'gross', 'entry_fee', 'exit_fee_share', 'side']
    cohorts = np.zeros((2 if active else 0, 6), dtype=np.float64)
    if active:
        trades[0, 4:6] = [1, 2]
        trades[0, 8:12] = [2, 2, net+4, net]
        cohort_nets = [max(net, 0)+30, min(net, 0)-30]
        cohorts[:, 0] = cohort_nets
        cohorts[:, 1] = 1
        cohorts[:, 2] = cohorts[:, 0] + 2
        cohorts[:, 3:5] = 1
        cohorts[:, 5] = 1
    totals = accounting.trade_totals(trades)
    cohort = accounting.cohort_totals(cohorts, columns)
    empty_parent = accounting.trade_totals(np.zeros((0, 16)))
    empty_cohort = accounting.cohort_totals(np.zeros((0, 6)), columns)
    return dict(session=session, symbol=symbol, **totals,
                cohorts=cohort, cohort_directions={'買い': cohort, '売り': empty_cohort},
                sources={'J2': totals, 'O06': empty_parent}, directions={'買い': totals, '売り': empty_parent},
                order_count=3 if active else 0, entry_order_count=2 if active else 0,
                adding_order_count=1 if active else 0,
                equity_peak=max(net, 0), equity_trough=min(net, 0), equity_drawdown=max(-net, 0),
                maximums=dict(held_long=2 if active else 0, held_short=0))


def rejected(callback: object) -> str:
    """
    機能: 不正な構造又は未完了guardが例外で拒否されることを確認する。
    引数: callback(Callable[[],object])は人工検査処理。
    返り値: strは確認された例外型。例外なしなら検査を失敗させる。
    """
    try:
        callback()
    except (AssertionError, FileNotFoundError) as error:
        return type(error).__name__
    raise AssertionError('拒否されるべき人工ケースが通過しました')


def guard_cases(assemble: object) -> list[dict]:
    """
    機能: 実金融資料から隔離した人工終端資料でguardの過少件数・対象違いを検査する。
    引数: assemble(object)は新合算モジュール。
    返り値: list[dict]は確認したguardケース。正式結果は読まない。
    """
    results = [dict(条件='根の明示通知なし', 拒否例外=rejected(lambda: assemble.completed_guards(False)))]
    baseline = [
        dict(合格=True, 人工専用=False, 検査件数=dict(口座=1240, 商品期間=320)),
        dict(合格=True, 人工専用=False, 対象=assemble.SESSION,
             検査件数=dict(口座=40, 商品期間=40), 開始終端ソース一致=True,
             追加による条件変更=0, 追加による参考再選択=0, 新正式売買生成=0, API取得=0, 実注文=0),
        dict(全合格=True, 対象=[assemble.SESSION], 元31結果確定後=True,
             正式追加損益実行=0, 追加損益による条件又は参考変更=0, SHA256={'人工': '固定'}),
        dict(全合格=True, 条件数=20, 口座数=40, 対象=assemble.SESSION,
             条件変更=0, 参考変更=0, 開始終端指紋一致=True,
             開始SHA256={'人工': '固定'}, SHA256={'人工': '固定'})]
    saved = (assemble.WORK, assemble.ORIGINAL_AUDIT, assemble.ADDITIONAL_AUDIT)
    cases = [('全正式件数の構造', None), ('元31が1239口座', (0, '口座', 1239)),
             ('追加が39口座', (1, '口座', 39)), ('追加監査が人工', (1, '人工専用', True)),
             ('追加対象が別場', (1, '対象', '2000-01-03_Night')),
             ('追加で参考を選び直す', (1, '追加による参考再選択', 1)),
             ('追加終端の開始指紋が違う', (3, '開始SHA256', {'人工': '変更'}))]
    try:
        for index, (label, alteration) in enumerate(cases):
            folder = HERE / '人工guard' / f'{index:05d}'
            folder.mkdir(parents=True, exist_ok=False)
            values = deepcopy(baseline)
            if alteration is not None:
                item, field, replacement = alteration
                if field == '口座':
                    values[item]['検査件数'][field] = replacement
                else:
                    values[item][field] = replacement
            assemble.WORK = folder
            assemble.ORIGINAL_AUDIT, assemble.ADDITIONAL_AUDIT = folder/'既知人工.json', folder/'追加人工.json'
            locations = [assemble.ORIGINAL_AUDIT, assemble.ADDITIONAL_AUDIT,
                         folder/'holdout_results/追加再生前固定.json', folder/'holdout_results/正式追加再生の終端.json']
            for path, value in zip(locations, values):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            if alteration is None:
                found = assemble.completed_guards(True)
                assert list(found) == values
                results.append(dict(条件=label, 構造通過=True, 注記='人工guard構造だけ。正式集計呼出しなし。'))
            else:
                results.append(dict(条件=label, 拒否例外=rejected(lambda: assemble.completed_guards(True))))
        assemble.WORK = HERE / '人工guard' / '欠測'
        assemble.ORIGINAL_AUDIT = assemble.WORK / '不存在.json'
        assemble.ADDITIONAL_AUDIT = assemble.WORK / '不存在追加.json'
        results.append(dict(条件='いずれかの正式終端が存在しない',
                            拒否例外=rejected(lambda: assemble.completed_guards(True))))
    finally:
        assemble.WORK, assemble.ORIGINAL_AUDIT, assemble.ADDITIONAL_AUDIT = saved
    return results


def check() -> None:
    """
    機能: 小人工2ケースの別掲・全32合算・非線形再計算とguardだけを確認する。
    引数: なし。
    返り値: None。実金融結果、原板、API、注文及び選定の読取実行はいずれも0。
    """
    assemble = module('追加合算の小人工構造読取', HERE/'assemble.py')
    accounting = module('追加合算の人工だけ会計102', WORK/'accounting.py')
    sessions = [str(date(2000, 1, 3)+timedelta(days=i//2)) + ('_Day' if i%2 == 0 else '_Night')
                for i in range(31)]
    cases = []
    for case in (0, 1):
        values = {0: 120., 1: -10., 4: 5., 6: -60., 30: 50.} if case == 0 else {0: -100., 1: 0., 30: 80.}
        prior = [row(accounting, session, symbol, values.get(i, 0), i in values)
                 for i, session in enumerate(sessions) for symbol in assemble.SYMBOLS]
        additional = [row(accounting, assemble.SESSION, symbol, 150. if case == 0 else -25., True)
                      for symbol in assemble.SYMBOLS]
        result = assemble.combine(accounting, prior, additional, sessions)
        for symbol, value in result.items():
            assert value['known31']['session_count'] == 31
            assert value['additional1']['session_count'] == 1
            assert value['all32']['session_count'] == 32
            assert value['all32']['cohorts']['profit'] > value['all32']['profit']
            assert value['all32']['cohorts']['loss'] > value['all32']['loss']
            assert value['stability32']['no_trade_sessions'] > 0
            assert value['stability32']['positive_session_rate'] < 1
            if case == 0:
                assert value['known31']['best_day'] == '2000-01-03'
                assert value['all32']['best_day'] == assemble.SESSION[:10]
                assert value['all32']['without_best_day']['net'] == value['known31']['net']
                assert value['all32']['without_best_day']['net'] != (
                    value['known31']['without_best_day']['net'] + value['additional1']['without_best_day']['net'])
            else:
                assert value['stability32']['flat_active_sessions'] == 1
        cases.append(dict(ケース=case, 人工口座数=len(prior)+len(additional),
                          元31と追加1を別掲=True, 全32金額枚数合算=True,
                          親内相殺と建玉群相殺前のG及びLを混同しない=True,
                          無取引及び活動0円を黒字へ含めない=True, 非線形大勝ち日除外を再計算=True))
    invalid = list(prior)
    invalid[-1] = invalid[0]
    duplicate = rejected(lambda: assemble.combine(accounting, invalid, additional, sessions))
    zero = [row(accounting, session, symbol, 0, False) for session in sessions for symbol in assemble.SYMBOLS]
    zero_extra = [row(accounting, assemble.SESSION, symbol, 0, False) for symbol in assemble.SYMBOLS]
    result = assemble.combine(accounting, zero, zero_extra, sessions)
    assert all(value['stability32']['positive_session_rate'] is None
               and value['all32']['profit_share'] is None
               and value['stability32']['no_trade_sessions'] == 32 for value in result.values())
    guards = guard_cases(assemble)
    process = subprocess.run([sys.executable, '-X', 'utf8', str(HERE/'assemble.py')],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert process.returncode == 2 and '--root-holdout-independent-complete' in process.stderr
    paths = [Path(__file__), HERE/'assemble.py', WORK/'accounting.py']
    paths += list((HERE/'人工guard').rglob('*.json'))
    assemble.save(HERE/'追加合算の小人工構造と正式終端guard検査.json', dict(
        全合格=True, 人工集計ケース=cases, 人工全無取引の金額割合未定義=True,
        人工重複口座の拒否例外=duplicate, 正式終端guard=guards,
        CLI無フラグ拒否終了コード=process.returncode,
        元31実損益読取=0, 追加1実損益読取=0, 正式全32集計=0,
        新規売買生成=0, 選定=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(ROOT)): assemble.digest(path) for path in paths}))
    print('小人工の別掲・全32合算・親玉G/L・無取引・大勝ち除外及び正式終端guardが一致', flush=True)


if __name__ == '__main__':
    check()
