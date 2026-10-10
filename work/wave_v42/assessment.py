"""原本全行の旧品質維持と局所品質を分けて判定する。"""

from __future__ import annotations

import importlib.util
import math
from numbers import Real
from pathlib import Path

import numpy as np

import design


STATISTICS_PATH = Path(__file__).resolve().parents[1] / 'wave_v39' / 'trade_statistics.py'
_module_spec = importlib.util.spec_from_file_location('_v42_旧固定統計', STATISTICS_PATH)
assert _module_spec is not None and _module_spec.loader is not None
statistics = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(statistics)
SYMBOLS = ('TOPIX', 'NK225')
COMPONENTS = {'F01': ('F03', 'F06', 'F07', 'F08', 'F09'),
              'F02': ('F04', 'F12', 'F13', 'F14', 'F15')}
EXECUTION_SUFFIXES = ('D01', 'D05', 'D15', 'OBS')
NEIGHBOR_SUFFIXES = ('A080', 'A120', 'T080', 'T120', 'D080', 'D120', 'K1', 'K3')
COUNT_FIELDS = ('profit_units', 'loss_units', 'zero_units', 'trades', 'long_trades',
                'short_trades', 'candidates', 'accepted', 'cancelled', 'active_sessions', 'positive_sessions')
RATIO_FIELDS = ('profit_factor', 'average_payoff')
NONNEGATIVE_FIELDS = COUNT_FIELDS + ('profit_yen', 'loss_yen', 'held_minutes', 'drawdown_yen')
AGGREGATE_FIELDS = frozenset(statistics.aggregate([]))


def validate_index(index: dict) -> None:
    """機能: 全260条件の集合・同一仕様・有限な必須統計を検査する。

    引数: index (dict[str, dict]) はIDに対応するspecと両銘柄集計。
    返り値: なし (None)。欠落、別名重複、不正値はValueError。
    比率Noneは分母0等を表す正規値として残し、基礎判定で不合格にする。
    辞書作成前に上書きされた重複は復元できず、保存資料の列挙側でも検査する。
    """
    specs = design.catalog() + design.supplementary()
    expected = {item['id']: item for item in specs}
    if len(specs) != 260 or len(expected) != 260:
        raise ValueError('設計の条件数又はID一意性が不正です')
    if not isinstance(index, dict) or len(index) != 260 or set(index) != set(expected):
        raise ValueError('全260条件のID集合が一致しません')
    for identifier, spec in expected.items():
        item = index[identifier]
        if not isinstance(item, dict) or item.get('spec') != spec:
            raise ValueError('IDに対応する固定仕様が一致しません: ' + identifier)
        values = item.get('symbols')
        if not isinstance(values, dict) or set(values) != set(SYMBOLS):
            raise ValueError('両銘柄の集計がありません: ' + identifier)
        for symbol in SYMBOLS:
            value = values[symbol]
            if not isinstance(value, dict) or not AGGREGATE_FIELDS <= set(value):
                raise ValueError('期間集計の必須項目がありません: ' + identifier + '/' + symbol)
            for field in AGGREGATE_FIELDS:
                number = value[field]
                if field in RATIO_FIELDS and number is None:
                    continue
                if isinstance(number, (bool, np.bool_)) or not isinstance(number, Real) or not math.isfinite(number):
                    raise ValueError('非有限又は数値でない集計: ' + identifier + '/' + symbol + '/' + field)
                if field in NONNEGATIVE_FIELDS and number < 0:
                    raise ValueError('非負であるべき集計が負です: ' + identifier + '/' + symbol + '/' + field)
                if field in COUNT_FIELDS and int(number) != number:
                    raise ValueError('件数が整数ではありません: ' + identifier + '/' + symbol + '/' + field)
            if value['active_sessions'] > 13 or value['positive_sessions'] > 13:
                raise ValueError('全13セッションを超える場数です: ' + identifier + '/' + symbol)


def display(value: dict) -> dict:
    """機能: 円・初期R・決済枚数と活動を同じ比較欄へまとめる。

    引数: value (dict) は単一銘柄の期間集計。
    返り値: 比較用の保存値 (dict)。両銘柄の円を合算して順位にしない。
    """
    fields = ('net_r', 'profit_yen', 'loss_yen', 'net_yen', 'drawdown_yen', 'trades',
              'profit_units', 'loss_units', 'zero_units', 'active_sessions', 'long_trades',
              'short_trades', 'profit_factor', 'average_payoff', 'without_max_trade', 'without_max_session')
    return {field: value[field] for field in fields}


def random_comparison(index: dict, identifier: str, symbol: str) -> dict:
    """機能: 固定64seedの全成績を残し、同候補方式と比較する。

    引数: index (dict)、identifier/symbol (str)。
    返り値: 中央値・同等以上数・全64明細 (dict)。最良seedの採用はしない。
    """
    value = index[identifier]['symbols'][symbol]
    rows = []
    for seed in range(64):
        condition = f'{identifier}_R{seed:02d}'
        row = index[condition]['symbols'][symbol]
        rows.append(dict(id=condition, seed=seed, **display(row)))
    median_r = float(np.median([row['net_r'] for row in rows]))
    median_yen = float(np.median([row['net_yen'] for row in rows]))
    return dict(比較対象=identifier, 乱数条件数=64, 乱数合計R中央値=median_r,
        乱数円収支中央値=median_yen, 同機会乱数中央値超過=bool(value['net_r'] > median_r),
        主以上合計Rの乱数数=sum(row['net_r'] >= value['net_r'] for row in rows),
        主以上円収支の乱数数=sum(row['net_yen'] >= value['net_yen'] for row in rows),
        全乱数=rows, 正式有意確率=False,
        解釈='候補時刻を保つ方向符号乗算の対照。退出・休止により実約定の時刻と件数は変わる。')


def neighbor_activity(value: dict) -> dict:
    """機能: 近傍用の活動数・黒字・PFを固定基準で判定する。

    引数: value (dict)。返り値: 固定6条件と合否 (dict)。
    最大勝ち除外と平均比は表示するが、近傍6/8判定へ追加しない。
    """
    pf = value['profit_factor']
    flags = dict(決済20以上=value['trades'] >= 20, 活動6以上=value['active_sessions'] >= 6,
        ロング3以上=value['long_trades'] >= 3, ショート3以上=value['short_trades'] >= 3,
        黒字=value['net_yen'] > 0, 利益損失比1_2以上=pf is not None and math.isfinite(pf) and pf >= 1.2)
    return dict(合格=all(flags.values()), 検査={key: bool(flag) for key, flag in flags.items()})


def evaluate_hypothesis(index: dict, identifier: str, randoms: dict) -> dict:
    """機能: 一つの品質条件の基礎・成分・執行・近傍を独立して評価する。

    引数: index/randoms (dict)、identifier (str)。返り値: 一仮説の全判定 (dict)。
    品質違いの良い成績や、相手確認によって主案の不合格を救済しない。
    """
    primary = index[identifier]['symbols']
    basic = {symbol: statistics.basic(primary[symbol]) for symbol in SYMBOLS}
    base_pass = all(value['合格'] for value in basic.values())
    components = {}
    for symbol in SYMBOLS:
        value = primary[symbol]
        rows = {}
        for control in COMPONENTS[identifier]:
            other = index[control]['symbols'][symbol]
            rows[control] = dict(主の合計R厳密超過=bool(value['net_r'] > other['net_r']),
                合計R差=value['net_r'] - other['net_r'], 円収支差=value['net_yen'] - other['net_yen'],
                対照=display(other))
        rand = randoms[identifier][symbol]
        flags = {name: row['主の合計R厳密超過'] for name, row in rows.items()}
        flags['乱数中央値'] = rand['同機会乱数中央値超過']
        components[symbol] = dict(合格=all(flags.values()),比較=flags,明細=rows,
            乱数合計R中央値=rand['乱数合計R中央値'])
    # ----------------------------------------
    # 4執行では基礎全項目、8近傍では旧版と同じ活動・黒字・PF基準を使う。
    executions = {f'{identifier}_{suffix}':
        {symbol: statistics.basic(index[f'{identifier}_{suffix}']['symbols'][symbol]) for symbol in SYMBOLS}
        for suffix in EXECUTION_SUFFIXES}
    neighbors = {}
    for symbol in SYMBOLS:
        rows = {}
        for suffix in NEIGHBOR_SUFFIXES:
            name = f'{identifier}_{suffix}'
            value = index[name]['symbols'][symbol]
            rows[name] = dict(近傍基準=neighbor_activity(value),基礎全項目=statistics.basic(value),成績=display(value))
        count = sum(row['近傍基準']['合格'] for row in rows.values())
        nets = [row['成績']['net_yen'] for row in rows.values()]
        median, worst = float(np.median(nets)), float(min(nets))
        net = primary[symbol]['net_yen']
        flags = {'主基礎合格': basic[symbol]['合格'], '活動黒字PF通過6以上': count >= 6,
            '全8収支中央値が主50%以上': median >= .5 * net, '全8最悪が主マイナス25%以上': worst >= -.25 * net}
        neighbors[symbol] = dict(合格=all(flags.values()),検査={k:bool(v) for k,v in flags.items()},
            近傍数=8,活動黒字PF通過数=int(count),全8収支中央値=median,全8最悪収支=worst,
            主収支=net,中央値下限=.5*net,最悪下限=-.25*net,全近傍=rows)
    added = all(value['合格'] for value in components.values())
    execution_pass = all(value['合格'] for group in executions.values() for value in group.values())
    neighbor_pass = base_pass and all(value['合格'] for value in neighbors.values())
    return dict(id=identifier,基礎候補=base_pass,板の比較付加価値=added,実行感度=execution_pass,
        窓距離感度=neighbor_pass,既知経済目安合格=base_pass and added and execution_pass and neighbor_pass,
        基礎=basic,成分対照=components,実行感度詳細=executions,近傍詳細=neighbors)


def assess(index: dict) -> dict:
    """機能: 主F01と副F02の結果を固定対照のまま全260条件から評価する。

    引数: index (dict[str,dict])。返り値: 両仮説と品質変更・旧観測との比較 (dict)。
    全13は既知であり、基礎候補と成分の付加価値を区別する。
    """
    validate_index(index)
    randoms = {name: {symbol: random_comparison(index, name, symbol) for symbol in SYMBOLS}
               for name in ('F01', 'F02', 'F03')}
    hypotheses = {name: evaluate_hypothesis(index, name, randoms) for name in ('F01','F02')}
    comparisons = {}
    for name, parent in (('F01','F00'),('F02','F01'),('F03','F18'),('F04','F03'),('F10','F01'),('F16','F02')):
        comparisons[name] = {}
        for symbol in SYMBOLS:
            value, control = index[name]['symbols'][symbol], index[parent]['symbols'][symbol]
            comparisons[name][symbol] = dict(比較相手=parent,基礎=statistics.basic(value),成績=display(value),
                合計R差=value['net_r']-control['net_r'],円収支差=value['net_yen']-control['net_yen'],
                最大下落差=value['drawdown_yen']-control['drawdown_yen'],
                候補数差=value['candidates']-control['candidates'],実取引数差=value['trades']-control['trades'])
    basic_all = {spec['id']: {symbol:statistics.basic(index[spec['id']]['symbols'][symbol]) for symbol in SYMBOLS}
                 for spec in design.catalog()}
    return dict(主仮説='F01',副仮説='F02',全条件数=260,主条件数=68,方向乱数条件数=192,
        仮説別=hypotheses,旧観測と品質と相手確認=comparisons,全主条件の基礎=basic_all,
        方向乱数=randoms,未知での有効性確認=False,全体目標達成=False,実装監査完了を意味しない=True,
        解釈='原本全行化は旧帯を固定した条件付き比較。旧品質維持とP局所品質を別々に判定する。'
             '黒字候補の存在と数量情報の追加価値を分離。近傍全8・乱数全64を残す。'
             '品質変更・相手確認・良かった近傍で主案を差し替えず、正式な有意確率は示さない。')


