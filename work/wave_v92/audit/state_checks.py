"""状態選択と原板対応を、別方式の区間判定・人工反例・未来切断で検査する。"""

from bisect import bisect_left
import copy
from pathlib import Path
import math

import numpy as np

import common


def confirmation(grid, condition, valid, a, b, seconds):
    """
    機能: 連続区間の開始行を伝播して、秒数と双方更新による確認を算定する。
    引数: grid(float配列)、condition/valid(bool配列)、a/b(int配列)、seconds(float)。
    返り値: bool配列。被検査器の逐次状態ループを使わない。
    """
    if not len(grid):
        return np.zeros(0, bool)
    eligible = condition & valid
    if seconds == 0:
        return eligible.copy()
    gap = np.r_[True, np.diff(grid) > 5. + 1e-8]
    starts = eligible & (gap | np.r_[True, ~eligible[:-1]])
    origin = np.maximum.accumulate(np.where(starts, np.arange(len(grid)), -1))
    output = np.zeros(len(grid), bool)
    rows = np.flatnonzero(eligible & (origin >= 0))
    began = origin[rows]
    output[rows] = (grid[rows] - grid[began] >= seconds) & (a[rows] > a[began]) & (b[rows] > b[began])
    return output


def restore(session, entries, config):
    """
    機能: 二市場の有効ER・範囲・旧J2許可から、区間方式で状態を独立復元する。
    引数: session/entries/config(dict)。
    返り値: dictの全状態配列。将来成績又は将来方向は使わない。
    """
    grid = session['grid']
    n = len(grid)
    valid, high, low, inside = (np.ones(n, bool) for _ in range(4))
    for symbol in common.SYMBOLS:
        market = session['markets'][symbol]
        current, er, bounds = market['current'], market['windows'][300], market['ranges'][180]
        valid &= current['valid'] & er['source_valid'] & np.isfinite(er['efficiency'])
        valid &= np.isfinite(er['total_variation']) & (er['total_variation'] > 0)
        high &= er['efficiency'] >= config['high_er']
        low &= er['efficiency'] <= config['low_er']
        inside &= bounds['source_valid'] & bounds['position_valid'] & np.isfinite(bounds['width']) & (bounds['width'] > 0)
        inside &= np.isfinite(current['mid']) & (current['mid'] >= bounds['low']) & (current['mid'] <= bounds['high'])
    raw = np.zeros(n, np.int8)
    common_direction = entries['common']
    for side, name in ((-1, 'short_allowed'), (1, 'long_allowed')):
        good = valid & high & (common_direction == side) & entries['entries']['J2'][name]
        raw[good] = side
    raw[valid & low & inside & (common_direction == 0)] = 2
    a, b = (session['markets'][symbol]['current']['index'] for symbol in common.SYMBOLS)
    mode = np.zeros(n, np.int8)
    for value in (-1, 1, 2):
        seconds = config.get('trend_mode_confirm_seconds', config['confirm_seconds']) if value in (-1, 1) else config['confirm_seconds']
        mode[confirmation(grid, raw == value, valid, a, b, seconds)] = value
    return dict(grid=grid, valid=valid, raw_mode=raw, mode=mode, source_top=a, source_nk=b,
                efficiency_top=session['markets']['TOPIX']['windows'][300]['efficiency'],
                efficiency_nk=session['markets']['NK225']['windows'][300]['efficiency'], common=common_direction)


def reversal(session, entry, config):
    """
    機能: 共通方向と双方両気配の反対証拠を独立区間時計で確認する。
    引数: session/entry/config (dict)。
    返り値: dict の現在有効性、解除方向、保有方向別返済旗。
    OR は各証拠の確認後に行い、異なる証拠の短時間交替を連続と扱わない。
    """
    grid, markets = session['grid'], [session['markets'][name] for name in common.SYMBOLS]
    current = np.logical_and.reduce([market['current']['valid'] for market in markets])
    both_common, both_quotes = current.copy(), current.copy()
    for market in markets:
        for window in (30, 300):
            values = market['windows'][window]
            both_common &= values['source_valid'] & np.isfinite(values['ret_bp'])
        values = market['windows'][30]
        both_quotes &= values['source_valid'] & np.isfinite(values['bid_change_ticks']) & np.isfinite(values['ask_change_ticks'])
    joint = np.where(both_common, entry['common'], 0).astype(np.int8)
    trend300 = np.zeros(len(grid), np.int8)
    for side in (-1, 1):
        valid = current.copy()
        for market in markets:
            values = market['windows'][300]
            valid &= values['source_valid'] & np.isfinite(values['ret_bp']) & (side * values['ret_bp'] >= 3.)
        trend300[valid] = side
    result = dict(current_valid=current, arm_common=joint, arm_trend300=trend300)
    a, b = (market['current']['index'] for market in markets)
    for side, name in ((1, 'long'), (-1, 'short')):
        joint_condition = both_common & (joint == -side)
        quote_condition = both_quotes.copy()
        for market in markets:
            values = market['windows'][30]
            quote_condition &= (-side * values['bid_change_ticks'] >= 1. - 1e-8) & (-side * values['ask_change_ticks'] >= 1. - 1e-8)
        seconds = config['reverse_confirm_seconds']
        c = confirmation(grid, joint_condition, both_common, a, b, seconds)
        q = confirmation(grid, quote_condition, both_quotes, a, b, seconds)
        kind = config['reverse_kind']
        result[f'reverse_{name}'] = c if kind == 'common' else q if kind == 'quotes' else c|q if kind == 'either' else np.zeros(len(grid), bool)
    return result


def mapping(grid, times):
    """
    機能: 標準二分探索で格子公開後10秒以内の最初原板行だけへ対応付ける。
    引数: grid/times(float配列)。
    返り値: int32配列。同一原板行へ複数格子なら最新だけを残す。
    """
    output = np.full(len(times), -1, np.int32)
    stamps = times.tolist()
    for g, stamp in enumerate(grid):
        row = bisect_left(stamps, float(stamp))
        if row < len(times) and times[row] - stamp <= 10.:
            output[row] = g
    return output


def slice_tree(value, stop, n):
    """
    機能: 同じ格子長の列だけを複製切断し、別長さの原本を巻き込まない。
    引数: value(object)、stop/n(int)。
    返り値: object。
    """
    if isinstance(value, dict):
        return {name: slice_tree(child, stop, n) for name, child in value.items()}
    if isinstance(value, np.ndarray) and value.ndim and len(value) == n:
        return value[:stop].copy()
    return copy.deepcopy(value)


def poison_tree(value, start, n):
    """
    機能: 切断後の未来列を型ごとに反転・異常化し、過去列への影響を検査できる形へする。
    引数: value(object)、start/n(int)。
    返り値: object。原本を変更しない。
    """
    if isinstance(value, dict):
        return {name: poison_tree(child, start, n) for name, child in value.items()}
    if isinstance(value, np.ndarray):
        copied = value.copy()
        if copied.ndim and len(copied) == n:
            if copied.dtype.kind == 'b':
                copied[start:] = ~copied[start:]
            elif copied.dtype.kind in 'iu':
                copied[start:] = 0
            elif copied.dtype.kind == 'f':
                copied[start:] = np.nan
        return copied
    return copy.deepcopy(value)


def sample(scenario, reflected=False):
    """
    機能: 高低ER境界・欠測・源更新停止・範囲逸脱などの人工二市場素材を作る。
    引数: scenario(str)、reflected(bool)。
    返り値: tuple[dict,dict]の格子素材と既知J2許可。
    """
    n = 32
    grid = np.arange(n, dtype=float) * 5
    if scenario == '格子欠落':
        grid[16:] += 20
    entry = dict(common=np.r_[np.zeros(8, np.int8), np.ones(8, np.int8), -np.ones(8, np.int8), np.zeros(8, np.int8)],
                 entries={'J2': dict(long_allowed=np.ones(n, bool), short_allowed=np.ones(n, bool))})
    markets = {}
    for symbol in common.SYMBOLS:
        er = np.r_[np.full(8, .2), np.full(8, .4), np.full(8, .5), np.full(8, .1)]
        current = dict(valid=np.ones(n, bool), index=np.arange(n, dtype=np.int32), mid=np.full(n, 100.))
        window = dict(source_valid=np.ones(n, bool), efficiency=er, total_variation=np.ones(n), ret_bp=entry['common'].astype(float)*4)
        short = dict(source_valid=np.ones(n, bool), ret_bp=entry['common'].astype(float),
                     bid_change_ticks=entry['common'].astype(float), ask_change_ticks=entry['common'].astype(float))
        bounds = dict(source_valid=np.ones(n, bool), position_valid=np.ones(n, bool), width=np.full(n, 2.),
                      low=np.full(n, 99.), high=np.full(n, 101.))
        if scenario == '欠測':
            current['valid'][10:13] = False
        elif scenario == 'ER零変動':
            window['total_variation'][:] = 0.
        elif scenario == 'ER非有限':
            window['efficiency'][4:11] = np.nan
        elif scenario == '範囲零幅':
            bounds['width'][:] = 0.
            bounds['position_valid'][:] = False
        elif scenario == '範囲外':
            current['mid'][:8] = 102.
        elif scenario == '片方のみ低ER' and symbol == 'NK225':
            window['efficiency'][:] = .9
        elif scenario == '片方源停止' and symbol == 'NK225':
            current['index'][:] = 0
        elif scenario == '期間窓無効':
            window['source_valid'][16:20] = False
        markets[symbol] = dict(current=current, windows={300: window, 30: short}, ranges={180: bounds})
    if scenario == '旧J2不許可':
        entry['entries']['J2']['long_allowed'][:] = False
        entry['entries']['J2']['short_allowed'][:] = False
    if reflected:
        entry['common'] *= -1
        entry['entries']['J2']['long_allowed'], entry['entries']['J2']['short_allowed'] = entry['entries']['J2']['short_allowed'], entry['entries']['J2']['long_allowed']
        for market in markets.values():
            bounds = market['ranges'][180]
            bounds['low'], bounds['high'] = 200 - bounds['high'], 200 - bounds['low']
            market['current']['mid'] = 200 - market['current']['mid']
            for window in market['windows'].values():
                for name in ('ret_bp', 'bid_change_ticks', 'ask_change_ticks'):
                    if name in window: window[name] *= -1
    return dict(grid=grid, markets=markets), entry


def subject_state(strategy, session, entry, config):
    """
    機能: 被検査器の旧分類と追加された追従時計だけを人工素材で接続する。
    引数: strategy (module)、session/entry/config (dict)。
    返り値: dict の状態。実素材では正式 prepare の出力も別途照合する。
    """
    previous = strategy.LEGACY
    while not hasattr(previous, 'state'):
        previous = previous.LEGACY
    result = previous.state(session, entry, config)
    if 'trend_mode_confirm_seconds' in config:
        result['mode'] = np.where(result['mode'] == 2, 2, 0).astype(np.int8)
        for side in (-1, 1):
            confirmed = previous.confirmation(result['grid'], result['raw_mode'] == side, result['valid'],
                                                     result['source_top'], result['source_nk'], config['trend_mode_confirm_seconds'])
            result['mode'][confirmed] = side
    return result


def evidence_switch_boundary(strategy):
    """
    機能: 異なる逆行証拠を先に OR する誤実装を拒絶する具体境界を検査する。
    引数: strategy (module)。
    返り値: dict。秒数・片市場停止・ER非有限の影響も調べる。
    """
    import catalog
    config = dict(catalog.catalog()[0], reverse_kind='either', reverse_confirm_seconds=15.)
    session, entry = sample('通常高低境界')
    n = len(session['grid'])
    entry['common'][:] = 0
    entry['common'][0:2] = -1
    for market in session['markets'].values():
        market['windows'][300]['ret_bp'][:] = -4
        market['windows'][30]['ret_bp'][:] = -1
        market['windows'][30]['bid_change_ticks'][:] = 0
        market['windows'][30]['ask_change_ticks'][:] = 0
        market['windows'][30]['bid_change_ticks'][2:4] = -1
        market['windows'][30]['ask_change_ticks'][2:4] = -1
        market['windows'][300]['efficiency'][:] = np.nan
    got = strategy.reversal_state(session, entry, config)
    assert not got['reverse_long'][:4].any(), '交互証拠を15秒連続と扱いました'
    joint = entry['common'] == -1
    quotes = (session['markets']['TOPIX']['windows'][30]['bid_change_ticks'] <= -1)
    wrong = confirmation(session['grid'], joint | quotes, np.ones(n, bool), np.arange(n), np.arange(n), 15.)
    assert wrong[3], '故障器の境界が発火していません'
    entry['common'][4:10] = -1
    got = strategy.reversal_state(session, entry, config)
    assert got['reverse_long'][7], 'ER非有限を反対確認へ誤って連結しました'
    stopped = copy.deepcopy(session)
    stopped['markets']['NK225']['current']['index'][4:10] = 4
    got_stopped = strategy.reversal_state(stopped, entry, config)
    assert not got_stopped['reverse_long'][4:10].any(), '片市場更新停止を確認しました'
    return dict(交互証拠を未確認=True, 誤OR時計を拒絶=True, ER非有限でも反対確認=True, 片市場停止を未確認=True)


def main():
    """
    機能: 全条件の人工状態・全31場の独立復元と未来切断を損益なしで検査する。
    引数: なし。
    返り値: None。
    """
    import sys
    sys.path.insert(0, str(common.WORK))
    import data
    import strategy
    import catalog
    material = data.load_inputs()
    configs = catalog.catalog()
    counts = dict(人工状態=0, 人工未来切断=0, 人工未来毒入れ=0, 実格子状態=0,
                  実格子未来切断=0, 実格子未来毒入れ=0, 実原板対応=0, 旧J2新規イベント=0,
                  人工独立反対確認=0, 実独立反対確認=0, 正式準備状態一致=0)
    scenarios = ('通常高低境界', '格子欠落', '欠測', 'ER零変動', 'ER非有限', '範囲零幅',
                 '範囲外', '片方のみ低ER', '片方源停止', '期間窓無効', '旧J2不許可')
    for config in configs:
        for scenario in scenarios:
            unreflected = None
            for reflected in (False, True):
                session, entry = sample(scenario, reflected)
                got = subject_state(strategy, session, entry, config)
                common.same(got, restore(session, entry, config))
                reverse_got = strategy.reversal_state(session, entry, config)
                common.same(reverse_got, reversal(session, entry, config))
                counts['人工独立反対確認'] += 1
                if unreflected is None:
                    unreflected = got['mode'].copy()
                else:
                    expected = np.where(unreflected == 2, 2, -unreflected)
                    np.testing.assert_array_equal(got['mode'], expected)
                counts['人工状態'] += 1
                for stop in (1, 8, 10, 16, 24, 31):
                    past = subject_state(strategy, slice_tree(session, stop, 32), slice_tree(entry, stop, 32), config)
                    common.same(past, slice_tree(got, stop, 32))
                    counts['人工未来切断'] += 1
                    future = subject_state(strategy, poison_tree(session, stop, 32), poison_tree(entry, stop, 32), config)
                    common.same(slice_tree(future, stop, 32), slice_tree(got, stop, 32))
                    counts['人工未来毒入れ'] += 1
                    reverse_past = strategy.reversal_state(slice_tree(session, stop, 32), slice_tree(entry, stop, 32), config)
                    common.same(reverse_past, slice_tree(reverse_got, stop, 32))
                    reverse_future = strategy.reversal_state(poison_tree(session, stop, 32), poison_tree(entry, stop, 32), config)
                    common.same(slice_tree(reverse_future, stop, 32), slice_tree(reverse_got, stop, 32))
        prepared = strategy.prepare(material, config)
        for key, session in material['grids'].items():
            entry = material['entries'][key]
            got = subject_state(strategy, session, entry, config)
            common.same(got, restore(session, entry, config))
            reverse_got = strategy.reversal_state(session, entry, config)
            common.same(reverse_got, reversal(session, entry, config))
            counts['実独立反対確認'] += 1
            for symbol in common.SYMBOLS:
                formal_signal = prepared[key, symbol]['signal']
                common.same({name: formal_signal[name] for name in got}, got)
                common.same({name: formal_signal[name] for name in reverse_got}, reverse_got)
                peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
                current = session['markets'][peer]['current']
                for name, source in (('peer_mid','mid'),('peer_bid','bid'),('peer_ask','ask'),('peer_source','index')):
                    common.same(formal_signal[name], current[source])
                expected_valid = (current['valid'] & current.get('q_valid', current['valid'])
                                  & np.isfinite(current['bid']) & np.isfinite(current['ask'])
                                  & np.isfinite(current['mid']) & (current['bid'] > 0)
                                  & (current['ask'] > current['bid']))
                common.same(formal_signal['peer_valid'], expected_valid)
                peer_record = material['prices'][key, peer]
                reference = material['metadata']['references'][key+'|'+peer]['ref_open']
                tick = peer_record['tick']
                ticks = (max(2, math.ceil(reference['value']*config['range_width_fraction']/tick-1e-10))
                         if config['range_width_mode'] == 'opening_fraction' else config['width_ticks'])
                common.same(formal_signal['peer_width'], ticks*tick)
                common.same(formal_signal['peer_tick'], tick)
                counts['正式準備状態一致'] += 1
            counts['実格子状態'] += 1
            if key in ('2026-09-24_Night', '2026-09-28_Day', '2026-10-06_Day', '2026-10-09_Night'):
                n = len(session['grid'])
                for stop in np.unique(np.rint(np.linspace(1, n - 1, 17)).astype(int)):
                    past = subject_state(strategy, slice_tree(session, stop, n), slice_tree(entry, stop, n), config)
                    common.same(past, slice_tree(got, stop, n))
                    counts['実格子未来切断'] += 1
                    future = subject_state(strategy, poison_tree(session, stop, n), poison_tree(entry, stop, n), config)
                    common.same(slice_tree(future, stop, n), slice_tree(got, stop, n))
                    counts['実格子未来毒入れ'] += 1
                    reverse_past = strategy.reversal_state(slice_tree(session, stop, n), slice_tree(entry, stop, n), config)
                    common.same(reverse_past, slice_tree(reverse_got, stop, n))
                    reverse_future = strategy.reversal_state(poison_tree(session, stop, n), poison_tree(entry, stop, n), config)
                    common.same(slice_tree(reverse_future, stop, n), slice_tree(reverse_got, stop, n))
        del prepared
        print(f'{config["id"]} 人工反例・全31状態・独立時計・将来切断合格', flush=True)
    prepared = strategy.prepare(material, configs[0])
    for key, value in prepared.items():
        record, signal = value['record'], value['signal']
        mapped = mapping(signal['grid'], record['time_s'])
        np.testing.assert_array_equal(mapped, signal['mapped'])
        counts['実原板対応'] += 1
        event = np.zeros(len(record['time_s']), np.int8)
        entries = material['entries'][key[0]]['entries']['J2']
        for candidate in material['legacy'][key]['candidates']:
            row, side = int(candidate[1]), int(candidate[2])
            g = mapped[row]
            if g >= 0 and entries['long_allowed' if side == 1 else 'short_allowed'][g]:
                event[row] = side
        np.testing.assert_array_equal(event, signal['event'])
        counts['旧J2新規イベント'] += 1
    common.save('全条件の状態と独立反対確認及び未来不変と原板対応.json',
                dict(全合格=True, 全期間既知=True, 条件数=len(configs), 検査件数=counts,
                     交互証拠の明示境界=evidence_switch_boundary(strategy),
                     損益計算=0, 損益閲覧=0, 現在API取得=0, 実注文=0, 旧変更=0,
                     SHA256=common.fingerprint([Path(__file__), Path(common.__file__), common.WORK / 'catalog.py',
                                               common.WORK / 'strategy.py', common.WORK / 'data.py'])))


if __name__ == '__main__':
    main()
