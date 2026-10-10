"""保存済み確定足だけで、M3逆の新規入口方向を一変数ずつ変更して生成する。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ("NK225", "TOPIX")
BASE_PARAMETERS = {
    "fast": 8,
    "slow": 30,
    "gap": 0.15,
    "slope": 0.03,
    "m1_confirmations": 2,
    "m3_confirmations": 2,
    "peer_delay_seconds": 60,
    "require_current_agreement": False,
    "max_age_minutes": None,
    "board_filter": None,
}


def variant_specs() -> list[dict]:
    """機能: 損益を参照せず事前固定した基準と20個の一変数変更を返す。

    引数: なし。
    返り値: id/name/description/change_count/changes を持つ候補一覧 (list[dict])。
    """
    definitions = [
        ("基準のM3逆", "EMA8/30、間隔0.15ATR、傾き0.03ATR、各２回確認、相手を追加60秒遅延する元のM3逆。", {}),
        ("短期EMAを５分", "短期EMAだけを８本から５本へ変更する。", {"fast": 5}),
        ("短期EMAを12分", "短期EMAだけを８本から12本へ変更する。", {"fast": 12}),
        ("長期EMAを20分", "長期EMAだけを30本から20本へ変更する。", {"slow": 20}),
        ("長期EMAを45分", "長期EMAだけを30本から45本へ変更する。", {"slow": 45}),
        ("EMA間隔を0.10ATR", "方向候補となるEMA間隔の下限だけを0.10ATRへ変更する。", {"gap": 0.10}),
        ("EMA間隔を0.25ATR", "方向候補となるEMA間隔の下限だけを0.25ATRへ変更する。", {"gap": 0.25}),
        ("EMA傾きを0.015ATR", "長期EMAの３本変化の下限だけを0.015ATRへ変更する。", {"slope": 0.015}),
        ("EMA傾きを0.06ATR", "長期EMAの３本変化の下限だけを0.06ATRへ変更する。", {"slope": 0.06}),
        ("銘柄内の確認を１回", "銘柄ごとのM1方向の連続確認だけを１回にする。", {"m1_confirmations": 1}),
        ("銘柄内の確認を３回", "銘柄ごとのM1方向の連続確認だけを３回にする。", {"m1_confirmations": 3}),
        ("両銘柄一致の確認を１回", "M3の両銘柄一致の連続確認だけを１回にする。", {"m3_confirmations": 1}),
        ("両銘柄一致の確認を３回", "M3の両銘柄一致の連続確認だけを３回にする。", {"m3_confirmations": 3}),
        ("相手の追加遅延なし", "既に公開済みの相手M1を使い、追加60秒だけをなくす。確定足の公開遅延120秒は維持する。", {"peer_delay_seconds": 0}),
        ("相手の追加遅延120秒", "公開済み相手M1の追加遅延だけを60秒から120秒へ変更する。", {"peer_delay_seconds": 120}),
        ("現在の一致がなければ新規禁止", "現在の両銘柄一致が保持中のM3方向を裏付けない間だけ、新規入口を中立にする。", {"require_current_agreement": True}),
        ("確認後15分で根拠を失効", "最後に同方向を連続確認できた時刻から15分超で新規禁止。同方向の確認継続中は期限を更新する。", {"max_age_minutes": 15}),
        ("確認後30分で根拠を失効", "最後に同方向を連続確認できた時刻から30分超で新規禁止。同方向の確認継続中は期限を更新する。", {"max_age_minutes": 30}),
        ("確認後60分で根拠を失効", "最後に同方向を連続確認できた時刻から60分超で新規禁止。同方向の確認継続中は期限を更新する。", {"max_age_minutes": 60}),
        ("板方向と売買方向の一致", "元のM3逆の売買方向と、保存済みM2の主方向が一致する場合だけ新規を許可する。", {"board_filter": "same_trade"}),
        ("板の逆方向と売買方向の一致", "元のM3逆の売買方向と、保存済みM2の逆方向が一致する場合だけ新規を許可する。", {"board_filter": "opposite_trade"}),
    ]
    return [
        {"id": f"S{index:02d}", "name": name, "description": description,
         "change_count": len(changes), "changes": changes.copy()}
        for index, (name, description, changes) in enumerate(definitions)
    ]


def _parameters(spec: dict) -> dict:
    """機能: 候補の変更内容を検査し、基準値へ適用する。

    引数: spec (dict) は variant_specs の候補１件。
    返り値: 全計算条件のコピー (dict)。
    """
    expected = {item["id"]: item for item in variant_specs()}
    if spec.get("id") not in expected:
        raise ValueError("固定済み候補に存在しない信号IDです")
    canonical = expected[spec["id"]]
    if spec.get("changes") != canonical["changes"] or spec.get("change_count") != canonical["change_count"]:
        raise ValueError("固定済み候補と変更内容が異なります")
    return {**BASE_PARAMETERS, **canonical["changes"]}


def _confirmed(candidates: np.ndarray, times: np.ndarray, confirmations: int) -> tuple[np.ndarray, np.ndarray]:
    """機能: 連続確認した方向を保持し、最後に確認できた時刻も記録する。

    引数: candidates (ndarray[int8])、times (ndarray[float])、confirmations (int)。
    返り値: 状態列と確認時刻列 (tuple[ndarray[int8], ndarray[float]])。
    """
    states = np.zeros(len(candidates), dtype=np.int8)
    confirmed_times = np.full(len(candidates), -np.inf, dtype=float)
    state, pending, count = 0, 0, 0
    last_time, last_confirmation = -np.inf, -np.inf
    for index, (candidate, stamp) in enumerate(zip(candidates, times)):
        candidate = int(candidate)
        if stamp - last_time > 90:
            pending, count = 0, 0
        if candidate == 0:
            pending, count = 0, 0
        elif candidate == pending:
            count += 1
        else:
            pending, count = candidate, 1
        if count >= confirmations:
            state, last_confirmation = pending, float(stamp)
        states[index] = state
        confirmed_times[index] = last_confirmation
        last_time = float(stamp)
    return states, confirmed_times


def _expand_times(event_times: np.ndarray, values: np.ndarray, target_times: np.ndarray) -> np.ndarray:
    """機能: 対象時刻以前に公開された最後の方向だけを対応させる。

    引数: event_times/target_times (ndarray[float])、values (ndarray[int8])。
    返り値: 対象時刻と同じ長さの方向列 (ndarray[int8])。
    """
    output = np.zeros(len(target_times), dtype=np.int8)
    positions = np.searchsorted(event_times, target_times, side="right") - 1
    valid = positions >= 0
    output[valid] = values[positions[valid]]
    return output


def _minute_model(ready: dict, parameters: dict) -> dict:
    """機能: 入力末尾までに公開された確定足だけでEMAとM1を再計算する。

    引数: ready (dict) は途中切断可能な入力、parameters (dict) は固定条件。
    返り値: 公開時刻・方向・確認時刻の辞書 (dict[str, ndarray])。
    """
    frame = pd.read_csv(ROOT / "candle_1min" / ready["symbol"] / f"{ready['session']}.csv")
    available = pd.to_datetime(frame.time).dt.as_unit("ns").astype("int64").to_numpy(float) / 1e9 + 120.0
    valid = frame.closed.astype(str).str.lower().eq("true").to_numpy(copy=True)
    valid &= (available <= ready["time_s"][-1]) & (available >= ready["start"] + 120.0)
    frame, available = frame.loc[valid].copy(), available[valid]
    if not np.all(np.diff(available) > 0):
        raise ValueError("確定足の公開時刻が昇順ではありません")
    close = frame.close.astype(float).reset_index(drop=True)
    fast = close.ewm(span=parameters["fast"], adjust=False, min_periods=parameters["fast"]).mean()
    slow = close.ewm(span=parameters["slow"], adjust=False, min_periods=parameters["slow"]).mean()
    positions = np.searchsorted(ready["time_s"], available, side="right") - 1
    atr = np.full(len(frame), np.nan)
    have = positions >= 0
    atr[have] = ready["atr"][positions[have]]
    gap = (fast - slow).to_numpy(float) / atr
    slope = slow.diff(3).to_numpy(float) / atr
    candidates = np.zeros(len(frame), dtype=np.int8)
    candidates[(gap >= parameters["gap"]) & (slope >= parameters["slope"])] = 1
    candidates[(gap <= -parameters["gap"]) & (slope <= -parameters["slope"])] = -1
    candidates[available < ready["start"] + 20 * 60] = 0
    states, confirmed_times = _confirmed(candidates, available, parameters["m1_confirmations"])
    return {"time_s": available, "states": states, "confirmed_times": confirmed_times}


def _minute_checks(ready: dict) -> np.ndarray:
    """機能: 開始20分後以降、各分の最初の有効原本行を選ぶ。

    引数: ready (dict) は途中切断可能な入力。
    返り値: 確認に用いる原本行位置 (ndarray[int64])。
    """
    targets = np.arange(ready["start"] + 20 * 60, ready["time_s"][-1] + 1e-8, 60.0)
    positions = np.searchsorted(ready["time_s"], targets, side="left")
    return np.unique(positions[positions < len(ready["time_s"])])


def _at_rows(indices: np.ndarray, values: np.ndarray, count: int, initial: int | float = 0) -> np.ndarray:
    """機能: 同時刻内の未来行を参照せず、公開行以降へ値を展開する。

    引数: indices (ndarray[int64])、values (ndarray)、count (int)、initial (int|float)。
    返り値: 指定原本行数の値列 (ndarray)、型は values と同じ。
    """
    output = np.full(count, initial, dtype=values.dtype)
    event_number = np.searchsorted(indices, np.arange(count), side="right") - 1
    valid = event_number >= 0
    output[valid] = values[event_number[valid]]
    return output


def build_one(spec: dict, inputs: dict, original_states: dict) -> dict[tuple[str, str], np.ndarray]:
    """機能: １候補の新規売買方向だけを、公開済み情報から生成する。

    引数: spec (dict) は固定候補、inputs (dict) は (セッション, 銘柄) 別入力、
          original_states (dict) は同キーの既存M1/M2/M3状態。途中切断時は元状態の先頭も利用可能。
    返り値: 入力原本各行の新規方向 -M3 を持つ辞書 (dict[tuple[str, str], ndarray[int8]])。
    注意: 現行観測で更新した入口方向であり、新規注文の有効化は呼出側で次行以降に行う。
          中立化・期限切れ・板フィルタは入口だけの制限であり、既存建玉の返済を指示しない。
    """
    parameters = _parameters(spec)
    for key, ready in inputs.items():
        if key != (ready["session"], ready["symbol"]) or ready["symbol"] not in SYMBOLS:
            raise ValueError("入力キーとセッション・銘柄が一致しません")
        if len(ready["time_s"]) == 0 or len(ready["time_s"]) != len(ready["seq"]):
            raise ValueError("入力原本行が空か、時刻と行番号の長さが一致しません")
        if not np.all(np.diff(ready["time_s"]) >= 0):
            raise ValueError("入力時刻が昇順ではありません")
    models = {key: _minute_model(ready, parameters) for key, ready in inputs.items()}
    result = {}
    for key, ready in inputs.items():
        peer_symbol = SYMBOLS[1 - SYMBOLS.index(key[1])]
        own, peer = models[key], models[(key[0], peer_symbol)]
        checks = _minute_checks(ready)
        check_times = ready["time_s"][checks]
        own_values = _expand_times(own["time_s"], own["states"], check_times)
        peer_values = _expand_times(peer["time_s"] + parameters["peer_delay_seconds"], peer["states"], check_times)
        agree = np.where((own_values == peer_values) & (own_values != 0), own_values, 0).astype(np.int8)
        states, confirmation_times = _confirmed(agree, check_times, parameters["m3_confirmations"])
        dense = _at_rows(checks, states, len(ready["seq"]))
        # ----------------------------------------
        # 維持中のM3自体は書き換えず、選んだ単独条件で新規入口だけを中立化する。
        if parameters["require_current_agreement"]:
            current_agree = _at_rows(checks, agree, len(ready["seq"]))
            dense[current_agree != dense] = 0
        if parameters["max_age_minutes"] is not None:
            confirmed_at = _at_rows(checks, confirmation_times, len(ready["seq"]), -np.inf)
            dense[ready["time_s"] - confirmed_at > parameters["max_age_minutes"] * 60.0] = 0
        direction = (-dense).astype(np.int8)
        if parameters["board_filter"] is not None:
            board = np.asarray(original_states[key]["M2"], dtype=np.int8)[:len(direction)]
            if len(board) != len(direction):
                raise ValueError("既存M2状態が入力原本より短くなっています")
            required = board if parameters["board_filter"] == "same_trade" else -board
            direction[direction != required] = 0
        if spec["id"] == "S00":
            original = np.asarray(original_states[key]["M3"], dtype=np.int8)[:len(direction)]
            assert np.array_equal(direction, -original), f"基準M3逆が元状態と一致しません: {key}"
        assert direction.dtype == np.int8 and np.isin(direction, [-1, 0, 1]).all()
        result[key] = direction
    return result


def build_all(inputs: dict, original_states: dict) -> dict[str, dict[tuple[str, str], np.ndarray]]:
    """機能: 固定済み全21候補の新規入口方向をまとめて生成する。

    引数: inputs (dict) は途中切断可能な２銘柄入力、original_states (dict) は既存方向状態。
    返り値: 信号ID別・入力キー別の新規方向 (dict[str, dict[tuple[str, str], ndarray[int8]]])。
    注意: メモリを節約する場合は variant_specs と build_one を順番に呼び出す。
    """
    return {spec["id"]: build_one(spec, inputs, original_states) for spec in variant_specs()}
