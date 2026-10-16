"""旧注文を保持し、当時の二市場気配を回復確認と中心帰還へ接続する。"""

import importlib.util
import math
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v91'


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


ENGINE = module('二市場回復と中心帰還執行92', HERE / 'engine.py')
# 旧strategyのimport engineを旧実装へ結び、追加名を混ぜない。
previous_engine = sys.modules.get('engine')
sys.modules['engine'] = module('二市場仮説保持執行91', OLD / 'engine.py')
try:
    LEGACY = module('二市場仮説保持状態91', OLD / 'strategy.py')
finally:
    if previous_engine is None:
        del sys.modules['engine']
    else:
        sys.modules['engine'] = previous_engine
LEGACY91 = LEGACY


def prepare(material, config):
    """
    機能: 旧入口をそのまま準備し、厳密過去格子の相手気配と各市場幅を添える。
    引数: material/config (dict)。
    返り値: dict は口座別record/signal。損益や将来価格は参照しない。
    """
    result = LEGACY.prepare(material, config)
    for key, value in result.items():
        signal = value['signal']
        session, symbol = key
        peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        peer_key = (session, peer)
        current = material['grids'][session]['markets'][peer]['current']
        peer_record = material['prices'][peer_key]
        reference = material['metadata']['references']['|'.join(peer_key)]['ref_open']
        assert reference['known_from_i'] == 0
        if config.get('range_width_mode', 'ticks') == 'opening_fraction':
            ticks = max(2, math.ceil(reference['value'] * float(config.get('range_width_fraction', .001))
                                     / peer_record['tick'] - 1e-10))
        else:
            assert config.get('range_width_mode', 'ticks') == 'ticks'
            ticks = float(config.get('width_ticks', 8))
        valid = (current['valid'] & current.get('q_valid', current['valid'])
                 & np.isfinite(current['bid']) & np.isfinite(current['ask'])
                 & np.isfinite(current['mid']) & (current['bid'] > 0)
                 & (current['ask'] > current['bid']))
        signal.update(peer_mid=current['mid'], peer_bid=current['bid'], peer_ask=current['ask'],
                      peer_source=current['index'], peer_valid=valid,
                      peer_width=ticks * peer_record['tick'], peer_tick=peer_record['tick'])
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
    return LEGACY.reversal_state(session, entry, config)


def play(config, key, prepared, finish=True):
    """
    機能: 同一の過去入力で仮説保持・反対返済・割合幅を独立に執行する。
    引数: config (dict)、key (tuple[str,str])、prepared (dict)、finish (bool)。
    返り値: dict は旧列を保つ全会計と、新しい基準更新イベント。
    """
    value = prepared[key]
    return ENGINE.execute(value['record'], value['signal'], config, finish=finish)
