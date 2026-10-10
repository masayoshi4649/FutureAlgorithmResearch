"""中期価格の主方向を保持し、短期価格・板を入口時刻の選別だけに使う。"""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from numba import njit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DESIGN_PATH = HERE / 'hierarchy_design_fixed.json'
DESIGN = json.loads(DESIGN_PATH.read_text(encoding='utf-8'))
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('v27_medium_price_legacy', ROOT / 'work/wave_v23/signals.py')
LEGACY = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = LEGACY
_spec.loader.exec_module(LEGACY)
_MAIN_CACHE, _SHORT_CACHE = {}, {}
SYMBOLS = ('TOPIX', 'NK225')


def catalog() -> list[dict]:
    """機能: 実装前に固定した96条件を複製して返す。

    引数: なし。返り値: ID・思想・固定パラメータの一覧 (list[dict])。
    注意: hierarchy_design_fixed.json も実行依存として指紋固定すること。
    """
    return deepcopy(DESIGN['条件'])


def clear_cache() -> None:
    """機能: 確定足・板・主方向キャッシュを全て解除し、公開ROOTを同期する。

    引数: なし。返り値: なし (None)。ROOT直接差替後にも呼べる。
    """
    LEGACY.ROOT = Path(ROOT)
    LEGACY.clear_cache()
    _MAIN_CACHE.clear()
    _SHORT_CACHE.clear()


def set_root(path: Path | str) -> None:
    """機能: 保存済み現在セッション等の確定足参照根へ明示的に切り替える。

    引数: path (Path|str) はcandle_1minを含む根。返り値: なし (None)。
    ROOTとLEGACY.ROOTを同期し、旧根のキャッシュを全て破棄する。
    """
    global ROOT
    ROOT = Path(path).resolve()
    clear_cache()


def uses_peer(spec: dict) -> bool:
    """機能: 相手の中期主方向を参照する条件か判定する。

    引数: spec (dict)。返り値: 相手参照の有無 (bool)。
    """
    return bool(spec['params']['peer_confirm'])


def neighbor_specs(spec: dict) -> list[dict]:
    """機能: 時計・相手遅延・短期確認強度の±20%を別々に定義する。

    引数: spec (dict)。返り値: v26と同形の6診断仕様 (list[dict])。
    confirmationは経過秒ではなく入口の価格・OFI閾値を意味する。
    """
    output = []
    for category, parameter in (('clock', 'clock_multiplier'), ('peer', 'peer_multiplier'), ('confirmation', 'confirmation_multiplier')):
        for suffix, factor in (('M20', .8), ('P20', 1.2)):
            params = dict(spec['params'])
            params[parameter] *= factor
            applied, reason = True, ''
            if category == 'peer' and not uses_peer(spec):
                applied, reason = False, '自市場のみのため相手遅延は不使用'
            if category == 'confirmation' and params['entry_kind'] == 'direction':
                applied, reason = False, '主方向のみのため短期入口閾値は不使用'
            output.append(dict(spec, id=f'{spec["id"]}_{category.upper()}_{suffix}', params=params,
                               diagnostic_parent=spec['id'], diagnostic_category=category,
                               applied=applied, skip_reason=reason,
                               description=spec['description'] + f' {category}を{factor}倍する一律反証。'))
    return output


def _size(value: float) -> int:
    """機能: 事前固定規則で時間窓を四捨五入する。

    引数: value (float)。返り値: 1以上の整数 (int)。
    """
    return max(1, int(np.floor(value + .5)))


def _asof(events: np.ndarray, values: np.ndarray, targets: np.ndarray, initial: float = 0.) -> np.ndarray:
    """機能: 指定時点以前に公開された最後の値だけを対応させる。

    引数: events/values/targets (ndarray)、initial (float)。返り値: 過去値配列 (ndarray)。
    """
    positions = np.searchsorted(events, targets, side='right') - 1
    output = np.full(len(targets), initial, dtype=float)
    valid = positions >= 0
    output[valid] = np.asarray(values)[positions[valid]]
    return output


@njit(cache=True)
def _persistent(arm: np.ndarray, measure: np.ndarray, release: float, inclusive: bool) -> np.ndarray:
    """機能: 中期の開始条件と撤回条件を分離して方向を保持する。

    引数: arm/measure (ndarray)、release (float)、inclusive (bool)。返り値: 主方向 (ndarray[int8])。
    """
    output = np.zeros(len(arm), dtype=np.int8)
    state = 0
    for index in range(len(arm)):
        if not np.isfinite(measure[index]):
            state = 0
        elif state:
            value = state * measure[index]
            if (inclusive and value <= release) or (not inclusive and value < release):
                state = 0
        if arm[index] != 0:
            state = int(arm[index])
        output[index] = state
    return output


def _main_from_bars(bars: dict, params: dict) -> np.ndarray:
    """機能: 既に公開された確定足だけで6種類の中期主方向を計算する。

    引数: bars/params (dict)。返り値: 確定足公開時点ごとの主方向 (ndarray[int8])。
    """
    kind = params['main_kind']
    fixed = DESIGN['主方向'][kind]
    scale = params['time_multiplier'] * params['clock_multiplier']
    close = pd.Series(np.asarray(bars['close'], dtype=float))
    atr = np.asarray(bars['atr'], dtype=float)
    arm = np.zeros(len(close), dtype=np.int8)
    inclusive, release = False, 0.
    if kind in ('ema8_30', 'ema15_60'):
        fast, slow, slope_bars = (_size(fixed[key] * scale) for key in ('fast', 'slow', 'slope_bars'))
        short = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
        long = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        measure = ((short - long) / atr).to_numpy(float)
        slope = (long.diff(slope_bars) / atr).to_numpy(float)
        arm[(measure > fixed['entry_gap_atr']) & (slope > fixed['entry_slope_atr'])] = 1
        arm[(measure < -fixed['entry_gap_atr']) & (slope < -fixed['entry_slope_atr'])] = -1
    elif kind == 'momentum20':
        window = _size(fixed['window'] * scale)
        measure = (close.diff(window) / atr).to_numpy(float)
        arm = LEGACY._signed(measure, fixed['enter_atr'])
        inclusive, release = True, fixed['release_atr']
    elif kind == 'breakout20':
        window = _size(fixed['window'] * scale)
        upper = pd.Series(np.asarray(bars['high'], dtype=float)).shift(1).rolling(window, min_periods=window).max()
        lower = pd.Series(np.asarray(bars['low'], dtype=float)).shift(1).rolling(window, min_periods=window).min()
        measure = ((close - (upper + lower) / 2) / atr).to_numpy(float)
        arm[(close > upper + fixed['buffer_atr'] * atr).to_numpy()] = 1
        arm[(close < lower - fixed['buffer_atr'] * atr).to_numpy()] = -1
    elif kind == 'vwap':
        vwap = pd.Series(np.asarray(bars['vwap'], dtype=float))
        measure = ((close - vwap) / atr).to_numpy(float)
        slope = (vwap.diff(_size(fixed['slope_bars'] * scale)) / atr).to_numpy(float)
        arm[(measure > fixed['entry_distance_atr']) & (slope > fixed['entry_slope_atr'])] = 1
        arm[(measure < -fixed['entry_distance_atr']) & (slope < -fixed['entry_slope_atr'])] = -1
    elif kind == 'regression30':
        window = max(2, _size(fixed['window'] * scale))
        weights = np.arange(window, dtype=float) - (window - 1) / 2
        denominator = float(np.dot(weights, weights))
        slopes = close.rolling(window, min_periods=window).apply(lambda values: float(np.dot(weights, values)) / denominator, raw=True)
        measure = (slopes * (window - 1) / atr).to_numpy(float)
        arm = LEGACY._signed(measure, fixed['enter_projected_atr'])
        inclusive, release = True, fixed['release_projected_atr']
    else:
        raise ValueError(f'未定義の主方向: {kind}')
    measure = np.asarray(measure, dtype=float).copy()
    valid = np.isfinite(atr) & (atr > 0)
    arm[~valid] = 0
    measure[~valid] = np.nan
    return _persistent(arm, measure, release, inclusive)


def _main_model(ready: dict, params: dict) -> dict:
    """機能: 参照根と入力終端を区別して、因果的な主方向を再利用する。

    引数: ready/params (dict)。返り値: 公開時刻・主方向・入力参照 (dict)。
    """
    key = (str(ROOT), id(ready), id(ready['atr']), len(ready['seq']), int(ready['seq'][-1]),
           float(ready['time_s'][-1]), params['main_kind'], params['time_multiplier'], params['clock_multiplier'])
    if key not in _MAIN_CACHE:
        bars = LEGACY._bars(ready)
        _MAIN_CACHE[key] = {'time_s': np.asarray(bars['time_s']), 'direction': _main_from_bars(bars, params),
                            'ready_ref': ready}
    return _MAIN_CACHE[key]


def _allowed(key: tuple[str, str], targets: np.ndarray, models: dict, params: dict) -> np.ndarray:
    """機能: 自市場主方向を、任意で遅延した相手主方向との一致に限定する。

    引数: key (tuple[str,str])、targets (ndarray)、models/params (dict)。返り値: 許可主方向 (ndarray[int8])。
    """
    own = models[key]
    values = _asof(own['time_s'], own['direction'], targets).astype(np.int8)
    if params['peer_confirm']:
        other_key = (key[0], 'TOPIX' if key[1] == 'NK225' else 'NK225')
        if other_key not in models:
            raise ValueError('相手確認には同じセッションの両銘柄が必要')
        other = models[other_key]
        delay = _size(60 * params['peer_multiplier'])
        peer = _asof(other['time_s'] + delay, other['direction'], targets).astype(np.int8)
        values[values != peer] = 0
    return values


def main_directions(spec: dict, inputs: dict) -> dict:
    """機能: 短期入口を適用する前の中期許可方向を原本行へ展開する。

    引数: spec/inputs (dict)。返り値: 主方向だけの区間別配列 (dict)。
    """
    if Path(LEGACY.ROOT) != Path(ROOT):
        clear_cache()
    params = spec['params']
    models = {key: _main_model(ready, params) for key, ready in inputs.items()}
    output = {}
    for key, ready in inputs.items():
        direction = _allowed(key, ready['time_s'], models, params)
        direction[(ready['time_s'] < ready['start'] + 1200) | ~np.isfinite(ready['atr']) | (ready['atr'] <= 0)] = 0
        output[key] = direction
    return output


def _short_model(ready: dict, frame: pd.DataFrame, params: dict) -> dict:
    """機能: 公開済み板だけで短期価格差とOFIを計算する。

    引数: ready/params (dict)、frame (DataFrame)。返り値: 解放時刻・seq・短期価格・OFI (dict)。
    """
    seconds, short_seconds = _size(60 * params['clock_multiplier']), _size(30 * params['clock_multiplier'])
    key = (id(ready), id(frame), id(ready['atr']), len(ready['seq']), int(ready['seq'][-1]), float(ready['time_s'][-1]), seconds, short_seconds)
    if key not in _SHORT_CACHE:
        model = LEGACY._board(ready, frame, seconds)
        short = (model['mid'] - _asof(model['time_s'], model['mid'], model['time_s'] - short_seconds, np.nan)) / model['atr']
        _SHORT_CACHE[key] = {'time_s': model['time_s'], 'seq': model['seq'], 'ofi': model['ofi'], 'short': short,
                             'ready_ref': ready, 'frame_ref': frame}
    return _SHORT_CACHE[key]


@njit(cache=True)
def _entry_filter(raw_seq: np.ndarray, raw_time: np.ndarray, allowed: np.ndarray,
                  event_seq: np.ndarray, event_time: np.ndarray, event_main: np.ndarray,
                  price_short: np.ndarray, ofi: np.ndarray, mode: int, scale: float) -> tuple:
    """機能: 原本順で入口を監視し、準備と後続発火を別イベントとして記録する。

    引数: raw/event各配列・allowed/price_short/ofi (ndarray)、mode (int)、scale (float)。
    返り値: 原本方向・発火時の準備seq・イベント発火方向 (tuple[ndarray,...])。
    主方向撤回は板イベントの間にも評価し、撤回後に古い入口や準備を復活させない。
    """
    output = np.zeros(len(raw_seq), dtype=np.int8)
    setup_used = np.full(len(event_seq), -1, dtype=np.int64)
    fired = np.zeros(len(event_seq), dtype=np.int8)
    state, armed, cursor, armed_seq = 0, 0, 0, -1
    supported, armed_at, last_event = -np.inf, -np.inf, -np.inf
    for row in range(len(raw_seq)):
        if state and state != allowed[row]:
            state = 0
        if armed and armed != allowed[row]:
            armed = 0
        while cursor < len(event_seq) and event_seq[cursor] <= raw_seq[row]:
            stamp, main = event_time[cursor], int(event_main[cursor])
            if stamp - last_event > 120 or stamp - supported > 120 or (state and state != main):
                state = 0
            if armed and (armed != main or stamp - armed_at > 600):
                armed = 0
            candidate = 0
            if mode == 1 and main * price_short[cursor] > .05 * scale:
                candidate = main
            elif mode == 2 and main * price_short[cursor] > .05 * scale and main * ofi[cursor] > .05 * scale:
                candidate = main
            elif mode == 3:
                if armed:
                    if event_seq[cursor] > armed_seq and armed * price_short[cursor] > .05 * scale:
                        candidate = armed
                        setup_used[cursor] = armed_seq
                        armed = 0
                elif main and main * price_short[cursor] < -.10 * scale:
                    armed, armed_at, armed_seq = main, stamp, event_seq[cursor]
            if candidate:
                state, supported = candidate, stamp
                fired[cursor] = candidate
            last_event = stamp
            cursor += 1
        if raw_time[row] - supported > 120 or (state and state != allowed[row]):
            state = 0
        if armed and (armed != allowed[row] or raw_time[row] - armed_at > 600):
            armed = 0
        output[row] = state
    return output, setup_used, fired


def build(spec: dict, inputs: dict, features: dict) -> dict:
    """機能: 固定条件の主方向と短期入口を分離して、原本行ごとの方向を返す。

    引数: spec/inputs/features (dict)。返り値: 区間別方向 (dict[tuple[str,str],ndarray[int8]])。
    未来価格・将来損益・指定した日付例は参照しない。新規・返済は別の注文管理器で実行する。
    """
    fixed = {value['id']: value for value in catalog()}
    expected = fixed.get(spec.get('id'))
    if expected is None and spec.get('diagnostic_parent') in fixed:
        expected = {value['id']: value for value in neighbor_specs(fixed[spec['diagnostic_parent']])}.get(spec.get('id'))
    if expected is None or expected['params'] != spec.get('params'):
        raise ValueError('実装前に固定した条件又は一律反証条件と一致しない')
    params = spec['params']
    main = main_directions(spec, inputs)
    if params['entry_kind'] == 'direction':
        return main
    models = {key: _main_model(ready, params) for key, ready in inputs.items()}
    output = {}
    modes = {'short_price': 1, 'ofi_price': 2, 'pullback_resume': 3}
    for key, ready in inputs.items():
        short = _short_model(ready, features[key], params)
        allowed_events = _allowed(key, short['time_s'], models, params)
        allowed_events[short['time_s'] < ready['start'] + 1200] = 0
        direction, _, _ = _entry_filter(ready['seq'], ready['time_s'], main[key], short['seq'], short['time_s'],
                                         allowed_events, short['short'], short['ofi'], modes[params['entry_kind']], params['confirmation_multiplier'])
        assert len(direction) == len(ready['seq']) and np.isin(direction, [-1, 0, 1]).all()
        output[key] = direction
    return output


if __name__ == '__main__':
    print(f'{len(catalog())}条件。実装前固定JSONを使用。売買損益は計算しません。')
