"""H019の主方向・短期価格・相手確認を別々に切り替える入口比較器。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v27'
sys.path.insert(0, str(OLD))
import hierarchy_signals as HIERARCHY
assert Path(HIERARCHY.__file__).resolve() == (OLD / 'hierarchy_signals.py').resolve()
BASE = next(value for value in HIERARCHY.catalog() if value['id'] == 'H019')
SCALES = (.8, 1., 1.2)
_SHORT_CACHE: dict = {}


def specification(main_scale: float = 1., short_scale: float = 1.,
                  peer_confirm: bool = True, short_confirm: bool = True,
                  peer_scale: float = 1.) -> dict:
    """機能: 損益と無関係に入口部品の仕様を構成する。

    引数: main_scale/short_scale/peer_scale (float) は固定三倍率、
    peer_confirm/short_confirm (bool) は相手確認／短期確認の有無。
    返り値: 識別子と五つの制御値を持つ仕様 (dict)。
    主方向倍率はEMA短長本数と傾き本数を一括変更し、価格閾値は変更しない。
    """
    if any(type(value) not in (int, float) or value not in SCALES
           for value in (main_scale, short_scale, peer_scale)):
        raise ValueError('倍率は0.8、1、1.2のいずれかです')
    if type(peer_confirm) is not bool or type(short_confirm) is not bool:
        raise ValueError('確認有無は真偽値で指定します')
    if not short_confirm and short_scale != 1.:
        raise ValueError('短期確認なしでは不使用の短期倍率を1へ統一します')
    if not peer_confirm and peer_scale != 1.:
        raise ValueError('相手確認なしでは不使用の相手倍率を1へ統一します')
    identifier = (f'M{round(main_scale*100):03d}_S{round(short_scale*100):03d}'
                  f'_P{int(peer_confirm)}_C{int(short_confirm)}_D{round(peer_scale*100):03d}')
    return dict(id=identifier, main_scale=float(main_scale), short_scale=float(short_scale),
                peer_confirm=peer_confirm, short_confirm=short_confirm, peer_scale=float(peer_scale))


def catalog() -> list[dict]:
    """機能: 不使用倍率による見かけの重複を除いた26仕様を返す。

    引数: なし。返り値: 主3×相手2×短期4状態の24仕様と相手遅延2仕様 (list[dict])。
    実際の方向列の一致は結果別に数え、26独立予測とは呼ばない。
    """
    result = []
    for main in SCALES:
        for peer in (False, True):
            result.append(specification(main, 1., peer, False))
            result.extend(specification(main, short, peer, True) for short in SCALES)
    result.extend(specification(peer_scale=scale) for scale in (.8, 1.2))
    assert len(result) == len({value['id'] for value in result}) == 26
    return result


def clear_cache() -> None:
    """機能: 入力又は足の参照根を変える前に全キャッシュを破棄する。

    引数: なし。返り値: なし (None)。
    """
    _SHORT_CACHE.clear()
    HIERARCHY.clear_cache()


def set_root(path: Path | str) -> None:
    """機能: 旧信号の確定1分足参照先を明示的に変更する。

    引数: path (Path|str) はcandle_1minを含む根。返り値: なし (None)。
    元原本の変更はせず、監査用の複写先へ切り替えるために用いる。
    """
    _SHORT_CACHE.clear()
    HIERARCHY.set_root(path)


def legacy_spec(spec: dict) -> dict:
    """機能: 主方向と相手の計算に使う旧H019の仕様を複製する。

    引数: spec (dict) は本比較器の仕様。返り値: 主方向倍率だけ接続した旧形の仕様 (dict)。
    旧固定カタログを変更せず、旧内部の因果関数へ渡す。
    """
    expected = specification(**{key: value for key, value in spec.items() if key != 'id'})
    if spec != expected:
        raise ValueError('識別子又は入口仕様が一致しません')
    result = deepcopy(BASE)
    result['id'] = spec['id']
    result['params'].update(clock_multiplier=spec['main_scale'],
                            peer_confirm=spec['peer_confirm'], peer_multiplier=spec['peer_scale'])
    return result


def short_model(ready: dict, frame, short_scale: float) -> dict:
    """機能: 同じ公開中値から短期価格の窓だけを独立計算する。

    引数: ready (dict)、frame (pandas.DataFrame)、short_scale (float)。
    返り値: 公開時刻・行番号・短期変化ATR比の辞書 (dict)。
    板数量は入口判定に使わない。旧板公開順と中値・ATRの対応は維持する。
    """
    seconds = HIERARCHY._size(30 * short_scale)
    key = (str(HIERARCHY.ROOT), id(ready), id(frame), id(ready['atr']),
           len(ready['seq']), int(ready['seq'][-1]), float(ready['time_s'][-1]), seconds)
    if key not in _SHORT_CACHE:
        model = HIERARCHY.LEGACY._board(ready, frame, 60)
        prior = HIERARCHY._asof(model['time_s'], model['mid'], model['time_s'] - seconds, np.nan)
        _SHORT_CACHE[key] = dict(time_s=model['time_s'], seq=model['seq'],
                                short=(model['mid']-prior)/model['atr'],
                                ready_ref=ready, frame_ref=frame)
    return _SHORT_CACHE[key]


def build(spec: dict, inputs: dict, features: dict) -> dict:
    """機能: 主方向窓・短期窓・相手有無・短期有無を独立に接続する。

    引数: spec (dict)、inputs (dict[tuple,dict])、features (dict[tuple,DataFrame])。
    返り値: 原本行ごとの-1/0/+1入口列 (dict[tuple,ndarray[int8]])。
    保有や損益は参照せず、暖機・閾値・主方向保持・短期TTLは元H019と同じ。
    """
    old_spec = legacy_spec(spec)
    if not inputs or not set(inputs) <= set(features):
        raise ValueError('入力又は対応する公開特徴が不足しています')
    for session, symbol in inputs:
        other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        if symbol not in ('TOPIX', 'NK225') or (spec['peer_confirm'] and (session, other) not in inputs):
            raise ValueError('相手確認には同じセッションの両市場が必要です')
    params = old_spec['params']
    main = HIERARCHY.main_directions(old_spec, inputs)
    if not spec['short_confirm']:
        return main
    # ----------------------------------------
    # 主方向は主窓だけ、短期価格は短期窓だけで計算する。
    models = {key: HIERARCHY._main_model(ready, params) for key, ready in inputs.items()}
    output = {}
    for key, ready in inputs.items():
        short = short_model(ready, features[key], spec['short_scale'])
        allowed = HIERARCHY._allowed(key, short['time_s'], models, params)
        allowed[short['time_s'] < ready['start'] + 1200] = 0
        direction, _, _ = HIERARCHY._entry_filter(ready['seq'], ready['time_s'], main[key],
            short['seq'], short['time_s'], allowed, short['short'], np.zeros(len(short['seq'])), 1, 1.)
        assert direction.dtype == np.int8 and direction.shape == ready['seq'].shape
        assert np.isin(direction, [-1, 0, 1]).all()
        output[key] = direction
    return output
