"""独立価格の分類と、変更しない原板執行・回復源を明示的に分ける。"""

import importlib.util
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v93'


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


ENGINE = module('二市場分離価格と現在入口執行94', HERE / 'engine.py')
LEGACY = module('二市場入口余地と失敗再準備状態93の読取94', OLD / 'strategy.py')
LEGACY91 = LEGACY.LEGACY91


def lane_current(current: dict,record: dict | None=None) -> dict:
    """
    機能: 価格currentの種類を値・独立index・原seq・時計へ明示的に正規化する。
    引数: current(dict)、record(dict|None)は旧I0だけに使う原板対応。
    返り値: dict。LP値を執行midやBBO源へ代入しない。
    """
    source=current['index'];size=len(source)
    values=current.get('value',current.get('mid'))
    assert values is not None
    if 'raw_seq' in current:
        sequence=current['raw_seq'];clock=current['time_s']
    else:
        assert record is not None
        sequence=np.full(size,-1,np.int64);clock=np.full(size,np.nan)
        accepted=(source>=0)&(source<len(record['seq']))
        sequence[accepted]=record['seq'][source[accepted]]
        clock[accepted]=record['time_s'][source[accepted]]
    return dict(index=source,raw_seq=sequence,time_s=clock,value=values,valid=current['valid'])


def price_state(session: dict,execution: dict,config: dict) -> dict:
    """
    機能: 選んだ価格laneだけで共通方向・ER分類を作り、旧OFIの逆証拠を添える。
    引数: session(dict)は価格、execution(dict)は旧板・flow、config(dict)。
    返り値: dictは格子別mode/raw_mode/valid/common/observableと価格原seqの確認源。
    G0旧準備の不明共同0代用を対照として保持し、G1/G2新規だけ観測可否を別判定する。
    回復mid・約定BBOはこの関数へ渡さず、独立価格で置き換えない。
    """
    grid=session['grid'];size=len(grid)
    markets=[session['markets'][symbol] for symbol in ('TOPIX','NK225')]
    current_valid=np.ones(size,bool);observable=np.ones(size,bool)
    er_valid=np.ones(size,bool);low=np.ones(size,bool);high=np.ones(size,bool);inside=np.ones(size,bool)
    common_valid=np.ones(size,bool)
    for market in markets:
        current=market['current'];value=current.get('value',current.get('mid'))
        er=market['windows'][300];bounds=market['ranges'][180]
        now=current['valid']&np.isfinite(value)&(value>0)
        current_valid&=now
        er_known=(now&er['source_valid']&np.isfinite(er['efficiency'])
                  &np.isfinite(er['total_variation'])&(er['total_variation']>0))
        er_valid&=er_known
        low&=er['efficiency']<=config['low_er'];high&=er['efficiency']>=config['high_er']
        bounds_known=(bounds['source_valid']&bounds['position_valid']&np.isfinite(bounds['width'])
                      &(bounds['width']>0)&np.isfinite(bounds['low'])&np.isfinite(bounds['high']))
        inside&=bounds_known&(value>=bounds['low'])&(value<=bounds['high'])
        market_observed=er_known&bounds_known
        for seconds in (30,300):
            window=market['windows'][seconds]
            known=now&window['source_valid']&np.isfinite(window['ret_bp'])
            common_valid&=known;market_observed&=known
        observable&=market_observed
    common=np.zeros(size,np.int8)
    allowed={}
    for side in (-1,1):
        direction=common_valid.copy();ratio=current_valid.copy();returns=[]
        reverse=np.zeros(size,bool)
        for symbol,market in zip(('TOPIX','NK225'),markets):
            long=market['windows'][300];short=market['windows'][30]
            direction&=(side*long['ret_bp']>=3.)&(side*short['ret_bp']>0)
            ratio&=long['source_valid']&np.isfinite(long['ret_bp'])&(side*long['ret_bp']>0)
            returns.append(side*long['ret_bp'])
            flow=execution['markets'][symbol]['flow'][15]
            sufficient=(flow['source_valid']&flow['valid']&~flow['missing_ofi']
                        &(flow['nonzero_ofi_count']>=3)&np.isfinite(flow['ofi_ratio']))
            reverse|=sufficient&(side*flow['ofi_ratio']<=-.1)
        common[direction]=side
        ratio&=np.minimum(returns[0],returns[1])>=.25*np.maximum(returns[0],returns[1])
        allowed[side]=ratio&~reverse
    raw=np.zeros(size,np.int8)
    for side in (-1,1):raw[er_valid&high&(common==side)&allowed[side]]=side
    # G0の準備は元のconjunctionを維持。不明共同0も旧対照として残す。
    raw[er_valid&low&inside&(common==0)]=2
    sources=[market['current']['raw_seq'] for market in markets]
    mode=np.zeros(size,np.int8)
    context_mode=np.zeros(size,np.int8)
    for candidate in (-1,1,2):
        valid=er_valid
        seconds=config.get('trend_mode_confirm_seconds',config['confirm_seconds']) if candidate in (-1,1) else config['confirm_seconds']
        mode[LEGACY91.LEGACY.confirmation(grid,raw==candidate,valid,sources[0],sources[1],float(seconds))]=candidate
    context_mode[LEGACY91.LEGACY.confirmation(grid,raw==2,observable,sources[0],sources[1],
                                            float(config['confirm_seconds']))]=2
    return dict(grid=grid,valid=er_valid,raw_mode=raw,mode=mode,source_top=sources[0],source_nk=sources[1],
                efficiency_top=markets[0]['windows'][300]['efficiency'],
                efficiency_nk=markets[1]['windows'][300]['efficiency'],common=common,
                arm_common=common,price_observable=observable,price_current_valid=current_valid,
                price_mode=context_mode)


def prepare(material, config):
    """
    機能: 旧執行と回復源を保持して、価格分類だけを独立laneへ差し替える。
    引数: material/config (dict)。
    返り値: dict は口座別record/signal。損益や将来価格は参照しない。
    """
    result = LEGACY.prepare(material, config)
    lane=config.get('price_lane','I0')
    assert lane in ('I0','I1','I2','I3')
    prices=material['price_lanes'][lane]
    normalized={}
    for session,value in prices.items():
        markets={}
        for symbol in ('TOPIX','NK225'):
            market=value['markets'][symbol]
            markets[symbol]=dict(market,current=lane_current(market['current'],material['prices'][(session,symbol)] if lane=='I0' else None))
        normalized[session]=dict(grid=value['grid'],markets=markets)
    states={session:price_state(value,material['grids'][session],config)
            for session,value in normalized.items()}
    for key, value in result.items():
        signal = value['signal']
        session, symbol = key
        peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        price_own=normalized[session]['markets'][symbol]['current']
        price_peer=normalized[session]['markets'][peer]['current']
        np.testing.assert_array_equal(signal['grid'],normalized[session]['grid'])
        if lane!='I0':
            # current_valid/peer_mid/peer_sourceは旧執行のまま。価格分類だけを交換する。
            signal.update(states[session])
        signal.update(price_observable=states[session]['price_observable'],
                      price_mode=states[session]['price_mode'],
                      price_own_index=price_own['index'],price_peer_index=price_peer['index'],
                      price_own_raw_seq=price_own['raw_seq'],price_peer_raw_seq=price_peer['raw_seq'],
                      price_own_time=price_own['time_s'],price_peer_time=price_peer['time_s'],
                      price_own_valid=price_own['valid'],price_peer_valid=price_peer['valid'])
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
