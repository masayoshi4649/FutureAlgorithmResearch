"""過去の気配・フロー・両市場確認を追加する入口四水準を損益なしで計算する。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import numba
from numba import njit


HERE = Path(__file__).resolve().parent
numba.config.CACHE_DIR = str(HERE / 'numba_cache')
SOURCES = ('T1L1', 'T2L0', 'T3L1', 'T4L0', 'E01P', 'R01P')
LEVELS = ('G0', 'G1', 'G2', 'G3')
TRACE_COLUMNS = ('候補行', '方向', '4イベント前行', '16イベント前行', '16イベント効率',
                 '16イベントOFI比', '相手先頭行', '相手同時計末尾行', '相手30秒前先頭行',
                 '相手OFI比', 'G1許可', 'G2許可', 'G3許可')


@njit(cache=True)
def own_gates(times, bid, ask, mid, ofi, valid, reset, tick):
    """機能: 自市場の中値イベント履歴・両気配の進行・OFIの一致を計算する。

    引数: times/bid/ask/mid/ofi/valid/reset(ndarray)、tick(float)。
    返り値: G1/G2の買売許可、根拠行、効率、OFI比(tuple)。
    無効板、reset、2呼値超の気配差、120秒超の時計空白で価格履歴を破棄する。
    """
    n = len(times)
    gates = np.zeros((2, 2, n), np.bool_)
    refs = np.full((2, n), -1, np.int64)
    efficiency = np.full(n, np.nan)
    ofi_ratio = np.full(n, np.nan)
    signed = np.zeros(n)
    absolute = np.zeros(n)
    unknown = np.zeros(n, np.int64)
    points = np.full(17, -1, np.int64)
    count = 0
    last_time = -1e30
    last_mid = np.nan
    acc_signed = acc_absolute = 0.
    acc_unknown = 0
    for i in range(n):
        if np.isfinite(ofi[i]):
            acc_signed += ofi[i]
            acc_absolute += abs(ofi[i])
        else:
            acc_unknown += 1
        signed[i], absolute[i], unknown[i] = acc_signed, acc_absolute, acc_unknown
        good = (valid[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i] > 0.
                and ask[i] >= bid[i] and ask[i] - bid[i] <= 2. * tick + 1e-9)
        if reset[i] or not good or times[i] < last_time or times[i] - last_time > 120.:
            count = 0
            last_mid = np.nan
        if not good:
            last_time = times[i]
            continue
        if count == 0:
            points[0] = i
            count = 1
            last_mid = mid[i]
        elif mid[i] != last_mid:
            if count < 17:
                points[count] = i
                count += 1
            else:
                for j in range(16):
                    points[j] = points[j + 1]
                points[16] = i
            last_mid = mid[i]
        last_time = times[i]
        if count >= 5:
            r4 = points[count - 5]
            if times[i] - times[r4] <= 120.:
                refs[0, i] = r4
                for direction_index in range(2):
                    side = 1 if direction_index == 0 else -1
                    gates[0, direction_index, i] = (side * (bid[i] - bid[r4]) >= tick - 1e-9
                        and side * (ask[i] - ask[r4]) >= tick - 1e-9)
        if count == 17:
            r16 = points[0]
            if times[i] - times[r16] <= 120.:
                refs[1, i] = r16
                distance = 0.
                for j in range(16):
                    distance += abs(mid[points[j + 1]] - mid[points[j]])
                progress = mid[i] - mid[r16]
                efficiency[i] = abs(progress) / distance if distance > 0. else 0.
                flow = signed[i] - signed[r16]
                denominator = absolute[i] - absolute[r16]
                if unknown[i] == unknown[r16] and denominator > 0.:
                    ofi_ratio[i] = flow / denominator
                    for direction_index in range(2):
                        side = 1 if direction_index == 0 else -1
                        gates[1, direction_index, i] = (gates[0, direction_index, i]
                            and side * progress >= 2. * tick - 1e-9
                            and efficiency[i] >= .30 - 1e-12
                            and side * ofi_ratio[i] >= .10 - 1e-12)
    return gates, refs, efficiency, ofi_ratio


@njit(cache=True)
def peer_gates(targets, times, bid, ask, ofi, valid, reset, tick):
    """機能: 一秒以上遅延した相手市場の両気配進行・30秒OFIを参照する。

    引数: targets/times/bid/ask/ofi/valid/reset(ndarray)、tick(float)。
    返り値: 相手の買売許可、参照先頭行と末尾行、前端行、OFI比(tuple)。
    同じ最終約定時計の先頭行を採用し、代理時計上の過去だけへ対応させる。
    """
    n = len(times)
    m = len(targets)
    first = np.zeros(n, np.int64)
    signed = np.zeros(n)
    absolute = np.zeros(n)
    bad = np.zeros(n, np.int64)
    acc_signed = acc_absolute = 0.
    acc_bad = 0
    for i in range(n):
        first[i] = i if i == 0 or times[i] != times[i - 1] else first[i - 1]
        finite = np.isfinite(ofi[i])
        if finite:
            acc_signed += ofi[i]
            acc_absolute += abs(ofi[i])
        if not valid[i] or reset[i] or not finite:
            acc_bad += 1
        signed[i], absolute[i], bad[i] = acc_signed, acc_absolute, acc_bad
    gates = np.zeros((2, m), np.bool_)
    selected = np.full(m, -1, np.int64)
    last = np.full(m, -1, np.int64)
    old = np.full(m, -1, np.int64)
    flow_ratio = np.full(m, np.nan)
    for i in range(m):
        end = np.searchsorted(times, targets[i] - 1., side='right') - 1
        if end < 0:
            continue
        p = first[end]
        selected[i], last[i] = p, end
        if targets[i] - times[p] > 5. + 1e-9:
            continue
        before = np.searchsorted(times, times[p] - 30., side='right') - 1
        if before < 0:
            continue
        r = first[before]
        old[i] = r
        if times[p] - 30. - times[r] > 5. + 1e-9:
            continue
        bad_before = bad[r - 1] if r > 0 else 0
        if bad[p] != bad_before:
            continue
        denominator = absolute[p] - absolute[r]
        if denominator <= 0.:
            continue
        flow_ratio[i] = (signed[p] - signed[r]) / denominator
        for direction_index in range(2):
            side = 1 if direction_index == 0 else -1
            gates[direction_index, i] = (side * (bid[p] - bid[r]) >= tick - 1e-9
                and side * (ask[p] - ask[r]) >= tick - 1e-9
                and side * flow_ratio[i] >= .05 - 1e-12)
    return gates, selected, last, old, flow_ratio


@njit(cache=True)
def parent_schedule(times, bid, ask, signal, reset, start, limit):
    """機能: v70と同じ予約・成立・約定・共通3630秒枠を入口列へ接続する。

    引数: times/bid/ask/signal/reset(ndarray)、start/limit(float)。
    返り値: fill方向・予約気配・発注判断行・予約行・末尾状態(tuple)。
    原本終端、将来の利確・損切り、実現損益を用いて入口を変更しない。
    """
    n = len(times)
    sides = np.zeros(n, np.int8)
    anchors = np.zeros(n)
    decisions = np.full(n, -1, np.int64)
    sources = np.full(n, -1, np.int64)
    side = 0
    source = -1
    anchor = 0.
    pending = False
    decision = -1
    lock_until = -1e30
    submitted = triggered = canceled = filled = 0
    for i in range(n):
        good = np.isfinite(bid[i]) and np.isfinite(ask[i]) and bid[i] > 0. and ask[i] >= bid[i]
        if pending and i > decision and good:
            if times[i] >= limit - 300.:
                canceled += 1
            else:
                sides[i], anchors[i], decisions[i], sources[i] = side, anchor, decision, source
                lock_until = times[i] + 3630.
                filled += 1
            side = 0
            pending = False
        # ----------------------------------------
        # 未成立の取消と、取消後の同観測候補による予約を分ける。
        if not pending and side != 0:
            if times[i] - times[source] >= 120. or times[i] >= limit - 300. or reset[i]:
                side = 0
                canceled += 1
            elif good and i > source:
                quote = ask[i] if side == 1 else bid[i]
                if side * (quote - anchor) >= 0.:
                    pending, decision = True, i
                    triggered += 1
        if (not pending and side == 0 and good and not reset[i] and signal[i] != 0
                and times[i] >= start + 300. and times[i] < limit - 300. and times[i] >= lock_until):
            side, source = int(signal[i]), i
            anchor = ask[i] if side == 1 else bid[i]
            submitted += 1
    return sides, anchors, decisions, sources, np.array([
        side, int(pending), decision, source, submitted, triggered, canceled, filled])


def sparse_schedule(ready: dict, feature: dict, signal: np.ndarray) -> tuple:
    """機能: 共通初回の疎な五列配列と未完了予約状態を作る。

    引数: ready/feature(dict)、signal(ndarray[int8])。
    返り値: fill_i/decision_i/source_i/side/anchor配列、末尾状態(tuple)。
    """
    raw = parent_schedule(ready['time_s'], feature['bid'], feature['ask'], signal, feature['reset'],
                          ready['start'], ready['limit'])
    rows = np.flatnonzero(raw[0])
    return np.column_stack((rows, raw[2][rows], raw[3][rows], raw[0][rows], raw[1][rows])), raw[4]


def build(inputs: dict, features: dict, base_signals: dict) -> dict:
    """機能: 保存入力又は追加追試入力へ固定四水準を適用する公開API。

    引数: inputs/features/base_signals(dict[tuple,object])。同場の両銘柄と元6列入口が必須。
    返り値: 24列signals、24配列schedule、候補根拠trace、末尾statesの辞書(dict)。
    順序はsource_index*4+gate_level。API、取引台帳、損益ファイルを読み込まない。
    """
    if not set(inputs) == set(features) == set(base_signals):
        raise ValueError('入力・特徴・元入口のキーが一致しません')
    own_models = {}
    for key, r in inputs.items():
        f = features[key]
        np.testing.assert_array_equal(r['seq'], f['seq'])
        np.testing.assert_array_equal(r['time_s'], f['time_s'])
        assert np.all(np.diff(r['time_s']) >= 0)
        assert base_signals[key].shape == (6, len(r['seq']))
        own_models[key] = own_gates(f['time_s'], f['bid'], f['ask'], f['mid'], f['best_ofi'],
                                    f['valid'], f['reset'], r['tick'])
    out_signals, out_schedule, out_trace, out_states = {}, {}, {}, {}
    for key, ready in sorted(inputs.items()):
        f = features[key]
        peer_key = key[0], 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
        if peer_key not in inputs:
            raise ValueError('G3には同じセッションの相手市場が必要です')
        pf = features[peer_key]
        own, refs, efficiency, flow = own_models[key]
        peer, peer_i, peer_last, peer_old, peer_flow = peer_gates(ready['time_s'], pf['time_s'],
            pf['bid'], pf['ask'], pf['best_ofi'], pf['valid'], pf['reset'], inputs[peer_key]['tick'])
        n = len(ready['seq'])
        rows = np.zeros((24, n), np.int8)
        trace, schedules, states = [], [], []
        for source in range(6):
            signal = base_signals[key][source]
            buy = signal > 0
            pass1 = np.where(buy, own[0, 0], own[0, 1])
            pass2 = np.where(buy, own[1, 0], own[1, 1])
            pass3 = pass2 & np.where(buy, peer[0], peer[1])
            for level, allowed in enumerate((np.ones(n, bool), pass1, pass2, pass3)):
                index = source * 4 + level
                rows[index] = np.where(allowed, signal, 0).astype(np.int8)
                scheduled, state = sparse_schedule(ready, f, rows[index])
                schedules.append(scheduled)
                states.append(state)
            selected = np.flatnonzero(signal)
            trace.append(np.column_stack((selected, signal[selected], refs[0, selected], refs[1, selected],
                efficiency[selected], flow[selected], peer_i[selected], peer_last[selected],
                peer_old[selected], peer_flow[selected], pass1[selected], pass2[selected], pass3[selected])))
        out_signals[key], out_schedule[key], out_trace[key], out_states[key] = rows, schedules, trace, states
    return dict(signals=out_signals, schedule=out_schedule, trace=out_trace, states=out_states)
