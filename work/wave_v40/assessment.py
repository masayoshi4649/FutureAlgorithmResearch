"""固定帯の板履歴、価格対照、執行と近傍を分けて既知成績を判定する。"""

from __future__ import annotations

import importlib.util
import math
from numbers import Real
from pathlib import Path

import numpy as np

import design


STATISTICS_PATH = Path(__file__).resolve().parents[1] / 'wave_v39' / 'trade_statistics.py'
_module_spec = importlib.util.spec_from_file_location('_v40_旧固定統計', STATISTICS_PATH)
assert _module_spec is not None and _module_spec.loader is not None
statistics = importlib.util.module_from_spec(_module_spec)
_module_spec.loader.exec_module(statistics)
SYMBOLS = ('TOPIX', 'NK225')
COMPONENTS = ('B01', 'B05', 'B06', 'B07', 'B08')
EXECUTION_SUFFIXES = ('D01', 'D05', 'D15', 'OBS')
NEIGHBOR_SUFFIXES = ('A080', 'A120', 'T080', 'T120', 'D080', 'D120', 'K1', 'K3')
COUNT_FIELDS = ('profit_units', 'loss_units', 'zero_units', 'trades', 'long_trades',
                'short_trades', 'candidates', 'accepted', 'cancelled', 'active_sessions', 'positive_sessions')
RATIO_FIELDS = ('profit_factor', 'average_payoff')
NONNEGATIVE_FIELDS = COUNT_FIELDS + ('profit_yen', 'loss_yen', 'held_minutes', 'drawdown_yen')
AGGREGATE_FIELDS = frozenset(statistics.aggregate([]))


def validate_index(index: dict) -> None:
    """機能: 全281条件の集合・同一仕様・有限な必須統計を検査する。

    引数: index (dict[str, dict]) はIDに対応するspecと両銘柄集計。
    返り値: なし (None)。欠落、別名重複、不正値はValueError。
    比率Noneは分母0等を表す正規値として残し、基礎判定で不合格にする。
    辞書作成前に上書きされた重複は復元できず、保存資料の列挙側でも検査する。
    """
    specs = design.catalog() + design.supplementary()
    expected = {item['id']: item for item in specs}
    if len(specs) != 281 or len(expected) != 281:
        raise ValueError('設計の条件数又はID一意性が不正です')
    if not isinstance(index, dict) or len(index) != 281 or set(index) != set(expected):
        raise ValueError('全281条件のID集合が一致しません')
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


def assess(index: dict) -> dict:
    """機能: 主B00の基礎・R対照・執行・8近傍を独立した段階で判定する。

    引数: index (dict[str, dict]) は全281の固定specとsymbols集計。
    返り値: 既知13セッションの経済判定 (dict)。相手確認で主を差し替えない。
    本関数の合格は実装監査完了、未知相場での優位、運用利益の保証を意味しない。
    """
    validate_index(index)
    primary = index['B00']['symbols']
    basic = {symbol: statistics.basic(primary[symbol]) for symbol in SYMBOLS}
    base_pass = all(cell['合格'] for cell in basic.values())
    randoms = {identifier: {symbol: random_comparison(index, identifier, symbol) for symbol in SYMBOLS}
               for identifier in ('B00', 'B01', 'B12')}
    components = {}
    for symbol in SYMBOLS:
        value = primary[symbol]
        rows = {}
        for identifier in COMPONENTS:
            other = index[identifier]['symbols'][symbol]
            rows[identifier] = dict(主の合計R厳密超過=bool(value['net_r'] > other['net_r']),
                合計R差=value['net_r'] - other['net_r'], 円収支差=value['net_yen'] - other['net_yen'],
                対照=display(other))
        rand = randoms['B00'][symbol]
        flags = {identifier: row['主の合計R厳密超過'] for identifier, row in rows.items()}
        flags['乱数中央値'] = rand['同機会乱数中央値超過']
        components[symbol] = dict(合格=all(flags.values()), 主=display(value), 比較=flags, 明細=rows,
            乱数合計R中央値=rand['乱数合計R中央値'],
            主以上合計Rの乱数数=rand['主以上合計Rの乱数数'],
            主以上円収支の乱数数=rand['主以上円収支の乱数数'])
    # ----------------------------------------
    # 執行4条件は元の基礎全部、窓距離8近傍は別の固定条件で判定する。
    executions = {f'B00_{suffix}': {symbol: statistics.basic(index[f'B00_{suffix}']['symbols'][symbol])
                                   for symbol in SYMBOLS} for suffix in EXECUTION_SUFFIXES}
    neighbors = {}
    for symbol in SYMBOLS:
        rows = {}
        for suffix in NEIGHBOR_SUFFIXES:
            identifier = f'B00_{suffix}'
            value = index[identifier]['symbols'][symbol]
            rows[identifier] = dict(近傍基準=neighbor_activity(value), 基礎全項目=statistics.basic(value), 成績=display(value))
        count = sum(row['近傍基準']['合格'] for row in rows.values())
        nets = [row['成績']['net_yen'] for row in rows.values()]
        median, worst = float(np.median(nets)), float(min(nets))
        main_net = primary[symbol]['net_yen']
        flags = {'主基礎合格': basic[symbol]['合格'], '活動黒字PF通過6以上': count >= 6,
            '全8収支中央値が主50%以上': median >= .5 * main_net,
            '全8最悪が主マイナス25%以上': worst >= -.25 * main_net}
        neighbors[symbol] = dict(合格=all(flags.values()), 検査={key: bool(flag) for key, flag in flags.items()},
            近傍数=8, 活動黒字PF通過数=int(count), 全8収支中央値=median, 全8最悪収支=worst,
            主収支=main_net, 中央値下限=.5 * main_net, 最悪下限=-.25 * main_net, 全近傍=rows)
    # ----------------------------------------
    # 相手確認と独立価格帯は別解釈。成績がよくてもB00の不合格を救済しない。
    peers = {}
    independent = {}
    for symbol in SYMBOLS:
        value = index['B12']['symbols'][symbol]
        peers[symbol] = dict(基礎=statistics.basic(value), 成績=display(value),
            確認なし合計R超過=bool(value['net_r'] > primary[symbol]['net_r']),
            確認なし合計R差=value['net_r'] - primary[symbol]['net_r'],
            確認なし円収支差=value['net_yen'] - primary[symbol]['net_yen'],
            同機会乱数中央値超過=randoms['B12'][symbol]['同機会乱数中央値超過'],
            乱数合計R中央値=randoms['B12'][symbol]['乱数合計R中央値'])
    for identifier in ('B10', 'B11'):
        independent[identifier] = {}
        for symbol in SYMBOLS:
            value = index[identifier]['symbols'][symbol]
            independent[identifier][symbol] = dict(基礎=statistics.basic(value), 成績=display(value),
                主の合計R厳密超過=bool(primary[symbol]['net_r'] > value['net_r']),
                主の合計R差=primary[symbol]['net_r'] - value['net_r'],
                主の円収支差=primary[symbol]['net_yen'] - value['net_yen'],
                主の最大下落差=primary[symbol]['drawdown_yen'] - value['drawdown_yen'])
    added = all(cell['合格'] for cell in components.values())
    execution_pass = all(cell['合格'] for group in executions.values() for cell in group.values())
    neighbor_pass = base_pass and all(cell['合格'] for cell in neighbors.values())
    return dict(主仮説='B00', 全条件数=281, 主条件数=89, 方向乱数条件数=192,
        基礎候補=base_pass, 板の比較付加価値=added, 実行感度=execution_pass, 窓距離感度=neighbor_pass,
        既知経済目安合格=base_pass and added and execution_pass and neighbor_pass,
        基礎=basic, 成分対照=components, 実行感度詳細=executions, 近傍詳細=neighbors,
        相手確認={'B12': peers}, 価格独立対照=independent, 方向乱数=randoms,
        未知での有効性確認=False, 全体目標達成=False, 実装監査完了を意味しない=True,
        解釈='全13期間は既知。情報Rの超過だけでは活動不足や基礎不合格を救済しない。'
             'B01等は共通帯内の条件除去、B10/B11は別母集団の価格戦略。相手確認を主へ差し替えない。'
             '近傍は全8を分母とし、不利な近傍を除外しない。正式有意確率ではない。')
