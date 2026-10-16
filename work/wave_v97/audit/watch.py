"""自己原板と公表済みpeerを分け、候補後の待機状態を独立に遷移させる。"""

from copy import deepcopy
import math

import numpy as np


def waiting_widths(reference: float, tick: float, config: dict) -> tuple[float, float, float, float]:
    """
    機能: 出口Sを使わず、保存始値の10bpから待機Wと三副幅を独立計算する。
    引数: reference/tick(float)、config(dict)は確定待機条件。
    返り値: tuple[float,float,float,float]。W、順行幅、押し幅、回復幅。
    """
    width = max(2, math.ceil(reference * config['entry_width_bp'] / 10000. / tick - 1e-10)) * tick
    parts = []
    for name in ('entry_advance_widths', 'entry_pullback_widths', 'entry_recovery_widths'):
        multiple = config[name]
        parts.append(0. if multiple == 0 else max(1, math.ceil(width * multiple / tick - 1e-10)) * tick)
    return width, *parts


def normal(source: np.ndarray) -> bool:
    """
    機能: 原行番号、原seq、代理時計、bid/askが正常な同時点の源を確認する。
    引数: source(ndarray[float])はindex/seq/clock/bid/askの5列。
    返り値: bool。新しいclock又は進行の判定とは分離した正常性。
    """
    return bool(np.isfinite(source).all() and source[0] >= 0 and source[1] >= 0
                and 0 < source[3] < source[4])


def pair_valid(observation: dict) -> bool:
    """
    機能: 同じ自己判断時点で正常peerが公表済みであり、未来代理時計でないことを確認する。
    引数: observation(dict)は自己rawと公表peerの別源。
    返り値: bool。待機群だけの現在pair資格。
    """
    return bool(observation['qok'] and normal(observation['own']) and observation['fresh']
        and observation['peer_valid'] and normal(observation['peer'])
        and observation['peer'][2] <= observation['own'][2] + 1e-8)


def start(observation: dict, config: dict, reference: float, tick: float) -> dict:
    """
    機能: 旧候補を受理した自己原行で価格起点と別源のBBO基準を固定する。
    引数: observation(dict)、config(dict)、reference/tick(float)。
    返り値: dict。局所待機状態。保有や手数料を発生させない。
    """
    own, peer = observation['own'], observation['peer']
    assert normal(own) and observation['qok'] and observation['quality'] and not observation['reset']
    side, row, clock = int(observation['side']), int(own[0]), own[2]
    quote = own[4] if side == 1 else own[3]
    width, advance, pullback, recovery = waiting_widths(reference, tick, config)
    return dict(active=True, kind=config['entry_wait_kind'], side=side, candidate_row=row,
        candidate_time=clock, candidate_price=quote, width=width, advance=advance,
        pullback=pullback, recovery=recovery, expires=clock + config['entry_wait_seconds'],
        favorable=side * quote, extreme=side * quote, extreme_row=row,
        phase_row=row, phase_time=clock, arm_row=-1, pullback_armed=False,
        anchor_row=row, anchor_grid=observation['grid_index'],
        anchor_own=own.copy(), anchor_peer=peer.copy() if pair_valid(observation) else np.full(5, np.nan),
        anchor_valid=pair_valid(observation),
        fallback_row=-1, fallback_used=False, trigger_row=-1, cancel_row=-1)


def phase(state: dict, observation: dict) -> None:
    """
    機能: 新しい不利extremeの自己原行にBBO基準だけを移し、候補起点を保持する。
    引数: state/observation(dict)。独立状態と当時の別源。
    返り値: None。呼出側所有の状態だけを更新する。
    """
    own, peer = observation['own'], observation['peer']
    state['phase_row'], state['phase_time'] = int(own[0]), own[2]
    state['anchor_own'] = own.copy()
    state['anchor_peer'] = peer.copy() if pair_valid(observation) else np.full(5, np.nan)
    state['anchor_valid'] = pair_valid(observation)
    state['anchor_row'], state['anchor_grid'] = int(own[0]), observation['grid_index']
    state['fallback_row'] = -1


def bbo_confirmation(state: dict, observation: dict, tick: float, peer_tick: float) -> bool:
    """
    機能: 同じ判断行の両源更新・strict時計・両bidask各1tick進行を確認する。
    引数: state/observation(dict)、tick/peer_tick(float)は自己と相手のラージ呼値。
    返り値: bool。異時点の自己・peer支持をラッチ合成しない。
    """
    if not state['anchor_valid'] or not pair_valid(observation):
        return False
    for source, anchor, step in ((observation['own'], state['anchor_own'], tick),
                                 (observation['peer'], state['anchor_peer'], peer_tick)):
        if not (source[0] > anchor[0] and source[1] > anchor[1]
                and source[2] > anchor[2] and source[2] > state['phase_time']):
            return False
        if not np.all(state['side'] * (source[3:5] - anchor[3:5]) >= step - step * 1e-8):
            return False
    return True


def bbo_fresh(state: dict, observation: dict) -> bool:
    """
    機能: 価格進行と分離して、両源の番号及びstrict時計更新だけ確認する。
    引数: state/observation(dict)は独立基準と現在源。
    返り値: bool。A2でも診断へ保存する更新性。
    """
    if not state['anchor_valid'] or not pair_valid(observation):
        return False
    return all(source[0] > anchor[0] and source[1] > anchor[1]
        and source[2] > anchor[2] and source[2] > state['phase_time']
        for source, anchor in ((observation['own'], state['anchor_own']),
                               (observation['peer'], state['anchor_peer'])))


def step(state: dict, observation: dict, tick: float, peer_tick: float, entry_cut: float) -> tuple[dict, dict]:
    """
    機能: 取消を先に判定し、自己価格のphase更新と最初の待機触発を独立に判断する。
    引数: state/observation(dict)、tick/peer_tick/entry_cut(float)。
    返り値: tuple[dict,dict]。新状態と取消flags/更新/触発の証拠。市場注文はまだ約定させない。
    """
    state = deepcopy(state)
    own, peer = observation['own'], observation['peer']
    row, clock = int(own[0]), own[2]
    output = dict(trigger=False, phase_changed=False, fallback=False, bbo_progress=False,
                  price_ready=False, cancel_flags=[])
    assert state['active'] and row > state['candidate_row']
    # ----------------------------------------
    # 同じ行の新候補へ乗換えず、硬い取消を閾値触発より先に扱う。
    conditions = (('新規cut', clock >= entry_cut), ('TTL', clock >= state['expires']),
        ('自己gap', observation['gap'] > 10. + 1e-8), ('reset', observation['reset']),
        ('自己BBO', not observation['qok']),
        ('両300逆方向', observation['fresh'] and observation['opposite']))
    output['cancel_flags'] = [name for name, hit in conditions if hit]
    if output['cancel_flags']:
        state['active'], state['cancel_row'] = False, row
        return state, output
    side, kind = state['side'], state['kind']
    quote = own[4] if side == 1 else own[3]
    oriented = side * quote
    state['favorable'] = max(state['favorable'], oriented)
    # ----------------------------------------
    # 押し必須の最初のarm行で新extremeを現在価格に置き直し、候補以来のminを使わない。
    if kind >= 6 and not state['pullback_armed']:
        if state['favorable'] - oriented >= state['pullback'] - tick * 1e-8:
            state['pullback_armed'], state['arm_row'] = True, row
            state['extreme'], state['extreme_row'] = oriented, row
            phase(state, observation)
            output['phase_changed'] = True
    elif kind >= 5:
        if oriented < state['extreme']:
            state['extreme'], state['extreme_row'] = oriented, row
            phase(state, observation)
            output['phase_changed'] = True
    # ----------------------------------------
    # 未知peer基準の最初のpostphase正常pairはanchorだけ。その同じ行では触発しない。
    requires_bbo = bool(kind != 2)
    if requires_bbo and not state['anchor_valid'] and pair_valid(observation):
        if (row > state['phase_row'] and own[2] > state['phase_time'] and peer[2] > state['phase_time']):
            state['anchor_own'], state['anchor_peer'] = own.copy(), peer.copy()
            state['anchor_valid'], state['fallback_row'] = True, row
            state['fallback_used'] = True
            state['anchor_row'], state['anchor_grid'] = row, observation['grid_index']
            output['fallback'] = True
    if kind == 1:
        output['price_ready'] = True
    elif kind in (2, 3, 4):
        output['price_ready'] = oriented - side * state['candidate_price'] >= state['advance'] - tick * 1e-8
    else:
        output['price_ready'] = bool((kind == 5 or state['pullback_armed'])
            and row > state['extreme_row'] and oriented - state['extreme'] >= state['recovery'] - tick * 1e-8)
    output['bbo_progress'] = bbo_confirmation(state, observation, tick, peer_tick) if requires_bbo else True
    qualified = bool(observation['qok'] and observation['quality'] and not observation['reset']
        and observation['fresh'] and observation['j2_allowed'] and pair_valid(observation))
    output['trigger'] = bool(qualified and output['price_ready'] and output['bbo_progress']
        and not output['fallback'] and not output['phase_changed'] and row > state['candidate_row'])
    if output['trigger']:
        state['active'], state['trigger_row'] = False, row
    return state, output
