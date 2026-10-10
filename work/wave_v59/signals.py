"""結果を参照せず固定した六入口を、確定移動平均から機械的に判定する。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from features import SETTINGS


HERE = Path(__file__).resolve().parent
FAMILIES = {'S1': '箱の端で反発', 'S2': '狭い帯への復帰', 'S3': '短い行き過ぎから反発',
            'M1': '短長移動平均の交差', 'M2': '移動平均の収束後の乖離', 'A1': '箱と傾向の自動選択'}
EXIT_NAMES = {'X1': '1幅利確・10分返済', 'X2': '1.5幅利確・半幅追跡', 'X3': '1幅追跡・場末返済'}
PRIMARY_EXITS = {'S1': 'X2', 'S2': 'X2', 'S3': 'X2', 'M1': 'X3', 'M2': 'X3', 'A1': 'X2'}


def methods() -> list[dict]:
    """機能: 六入口・四期間・三出口の72条件と、事前固定の主条件を列挙する。

    引数: なし。
    返り値: 条件ID・入口・設定・出口・主条件印を持つ一覧(list[dict])。
    """
    return [dict(id=f'{family}_{setting["id"]}_{exit_id}', family=family,
                 setting_id=setting['id'], exit_id=exit_id,
                 name=f'{name}／{setting["seconds"] // 60}分足SMA{setting["short"]}/{setting["long"]}／{exit_name}',
                 primary=setting['id'] == 'M1_5_20' and exit_id == PRIMARY_EXITS[family])
            for family, name in FAMILIES.items() for setting in SETTINGS
            for exit_id, exit_name in EXIT_NAMES.items()]


def fixed_width(opening_mid: float, tick: float) -> tuple[float, float]:
    """機能: 観測始値だけから共通幅と収束境界を固定する。

    引数: opening_mid(float) は場内最初の中値、tick(float) はラージ呼値。
    返り値: W と H(tuple[float,float])。銘柄名による分岐はしない。
    """
    width = max(2. * tick, math.ceil(opening_mid * .00025 / tick - 1e-10) * tick)
    half = math.ceil(.5 * width / tick - 1e-10) * tick
    return float(width), float(half)


def candidates(frame: pd.DataFrame, opening_mid: float, tick: float) -> dict[str, np.ndarray]:
    """機能: 六入口を同じ過去情報で判定し、公開原本行に候補を置く。

    引数: frame(pd.DataFrame) は確定足特徴、opening_mid/tick(float) は場初期値。
    返り値: 入口IDごとの Nx6 候補配列(dict[str,np.ndarray])。
    列は[原本有効行位置,方向,W,固定下限,固定上限,状態0箱/1傾向]。空候補も6列。
    """
    width, half = fixed_width(opening_mid, tick)
    current, previous = frame['close'], frame['close_lag1']
    short, long = frame['sma_short'], frame['sma_long']
    gap, old_gap = frame['gap'], frame['gap_lag1']
    low, high = frame['prior_box_low'], frame['prior_box_high']
    box = high - low
    range_gate = (box.ge(2 * width) & box.le(6 * width) & frame['er'].le(.35)
                  & (long - frame['sma_long_lag3']).abs().le(width)
                  & current.ge(low) & current.le(high))
    lower, upper = low - tick, high + tick
    raw_in_box = frame['mid'].ge(lower) & frame['mid'].le(upper)
    z = (current - long) / frame['std_long']
    previous_z = (previous - frame['sma_long_lag1']) / frame['std_long_lag1']
    usable_std = frame['std_long'].gt(0) & frame['std_long_lag1'].gt(0)

    # ----------------------------------------
    # 箱の中を狙う三入口と、方向が立ち上がる二入口を独立に作る。
    entry = {
        'S1': (previous.le(low + .2 * box) & current.ge(previous + tick) & current.le(low + .4 * box),
               previous.ge(high - .2 * box) & current.le(previous - tick) & current.ge(high - .4 * box)),
        'S2': (usable_std & previous_z.le(-1.5) & z.gt(-1.5) & current.lt(long),
               usable_std & previous_z.ge(1.5) & z.lt(1.5) & current.gt(long)),
        'S3': (frame['prior_move_start_observed'].eq(True) & frame['prior_move'].le(-width) & current.ge(previous + tick) & current.lt(long),
               frame['prior_move_start_observed'].eq(True) & frame['prior_move'].ge(width) & current.le(previous - tick) & current.gt(long)),
        'M1': (old_gap.le(0) & gap.gt(0), old_gap.ge(0) & gap.lt(0)),
        'M2': (frame['latest_three_observed'] & old_gap.abs().le(half) & frame['gap_lag2'].abs().le(half) & gap.gt(half)
               & short.gt(frame['sma_short_lag1']) & current.gt(short),
               frame['latest_three_observed'] & old_gap.abs().le(half) & frame['gap_lag2'].abs().le(half) & gap.lt(-half)
               & short.lt(frame['sma_short_lag1']) & current.lt(short)),
    }
    entry['A1'] = (
        (range_gate & entry['S1'][0]) | (~range_gate & frame['er'].ge(.55) & entry['M1'][0]),
        (range_gate & entry['S1'][1]) | (~range_gate & frame['er'].ge(.55) & entry['M1'][1]),
    )
    output = {}
    for family, (buy, sell) in entry.items():
        is_range = range_gate if family == 'A1' else pd.Series(family.startswith('S'), index=frame.index)
        enabled = frame['can_trade'] & (~is_range | (range_gate & raw_in_box & frame['prior_box_observed_fraction'].ge(.8)))
        selected = enabled & (buy ^ sell)
        sides = np.where(buy[selected], 1., -1.)
        kinds = np.where(is_range[selected], 0., 1.)
        rows = np.column_stack((
            frame.loc[selected, 'ready_index'].to_numpy(), sides, np.full(int(selected.sum()), width),
            np.where(kinds == 0, lower[selected], np.nan),
            np.where(kinds == 0, upper[selected], np.nan), kinds,
        )).astype(np.float64)
        assert rows.shape[1] == 6
        assert len(rows) < 2 or np.all(np.diff(rows[:, 0]) > 0)
        output[family] = rows
    return output


def audit_prefix(frame: pd.DataFrame, opening_mid: float, tick: float, full: dict) -> dict:
    """機能: 公開特徴の途中切断でも既判定の候補が変わらないことを確認する。

    引数: frame(pd.DataFrame)、opening_mid/tick(float)、full(dict) は全候補。
    返り値: 切断一致と候補数の証跡(dict)。未来収益は参照しない。
    """
    tested = 0
    for size in sorted(set((0, 1, len(frame) // 3, len(frame) * 3 // 4))):
        part = frame.iloc[:size].copy()
        value = candidates(part, opening_mid, tick)
        for family, rows in full.items():
            expected = rows[:0] if part.empty else rows[rows[:, 0] <= part.iloc[-1]['ready_index']]
            np.testing.assert_array_equal(value[family], expected)
            tested += 1
    return {'途中切断比較数': tested, '一致': True, '候補数': {k: len(v) for k, v in full.items()}}


def main(destination: Path = HERE) -> None:
    """機能: 抽出済みの場の候補と事前固定条件を保存する。

    引数: destination(Path) は旧23場または通知後に作られた確認2場の保存先。
    返り値: なし(None)。入力特徴と場初期値だけを読み、売買結果は開かない。
    """
    features = pickle.loads((destination / 'features.pkl').read_bytes())
    inputs = pickle.loads((destination / 'inputs.pkl').read_bytes())
    quotes = pickle.loads((destination / 'quotes.pkl').read_bytes())
    output, audits = {}, []
    for key, settings in features.items():
        output[key] = {}
        for setting_id, frame in settings.items():
            rows = candidates(frame, float(quotes[key]['mid'][0]), float(inputs[key]['tick']))
            output[key][setting_id] = rows
            audits.append({'セッション': key[0], '銘柄': key[1], '設定': setting_id,
                           **audit_prefix(frame, float(quotes[key]['mid'][0]), float(inputs[key]['tick']), rows)})
    assert len(methods()) == 72 and sum(x['primary'] for x in methods()) == 6
    (destination / '入口候補.pkl').write_bytes(pickle.dumps(output, protocol=pickle.HIGHEST_PROTOCOL))
    evidence = {'合格': True, '条件': methods(), '候補列': ['ready_index', 'side', 'W', 'lower', 'upper', 'regime'],
                '候補監査': audits, '損益参照': False, 'ATR使用': False, '原本直接読取': False,
                '対象場数': len(set(key[0] for key in features)),
                '入口品質': {'共通': 'long+3足経過・現在/前足実観測・現long窓80%以上・元終値年齢<=1足幅',
                         'レンジ系': '現在除外の前箱long本も80%以上実観測。箱状態で品質不適格なら見送り、傾向へ変更しない。',
                         'M1': '現在/前足実観測とMA有限。前足can_tradeは要求しない。初期状態entryはしない。',
                         'M2': '現在と過去2足の3足すべて実観測。',
                         'S3': '行き過ぎ計測の起点t-1-shortも実観測。'},
                'コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (destination / '入口仕様と監査.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'合格': True, '口座数': len(output), '期間別監査数': len(audits), '条件数': 72}, ensure_ascii=False))


if __name__ == '__main__':
    main()
