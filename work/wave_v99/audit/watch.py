"""旧待機幾何へ四つの時計政策だけを独立追加する。"""

from copy import deepcopy
import math

import numpy as np

import common


OLD = common.module('98読取の97純待機幾何', common.ROOT / 'work/wave_v97/audit/watch.py')
waiting_widths, normal, pair_valid, phase = OLD.waiting_widths, OLD.normal, OLD.pair_valid, OLD.phase


def start(observation: dict, config: dict, reference: float, tick: float) -> dict:
    """
    機能: 旧候補起点に時計政策と別epochの空状態を追加する。
    引数: observation/config(dict)、reference/tick(float)。
    返り値: dict。候補価格、幅、TTLは旧計算と一致する状態。
    """
    state = OLD.start(observation, config, reference, tick)
    state.update(policy=config['entry_clock_policy'], epoch_active=False,
        epoch_row=-1, epoch_time=math.nan, epoch_valid=False,
        epoch_own=np.full(5, np.nan), epoch_peer=np.full(5, np.nan),
        epoch_baseline_row=-1, epoch_baseline_grid=-1, reprepare_row=-1,
        gap_count=0, reprepare_count=0)
    return state


def bbo_fresh(state: dict, observation: dict) -> bool:
    """
    機能: C2だけ各anchor時計非逆行へ変え、他政策は旧strict時計を保つ。
    引数: state/observation(dict)は当時の比較基準と現在源。
    返り値: bool。異なる商品を原seqで同じ受信順へ接続しない。
    """
    if state['policy'] != 'C2':
        return OLD.bbo_fresh(state, observation)
    if not state['anchor_valid'] or not pair_valid(observation):
        return False
    return all(source[0] > anchor[0] and source[1] > anchor[1] and source[2] >= anchor[2]
        for source, anchor in ((observation['own'], state['anchor_own']),
                              (observation['peer'], state['anchor_peer'])))


def bbo_confirmation(state: dict, observation: dict, tick: float, peer_tick: float) -> bool:
    """
    機能: 政策の源資格に両市場bid/askの各1呼値順行を接続する。
    引数: state/observation(dict)、tick/peer_tick(float)。
    返り値: bool。同一判断時点の双方が成立すること。
    """
    if not bbo_fresh(state, observation):
        return False
    return all(np.all(state['side'] * (source[3:5] - anchor[3:5]) >= step - step * 1e-8)
        for source, anchor, step in ((observation['own'], state['anchor_own'], tick),
                                    (observation['peer'], state['anchor_peer'], peer_tick)))


def begin_epoch(state: dict, observation: dict) -> None:
    """
    機能: gap行の自己と公表peerを別epochへ保存し、旧価格幾何を更新しない。
    引数: state/observation(dict)。
    返り値: None。候補起点、TTL及び占有数量は変更しない。
    """
    state['epoch_active'] = True
    state['epoch_row'] = int(observation['own'][0])
    state['epoch_time'] = observation['own'][2]
    state['epoch_valid'] = pair_valid(observation)
    state['epoch_own'] = observation['own'].copy()
    state['epoch_peer'] = observation['peer'].copy()
    state['epoch_baseline_row'] = state['epoch_row']
    state['epoch_baseline_grid'] = observation['grid_index']
    state['reprepare_row'] = -1
    state['gap_count'] += 1


def epoch_step(state: dict, observation: dict) -> dict:
    """
    機能: 未知epochの初回ペア固定と後続の両源確認を分けて再準備する。
    引数: state/observation(dict)は別epochと現在の正常性。
    返り値: dict。基準固定又は再準備の証拠。quote順行を再準備へ要求しない。
    """
    own, peer = observation['own'], observation['peer']
    row = int(own[0])
    result = dict(epoch_baseline=False, reprepared=False, epoch_fresh=False)
    if not pair_valid(observation) or row <= state['epoch_row']:
        return result
    if not state['epoch_valid']:
        if own[2] > state['epoch_time'] and peer[2] > state['epoch_time']:
            state['epoch_valid'] = True
            state['epoch_own'], state['epoch_peer'] = own.copy(), peer.copy()
            state['epoch_baseline_row'], state['epoch_baseline_grid'] = row, observation['grid_index']
            result['epoch_baseline'] = True
        return result
    fresh = all(source[0] > anchor[0] and source[1] > anchor[1]
        and source[2] > anchor[2] and source[2] > state['epoch_time']
        for source, anchor in ((own, state['epoch_own']), (peer, state['epoch_peer'])))
    result['epoch_fresh'] = fresh
    if not (fresh and observation['quality'] and not observation['reset'] and observation['j2_allowed']):
        return result
    quote = own[4] if state['side'] == 1 else own[3]
    state['favorable'] = state['extreme'] = state['side'] * quote
    state['extreme_row'], state['arm_row'], state['pullback_armed'] = row, -1, False
    phase(state, observation)
    state['epoch_active'], state['reprepare_row'] = False, row
    state['reprepare_count'] += 1
    result['reprepared'] = True
    return result


def step(state: dict, observation: dict, tick: float, peer_tick: float, entry_cut: float) -> tuple[dict, dict]:
    """
    機能: 旧取消と幾何を保持し、C1 gap除去/C2時計/C3別epochだけ独立判定する。
    引数: state/observation(dict)、tick/peer_tick/entry_cut(float)。
    返り値: tuple[dict,dict]。更新状態と最初trigger/取消/epochの根拠。
    """
    if state['policy'] == 'C0':
        return OLD.step(state, observation, tick, peer_tick, entry_cut)
    state = deepcopy(state)
    own, peer = observation['own'], observation['peer']
    row, clock = int(own[0]), own[2]
    result = dict(trigger=False, phase_changed=False, fallback=False, bbo_progress=False,
        price_ready=False, cancel_flags=[], epoch_started=False, epoch_baseline=False, reprepared=False)
    assert state['active'] and row > state['candidate_row']
    conditions = (('新規cut', clock >= entry_cut), ('TTL', clock >= state['expires']),
        ('reset', observation['reset']), ('自己BBO', not observation['qok']),
        ('両300逆方向', observation['fresh'] and observation['opposite']))
    result['cancel_flags'] = [name for name, hit in conditions if hit]
    if result['cancel_flags']:
        state['active'], state['cancel_row'] = False, row
        state['epoch_active'] = False
        return state, result
    # ----------------------------------------
    # C3だけgap後に旧幾何を停止する。C1/C2のgap行に発注禁止を暗黙追加しない。
    if state['policy'] == 'C3':
        if observation['gap'] > 10. + 1e-8:
            begin_epoch(state, observation)
            result['epoch_started'] = True
            return state, result
        if state['epoch_active']:
            result.update(epoch_step(state, observation))
            return state, result
    side, kind = state['side'], state['kind']
    quote = own[4] if side == 1 else own[3]
    oriented = side * quote
    state['favorable'] = max(state['favorable'], oriented)
    if kind >= 6 and not state['pullback_armed']:
        if state['favorable'] - oriented >= state['pullback'] - tick * 1e-8:
            state['pullback_armed'], state['arm_row'] = True, row
            state['extreme'], state['extreme_row'] = oriented, row
            phase(state, observation)
            result['phase_changed'] = True
    elif kind >= 5 and oriented < state['extreme']:
        state['extreme'], state['extreme_row'] = oriented, row
        phase(state, observation)
        result['phase_changed'] = True
    requires_bbo = bool(kind != 2)
    if requires_bbo and not state['anchor_valid'] and pair_valid(observation):
        eligible = (row > state['phase_row'] and own[2] >= state['phase_time']) if state['policy'] == 'C2' else (
            row > state['phase_row'] and own[2] > state['phase_time'] and peer[2] > state['phase_time'])
        if eligible:
            state['anchor_own'], state['anchor_peer'] = own.copy(), peer.copy()
            state['anchor_valid'], state['fallback_row'], state['fallback_used'] = True, row, True
            state['anchor_row'], state['anchor_grid'] = row, observation['grid_index']
            result['fallback'] = True
    if kind == 1:
        result['price_ready'] = True
    elif kind in (2, 3, 4):
        result['price_ready'] = oriented - side * state['candidate_price'] >= state['advance'] - tick * 1e-8
    else:
        result['price_ready'] = bool((kind == 5 or state['pullback_armed']) and row > state['extreme_row']
            and oriented - state['extreme'] >= state['recovery'] - tick * 1e-8)
    result['bbo_progress'] = bbo_confirmation(state, observation, tick, peer_tick) if requires_bbo else True
    qualified = bool(observation['quality'] and observation['qok'] and not observation['reset']
        and observation['fresh'] and observation['j2_allowed'] and pair_valid(observation))
    result['trigger'] = bool(qualified and result['price_ready'] and result['bbo_progress']
        and not result['fallback'] and not result['phase_changed'] and row > state['phase_row'])
    if result['trigger']:
        state['active'], state['trigger_row'] = False, row
    return state, result
