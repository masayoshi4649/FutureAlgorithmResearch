"""既進行・停止・実復帰を分け、同じ仮説が終わるまで同方向へ再発火しない。"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
SOURCE_PATH = HERE.parent / "catalog119.py"
SOURCE_SPEC = importlib.util.spec_from_file_location("_stability119_v2_frozen_catalog", SOURCE_PATH)
SOURCE = importlib.util.module_from_spec(SOURCE_SPEC)
SOURCE_SPEC.loader.exec_module(SOURCE)
SCALES = (20, 40)
FAMILIES = (
    ("A", "両市場の進行失速後の実復帰", "両市場の2幅進行→各2本の極値更新停止→各0.5幅復帰と自己2本帯の逆抜けを待つ。"),
    ("B", "安定中心からの乖離後の復帰", "自己平均が安定したときの2幅乖離から0.5幅の実復帰を待ち、相手3本の復帰方向も確認する。"),
    ("C", "共同進行直後の逆張り対照", "両市場の同方向2幅進行だけで直ちに逆張りし、停止と復帰を待つ価値を比較する。"),
    ("D", "自己だけの進行失速後の実復帰", "自己2幅進行→2本の極値更新停止→0.5幅復帰と自己2本帯の逆抜け。相手を要求しない対照。"),
)


# ----------------------------------------


def available(bars: dict) -> np.ndarray:
    """
    機能: 既知の確定足と公開現在値の使用資格を分離して求める。
    引数: bars(dict[str,ndarray]) は118型の分足。
    返り値: ndarray[bool] は公開遅れ60秒以内の当時資格。価格時計模型である。
    """
    delay = bars["pub_price_time_s"] - bars["t_s"]
    return (bars["valid"] & np.isfinite(bars["anchor"]) & (bars["anchor"] > 0)
            & (bars["pub_raw_row"] >= 0) & np.isfinite(delay) & (delay >= 0) & (delay <= 60.))


def extreme(bars: dict, history: dict, row: int, direction: int) -> float:
    """
    機能: 現足までに実際に既知の過去帯と公開現在値から原方向の極値を求める。
    引数: bars/history(dict)、row(int)、direction(int) は原進行の向き±1。
    返り値: float は有限の高値又は安値。形成中の未来高安は使わない。
    """
    if direction == 1:
        return max(history["prior_high"][row], bars["high"][row], bars["anchor"][row])
    return min(history["prior_low"][row], bars["low"][row], bars["anchor"][row])


def current_extreme(bars: dict, row: int, direction: int) -> float:
    """
    機能: 現在公開足とその公開現在値だけから原方向の極値を求める。
    引数: bars(dict)、row(int)、direction(int) は原進行の向き±1。
    返り値: float は当時既知の高値又は安値。
    """
    return (max(bars["high"][row], bars["anchor"][row]) if direction == 1
            else min(bars["low"][row], bars["anchor"][row]))


def signals(own: dict, peer: dict, history: dict, other: dict, indexes: np.ndarray,
            family: str) -> dict:
    """
    機能: 一つの入口仮説を逐次処理し、準備と発火済みの保有撤回参照を別管理する。
    引数: own/peer/history/other(dict)、indexes(ndarray[int64])、family(str) はA/B/C/D。
    返り値: dict はentry・exit_long・exit_short・width・validの一分列。
        発火後の同方向再準備は元仮説終端まで禁止。未約定又は早期SL/TPでも禁止を維持する。
    """
    assert family in ("A", "B", "C", "D")
    n = len(own["close"])
    entry = np.zeros(n, dtype=np.int8)
    exits = np.zeros((2, n), dtype=bool)
    width = history["width"].copy()
    valid = np.zeros(n, dtype=bool)
    own_known, peer_known = available(own), available(peer)
    phase, armed_direction, last_trigger, last_seen_peer = 0, 0, 0, -1
    own_peak = peer_peak = fixed_width = fixed_peer_width = fixed_center = math.nan
    own_stall = peer_stall = 0
    last_armed_peer = -1
    active = np.zeros(2, dtype=bool)
    targets = np.full(2, np.nan)
    barriers = np.full(2, np.nan)
    trade_width = np.full(2, np.nan)

    for i in range(n):
        price = own["anchor"][i]
        mean = history["mean"][i]
        mean_five_change = (mean - history["mean"][i - 5]
                            if i >= 5 and math.isfinite(mean) and math.isfinite(history["mean"][i - 5]) else math.nan)

        # ----------------------------------------
        # 欠測で準備が切れても、発火済みの方向別参照は残して既知価格で撤回する。
        if own_known[i]:
            for side in range(2):
                if not active[side]:
                    continue
                d = 1 if side == 0 else -1
                reached = d * (price - targets[side]) >= 0
                if family == "B":
                    failed = math.isfinite(mean_five_change) and d * mean_five_change <= -.5 * trade_width[side]
                else:
                    original_direction = -d
                    failed = original_direction * (current_extreme(own, i, original_direction) - barriers[side]) > 0
                if reached or failed:
                    exits[side, i] = True
                    active[side] = False

        j = int(indexes[i])
        new_peer = j >= 0 and j > last_seen_peer
        if j >= 0:
            last_seen_peer = max(last_seen_peer, j)
        own_ready = (own_known[i] and math.isfinite(history["width"][i])
                     and history["width"][i] > 0 and math.isfinite(mean)
                     and math.isfinite(history["delta"][i]))
        peer_ready = (j >= 0 and new_peer and peer_known[j]
                      and math.isfinite(other["width"][j]) and other["width"][j] > 0
                      and math.isfinite(other["delta"][j]))
        ready = own_ready and (family == "D" or peer_ready)
        valid[i] = ready
        if not ready:
            phase, armed_direction, last_trigger = 0, 0, 0
            own_stall = peer_stall = 0
            continue

        w = history["width"][i]
        od = history["delta"][i]
        pd = other["delta"][j] if family != "D" else 0.
        pw = other["width"][j] if family != "D" else math.nan
        trigger = 0
        if family == "B":
            if math.isfinite(mean_five_change) and abs(mean_five_change) <= .25 * w:
                deviation = price - mean
                trigger = 1 if deviation >= 2. * w else (-1 if deviation <= -2. * w else 0)
        elif family == "D":
            trigger = 1 if od >= 2. * w else (-1 if od <= -2. * w else 0)
        else:
            trigger = (1 if od >= 2. * w and pd >= 2. * pw
                       else (-1 if od <= -2. * w and pd <= -2. * pw else 0))

        # ----------------------------------------
        # 一度使った波は、準備条件の解除を挟むまで次の準備へ移さない。
        if phase == 2:
            if trigger == 0:
                phase, last_trigger = 0, 0
            continue
        newly_armed = False
        if phase == 0 and trigger != 0 and trigger != last_trigger:
            side = 1 if trigger == 1 else 0
            if not active[side]:
                phase, armed_direction = 1, trigger
                fixed_width, fixed_peer_width, fixed_center = w, pw, mean
                own_peak = extreme(own, history, i, armed_direction)
                peer_peak = extreme(peer, other, j, armed_direction) if family == "A" else math.nan
                own_stall = peer_stall = 0
                last_armed_peer = j
                newly_armed = True
        last_trigger = trigger
        if phase != 1:
            continue
        width[i] = fixed_width
        if not newly_armed:
            candidate = current_extreme(own, i, armed_direction)
            if armed_direction * (candidate - own_peak) > 0:
                own_peak, own_stall = candidate, 0
            else:
                own_stall += 1
            if family == "A" and j != last_armed_peer:
                candidate = current_extreme(peer, j, armed_direction)
                if armed_direction * (candidate - peer_peak) > 0:
                    peer_peak, peer_stall = candidate, 0
                else:
                    peer_stall += 1
                last_armed_peer = j

        # ----------------------------------------
        # 中心へ到達済み又はBの中心が原方向へ移る場合、遅れた逆張りを新規に作らない。
        if armed_direction * (price - fixed_center) <= 0:
            phase = 2
            continue
        if family == "B" and math.isfinite(mean_five_change) and armed_direction * mean_five_change >= .5 * fixed_width:
            phase = 2
            continue
        fired = family == "C" and newly_armed
        retraced = armed_direction * (own_peak - price) >= .5 * fixed_width
        if family == "B":
            peer_short = other["short"][j]
            fired = retraced and math.isfinite(peer_short) and -armed_direction * peer_short >= .25 * fixed_peer_width
        elif family in ("A", "D") and not newly_armed and i >= 2 and np.all(own["valid"][i - 2:i]):
            reverse_break = (price < float(np.min(own["low"][i - 2:i])) if armed_direction == 1
                             else price > float(np.max(own["high"][i - 2:i])))
            fired = own_stall >= 2 and retraced and reverse_break
            if family == "A":
                peer_retraced = armed_direction * (peer_peak - peer["anchor"][j]) >= .5 * fixed_peer_width
                fired = fired and peer_stall >= 2 and peer_retraced
        if fired:
            d = -armed_direction
            side = 0 if d == 1 else 1
            assert not active[side]
            entry[i] = d
            active[side] = True
            targets[side], barriers[side], trade_width[side] = fixed_center, own_peak, fixed_width
            phase = 2
    return dict(entry=entry, exit_long=exits[0], exit_short=exits[1], width=width, valid=valid)


def build(own: dict, peer: dict, symbol: str, previous_close: float | None = None) -> dict:
    """
    機能: 四入口×20/40分尺度を、既119の幅と相手公開資格から構成する。
    引数: own/peer(dict) は118型分足、symbol(str) はTOPIX/NK225、previous_close(float|None) は未使用互換引数。
    返り値: dict はspecs・entry・exit_long・exit_short・width・valid。原市場・金融エンジンを読まない。
    """
    assert symbol in SOURCE.TICKS
    n = SOURCE.inspect_bars(own)
    SOURCE.inspect_bars(peer)
    other_symbol = "NK225" if symbol == "TOPIX" else "TOPIX"
    indexes = SOURCE.peer_index(own, peer)
    histories = {length: SOURCE.historical(own, length, SOURCE.TICKS[symbol]) for length in SCALES}
    others = {length: SOURCE.historical(peer, length, SOURCE.TICKS[other_symbol]) for length in SCALES}
    specs, results = [], []
    for family, name, thought in FAMILIES:
        for length in SCALES:
            results.append(signals(own, peer, histories[length], others[length], indexes, family))
            specs.append(dict(id=f"{family}_L{length:02d}", family=family, name=f"{name}・{length}分尺度",
                description=thought,
                scale=length, width_definition="既catalog119.historicalの幅。準備時の自己・相手幅を固定。",
                center="準備時の自己L分平均を固定。A/C/Dは原方向極値再開、Bは現rolling中心5本変化が反対保有に不利0.5固定幅で撤回。全案固定中心到達でも撤回。",
                rearm="発火後の同方向参照は仮説終端まで保持し、その方向の再準備を禁止。SL/TP又は未約定でもこの保守的禁止は残る。準備解除を挟まない同波連射を禁止。",
                missing="未発火の準備だけを破棄。既発火の方向別固定参照は残し、入口validと独立に既知価格で撤回。相手同一足は二度数えず、新足なしは共同準備を破棄。",
                peer="自己より1分以上前かつ自己公開価格時計以前の相手足。真受信順の証明ではない。",
                neutral="entry0は新規なし。中立と欠測だけで返済しない。", reuse="未測定の対照条件。過去の負け方向を反転して採用したものではない。"))
    out = dict(specs=specs)
    for key in ("entry", "exit_long", "exit_short", "width", "valid"):
        out[key] = np.asarray([result[key] for result in results])
        assert out[key].shape == (8, n)
    assert not np.any((out["entry"] != 0) & ~out["valid"])
    assert np.isin(out["entry"], (-1, 0, 1)).all()
    return out
