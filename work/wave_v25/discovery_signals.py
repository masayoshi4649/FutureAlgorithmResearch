"""15機序120条件を、解放済み市場情報だけから逐次生成する新規方向カタログ。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("v25_legacy_signals", ROOT / "work/wave_v23/signals.py")
LEGACY = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = LEGACY
_spec.loader.exec_module(LEGACY)
_CACHE: dict = {}
SYMBOLS = ("NK225", "TOPIX")


def catalog() -> list[dict]:
    """機能: 新損益を参照せず固定した15機序×8条件を返す。

    引数: なし。
    返り値: ID・名称・機序・説明・固定パラメータの一覧 (list[dict])。
    """
    families = [
        ("cross_confirm", "両市場のフローと応答", "両市場でフローと価格進行が同方向の場面に入り、反対フローと短期価格で撤回する。"),
        ("cross_lag", "相手の進行から遅行側へ", "相手のフローと価格が先行し、自銘柄はまだ伸び切らず短期価格が追随し始める場面を拾う。"),
        ("cross_absorption", "両市場の吸収から反転", "同方向フローがあるのに両市場とも価格進行が鈍くなり、短い価格方向が逆へ揃ったとき反転する。"),
        ("persistent", "フロー強度と持続", "現在と過去二時点のOFI方向が続き、推定売買と価格も揃う場合に限って追随する。"),
        ("absorption_failure", "吸収の失敗から継続", "大きいフローでも進まない場面を準備状態とし、その後に吸収帯を抜けた価格と同方向フローを確認して進む。"),
        ("refill_rebound", "補充代理の後に価格確認", "補充らしい数量回復を発見しただけでは入らず、後続の価格反発とOFIを確認する。取消と約定は識別しない。"),
        ("far_to_near", "遠い板から近い板へ伝播", "遠い板が先行し近い板が弱い間に準備し、後で近い板と価格が同方向へ動いたら入る。準備と発火を別時刻にする。"),
        ("flow_reversal", "長いフローから短い反転", "前から蓄積した長めのフローに対し、短いフローと価格が反転した場面を拾う。参加者の返済とは断定しない。"),
        ("fragility", "流動性に対する価格感応", "少ない推定取引量で通常より大きく価格が動き、近い板変化が同方向の場合に進行へ追随する。"),
        ("shock_branch", "衝撃後の回復と未回復", "急変を記録し、後続で板が戻って価格反転なら逆張り、板が戻らず価格続伸なら順張りへ分岐する。"),
        ("event_clock", "更新回数で測る売買圧力", "時計時間ではなく原本更新数を揃えた窓でOFI・推定売買・価格の同方向性を測る。"),
        ("volume_burst", "推定取引量の加速と方向", "直近の推定取引量の増加速度を、その前の長い区間と比較し、フローと価格が揃った加速へ追随する。"),
        ("session_adaptive", "既知時間帯と市場状態の選択", "開始帯と米国開始帯は速い両市場フローを使い、通常帯は効率比で順張りと吸収反転を機械的に選ぶ。"),
        ("trend_pullback", "流れの中の押し戻り確認", "長めの価格方向を認めた後の逆向き押し戻りを準備し、価格とフローが元方向へ再開したら入る。"),
        ("failed_breakout", "帯の突破失敗と流れの反転", "過去の価格帯を抜けた時点を記録し、後で帯内へ戻ってフローも逆転した場合だけ逆方向へ入る。"),
    ]
    result = []
    for family_index, (kind, family, idea) in enumerate(families):
        for window_index, seconds in enumerate((60, 120, 300, 600)):
            for strict in (0, 1):
                index = family_index * 8 + window_index * 2 + strict
                params = dict(kind=kind, seconds=seconds, strict=bool(strict),
                              flow_threshold=(.03, .08)[strict], trade_threshold=(.08, .18)[strict],
                              price_threshold=(.10, .25)[strict], confirm_move_atr=(.15, .30)[strict],
                              absorption_max_atr=(.35, .20)[strict], refill_threshold=(.20, .40)[strict],
                              far_threshold=(.05, .10)[strict], near_setup_threshold=.03,
                              near_confirm_threshold=(.03, .07)[strict], peer_delay_seconds=60,
                              warmup_minutes=20, setup_ttl_seconds=max(300, seconds * 2),
                              signal_ttl_seconds=max(120, min(900, seconds * 2)),
                              event_count=(300, 1000, 3000, 8000)[window_index],
                              impact_ratio=(1.25, 2.0)[strict], shock_atr=(.60, 1.0)[strict],
                              volume_acceleration=(1.5, 3.0)[strict], trend_efficiency=(.20, .35)[strict])
                result.append(dict(id=f"D{index:03d}", name=f"{family}・{seconds}秒・{'強確認' if strict else '広め'}",
                                   family=family, description=idea, params=params))
    return result


def clear_cache() -> None:
    """機能: 入力の切断・改変を伴う監査時に、中間値の再利用を解除する。

    引数: なし。
    返り値: なし (None)。
    """
    _CACHE.clear()
    LEGACY.clear_cache()


def neighbor_specs(spec: dict) -> list[dict]:
    """機能: 主探索カタログを変えず、全候補へ同じ近傍反証条件を作る。

    引数: spec (dict) はcatalogの固定条件1件。
    返り値: フロー系・価格系の閾値群を各±20%にした4条件 (list[dict])。
    注意: 複数閾値を同率で動かす一律感度診断であり、損益を見て採用条件を選ばない。
    """
    groups = {
        "FLOW": ("flow_threshold", "trade_threshold", "far_threshold", "near_setup_threshold", "near_confirm_threshold", "refill_threshold"),
        "PRICE": ("price_threshold", "confirm_move_atr", "absorption_max_atr", "shock_atr"),
    }
    result = []
    for group, names in groups.items():
        for label, factor in (("M20", .8), ("P20", 1.2)):
            params = dict(spec["params"])
            for name in names:
                params[name] *= factor
            result.append(dict(spec, id=f"{spec['id']}_{group}_{label}", params=params,
                               name=spec["name"] + f"・{group}閾値{factor:.1f}倍診断", diagnostic_parent=spec["id"],
                               description=spec["description"] + " 主探索とは別の一律近傍反証。"))
    return result


def _asof(events: np.ndarray, values: np.ndarray, targets: np.ndarray, initial: float = 0) -> np.ndarray:
    """機能: 公開時刻または行番号以前の最後の値だけを対応させる。

    引数: events/values/targets (ndarray)、initial (float) は開始前の値。
    返り値: targetsと同じ長さの過去値列 (ndarray)。
    """
    result = np.full(len(targets), initial, dtype=np.asarray(values).dtype)
    positions = np.searchsorted(events, targets, side="right") - 1
    valid = positions >= 0
    result[valid] = values[positions[valid]]
    return result


def _sign(values: np.ndarray, threshold: float = 0) -> np.ndarray:
    """機能: 欠損を中立にし、正負対称の閾値で方向化する。

    引数: values (ndarray)、threshold (float) は絶対値下限。
    返り値: -1/0/1 の方向列 (ndarray[int8])。
    """
    array = np.asarray(values, dtype=float)
    return np.where(array > threshold, 1, np.where(array < -threshold, -1, 0)).astype(np.int8)


def _book(ready: dict, frame: pd.DataFrame, seconds: int) -> dict:
    """機能: 解放済み板と確定足を使い、機序共通の過去特徴を用意する。

    引数: ready (dict)、frame (DataFrame)、seconds (int) は集計窓秒数。
    返り値: 解放行・時刻・フロー・価格応答・確定足状態の辞書 (dict)。
    """
    key = (id(ready), id(frame), id(ready["atr"]), len(ready["seq"]), int(ready["seq"][-1]), seconds)
    if key in _CACHE:
        return _CACHE[key]
    board = dict(LEGACY._board(ready, frame, seconds))
    current = frame.loc[(frame.seq <= ready["seq"][-1]) & (frame.time_s <= ready["time_s"][-1])].copy()
    np.testing.assert_array_equal(current.seq.to_numpy(), board["seq"])
    current.index = pd.to_datetime(current.time_s, unit="s", utc=True)
    board["depth_total"] = (current.bid_qty + current.ask_qty).to_numpy(float)
    board["raw_trade_signed"] = (current.trade_pos - current.trade_neg).to_numpy(float)
    board["raw_trade_total"] = (current.trade_pos + current.trade_neg).to_numpy(float)
    board["quantity"] = board["trade_pos"] + board["trade_neg"]
    total_refill = board["refill_bid"] + board["refill_ask"]
    board["refill_pressure"] = np.divide(board["refill_bid"] - board["refill_ask"], total_refill,
                                          out=np.zeros_like(total_refill), where=total_refill > 0)
    total_supply = board["added_bid"] + board["removed_bid"] + board["added_ask"] + board["removed_ask"]
    board["supply"] = np.divide(board["added_bid"] + board["removed_ask"] - board["added_ask"] - board["removed_bid"],
                                total_supply, out=np.zeros_like(total_supply), where=total_supply > 0)
    bars = LEGACY._bars(ready)
    board["efficiency"] = _asof(bars["time_s"], bars["er30"].to_numpy(float), board["time_s"], np.nan)
    board["trend"] = _asof(bars["time_s"], LEGACY._ema(bars, 8, 30, .15, .02), board["time_s"])
    short_average = bars["close"].ewm(span=8, adjust=False, min_periods=8).mean().to_numpy(float)
    board["short_average"] = _asof(bars["time_s"], short_average, board["time_s"], np.nan)
    board["price_short"] = (board["mid"] - _asof(board["time_s"], board["mid"], board["time_s"] - 30, np.nan)) / board["atr"]
    board["band_high"] = pd.Series(board["mid"], index=board["index"]).shift(1).rolling(f"{seconds * 3}s", min_periods=5).max().to_numpy(float)
    board["band_low"] = pd.Series(board["mid"], index=board["index"]).shift(1).rolling(f"{seconds * 3}s", min_periods=5).min().to_numpy(float)
    board["ready_ref"] = ready
    board["frame_ref"] = frame
    _CACHE[key] = board
    return board


def _peer(own: dict, other: dict, names: tuple[str, ...], delay: int) -> dict:
    """機能: 独立市場の特徴を追加遅延した公開時刻でのみ対応させる。

    引数: own/other (dict) は両市場特徴、names (tuple[str,...])、delay (int) は追加秒数。
    返り値: 自市場の解放時刻で利用できる相手特徴 (dict)。
    """
    return {name: _asof(other["time_s"] + delay, np.asarray(other[name]), own["time_s"], 0)
            for name in names}


def _hold(candidate: np.ndarray, veto: np.ndarray, times: np.ndarray, ttl: float, max_gap: float) -> np.ndarray:
    """機能: 発生した方向を期限付きで保ち、逆の確証または長い欠測で解除する。

    引数: candidate/veto (ndarray[int8])、times (ndarray)、ttl/max_gap (float) は秒数。
    返り値: 解放イベントごとの方向 (ndarray[int8])。
    """
    result = np.zeros(len(times), dtype=np.int8)
    state, supported, previous = 0, -np.inf, -np.inf
    for i, time in enumerate(times):
        if time - previous > max_gap or time - supported > ttl:
            state = 0
        if state and veto[i] == -state:
            state = 0
        if candidate[i] != 0:
            state, supported = int(candidate[i]), float(time)
        result[i] = state
        previous = float(time)
    return result


def _sequence(setup: np.ndarray, flow: np.ndarray, board: dict, params: dict, mode: str) -> np.ndarray:
    """機能: 準備を記録してから後続イベントで価格確認し、一回だけ方向を発火する。

    引数: setup/flow (ndarray[int8])、board/params (dict)、mode (str) は確認方式。
    返り値: 確認時だけ非中立になる候補列 (ndarray[int8])。
    注意: 同じイベントで準備と発火を行わず、準備時のATR・価格帯を保持する。
    """
    result = np.zeros(len(setup), dtype=np.int8)
    armed, began, anchor, scale, boundary, depth = 0, -np.inf, 0., 1., 0., 1.
    times, mid, atr = board["time_s"], board["mid"], board["atr"]
    for i, time in enumerate(times):
        if armed:
            if time - began > params["setup_ttl_seconds"]:
                armed = 0
            else:
                move = armed * (mid[i] - anchor) / scale
                expected = armed
                confirmed = move >= params["confirm_move_atr"] and flow[i] == armed
                if mode == "far":
                    confirmed &= armed * board["dflow_near"][i] > params["near_confirm_threshold"]
                    confirmed &= armed * board["dflow_far"][i] > params["far_threshold"]
                elif mode == "failed":
                    expected = -armed
                    confirmed = armed * (mid[i] - boundary) / scale < -params["confirm_move_atr"] and flow[i] == -armed
                elif mode == "shock":
                    recovered = board["depth_total"][i] / depth
                    if move <= -params["confirm_move_atr"] and recovered >= 1.1 and flow[i] != armed:
                        expected, confirmed = -armed, True
                    else:
                        confirmed &= recovered <= 1.0
                if confirmed and time > began:
                    result[i] = expected
                    armed = 0
                    continue
                if mode not in ("failed", "shock") and flow[i] == -armed:
                    armed = 0
        if not armed and setup[i] != 0 and np.isfinite(atr[i]) and atr[i] > 0:
            armed, began, anchor, scale = int(setup[i]), float(time), float(mid[i]), float(atr[i])
            boundary = board["band_high"][i] if armed > 0 else board["band_low"][i]
            depth = max(1., float(board["depth_total"][i]))
    return result


def _event_candidate(board: dict, params: dict) -> np.ndarray:
    """機能: 原本更新回数を揃えた過去イベント窓でフローと価格を比較する。

    引数: board/params (dict) は特徴と固定条件。
    返り値: 各解放イベントの方向 (ndarray[int8])。
    """
    event_count = np.cumsum(board["events"])
    starts = np.searchsorted(event_count, event_count - params["event_count"], side="left")
    sums = {}
    for name in ("raw_ofi", "raw_ofi_abs", "raw_trade_signed", "raw_trade_total"):
        cumulative = np.r_[0.0, np.cumsum(board[name])]
        sums[name] = cumulative[1:] - cumulative[starts]
    ratio = np.divide(sums["raw_ofi"], sums["raw_ofi_abs"], out=np.zeros(len(starts)), where=sums["raw_ofi_abs"] > 0)
    trade = np.divide(sums["raw_trade_signed"], sums["raw_trade_total"], out=np.zeros(len(starts)), where=sums["raw_trade_total"] > 0)
    direction = _sign(ratio, params["flow_threshold"])
    progress = (board["mid"] - board["mid"][starts]) / board["atr"]
    good = (event_count >= params["event_count"]) & (_sign(progress, params["price_threshold"]) == direction)
    good &= _sign(trade, params["trade_threshold"]) == direction
    return np.where(good, direction, 0).astype(np.int8)


def _candidate(params: dict, ready: dict, own: dict, peer: dict, slow: dict, fast: dict) -> np.ndarray:
    """機能: 異なる市場機序の反証可能な条件を方向候補へ変換する。

    引数: params/ready/own/peer/slow/fast (dict) は固定仕様と当時の特徴。
    返り値: 自市場の解放イベントごとの方向候補 (ndarray[int8])。
    """
    kind, seconds = params["kind"], params["seconds"]
    flow = _sign(own["ofi"], params["flow_threshold"])
    trade = _sign(own["trade"], params["trade_threshold"])
    progress = _sign(own["progress"], params["price_threshold"])
    short = _sign(own["price_short"], .03)
    counterpart = _sign(peer["ofi"], params["flow_threshold"])
    if kind == "cross_confirm":
        other_price = _sign(peer["progress"], params["price_threshold"])
        good = (flow == counterpart) & (flow == progress) & (flow == other_price)
        if params["strict"]:
            good &= flow == trade
        return np.where(good, flow, 0).astype(np.int8)
    if kind == "cross_lag":
        other_price = _sign(peer["progress"], params["price_threshold"] + .15)
        good = (counterpart == other_price) & (short == counterpart) & (flow != -counterpart)
        good &= counterpart * own["progress"] < counterpart * peer["progress"] - .10
        return np.where(good, counterpart, 0).astype(np.int8)
    if kind == "cross_absorption":
        other_short = _sign(peer["price_short"], .03)
        absorbed = (flow == counterpart) & (flow * own["progress"] <= params["absorption_max_atr"])
        absorbed &= counterpart * peer["progress"] <= params["absorption_max_atr"]
        absorbed &= (short == -flow) & (other_short == -flow)
        return np.where(absorbed, -flow, 0).astype(np.int8)
    if kind == "persistent":
        earlier = _asof(own["time_s"], flow, own["time_s"] - seconds)
        middle = _asof(own["time_s"], flow, own["time_s"] - seconds / 2)
        good = (flow == earlier) & (flow == middle) & (flow == trade) & (flow == progress)
        good &= counterpart != -flow
        return np.where(good, flow, 0).astype(np.int8)
    if kind == "absorption_failure":
        setup = np.where((flow == trade) & (np.abs(own["progress"]) <= params["absorption_max_atr"]), flow, 0).astype(np.int8)
        return _sequence(setup, flow, own, params, "continuation")
    if kind == "refill_rebound":
        wall = _sign(own["refill_pressure"], params["refill_threshold"])
        setup = np.where((np.abs(own["progress"]) <= params["absorption_max_atr"]) & (counterpart != -wall), wall, 0).astype(np.int8)
        return _sequence(setup, flow, own, params, "rebound")
    if kind == "far_to_near":
        far = _sign(own["dflow_far"], params["far_threshold"])
        setup = np.where((np.abs(own["dflow_near"]) < params["near_setup_threshold"]) & (counterpart != -far), far, 0).astype(np.int8)
        return _sequence(setup, flow, own, params, "far")
    if kind == "flow_reversal":
        historical = _asof(slow["time_s"], _sign(slow["ofi"], params["flow_threshold"]), own["time_s"] - seconds)
        good = (flow == -historical) & (flow == short) & (counterpart != -flow)
        if params["strict"]:
            good &= flow == trade
        return np.where(good, flow, 0).astype(np.int8)
    if kind == "fragility":
        response = np.divide(np.abs(own["progress"]), own["quantity"], out=np.full(len(flow), np.nan), where=own["quantity"] > 0)
        typical = pd.Series(response, index=own["index"]).shift(1).rolling("1800s", min_periods=30).median().to_numpy(float)
        good = response > typical * params["impact_ratio"]
        good &= (progress == _sign(own["dflow_near"], params["near_confirm_threshold"])) & (counterpart != -progress)
        return np.where(good, progress, 0).astype(np.int8)
    if kind == "shock_branch":
        shock = _sign(own["shock"], params["shock_atr"])
        return _sequence(shock, flow, own, params, "shock")
    if kind == "event_clock":
        candidate = _event_candidate(own, params)
        candidate[counterpart == -candidate] = 0
        return candidate
    if kind == "volume_burst":
        t = own["time_s"]
        accumulated = np.cumsum(own["raw_trade_total"])
        before = _asof(t, accumulated, t - seconds, np.nan)
        earlier = _asof(t, accumulated, t - seconds * 6, np.nan)
        historical_rate = (before - earlier) / (5 * seconds)
        current_rate = (accumulated - before) / seconds
        good = (historical_rate > 0) & (current_rate > historical_rate * params["volume_acceleration"])
        good &= (flow == trade) & (flow == progress) & (counterpart != -flow)
        return np.where(good, flow, 0).astype(np.int8)
    if kind == "session_adaptive":
        swift = _asof(fast["time_s"], _sign(fast["ofi"], params["flow_threshold"]), own["time_s"])
        fast_progress = _asof(fast["time_s"], _sign(fast["progress"], params["price_threshold"]), own["time_s"])
        event_band = own["time_s"] < ready["start"] + 3600
        event_band |= (own["time_s"] >= ready["us_open"]) & (own["time_s"] < ready["us_open"] + 3600)
        speedy = np.where((swift == fast_progress) & (swift == counterpart), swift, 0)
        trend = np.where((own["efficiency"] >= params["trend_efficiency"]) & (own["trend"] == flow) & (counterpart != -flow), flow, 0)
        absorbed = (own["efficiency"] < params["trend_efficiency"] / 2) & (flow * own["progress"] < params["absorption_max_atr"])
        rebound = np.where(absorbed & (short == -flow) & (counterpart != flow), -flow, 0)
        regular = np.where(own["efficiency"] >= params["trend_efficiency"], trend, rebound)
        return np.where(event_band, speedy, regular).astype(np.int8)
    if kind == "trend_pullback":
        trend = own["trend"]
        displacement = trend * (own["mid"] - own["short_average"]) / own["atr"]
        setup = np.where((own["efficiency"] >= params["trend_efficiency"]) & (displacement < -params["price_threshold"]) & (counterpart != -trend), trend, 0).astype(np.int8)
        return _sequence(setup, flow, own, params, "pullback")
    if kind == "failed_breakout":
        upper = own["mid"] > own["band_high"] + params["price_threshold"] * own["atr"]
        lower = own["mid"] < own["band_low"] - params["price_threshold"] * own["atr"]
        setup = np.where(upper, 1, np.where(lower, -1, 0)).astype(np.int8)
        setup[own["efficiency"] >= params["trend_efficiency"] + .20] = 0
        return _sequence(setup, flow, own, params, "failed")
    raise ValueError(f"未知の市場機序です: {kind}")


def build(spec: dict, inputs: dict, features: dict) -> dict[tuple[str, str], np.ndarray]:
    """機能: 固定した一条件を、当時利用できたデータだけで全区間へ適用する。

    引数: spec (dict) はcatalogの1件、inputs/features (dict) は (セッション,銘柄) 別の入力と板特徴。
    返り値: 同じキーで原本行ごとの方向を持つ辞書 (dict[tuple[str,str],ndarray[int8]])。
    注意: 新規注文は呼出側で次行以降に有効化する。方向の0や変更で既存玉を返済するかは注文管理側の責任。
    """
    fixed = {item["id"]: item for item in catalog()}
    expected = fixed.get(spec.get("id"))
    if expected is None and spec.get("diagnostic_parent") in fixed:
        expected = {item["id"]: item for item in neighbor_specs(fixed[spec["diagnostic_parent"]])}.get(spec.get("id"))
    if expected is None or spec.get("params") != expected["params"]:
        raise ValueError("損益参照前に固定したカタログまたは一律近傍条件と一致しません")
    params = spec["params"]
    seconds = params["seconds"]
    models = {key: _book(ready, features[key], seconds) for key, ready in inputs.items()}
    output = {}
    for key, ready in inputs.items():
        other_key = (key[0], SYMBOLS[1 - SYMBOLS.index(key[1])])
        if other_key not in models:
            raise ValueError("相手銘柄の同一セッション入力が必要です")
        own = models[key]
        other = _peer(own, models[other_key], ("ofi", "progress", "price_short"), params["peer_delay_seconds"])
        slow = _book(ready, features[key], seconds * 3) if params["kind"] == "flow_reversal" else own
        fast = _book(ready, features[key], 60) if params["kind"] == "session_adaptive" else own
        candidate = _candidate(params, ready, own, other, slow, fast)
        opposite_flow = _sign(own["ofi"], params["flow_threshold"])
        opposite_price = _sign(own["price_short"], .03)
        veto = np.where(opposite_flow == opposite_price, opposite_flow, 0).astype(np.int8)
        values = _hold(candidate, veto, own["time_s"], params["signal_ttl_seconds"], max(120, seconds))
        direction = _asof(own["seq"], values, ready["seq"]).astype(np.int8)
        direction[ready["time_s"] < ready["start"] + params["warmup_minutes"] * 60] = 0
        direction[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
        assert len(direction) == len(ready["seq"]) and np.isin(direction, [-1, 0, 1]).all()
        output[key] = direction
    return output
