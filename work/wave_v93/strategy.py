"""旧注文を保持し、判断時の入口余地と失敗後の新観測を添える。"""

import importlib.util
import math
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v92'


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


ENGINE = module('二市場入口余地と失敗再準備執行93', HERE / 'engine.py')
LEGACY = module('二市場回復と中心帰還状態92の読取93', OLD / 'strategy.py')
LEGACY91 = LEGACY.LEGACY91


def prepare(material, config):
    """
    機能: 旧入口をそのまま準備し、失敗後に検証する格子源時計と可観測性を添える。
    引数: material/config (dict)。
    返り値: dict は口座別record/signal。損益や将来価格は参照しない。
    """
    result = LEGACY.prepare(material, config)
    for key, value in result.items():
        signal = value['signal']
        session, symbol = key
        peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        peer_key = (session, peer)
        markets = material['grids'][session]['markets']
        current = markets[peer]['current']
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
        # ----------------------------------------
        # 追加時計は既存の厳密過去源番号だけから取り、未来端点を探索しない。
        size = len(signal['grid'])
        source_times = {}
        oldest = np.full(size, np.inf)
        observable = signal['valid'].copy()
        for market_symbol in ('TOPIX', 'NK225'):
            market = markets[market_symbol]
            raw = material['prices'][(session, market_symbol)]
            source = market['current']['index']
            clock = np.full(size, np.nan)
            accepted = (source >= 0) & (source < len(raw['time_s']))
            clock[accepted] = raw['time_s'][source[accepted]]
            source_times[market_symbol] = clock
            bounds = market['ranges'][180]
            observable &= (bounds['source_valid'] & bounds['position_valid']
                           & np.isfinite(bounds['width']) & (bounds['width'] > 0)
                           & np.isfinite(bounds['low']) & np.isfinite(bounds['high'])
                           & np.isfinite(market['current']['mid']))
            for seconds in (30, 300):
                window = market['windows'][seconds]
                observable &= window['source_valid'] & np.isfinite(window['ret_bp'])
            for history in (market['windows'][30], market['windows'][300], bounds):
                old_source = history['old']
                old_clock = np.full(size, np.nan)
                known = (old_source >= 0) & (old_source < len(raw['time_s']))
                old_clock[known] = raw['time_s'][old_source[known]]
                oldest = np.minimum(oldest, old_clock)
        signal.update(own_source=markets[symbol]['current']['index'],
                      own_source_time=source_times[symbol], peer_source_time=source_times[peer],
                      raw_range_valid=observable, raw_range_eligible=signal['raw_mode'] == 2,
                      raw_oldest_time=oldest)
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
    機能: 同一の過去入力で入口余地・停止OR・中心利確・失敗後休止を執行する。
    引数: config (dict)、key (tuple[str,str])、prepared (dict)、finish (bool)。
    返り値: dict は旧列を保つ全会計と、新しい基準更新イベント。
    """
    value = prepared[key]
    return ENGINE.execute(value['record'], value['signal'], config, finish=finish)
