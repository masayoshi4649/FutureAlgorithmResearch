"""価格帯方向の境界と因果性を、売買・損益を使わず独立に検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import socket
import time

import numpy as np
import pandas as pd

import band_signals as signal


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PERIODS = ('2026-09-22_Night', '2026-09-29_Day')
ARRAYS = ('direction', 'source_episode', 'source_row')


def digest(path: Path) -> str:
    """機能: 読取対象を指紋へ変換する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_network(*args: object, **kwargs: object) -> None:
    """機能: 監査中の通信を拒否する。

    引数: args/kwargs (object)。返り値: なし (None)、常に例外。
    """
    raise RuntimeError('入力因果監査は保存資料だけを使う')


def cut_inputs(inputs: dict, fraction: float, duplicate: bool = False) -> tuple:
    """機能: 両市場を共通時計で切り、必要時は片側の同時刻群の途中を末尾にする。

    引数: inputs (dict)、fraction (float)、duplicate (bool)。
    返り値: 切断入力・キー別長さ・時計証跡 (tuple)。
    """
    cuts, clocks = {}, []
    for session in sorted({key[0] for key in inputs}):
        keys = sorted(key for key in inputs if key[0] == session)
        first = inputs[(session, 'NK225')]
        times = first['time_s']
        pivot = min(len(times) - 1, int(len(times) * fraction))
        if duplicate:
            positions = np.flatnonzero(np.diff(times) == 0)
            assert len(positions), '同時刻境界の人工的な代用は行わない'
            pivot = int(positions[np.argmin(np.abs(positions - pivot))])
        clock = float(times[pivot])
        for key in keys:
            cuts[key] = int(np.searchsorted(inputs[key]['time_s'], clock, side='right'))
        if duplicate:
            cuts[(session, 'NK225')] = pivot + 1
            assert times[pivot] == times[pivot + 1]
        clocks.append(dict(session=session, clock=clock, fraction=fraction,
            同時刻群途中=duplicate, cuts={key[1]: cuts[key] for key in keys}))
    truncated = {key: {name: value[:cuts[key]].copy()
        if isinstance(value, np.ndarray) and value.ndim and len(value) == len(ready['seq'])
        else value for name, value in ready.items()} for key, ready in inputs.items()}
    return truncated, cuts, clocks


def mutate_future(inputs: dict, frames: dict, events: dict, cuts: dict) -> tuple:
    """機能: 各市場の比較末尾より後だけ、価格・ATR・出来高代理・板側を変える。

    引数: inputs/frames/events/cuts (dict)。返り値: 改変した独立コピー3組 (tuple)。
    """
    rr, ff, ee = {}, {}, {}
    for key, ready in inputs.items():
        cut = cuts[key]
        boundary = ready['seq'][cut]
        rr[key] = dict(ready, atr=ready['atr'].copy(), last=ready['last'].copy())
        rr[key]['atr'][cut:] = 777.
        rr[key]['last'][cut:] = 900000.
        ff[key] = frames[key].copy(deep=True)
        mask = ff[key].seq >= boundary
        ff[key].loc[mask, ['source_mid_last', 'source_bid_last', 'source_ask_last']] = [900000., 899999., 900001.]
        ee[key] = events[key].copy(deep=True)
        mask = ee[key].release_seq >= boundary
        ee[key].loc[mask, 'volume_to_side_qty'] = 99999.
        ee[key].loc[mask, 'current_price'] = 900001.
        ee[key].loc[mask, 'side'] = -ee[key].loc[mask, 'side']
        ee[key].loc[mask, 'stable'] = ~ee[key].loc[mask, 'stable']
    return rr, ff, ee


def reflect(inputs: dict, frames: dict, events: dict) -> tuple:
    """機能: 両市場の上下と価格帯側を同時に反転する。

    引数: inputs/frames/events (dict)。返り値: 上下反射した3組 (tuple)。
    """
    rr, ff, ee = {}, {}, {}
    for key, ready in inputs.items():
        frame, ev = frames[key], events[key]
        center = float(np.nanmax(frame.source_ask_last)) * 2. + 100.
        rr[key] = dict(ready, last=center - ready['last'])
        ff[key] = frame.copy(deep=True)
        ff[key]['source_mid_last'] = center - frame.source_mid_last
        ff[key]['source_bid_last'] = center - frame.source_ask_last
        ff[key]['source_ask_last'] = center - frame.source_bid_last
        ee[key] = ev.copy(deep=True)
        ee[key]['current_price'] = center - ev.current_price
        ee[key]['side'] = -ev.side
    return rr, ff, ee


def compare(expected: dict, actual: dict, cuts: dict | None = None,
            reflected: bool = False) -> None:
    """機能: 方向と根拠2列を厳密一致で検査する。

    引数: expected/actual (dict)、cuts (dict|None)、reflected (bool)。返り値: なし (None)。
    """
    for key, row in expected.items():
        n = cuts[key] if cuts is not None else len(row['direction'])
        for name in ARRAYS:
            value = row[name][:n]
            if reflected and name == 'direction':
                value = -value
            np.testing.assert_array_equal(value, actual[key][name][:n], err_msg=f'{key}/{name}')


def synthetic() -> dict:
    """機能: 実装者の人工例とは独立した準備消費・再武装・公開境界を検査する。

    引数: なし。返り値: 検査名と件数 (dict)。
    """
    params = deepcopy(signal.catalog()[34]['params'])
    params.update(warmup_seconds=0., peer_mode='none')
    n = 10
    seq = np.arange(n, dtype=np.int64) * 2 + 1
    model = dict(time=np.arange(n, dtype=float) * 10., seq=seq,
        mid=np.array([100., 97., 100., 100., 100., 97., 100., 100., 100., 100.]),
        bid=np.full(n, 99.5), ask=np.full(n, 100.5), atr=np.full(n, 10.),
        atr_row=seq.copy(), source_time=np.arange(n, dtype=float) * 10. - 1.,
        source_first=seq-1, source_last=seq-1, valid=np.ones(n, bool),
        predicate=np.array([1, 0, 1, 0, 1, 0, 1, 0, 1, 1], bool),
        direction=np.ones(n, np.int8), anchor=np.zeros(n, np.int64),
        short_anchor=np.zeros(n, np.int64), stall_range=np.zeros(n),
        reset_window=np.zeros(n, np.int64), tick=1., window=120., start=0.)
    ep = signal.common_episodes(model, {}, params)
    assert [row['setup_seq'] for row in ep] == [1, 9, 17]
    assert [row['resolution_seq'] for row in ep] == [3, 11, None]
    checks = {'終了行のfalseを再武装に流用しない': True,
        '終了後別行falseと更に別行trueが必要': True}
    stalled = deepcopy(model)
    stalled['mid'][1:4] = 100.
    stalled['predicate'][1:4] = False
    stalled['mid'][4] = 97.
    later = signal.common_episodes(stalled, {}, params)
    assert later[0]['setup_seq'] == 1 and later[0]['confirmation_seq'] == 9
    checks['準備後停滞falseだけでは失効しない'] = True
    expiry = deepcopy(params)
    expiry.update(setup_lifetime_min=10., setup_lifetime_windows=0.)
    expired = signal.common_episodes(model, {}, expiry)
    assert expired[0]['resolution'] == 'expired' and expired[0]['response_direction'] == 0
    checks['期限等号では反応より失効が優先'] = True
    # ----------------------------------------
    # 同じ公開時刻でも、現在の原本seqより後の出来高を混ぜない。
    events = pd.DataFrame(dict(current_seq=[8, 10, 12], release_seq=[9, 11, 13],
        release_time_s=[40., 40., 40.], side=[1, 1, 0], current_price=[100.5]*3,
        volume_to_side_qty=[2., 999., np.nan], stable=[True, True, True]))
    index = signal.volume_index(events)
    score = signal.volume_score(index, 1, 100.5, 40., 9, 120.)
    assert score['stable_volume_score'] == 2. and score['volume_count'] == 1
    checks['同時刻後続seqの出来高と側不明を除外'] = True
    rounding = pd.DataFrame(dict(current_seq=[0, 2], release_seq=[1, 3],
        release_time_s=[0., 10.], side=[1, 1], current_price=[100., 100.],
        volume_to_side_qty=[.3, 2.], stable=[False, True]))
    score = signal.volume_score(signal.volume_index(rounding), 1, 100., 10., 3, 1.)
    assert score['all_volume_score'] == score['stable_volume_score'] == 2.
    checks['窓外0.3の丸めでK2の部分集合を逆転させない'] = True
    peer = dict(time=np.array([40.]), seq=np.array([9]), valid=np.array([True]),
        peer_direction=np.array([0], np.int8), source_last=np.array([8]),
        anchor=np.array([0]), short_anchor=np.array([0]))
    assert not signal.peer_information(peer, 99.999, params)['peer_available']
    assert signal.peer_information(peer, 100., params)['peer_available']
    assert signal.peer_information(peer, 160., params)['peer_available']
    assert not signal.peer_information(peer, 160.001, params)['peer_available']
    checks['相手の公開60秒と鮮度60秒の等号'] = True
    return dict(全合格=True, 検査数=len(checks), 検査=checks)


def main() -> None:
    """機能: 全270条件の代表期間因果検査と境界反例を記録する。

    引数: なし。返り値: なし (None)、新売買・損益計算をしない。
    """
    socket.socket.connect = no_network
    socket.create_connection = no_network
    paths = [HERE/'band_signals.py', HERE/'band_design.py', Path(__file__),
        ROOT/'work/wave_v23/inputs.pkl', ROOT/'work/wave_v23/features_depth.pkl', HERE/'events.pkl']
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    started = time.perf_counter()
    tests = synthetic()
    all_inputs = pickle.loads(paths[3].read_bytes())
    all_frames = pickle.loads(paths[4].read_bytes())
    all_events = pickle.loads(paths[5].read_bytes())
    inputs = {k: v for k, v in all_inputs.items() if k[0] in PERIODS}
    frames = {k: all_frames[k] for k in inputs}
    events = {k: all_events[k] for k in inputs}
    prefix1, cut1, clocks1 = cut_inputs(inputs, .37)
    prefix2, cut2, clocks2 = cut_inputs(inputs, .73, True)
    rr, ff, ee = mutate_future(inputs, frames, events, cut2)
    mr, mf, me = reflect(inputs, frames, events)
    records = []
    signal.clear_cache()
    for scale in (.8, 1., 1.2):
        for spec in signal.catalog():
            base = signal.build(spec, inputs, frames, events, scale)
            compare(base, signal.build(spec, prefix1, frames, events, scale), cut1)
            compare(base, signal.build(spec, prefix2, frames, events, scale), cut2)
            compare(base, signal.build(spec, rr, ff, ee, scale), cut2)
            compare(base, signal.build(spec, mr, mf, me, scale), reflected=True)
            for key in inputs:
                records.append(dict(id=spec['id'], clock_scale=scale, session=key[0], symbol=key[1],
                    prefix検査数=2, 未来改変検査数=1, 上下反射検査数=1,
                    比較列=list(ARRAYS), 全一致=True))
            if len(records) % 180 == 0:
                print(f'独立方向監査 {len(records)//4}/270 全一致', flush=True)
    assert len(records) == 270 * 4
    assert before == {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    value = dict(全監査合格=True, 条件時計数=270, 代表期間=list(PERIODS), 入力区間数=4,
        条件入力組数=len(records), prefix入力比較数=2160, 未来改変入力比較数=1080,
        上下反射入力比較数=1080, prefix配列比較数=6480, 未来改変配列比較数=3240,
        上下反射配列比較数=3240, 比較列=list(ARRAYS), 共通時計切断=clocks1+clocks2,
        人工検査=tests, 検査行=records, 参照SHA256=before, 入力ソース前後不変=True,
        新損益読取=False, 売買再生=False, 現在保存物使用=False, API取得数=0,
        経過秒=time.perf_counter()-started)
    (HERE/'band_signal_independent_audit.json').write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (HERE/'band_signal_independent_audit.md').write_text(
        '# 価格帯信号の独立因果監査\n\n全90条件×窓倍率3を夜間・日中の両銘柄で検査した。'
        '共通時計37%と同時刻群の途中73%で切断し、方向・準備ID・根拠seqの3列が全一致した。'
        '未来価格・ATR・公開板・出来高代理の改変と上下反射も一致した。\n\n'
        'この検査は公開順の再現性を確認するもので、収益性を示さない。全26入力の母集団同一性・参照検査は'
        '実装者の別監査と結合する。API・保存ライブ・新損益は使用していない。\n', encoding='utf-8')
    print(dict(全監査合格=True, 条件時計数=270, 経過秒=value['経過秒']), flush=True)


if __name__ == '__main__':
    main()
