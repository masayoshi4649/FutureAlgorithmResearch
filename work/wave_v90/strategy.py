"""現在の二市場価格経路で追従と持続指値の新規・失効だけを選択する。"""

import math
import numpy as np

import engine


SYMBOLS = ('TOPIX', 'NK225')


def confirmation(grid, condition, valid, source_a, source_b, seconds):
    """
    機能: 欠測を跨がない条件持続と両市場の開始後更新を確認する。
    引数: grid (ndarray[float])、condition/valid (ndarray[bool])、
        source_a/source_b (ndarray[int])、seconds (float)。
    返り値: ndarray[bool] の確認完了旗。
    """
    result = np.zeros(len(grid), dtype=bool)
    began = -1
    previous = -1e30
    for i in range(len(grid)):
        gap = grid[i] - previous > 5.0 + 1e-8
        previous = grid[i]
        if not valid[i] or not condition[i]:
            began = -1
            continue
        if began < 0 or gap:
            began = i
        if seconds == 0 or (grid[i] - grid[began] >= seconds
                            and source_a[i] > source_a[began] and source_b[i] > source_b[began]):
            result[i] = True
    return result


def mapping(grid, record):
    """
    機能: 過去格子を10秒以内の最初の自市場原板へ一度だけ公開する。
    引数: grid (ndarray[float])、record (dict、time_s配列)。
    返り値: ndarray[int32] は更新行のみの最新格子番号。
    """
    times = record['time_s']
    result = np.full(len(times), -1, dtype=np.int32)
    for g, i in enumerate(np.searchsorted(times, grid, side='left')):
        if i < len(times) and times[i] - grid[g] <= 10.0:
            result[i] = g
    return result


def state(session, entry, config):
    """
    機能: 双方ERと共通方向・範囲内価格から新規可能な現在状態を作る。
    引数: session (dict) は格子特徴、entry (dict) は旧J2許可、config (dict)。
    返り値: dict はvalid/raw_mode/mode/grid/源行とER等の診断用過去列。
    不明は0、往復は2、追従は1又は-1。往復への欠測代用を行わない。
    """
    grid = session['grid']
    size = len(grid)
    markets = [session['markets'][symbol] for symbol in SYMBOLS]
    valid = np.ones(size, dtype=bool)
    high = np.ones(size, dtype=bool)
    low = np.ones(size, dtype=bool)
    inside = np.ones(size, dtype=bool)
    for market in markets:
        current, window, bounds = market['current'], market['windows'][300], market['ranges'][180]
        valid &= (current['valid'] & window['source_valid'] & np.isfinite(window['efficiency'])
                  & np.isfinite(window['total_variation']) & (window['total_variation'] > 0))
        high &= window['efficiency'] >= config['high_er']
        low &= window['efficiency'] <= config['low_er']
        inside &= (bounds['source_valid'] & bounds['position_valid'] & np.isfinite(bounds['width'])
                   & (bounds['width'] > 0) & np.isfinite(current['mid'])
                   & (current['mid'] >= bounds['low']) & (current['mid'] <= bounds['high']))
    common = entry['common']
    raw = np.zeros(size, dtype=np.int8)
    for side in (-1, 1):
        allowed = entry['entries']['J2']['long_allowed' if side == 1 else 'short_allowed']
        raw[valid & high & (common == side) & allowed] = side
    raw[valid & low & inside & (common == 0)] = 2
    source_a, source_b = (market['current']['index'] for market in markets)
    mode = np.zeros(size, dtype=np.int8)
    for candidate in (-1, 1, 2):
        confirmed = confirmation(grid, raw == candidate, valid, source_a, source_b, float(config['confirm_seconds']))
        mode[confirmed] = candidate
    return dict(grid=grid, valid=valid, raw_mode=raw, mode=mode,
                source_top=source_a, source_nk=source_b,
                efficiency_top=markets[0]['windows'][300]['efficiency'],
                efficiency_nk=markets[1]['windows'][300]['efficiency'], common=common)


def prepare(material, config):
    """
    機能: 新損益を参照せず固定条件の入力・旧J2イベント・現在状態を接続する。
    引数: material (dict) はdata.load_inputs返り値、config (dict)。
    返り値: dict[tuple,dict] は口座別record/signal。
    """
    states = {session: state(grid, material['entries'][session], config)
              for session, grid in material['grids'].items()}
    output = {}
    for key, record in material['prices'].items():
        session = key[0]
        entry = material['entries'][session]
        signal = dict(states[session], mapped=mapping(states[session]['grid'], record),
                      quality=material['features'][key]['quality'], reset=material['features'][key]['reset'])
        event = np.zeros(len(record['time_s']), dtype=np.int8)
        allowed = entry['entries']['J2']
        for candidate in material['legacy'][key]['candidates']:
            i, side = int(candidate[1]), int(candidate[2])
            g = int(signal['mapped'][i])
            if g >= 0 and allowed['long_allowed' if side == 1 else 'short_allowed'][g]:
                event[i] = side
        signal['event'] = event
        reference = material['metadata']['references']['|'.join(key)]['ref_open']
        assert reference['known_from_i'] == 0
        signal['trend_width'] = max(2, math.ceil(reference['value'] * config.get('trend_width_fraction', .004)
                                                / record['tick'] - 1e-10)) * record['tick']
        output[key] = dict(record=record, signal=signal)
    return output


def play(config, key, prepared, finish=True):
    """
    機能: 同じ原板気配・料金・数量制約で一口座の状態選択を執行する。
    引数: config (dict)、key (tuple[str,str])、prepared (dict)、finish (bool)。
    返り値: dict は注文、決済親、全原板清算時価と予約・状態台帳。
    """
    value = prepared[key]
    return engine.execute(value['record'], value['signal'], config, finish=finish)
