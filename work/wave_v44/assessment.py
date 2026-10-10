"""順行到達後の減量について、基礎・中央改善・感度・情報対照を分離して判定する。"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from statistics import median
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE.parent / 'wave_v38/adaptive_assessment.py'
_spec = importlib.util.spec_from_file_location('profit_gate_assessment_design_v44', HERE / 'design.py')
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
PRIMARY, CONTROL, BASELINE = design.PRIMARY, design.CONTROL, design.BASELINE
SENSITIVITIES = {'順行閾値': ('A120', 'A180'), '入口時計': ('E080', 'E120'),
    '悪化窓': ('D080', 'D120'), '回復窓': ('G080', 'G120'),
    '執行': ('L001', 'L005', 'L015', 'O000')}

# ----------------------------------------
# 旧基礎の五関数を原文で引き継ぎ、固定時に構文木の一致を要求する。
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


def all_specs() -> list[dict]:
    """機能: 主35と補助128の重複のない固定仕様を取得する。

    引数: なし。返り値: 全163仕様(list[dict])。
    """
    primary, extra = design.catalog(), design.supplementary()
    assert len(primary) == 35 and len(extra) == 128
    result = primary + extra
    assert len({s['id'] for s in result}) == 163
    assert sum(s['primary'] for s in result) == 1
    return result


def main_variant(variant: str) -> str:
    """機能: 配分と回数を変えない主案の診断IDを返す。

    引数: variant(str)。返り値: 条件ID(str)。
    """
    return 'G150_F25_N1__' + variant


def validate(index: dict, sessions: dict, names: list[str], ledgers: dict) -> dict:
    """機能: 全条件・全場・仕様・乱数seedの完全性を採否より先に要求する。

    引数: index/sessions/ledgers(dict)、names(list[str])。返り値: ID別固定仕様(dict)。
    """
    expected = {s['id']: s for s in all_specs()}
    assert set(index) == set(sessions) == set(ledgers) == set(expected)
    assert len(names) == len(set(names)) == 13 and names == sorted(names)
    assert all(isinstance(n, str) and n for n in names)
    keys = {(name, symbol) for name in names for symbol in SYMBOLS}
    for identifier, spec in expected.items():
        value = index[identifier]
        assert value['id'] == identifier and value['spec'] == spec
        for dataset in (sessions[identifier], ledgers[identifier]):
            assert len(dataset) == 26
            assert {(r['session'], r['symbol']) for r in dataset} == keys
        assert all(r['id'] == identifier for r in sessions[identifier])
        for period in PERIODS:
            assert set(value[period]) == set(SYMBOLS)
            for aggregate in value[period].values():
                ratios(aggregate)
                assert finite(aggregate['drawdown_yen']) >= 0
                finite(aggregate['net_r'])
    for field in ('bad_seed', 'good_seed'):
        group = [s for s in expected.values() if s.get(field) is not None]
        assert len(group) == 64 and {s[field] for s in group} == set(range(64))
        other = 'good_seed' if field == 'bad_seed' else 'bad_seed'
        assert all(type(s[field]) is int and s.get(other) is None for s in group)
    return expected


def adjustment_counts(record: dict, row: dict) -> dict:
    """機能: 減量・復元の実約定を予約と区別して元組別に数える。

    引数: record(dict)は台帳、row(dict)は場集計。返り値: 元組ID別回数(dict)。
    """
    counts = {int(c[0]): dict(reductions=0, restorations=0) for c in record['cycles']}
    for event in record['adjustment_events']:
        assert isinstance(event, list) and len(event) == 11
        list(map(finite, event))
        assert event[1] == int(event[1]) and int(event[1]) in counts
        if event[2] == 2:
            assert event[3] in (-1, 1)
            field = 'reductions' if event[3] == -1 else 'restorations'
            counts[int(event[1])][field] += 1
    for field in ('reductions', 'restorations'):
        close(row[field], sum(c[field] for c in counts.values()), '実調整件数:'+field)
    return counts


def initial_groups(record: dict, shadow: bool = False) -> dict:
    """機能: 初回約定と初回ATRから共通影の組識別・初期Rを検査する。

    引数: record(dict)、shadow(bool)。返り値: 元組ID別の初回情報(dict)。
    復元注文は初回に含めず、退役前の元予定数量を尺度にする。
    """
    cycles = record['shadow_cycles'] if shadow else record['cycles']
    orders = record['shadow_orders'] if shadow else record['orders']
    quantity = finite(record['config']['initial_qty'])
    assert quantity == (5 if record['symbol'] == 'TOPIX' else 10)
    openings = {}
    for order in orders:
        assert isinstance(order, list) and len(order) == 8
        list(map(finite, order))
        if order[6] == 20:
            campaign = int(order[2])
            assert order[2] == campaign and campaign >= 0 and campaign not in openings
            assert order[7] == 1 and order[3] in (-1, 1)
            assert int(order[0]) == order[0] and int(order[1]) == order[1] and 0 <= order[1] < order[0]
            assert order[4] == quantity and order[5] > 0
            openings[campaign] = order
    result = {}
    for cycle in cycles:
        assert isinstance(cycle, list) and len(cycle) == 10
        list(map(finite, cycle))
        campaign = int(cycle[0])
        assert campaign == cycle[0] and campaign >= 0 and campaign not in result
        assert cycle[1] == int(cycle[1]) and cycle[2] == int(cycle[2]) and 0 <= cycle[1] <= cycle[2]
        assert cycle[5] > 0 and cycle[8] in (-1, 1)
        initial = openings[campaign]
        assert initial[0] == cycle[1] and initial[3] == cycle[8]
        close(cycle[4], quantity * cycle[5], '初回q0×A0')
        signature = tuple(initial[:2] + initial[3:6] + [cycle[4], cycle[5]])
        result[campaign] = dict(cycle=cycle, signature=signature, quantity=quantity)
    assert set(result) == set(openings)
    assert len({(g['cycle'][1], g['cycle'][8]) for g in result.values()}) == len(result)
    return result


def shadow_records(record: dict) -> dict:
    """機能: 同じ影組を尺度にするため、全影指紋と実初回との一致を要求する。

    引数: record(dict)。返り値: 実元組の初回情報(dict)。全行注文検証は別監査が担う。
    """
    fields = {'trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve',
              'plans', 'execution_plans', 'prepare_events', 'entry_preparations'}
    fingerprints = record['shadow_fingerprints']
    assert set(fingerprints) == fields
    for fingerprint in fingerprints.values():
        assert set(fingerprint) == {'shape', 'dtype', 'SHA256'}
        assert isinstance(fingerprint['shape'], list)
        assert all(type(n) is int and n >= 0 for n in fingerprint['shape'])
        assert isinstance(fingerprint['dtype'], str) and fingerprint['dtype']
        assert isinstance(fingerprint['SHA256'], str) and len(fingerprint['SHA256']) == 64
        assert all(c in '0123456789abcdef' for c in fingerprint['SHA256'])
    own, shadow = initial_groups(record), initial_groups(record, True)
    assert set(own) == set(shadow), '初回新規の母集団差'
    for campaign in own:
        assert own[campaign]['signature'] == shadow[campaign]['signature'], '影と実の初回差'
        assert own[campaign]['cycle'][2] <= shadow[campaign]['cycle'][2], '影終了後の実返済'
    return own


def pair_context(spec: dict) -> tuple:
    """機能: 元組の対応を許す入口・執行条件の識別子を返す。

    引数: spec(dict)。返り値: 入口と執行の固定識別子(tuple)。
    """
    return (spec['signal_id'], spec['entry_scale'], spec['min_delay_seconds'], spec['observed_fill'])


def samples(values: list[float]) -> dict:
    """機能: 全対応差の規模と最大正差への依存を表示する。

    引数: values(list[float])。返り値: 合計・中央値・改善悪化数等(dict)。
    """
    values = [finite(v) for v in values]
    total = sum(values)
    return dict(件数=len(values), 合計=total, 平均=total/len(values) if values else None,
        中央値=median(values) if values else None, 改善数=sum(v > EPS for v in values),
        悪化数=sum(v < -EPS for v in values), 同値数=sum(abs(v) <= EPS for v in values),
        最大正差除外=total-max([0.] + values))


def paired_comparison(primary: str, other: str, specs: dict, index: dict,
                      books: dict, groups: dict, names: list[str], keep_rows: bool = True) -> dict:
    """機能: 共通影・共通初回の全組を対応させ、円差と初回R差を導出する。

    引数: primary/other(str)、specs/index/books/groups(dict)、names(list[str])、keep_rows(bool)。
    返り値: 4セルの対応差と任意の全元組明細(dict)。別入口や遅延の組番号対応を拒否する。
    """
    assert pair_context(specs[primary]) == pair_context(specs[other]), '入口又は執行が異なる組対応'
    output = []
    for key in sorted(books[primary]):
        left, right = books[primary][key], books[other][key]
        assert left['shadow_fingerprints'] == right['shadow_fingerprints'], '共通影指紋差'
        assert left['shadow_cycles'] == right['shadow_cycles'] and left['shadow_orders'] == right['shadow_orders']
        a, b = groups[primary][key], groups[other][key]
        assert set(a) == set(b)
        factor = 1000. if key[1] == 'TOPIX' else 10.
        for campaign in sorted(a):
            assert a[campaign]['signature'] == b[campaign]['signature'], '対応組の初回差'
            one, two = a[campaign]['cycle'], b[campaign]['cycle']
            risk = a[campaign]['quantity'] * one[5]
            output.append(dict(session=key[0], symbol=key[1], campaign=campaign,
                初回行=int(one[1]), 初回方向=int(one[8]), 初回枚数=a[campaign]['quantity'],
                初回ATR=one[5], 共通初回R円=risk*factor,
                主案収支円=one[3]*factor, 対照収支円=two[3]*factor,
                主案R=one[3]/risk, 対照R=two[3]/risk,
                差円=(one[3]-two[3])*factor, 差R=(one[3]-two[3])/risk))
    periods = {}
    for period in PERIODS:
        periods[period] = {}
        for symbol in SYMBOLS:
            part = [r for r in output if r['symbol'] == symbol and r['session'] in names_for(period, names)]
            for identifier, field in ((primary, '主案'), (other, '対照')):
                close(sum(r[field+'収支円'] for r in part), index[identifier][period][symbol]['net_yen'], '全組の期間円')
                close(sum(r[field+'R'] for r in part), index[identifier][period][symbol]['net_r'], '共通初回Rの期間値')
            periods[period][symbol] = dict(全元組数=len(part), 差円=samples([r['差円'] for r in part]),
                差R=samples([r['差R'] for r in part]))
    result = dict(主案ID=primary, 対照ID=other, 共通影と初回全一致=True,
                  全対応元組数=len(output), 期間別=periods)
    if keep_rows:
        result['全元組対応'] = output
    return result


def improvement(candidate: dict, reference: dict) -> dict:
    """機能: 中央の増益とDD関係を分けて判断する。

    引数: candidate/reference(dict)。返り値: 収益追加改善と4セル関係(dict)。
    """
    comparison = relation(candidate, reference)
    rows = comparison['差']
    later = all(r['収支差円'] > EPS for r in rows if r['期間'] == 'symbols')
    full = all(r['収支差円'] >= -EPS for r in rows if r['期間'] == 'all_symbols')
    return dict(後七両銘柄増益=later, 全十三両銘柄非減益=full,
                中央収益追加改善=later and full, 収益DD関係=comparison)


def random_comparison(index: dict, specs: dict, books: dict, groups: dict, names: list[str], field: str) -> dict:
    """機能: 片側情報だけの64固定符号対照を共通初回Rで比較する。

    引数: index/specs/books/groups(dict)、names(list[str])、field(str)。返り値: 全分布と超過判定(dict)。
    正式p値や最良seed選択は行わず、公開機会を保持した対照と明示する。
    """
    selected = sorted([s for s in specs.values() if s.get(field) is not None], key=lambda s:s[field])
    assert [s[field] for s in selected] == list(range(64))
    confirmations = {}
    for spec in selected:
        value = paired_comparison(PRIMARY, spec['id'], specs, index, books, groups, names, False)
        confirmations[spec['id']] = value['全対応元組数']
    periods = {}
    for period in PERIODS:
        periods[period] = {}
        for symbol in SYMBOLS:
            main = index[PRIMARY][period][symbol]
            rows = [dict(id=s['id'], seed=s[field], 元組R=index[s['id']][period][symbol]['net_r'],
                収支円=index[s['id']][period][symbol]['net_yen'], 最大下落円=index[s['id']][period][symbol]['drawdown_yen'],
                減量回数=index[s['id']][period][symbol]['reductions'], 復元回数=index[s['id']][period][symbol]['restorations']) for s in selected]
            midpoint = median(r['元組R'] for r in rows)
            periods[period][symbol] = dict(主案元組R=main['net_r'], 乱数元組R中央値=midpoint,
                乱数収支中央値円=median(r['収支円'] for r in rows),
                乱数下落中央値円=median(r['最大下落円'] for r in rows),
                元組R中央値差=main['net_r']-midpoint,
                主以上元組Rの本数=sum(r['元組R'] >= main['net_r']-EPS for r in rows),
                主以上収支円の本数=sum(r['収支円'] >= main['net_yen']-EPS for r in rows),
                主以下下落円の本数=sum(r['最大下落円'] <= main['drawdown_yen']+EPS for r in rows), 全64=rows)
    later = all(r['元組R中央値差'] > EPS for r in periods['symbols'].values())
    full = all(r['元組R中央値差'] >= -EPS for r in periods['all_symbols'].values())
    return dict(変更情報=field, 後七両市場中央値超過=later, 全十三両市場中央値非劣=full,
        構造保存対照の利益超過=later and full, 共通影確認組数=confirmations, 期間別=periods,
        最良seed採用=False, 正式p値=False, ゲート全体の無情報対照=False)


def assess(index: dict, sessions: dict, names: list[str], ledgers: dict, verification: bool = False) -> dict:
    """機能: 主案を固定し、経済基礎・改善・感度・情報価値を別々に出力する。

    引数: index/sessions/ledgers(dict)、names(list[str])、verification(bool)。
    返り値: 全163条件と主案の既知内判定(dict)。未知市場の保証を要求又は主張しない。
    """
    assert type(verification) is bool
    specs = validate(index, sessions, names, ledgers)
    checks = {identifier:condition_checks(index[identifier], sessions[identifier], ledgers[identifier], names)
              for identifier in specs}
    books, groups = {}, {}
    for identifier in specs:
        books[identifier] = {(r['session'],r['symbol']):r for r in ledgers[identifier]}
        rows = {(r['session'],r['symbol']):r for r in sessions[identifier]}
        groups[identifier] = {}
        for key, record in books[identifier].items():
            groups[identifier][key] = shadow_records(record)
            adjustment_counts(record, rows[key])
    paired_ids = (CONTROL, BASELINE, main_variant('INV'), main_variant('AV_ALL'))
    pairs = {other:paired_comparison(PRIMARY, other, specs, index, books, groups, names) for other in paired_ids}
    central = {other:improvement(index[PRIMARY], index[other]) for other in (CONTROL, BASELINE)}
    detail = checks[PRIMARY]
    active = all(c['減量約定回数'] > 0 and c['復元約定回数'] > 0
                 for period in detail['期間別'].values() for c in period.values())
    sensitivity = {}
    for category, variants in SENSITIVITIES.items():
        selected = {}
        for variant in variants:
            identifier = main_variant(variant)
            value = checks[identifier]
            basic_later = all(all(c['基礎検査'].values()) for c in value['期間別']['symbols'].values())
            selected[variant] = dict(id=identifier, 後七両銘柄の収支PF平均比=basic_later, **value)
        sensitivity[category] = dict(全変形の後七基礎=all(v['後七両銘柄の収支PF平均比'] for v in selected.values()),
            全変形の四セル集中活動込み基礎=all(v['基礎候補'] for v in selected.values()), 条件別=selected)
    assert sum(len(v['条件別']) for v in sensitivity.values()) == 12
    clocks = {}
    for name, prefix in (('主案','G150_F25_N1'), ('無ゲートC01','G000_F25_N1'), ('A0','A0')):
        selected = {v:checks[prefix+'__'+v] for v in ('E080','V000','E120')}
        clocks[name] = dict(三時計の基礎集中活動=all(v['基礎候補'] for v in selected.values()), 条件別=selected)
    randoms = {field:random_comparison(index,specs,books,groups,names,field) for field in ('bad_seed','good_seed')}
    direction = {}
    for variant in ('INV','AV_ALL'):
        other = main_variant(variant)
        cells = pairs[other]['期間別']
        later = all(c['差R']['合計'] > EPS for c in cells['symbols'].values())
        full = all(c['差R']['合計'] >= -EPS for c in cells['all_symbols'].values())
        direction[variant] = dict(id=other, 後七両市場差R正=later, 全十三両市場差R非負=full,
                                  利益超過=later and full, 収益DD関係=relation(index[PRIMARY],index[other]))
    bad_information = active and randoms['bad_seed']['構造保存対照の利益超過'] and all(v['利益超過'] for v in direction.values())
    good_information = active and randoms['good_seed']['構造保存対照の利益超過']
    economic = detail['基礎候補'] and central[CONTROL]['中央収益追加改善'] and active
    robust = all(v['全変形の後七基礎'] for v in sensitivity.values())
    return dict(全条件数=163, 主条件数=35, 補助条件数=128, 全入力数=163*26,
        主案ID=PRIMARY, 元C01ID=CONTROL, 元A0ID=BASELINE, 監査完了=verification,
        経済目安合格=bool(economic), 既知比較の研究候補=bool(verification and economic),
        中央の基礎候補=detail['基礎候補'], 中央の収益追加改善=central[CONTROL]['中央収益追加改善'],
        全期間両銘柄で減量復元実約定=active, 指定八波=detail['指定八波'], 波通過数=detail['波通過数'],
        十二感度の後七基礎=robust, 入口三時計の集中活動耐性=clocks['主案']['三時計の基礎集中活動'],
        耐性付き研究候補=bool(verification and economic and robust and clocks['主案']['三時計の基礎集中活動']),
        悪化情報の利益付加価値支持=bool(bad_information), 回復情報の構造保存対照超過=bool(good_information),
        情報対照を通過した研究候補=bool(verification and economic and bad_information and good_information),
        中央比較=central, 同じ影の元組差=pairs, 十二感度=sensitivity, 入口時計比較=clocks,
        方向除去反転対照=direction, 乱数対照=randoms, 全条件=checks,
        主案の事後差替=False, 全体目標達成=False, 未知での有効性確認=False,
        全十三と後七は既知=True, 損失組と未調整組の除外=False,
        ゲート自体の独立した予測価値='未判定。元C01との全組対応差は示すが、完全な機会同率対照ではない。')


def rules() -> dict:
    """機能: 結果を見る前の経済基準と未確認範囲を返す。

    引数: なし。返り値: 変更しない判定規則(dict)。
    """
    return dict(主案=PRIMARY, 条件数=163, 主35補助128=True,
        基礎='全13/後7×両銘柄の収支正、元組PF>1、平均元組勝敗比>1、最大1勝ち組/1黒字場を別々に除いて非負。実取引と買売双方。',
        枚数='返済脚の利益/損失額と勝ち/負け枚数から1枚平均比を別表示。1枚比や上位2勝同時除外は今回追加の必須ゲートにしない。',
        中央改善='主案の元C01比が後7の両銘柄で厳密増益、全13の両銘柄で非減益。A0比較は別判定。全セルDD非劣位は唯一の採用条件にしない。',
        作動='全4セルで減量と復元の実約定がともに1回以上。未作動の黒字をゲート機構の成功にしない。',
        経済研究候補='監査完了 AND 中央基礎 AND 中央改善 AND 実調整作動。感度と情報価値は別ラベル。',
        感度='12変形の後7両銘柄で収支正/PF>1/平均元組比>1。全13・除外・活動も表示。入口3時計では四セルの基礎/除外/活動を別判定。',
        耐性付き候補='経済研究候補 AND 12感度後7基礎 AND 主案入口3時計の基礎/集中/活動。失敗でも中央黒字を消さない。',
        悪化情報='実調整作動 AND INV/AV_ALL/悪化64の中央値それぞれに後7両銘柄の総Rが厳密超過、全13では非劣。',
        回復情報='実調整作動 AND 回復64の中央値に後7両銘柄の総Rが厳密超過、全13では非劣。復元なし対照がないため復元の存在自体の価値とは呼ばない。',
        情報候補='経済研究候補 AND 悪化情報 AND 回復情報。耐性は独立ラベルで併記。',
        対応='同一入口/執行/影10指紋/影全初回/実全初回を確認し、全組の差Rを共通q0×A0で計算。異なる入口時計/遅延同士の組対応は禁止。',
        波='指定8波は旧20分基準、全件表示の別ラベル。基礎や感度へ混同しない。',
        乱数='悪化64と回復64を別々に全表示。元の公開機会とarmを保持した構造保存対照。正式p値なし、最良seed採用なし。',
        未定義='比率の分母不足は未確認で合格にしない。非有限/欠落/重複/仕様差は拒否。',
        比較誤差=EPS, 限界='全13と後7は既知。万能保証を完了条件へ追加せず、未知優位も断言しない。')


def freeze() -> dict:
    """機能: 原文継承と人工証拠を確認して採否だけを結果前に固定する。

    引数: なし。返り値: 固定資料(dict)。新損益は読まない。
    """
    def functions(path: Path) -> dict:
        """機能: 継承した五関数の構文を抽出する。

        引数: path(Path)。返り値: 関数名と構文(dict)。
        """
        tree = ast.parse(path.read_text(encoding='utf-8'))
        return {n.name:ast.dump(n,include_attributes=False) for n in tree.body
                if isinstance(n,ast.FunctionDef) and n.name in INHERITED}
    assert functions(SOURCE) == functions(Path(__file__)) and len(functions(SOURCE)) == 5
    test_path = HERE/'check_assessment.json'
    test = json.loads(test_path.read_text(encoding='utf-8'))
    assert test['全合格'] is True and test['新実相場損益'] is False
    paths = [Path(__file__), HERE/'check_assessment.py', test_path, HERE/'design.py', SOURCE,
             HERE/'反証設計案.md', HERE/'反証計画.md', HERE.parent/'wave_v38/探索条件の固定.json',
             HERE.parent/'wave_v37/partial_design_fixed.json']
    hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert test['採否実装SHA256'] == hashes[Path(__file__).relative_to(ROOT).as_posix()]
    for name, value in test['参照資料SHA256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == value
    result = dict(規則=rules(), 条件=all_specs(), 旧関数原文継承=list(INHERITED),
        旧関数構文全一致=True, SHA256=hashes, 新実相場損益=False, 現在API取得数=0)
    path = HERE/'assessment_fixed.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == result
    else:
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return result


if __name__ == '__main__':
    freeze()
    print('163条件の基礎・改善・感度・情報対照を結果前に固定しました。')

