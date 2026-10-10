"""時間窓合議の黒字基礎・中央差・時計耐性を、固定した二出口で別々に判定する。"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE.parent / 'wave_v38/adaptive_assessment.py'
_spec = importlib.util.spec_from_file_location('window_assessment_design_v43', HERE / 'design.py')
design = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = design
_spec.loader.exec_module(design)
assert Path(design.__file__).resolve() == HERE / 'design.py'
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('all_symbols', 'symbols')
SUM_FIELDS = ('net_yen', 'gross_profit_yen', 'gross_loss_yen', 'profit_units',
    'loss_units', 'zero_units', 'cycles', 'cycle_wins', 'cycle_losses',
    'cycle_profit_yen', 'cycle_loss_yen', 'reductions', 'restorations')
COUNT_FIELDS = ('profit_units', 'loss_units', 'zero_units', 'cycles', 'cycle_wins',
    'cycle_losses', 'reductions', 'restorations')
EPS = 1e-6
INHERITED = ('finite', 'ratios', 'basic', 'relation', 'names_for')

# ----------------------------------------
# 次の五関数は旧版を原文で引き継ぎ、固定時に構文木の一致を検査する。
def finite(value: object) -> float:
    """機能: 真偽値・欠損・非有限値を数値と混同せず拒否する。

    引数: value (object)。返り値: 有限数値 (float)。
    """
    assert type(value) in (int, float) and math.isfinite(value)
    return float(value)

def ratios(value: dict) -> dict:
    """機能: 元組と返済脚・枚数の比率をそれぞれ独立に導出する。

    引数: value (dict) は期間集計。返り値: 比率と平均額 (dict)。
    """
    for key in SUM_FIELDS:
        finite(value[key])
    for key in COUNT_FIELDS:
        assert value[key] >= 0 and int(value[key]) == value[key]
    for key in ('gross_profit_yen', 'gross_loss_yen', 'cycle_profit_yen', 'cycle_loss_yen'):
        assert value[key] >= 0
    assert value['cycle_wins'] + value['cycle_losses'] <= value['cycles']
    wins, losses = value['cycle_wins'], value['cycle_losses']
    win = value['cycle_profit_yen'] / wins if wins else None
    loss = value['cycle_loss_yen'] / losses if losses else None
    pf = value['cycle_profit_yen'] / value['cycle_loss_yen'] if value['cycle_loss_yen'] > 0 else None
    payoff = win / loss if win is not None and loss is not None and loss > 0 else None
    unit_win = value['gross_profit_yen'] / value['profit_units'] if value['profit_units'] else None
    unit_loss = value['gross_loss_yen'] / value['loss_units'] if value['loss_units'] else None
    return dict(元組PF=pf, 平均元組勝敗比=payoff, 平均勝ち元組円=win, 平均負け元組円=loss,
        返済脚金額比=value['gross_profit_yen'] / value['gross_loss_yen'] if value['gross_loss_yen'] > 0 else None,
        一枚平均利益円=unit_win, 一枚平均損失円=unit_loss,
        一枚平均勝敗比=unit_win / unit_loss if unit_win is not None and unit_loss is not None and unit_loss > 0 else None)

def basic(value: dict, rows: list[dict], names: list[str], concentration: bool) -> dict:
    """機能: 元組基礎と最大勝ち除外を、明細と期間の一致を検算して判定する。

    引数: value (dict)、rows (list[dict])、names (list[str])、concentration (bool)。
    返り値: 検査・比率・除外後収支 (dict)。診断では最大勝ち除外は表示のみ。
    """
    assert len(rows) == len(names) and {r['session'] for r in rows} == set(names)
    assert len({r['session'] for r in rows}) == len(rows)
    assert len({r['symbol'] for r in rows}) == 1
    for field in SUM_FIELDS:
        assert abs(finite(value[field]) - sum(finite(r[field]) for r in rows)) <= EPS, field
    assert finite(value['drawdown_yen']) >= 0
    measured = ratios(value)
    maximum = max([0.] + [finite(r['maximum_trade_profit']) for r in rows])
    best_session = max([0.] + [finite(r['net_yen']) for r in rows])
    assert all(r['maximum_trade_profit'] >= 0 for r in rows)
    removed_trade = value['net_yen'] - maximum
    removed_session = value['net_yen'] - best_session
    checks = dict(収支正=value['net_yen'] > 0,
        元組PF1超=measured['元組PF'] is not None and measured['元組PF'] > 1,
        平均元組勝敗比1超=measured['平均元組勝敗比'] is not None and measured['平均元組勝敗比'] > 1)
    exclusion = dict(最大勝ち元組除外非負=removed_trade >= -EPS, 最大黒字場除外非負=removed_session >= -EPS)
    return dict(合格=all(checks.values()) and (all(exclusion.values()) if concentration else True),
        基礎検査=checks, 最大勝ち除外検査=exclusion, 最大勝ち除外を採否へ使用=concentration,
        比率=measured, 最大勝ち元組円=maximum, 最大黒字場円=best_session,
        最大勝ち元組除外収支円=removed_trade, 最大黒字場除外収支円=removed_session,
        稼働セッション数=sum(r['cycles'] > 0 for r in rows),
        減量約定回数=value['reductions'], 復元約定回数=value['restorations'])

def relation(candidate: dict, reference: dict) -> dict:
    """機能: 全13/後7の両市場で収支と時価DDの非劣位・交換を区別する。

    引数: candidate/reference (dict)。返り値: 4セルの差と関係 (dict)。
    """
    rows = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            a, b = candidate[period][symbol], reference[period][symbol]
            net = finite(a['net_yen']) - finite(b['net_yen'])
            dd = finite(a['drawdown_yen']) - finite(b['drawdown_yen'])
            assert a['drawdown_yen'] >= 0 and b['drawdown_yen'] >= 0
            rows.append(dict(期間=period, 銘柄=symbol, 収支差円=net, 最大下落差円=dd))
    positive = all(r['収支差円'] >= -EPS and r['最大下落差円'] <= EPS for r in rows)
    negative = all(r['収支差円'] <= EPS and r['最大下落差円'] >= -EPS for r in rows)
    strict = any(abs(r[k]) > EPS for r in rows for k in ('収支差円', '最大下落差円'))
    label = '同値' if not strict else '同時改善' if positive else '対照優位' if negative else '交換又は混在'
    return dict(関係=label, 同時改善=positive and strict, 対照が厳密支配=negative and strict,
        完全同値=not strict, 差=rows)

def names_for(period: str, sessions: list[str]) -> list[str]:
    """機能: 全13又は同じ後7のセッション集合を返す。

    引数: period (str)、sessions (list[str])。返り値: 対象セッション (list[str])。
    """
    assert period in PERIODS
    return sessions if period == 'all_symbols' else sessions[6:]


def close(left: object, right: object, label: str) -> None:
    """機能: 有限な独立数値が丸め誤差内で一致することを要求する。

    引数: left/right(object)、label(str)。返り値: なし(None)。
    """
    assert abs(finite(left) - finite(right)) <= EPS, label


def identifier(window: str, manager: str, variant: str = 'V000') -> str:
    """機能: 固定された入口・出口・執行条件から識別子を返す。

    引数: window/manager/variant(str)。返り値: 条件ID(str)。
    """
    return f'{window}__{manager}__{variant}'


def ledger_activity(rows: list[dict], ledgers: list[dict], names: list[str]) -> dict:
    """機能: 全元組の収支・初期R・買売数と場別保存値を別式で照合する。

    引数: rows/ledgers(list[dict])、names(list[str])。返り値: 場・銘柄別の活動(dict)。
    入口が違う条件同士の元組番号は対応させない。全行会計は別の独立監査が担う。
    """
    expected = {(name, symbol) for name in names for symbol in SYMBOLS}
    mapping = {(r['session'], r['symbol']): r for r in rows}
    books = {(r['session'], r['symbol']): r for r in ledgers}
    assert len(rows) == len(mapping) == len(ledgers) == len(books) == 26
    assert set(mapping) == set(books) == expected
    output = {}
    for key, record in books.items():
        row, cycles = mapping[key], record['cycles']
        factor = 1000. if key[1] == 'TOPIX' else 10.
        close(record['config']['point_value'], factor, '小口倍率')
        assert isinstance(cycles, list)
        used = set()
        for cycle in cycles:
            assert isinstance(cycle, list) and len(cycle) == 10
            list(map(finite, cycle))
            assert cycle[0] >= 0 and int(cycle[0]) == cycle[0] and cycle[0] not in used
            used.add(cycle[0])
            assert 0 <= cycle[1] <= cycle[2] and int(cycle[1]) == cycle[1] and int(cycle[2]) == cycle[2]
            assert cycle[4] > 0 and cycle[5] > 0 and cycle[8] in (-1, 1)
        profits = [c[3] * factor for c in cycles]
        gains = [p for p in profits if p > 0]
        losses = [-p for p in profits if p < 0]
        measured = dict(cycles=len(cycles), cycle_wins=len(gains), cycle_losses=len(losses),
            net_yen=sum(profits), cycle_profit_yen=sum(gains), cycle_loss_yen=sum(losses),
            maximum_trade_profit=max([0.] + gains), net_r=sum(c[3] / c[4] for c in cycles))
        for field, value in measured.items():
            close(row[field], value, f'{key}:{field}')
        assert row['two_largest_cycle_profits'] == sorted(gains, reverse=True)[:2]
        output[key] = dict(買い元組数=sum(c[8] == 1 for c in cycles),
            売り元組数=sum(c[8] == -1 for c in cycles), 元組数=len(cycles))
    return output


def condition_checks(value: dict, rows: list[dict], ledgers: list[dict], names: list[str]) -> dict:
    """機能: 一条件の4セルを旧基礎・集中・買売活動・枚単価へ分離する。

    引数: value(dict)、rows/ledgers(list[dict])、names(list[str])。返り値: 判定と全内訳(dict)。
    """
    activity = ledger_activity(rows, ledgers, names)
    details = {}
    for period in PERIODS:
        chosen = names_for(period, names)
        details[period] = {}
        for symbol in SYMBOLS:
            part = [r for r in rows if r['symbol'] == symbol and r['session'] in chosen]
            result = basic(value[period][symbol], part, chosen, True)
            for row in part:
                close(row['net_yen'], row['gross_profit_yen'] - row['gross_loss_yen'], '返済脚の収支')
                close(row['net_yen'], row['cycle_profit_yen'] - row['cycle_loss_yen'], '元組の収支')
            aggregate = value[period][symbol]
            close(aggregate['net_r'], sum(r['net_r'] for r in part), '期間総R')
            calculated = result['比率']['平均元組勝敗比']
            if calculated is None:
                assert aggregate['average_cycle_payoff'] is None
            else:
                close(aggregate['average_cycle_payoff'], calculated, '保存された平均元組比')
            longs = sum(activity[(name, symbol)]['買い元組数'] for name in chosen)
            shorts = sum(activity[(name, symbol)]['売り元組数'] for name in chosen)
            best_two = sorted([p for r in part for p in r['two_largest_cycle_profits']], reverse=True)[:2]
            active = aggregate['cycles'] > 0 and longs > 0 and shorts > 0
            unit_ratio = result['比率']['一枚平均勝敗比']
            result.update(買い元組数=longs, 売り元組数=shorts, 実取引と買売双方=bool(active),
                活動込み基礎候補=bool(result['合格'] and active),
                一枚平均勝敗比1超=unit_ratio is not None and unit_ratio > 1,
                上位二勝ち元組同時除外収支円=aggregate['net_yen'] - sum(best_two),
                上位二勝ち元組円=best_two, 収支円=aggregate['net_yen'],
                時価最大下落円=aggregate['drawdown_yen'], 元組数=aggregate['cycles'])
            details[period][symbol] = result
    all_cells = [cell for group in details.values() for cell in group.values()]
    passes = value['wave_passes']
    assert type(passes) is int and 0 <= passes <= 8
    return dict(基礎候補=all(c['活動込み基礎候補'] for c in all_cells),
        元組基礎と大勝ち除外=all(c['合格'] for c in all_cells),
        実取引と買売双方=all(c['実取引と買売双方'] for c in all_cells),
        全セル一枚平均勝敗比1超=all(c['一枚平均勝敗比1超'] for c in all_cells),
        指定八波=passes == 8, 波通過数=passes, 期間別=details)


def validate(index: dict, sessions: dict, names: list[str], ledgers: dict) -> None:
    """機能: 条件・場・保存仕様の欠落や差替えを評価前に拒否する。

    引数: index/sessions/ledgers(dict)、names(list[str])。返り値: なし(None)。
    """
    expected = {s['id']: s for s in design.catalog()}
    assert len(expected) == 32 and set(index) == set(sessions) == set(ledgers) == set(expected)
    assert len(names) == len(set(names)) == 13 and names == sorted(names)
    assert all(isinstance(n, str) and n for n in names)
    keys = {(name, symbol) for name in names for symbol in SYMBOLS}
    for key, spec in expected.items():
        value = index[key]
        assert value['id'] == key and value['spec'] == spec
        assert len(sessions[key]) == 26
        assert {(r['session'], r['symbol']) for r in sessions[key]} == keys
        assert all(r['id'] == key for r in sessions[key])
        for period in PERIODS:
            assert set(value[period]) == set(SYMBOLS)
            for aggregate in value[period].values():
                ratios(aggregate)
                assert finite(aggregate['drawdown_yen']) >= 0
                finite(aggregate['net_r'])


def assess(index: dict, sessions: dict, names: list[str], ledgers: dict,
           verification: bool = False) -> dict:
    """機能: 固定二出口について中央差・三中心・四執行・波を独立に判定する。

    引数: index/sessions/ledgers(dict)、names(list[str])、verification(bool)。
    返り値: 全32内訳と出口別の研究候補判定(dict)。未知優位や全体解決を宣言しない。
    """
    assert type(verification) is bool
    validate(index, sessions, names, ledgers)
    all_checks = {key: condition_checks(value, sessions[key], ledgers[key], names)
                  for key, value in index.items()}
    exits = {}
    for manager in design.MANAGERS:
        primary = identifier('M2_100', manager)
        baseline = identifier('S100', manager)
        comparison = relation(index[primary], index[baseline])
        cells = comparison['差']
        profit = all(r['収支差円'] > EPS for r in cells if r['期間'] == 'symbols') and all(
            r['収支差円'] >= -EPS for r in cells if r['期間'] == 'all_symbols')
        center_rows = {}
        for kind in ('S', 'M2', 'V2', 'U3'):
            group = {}
            for center in ('080', '100', '120'):
                window = kind + center if kind == 'S' else kind + '_' + center
                candidate = identifier(window, manager)
                group[center] = dict(id=candidate, **all_checks[candidate])
            worst = {period: {symbol: dict(
                最小収支円=min(v['期間別'][period][symbol]['収支円'] for v in group.values()),
                最大時価下落円=max(v['期間別'][period][symbol]['時価最大下落円'] for v in group.values()),
                最小一勝ち組除外収支円=min(v['期間別'][period][symbol]['最大勝ち元組除外収支円'] for v in group.values()),
                最小一黒字場除外収支円=min(v['期間別'][period][symbol]['最大黒字場除外収支円'] for v in group.values()),
                最小稼働場数=min(v['期間別'][period][symbol]['稼働セッション数'] for v in group.values()),
                最小元組数=min(v['期間別'][period][symbol]['元組数'] for v in group.values()))
                for symbol in SYMBOLS} for period in PERIODS}
            center_rows[kind] = dict(三中心耐性=all(v['基礎候補'] for v in group.values()), 中心別=group, 三点要約=worst)
        execution = {}
        for variant in ('L001', 'L005', 'L015', 'O000'):
            candidate = identifier('M2_100', manager, variant)
            detail = all_checks[candidate]
            passed = all(all(c['基礎検査'].values()) for c in detail['期間別']['symbols'].values())
            execution[variant] = dict(id=candidate, 後七の執行基礎=passed, **detail)
        economic = all_checks[primary]['基礎候補'] and profit and center_rows['M2']['三中心耐性']
        exits[manager] = dict(主案ID=primary, 単一中央ID=baseline,
            中央の基礎候補=all_checks[primary]['基礎候補'], 中央の収益追加改善=profit,
            中央の収益DD関係=comparison, 三中心耐性=center_rows['M2']['三中心耐性'],
            四執行基礎=all(v['後七の執行基礎'] for v in execution.values()),
            指定八波=all_checks[primary]['指定八波'], 波通過数=all_checks[primary]['波通過数'],
            経済目安合格=bool(economic), 監査完了=verification,
            既知比較の研究候補=bool(verification and economic),
            三中心比較=center_rows, 四執行=execution)
    return dict(全条件数=32, 全入力数=832, 全指定波数=256,
        全13=names, 後半7=names[6:], 全期間既知=True, 監査完了=verification,
        出口別=exits, 全条件=all_checks, 主案の事後差替=False,
        見送り量対照実施=False, 合議固有の予測付加価値='未判定',
        未知での有効性確認=False, 全体目標達成=False, 現在API取得数=0)


def rules() -> dict:
    """機能: 結果前に固定する判定と、判定しない範囲を返す。

    引数: なし。返り値: 採否規則(dict)。
    """
    return dict(条件数=32, 期間='全13と同じ後7。全て既読。銘柄別4セル。',
        基礎='4セルで収支正・元組PF>1・平均元組勝敗比>1。最大1勝ち組と最大1黒字場を別々に除外し非負。',
        活動='各4セルで元組取引あり、買い元組・売り元組双方あり。稼働場数や基準比の追加下限なし。',
        集中補足='上位2勝ち組を同時除外して表示。採否へ追加しない。',
        枚数='1枚平均勝敗比と金額・勝敗枚数は別表示。元組比へ混ぜない。',
        中央収益='出口別M2中央−単一中央の円収支。後7両銘柄>0、全13両銘柄>=0。',
        DD='収支DDの全セル同時改善・交換又は混在・対照優位・同値を別ラベル。DD全セル非劣位を唯一の採用条件にしない。',
        時計='M2中心0.8/1/1.2が全て基礎・集中・活動を満たす。S/V2/U3も同じ基準を表示。',
        執行='中央M2の1/5/15秒と観測価格を別再生。後7両銘柄の収支正・元組PF>1・平均元組比>1を別判定。',
        波='旧8波の20分正方向保有を別判定。基礎と時計の判定には混ぜず、未達を隠さない。',
        研究候補='出口ごとに監査完了AND中央基礎AND中央収益追加改善AND三中心耐性。波と執行は別ラベル併記。',
        主案='M2_100を二出口で別判定。V2/U3/最良中心/最良出口へ事後差替なし。',
        反証未実施='同率間引き・観測価格と遅延同時・全中心の執行感度。合議固有の予測追加価値は未判定。',
        比較誤差=EPS, 未定義='比率の分母欠落は未確認。非有限・欠落・重複・仕様差は拒否。')


def freeze() -> dict:
    """機能: 旧関数の構文同一と人工検査を確認して判定規則を固定する。

    引数: なし。返り値: 固定資料(dict)。実相場の成績は読み込まない。
    """
    source = ast.parse(SOURCE.read_text(encoding='utf-8'))
    actual = ast.parse(Path(__file__).read_text(encoding='utf-8'))
    selected = lambda tree: {n.name: ast.dump(n, include_attributes=False) for n in tree.body
                             if isinstance(n, ast.FunctionDef) and n.name in INHERITED}
    assert selected(source) == selected(actual) and len(selected(actual)) == 5
    test_path = HERE / 'check_assessment.json'
    test = json.loads(test_path.read_text(encoding='utf-8'))
    assert test['全合格'] is True and test['新実相場損益'] is False
    paths = [Path(__file__), HERE / 'check_assessment.py', test_path, HERE / 'design.py', SOURCE,
             HERE / '反証計画.md', HERE.parent / 'wave_v38/探索条件の固定.json']
    files = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert test['採否実装SHA256'] == files[Path(__file__).relative_to(ROOT).as_posix()]
    output = dict(規則=rules(), 条件=design.catalog(), 旧関数原文継承=list(INHERITED),
                  旧関数構文全一致=True, SHA256=files, 新実相場損益=False, 現在API取得数=0)
    path = HERE / 'assessment_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == output
    else:
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return output


if __name__ == '__main__':
    freeze()
    print('32条件の判定規則と旧関数同一を固定しました。新損益は未計算です。')
