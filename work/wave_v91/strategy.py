"""旧入口を保持し、持続する往復仮説と独立した反対返済を因果的に接続する。"""

import importlib.util
import math
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v90'


def module(name, path):
    """
    機能: 旧又は追加の実装を固有名で取り込み、通常名の衝突を避ける。
    引数: name (str)、path (Path)。
    返り値: object は読取モジュール。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


ENGINE = module('二市場仮説保持執行91', HERE / 'engine.py')
# 旧strategyのimport engineを旧実装へ結び、追加名を混ぜない。
previous_engine = sys.modules.get('engine')
sys.modules['engine'] = module('二市場固定執行90r1', OLD / 'engine.py')
try:
    LEGACY = module('二市場固定状態90r1', OLD / 'strategy.py')
finally:
    if previous_engine is None:
        del sys.modules['engine']
    else:
        sys.modules['engine'] = previous_engine


def prepare(material, config):
    """
    機能: 旧入口と分類を保持し、反対方向と固定割合幅だけ別軸として準備する。
    引数: material/config (dict)。
    返り値: dict は口座別record/signal。損益と将来の範囲は参照しない。
    """
    result = LEGACY.prepare(material, config)
    states = {key: reversal_state(value, material['entries'][key], config)
              for key, value in material['grids'].items()}
    for key, value in result.items():
        signal = value['signal']
        if 'trend_mode_confirm_seconds' in config:
            seconds = float(config['trend_mode_confirm_seconds'])
            assert seconds >= 0
            mode = np.where(signal['mode'] == 2, 2, 0).astype(np.int8)
            for side in (-1, 1):
                confirmed = LEGACY.confirmation(signal['grid'], signal['raw_mode'] == side,
                                                signal['valid'], signal['source_top'], signal['source_nk'], seconds)
                mode[confirmed] = side
            signal['mode'] = mode
        signal.update(states[key[0]])
        record = value['record']
        reference = material['metadata']['references']['|'.join(key)]['ref_open']
        assert reference['known_from_i'] == 0
        if config.get('range_width_mode', 'ticks') == 'opening_fraction':
            ticks = max(2, math.ceil(reference['value'] * float(config.get('range_width_fraction', .001))
                                     / record['tick'] - 1e-10))
        else:
            assert config.get('range_width_mode', 'ticks') == 'ticks'
            ticks = float(config.get('width_ticks', 8))
        signal['range_width'] = ticks * record['tick']
    return result


def reversal_state(session, entry, config):
    """
    機能: 入口ERとは独立に、二市場の既知共同方向と両気配の逆進行を確認する。
    引数: session/entry/config (dict) は過去格子、旧共通方向、事前条件。
    返り値: dict は格子別の共通方向、現在鮮度、保有方向別の反対返済旗。
    commonは双方300秒各3bp以上に加え双方30秒同方向、quotesは双方30秒両気配各1呼値。
    eitherはcommonとquotesを独立した持続時計で確認してから論理和を取る。
    異なる証拠が交互に成立しても、それぞれの確認時計を引き継がない。
    欠測、中立、高ERでない状態は反対の証拠へ代用しない。
    """
    grid = session['grid']
    markets = [session['markets'][symbol] for symbol in ('TOPIX', 'NK225')]
    current_valid = np.ones(len(grid), dtype=bool)
    common_valid = current_valid.copy()
    quotes_valid = current_valid.copy()
    for market in markets:
        current_valid &= market['current']['valid']
        for window in (30, 300):
            value = market['windows'][window]
            common_valid &= value['source_valid'] & np.isfinite(value['ret_bp'])
        value = market['windows'][30]
        quotes_valid &= (value['source_valid'] & np.isfinite(value['bid_change_ticks'])
                         & np.isfinite(value['ask_change_ticks']))
    common_valid &= current_valid
    quotes_valid &= current_valid
    common = np.where(common_valid, entry['common'], 0).astype(np.int8)
    trend300 = np.zeros(len(grid), dtype=np.int8)
    for side in (-1, 1):
        eligible = current_valid.copy()
        for market in markets:
            value = market['windows'][300]
            eligible &= (value['source_valid'] & np.isfinite(value['ret_bp'])
                         & (side * value['ret_bp'] >= 3.))
        trend300[eligible] = side
    source_a, source_b = (market['current']['index'] for market in markets)
    result = dict(current_valid=current_valid, arm_common=common, arm_trend300=trend300)
    kind = config.get('reverse_kind', 'none')
    assert kind in ('none', 'common', 'quotes', 'either')
    seconds = float(config.get('reverse_confirm_seconds', 15.))
    assert seconds >= 0
    for side, name in ((1, 'long'), (-1, 'short')):
        joint = common_valid & (common == -side)
        quotes = quotes_valid.copy()
        for market in markets:
            value = market['windows'][30]
            quotes &= ((-side * value['bid_change_ticks'] >= 1. - 1e-8)
                       & (-side * value['ask_change_ticks'] >= 1. - 1e-8))
        if kind == 'none':
            condition = np.zeros(len(grid), dtype=bool)
            valid = current_valid
        elif kind == 'common':
            condition, valid = joint, common_valid
        elif kind == 'quotes':
            condition, valid = quotes, quotes_valid
        else:
            result[f'reverse_{name}'] = (
                LEGACY.confirmation(grid, joint, common_valid, source_a, source_b, seconds)
                | LEGACY.confirmation(grid, quotes, quotes_valid, source_a, source_b, seconds))
            continue
        result[f'reverse_{name}'] = LEGACY.confirmation(grid, condition, valid, source_a, source_b, seconds)
    return result


def play(config, key, prepared, finish=True):
    """
    機能: 同一の過去入力で仮説保持・反対返済・割合幅を独立に執行する。
    引数: config (dict)、key (tuple[str,str])、prepared (dict)、finish (bool)。
    返り値: dict は旧列を保つ全会計と、新しい基準更新イベント。
    """
    value = prepared[key]
    return ENGINE.execute(value['record'], value['signal'], config, finish=finish)
