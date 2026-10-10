"""当時の相場状態で信号手法を選び直す、結果参照前に固定した機械的選択器。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import signals


OUT = Path(__file__).resolve().parent
SYMBOLS = ("NK225", "TOPIX")


def catalog() -> list[dict]:
    """機能: 事後の損益順位を使わない10種類の手法選択仕様を返す。

    引数: なし。
    返り値: 識別子・説明・固定閾値・候補系統の一覧 (list[dict])。
    """
    definitions = [
        ("効率比で順張りと吸収を切替", "efficiency", "30分効率比が0.30以上なら60分方向追随、0.15以下なら補充吸収、中間なら最良板。2回確認し最低3分保持する。", {"high": .30, "low": .15, "trend": "F08", "range": "F40", "middle": "F32", "confirm": 2, "hold_minutes": 3}),
        ("効率比で多数決と転換を切替", "efficiency", "効率比0.35以上は三系統多数決、0.20以下は蓄積フロー反転、中間は最良板。2回確認し最低5分保持する。", {"high": .35, "low": .20, "trend": "F35", "range": "F47", "middle": "F32", "confirm": 2, "hold_minutes": 5}),
        ("両市場一致から選ぶ", "agreement", "両市場EMAが一致し効率比0.25以上なら両銘柄順張り。低効率は突破失敗、中間・不一致は最良板を選ぶ。", {"high": .25, "low": .15, "trend": "F24", "range": "F14", "middle": "F32", "confirm": 2, "hold_minutes": 3, "peer_delay": 60}),
        ("吸収とフロー継続を切替", "flow", "強いフローの価格停滞と短期反転なら吸収反転、同方向フローの持続なら継続追随、それ以外は最良板を選ぶ。", {"absorption": "F39", "persistent": "F38", "middle": "F32", "confirm": 1, "hold_minutes": 3}),
        ("衝撃後の板回復で切替", "shock", "60秒で0.75ATR動いた後、板数量回復なら反転、板不足なら継続。通常は効率比で60分順張りか最良板を選ぶ。", {"shock_atr": .75, "recovered": 1.25, "depleted": .8, "high": .30, "recover": "F49", "continue": "F50", "trend": "F08", "middle": "F32", "confirm": 1, "hold_minutes": 3}),
        ("近遠の板と補充壁で切替", "distance", "同価格補充の支えから反発すれば補充壁、近遠が同方向なら近い板追随、遠い板だけ先行なら先行圧力、それ以外は最良板を選ぶ。", {"refill": .20, "pressure": .10, "flow": .05, "wall": "F44", "near": "F42", "far": "F43", "middle": "F32", "confirm": 2, "hold_minutes": 3}),
        ("開場と米国開始の時間切替", "clock", "開始90分までは短期EMA。夜間の米国開始後60分は効率比が0.20以上なら高安突破、低ければ補充吸収。通常は多数決か最良板を選ぶ。", {"opening_minutes": 90, "us_minutes": 60, "us_efficiency": .20, "high": .30, "opening": "F00", "us_trend": "F04", "us_range": "F40", "trend": "F35", "middle": "F32", "confirm": 2, "hold_minutes": 3}),
        ("現在の根拠強度で選ぶ", "strength", "効率比・OFI・吸収・最良板偏差を各固定閾値との比で比較し、現在方向がある系統で最大のものを選ぶ。損益で重みを学習しない。", {"er_scale": .30, "ofi_scale": .08, "micro_scale": .06, "trade_scale": .15, "absorption_progress": .35, "score_cap": 3.0, "choices": ["F35", "F38", "F40", "F32"], "middle": "F32", "confirm": 2, "hold_minutes": 3}),
        ("局面の継続を待って切替", "sticky", "効率比0.40以上で60分方向追随、0.20以下でフロー転換。中間では直前系統を維持し、3回確認・最低10分滞在で細かな切替を抑える。", {"high": .40, "low": .20, "trend": "F08", "range": "F47", "middle": "F32", "confirm": 3, "hold_minutes": 10}),
        ("両市場の吸収を優先する切替", "market", "両市場が吸収から同方向へ転換した候補を優先。共通圧力なら板枯渇、流れがある通常時は多数決、低効率はフロー転換、中間は最良板を選ぶ。", {"high": .30, "low": .15, "turn": "F53", "pressure": "F52", "trend": "F35", "range": "F47", "middle": "F32", "confirm": 2, "hold_minutes": 3}),
    ]
    return [dict(id=f"X{i:02d}", name=name, family="機械的な手法選択", description=description,
                 params=dict(kind=kind, decision_seconds=60, warmup_minutes=20, **params),
                 responsibility="本モジュールは信号手法の選択と新規方向を担当する。既存建玉の返済・反転・損失制限は組み合わせる共通管理が担当する。")
            for i, (name, kind, description, params) in enumerate(definitions)]


def _expand(events: np.ndarray, values: np.ndarray, targets: np.ndarray, initial: float = 0) -> np.ndarray:
    """機能: 原本行または解放時刻以前の最後の値だけを対応させる。

    引数: events/targets (ndarray)、values (ndarray)、initial (float) は初期値。
    返り値: 対象と同じ長さの過去値列 (ndarray)。
    """
    result = np.full(len(targets), initial, dtype=values.dtype)
    positions = np.searchsorted(events, targets, side="right") - 1
    valid = positions >= 0
    result[valid] = values[positions[valid]]
    return result


def _controls(inputs: dict, features: dict, directions: dict) -> dict:
    """機能: 未来を使わず各分の手法選択に必要な相場状態を作る。

    引数: inputs/features (dict) は区間別原本・板特徴、directions (dict) は固定済み基礎信号。
    返り値: 各区間の判断行と当時の相場状態 (dict)。
    """
    result = {}
    for key, ready in inputs.items():
        targets = np.arange(ready["start"] + 1200, np.nextafter(float(ready["time_s"][-1]), np.inf), 60.0)
        indices = np.searchsorted(ready["time_s"], targets, side="left")
        indices = np.unique(indices[indices < len(ready["time_s"])])
        times = ready["time_s"][indices]
        rows = ready["seq"][indices]
        bars = signals._bars(ready)
        board2 = signals._board(ready, features[key], 120)
        board5 = signals._board(ready, features[key], 300)
        needed = {"dflow_near", "dflow_far", "pressure_near", "pressure_far", "refill_bid", "refill_ask"}
        if not needed.issubset(board2):
            raise ValueError("距離・補充の追加板特徴が不足しています")
        own = directions["F01"][key][indices]
        peer_key = (key[0], SYMBOLS[1 - SYMBOLS.index(key[1])])
        peer = inputs[peer_key]
        peer_ema = _expand(peer["time_s"] + 60, directions["F01"][peer_key], times)
        control = dict(indices=indices, time_s=times, seq=rows,
                       efficiency=_expand(bars["time_s"], bars["er30"].to_numpy(float), times, np.nan),
                       own_ema=own, peer_ema=peer_ema,
                       age_minutes=(times - ready["start"]) / 60,
                       us_minutes=(times - ready["us_open"]) / 60 if ready["us_open"] else np.full(len(times), np.nan))
        for name in ("shock", "depth_ratio", "short_change", "dflow_near", "dflow_far", "pressure_near", "pressure_far", "refill_bid", "refill_ask", "weighted"):
            control[name] = _expand(board2["seq"], np.asarray(board2[name]), rows, 0)
        for name in ("ofi", "trade", "progress"):
            control[name] = _expand(board5["seq"], np.asarray(board5[name]), rows, 0)
        control["signals"] = {identifier: values[key][indices] for identifier, values in directions.items() if identifier.startswith("F")}
        result[key] = control
    return result


def _proposal(params: dict, control: dict, index: int, selected: str) -> tuple[str, str]:
    """機能: 観測済み相場状態から次に使う手法と理由を機械的に決める。

    引数: params (dict) は固定条件、control (dict) は相場状態、index (int) は当該判断点、selected (str) は現行手法。
    返り値: 提案する手法IDと日本語理由 (tuple[str,str])。
    """
    kind, er = params["kind"], control["efficiency"][index]
    current = {name: values[index] for name, values in control["signals"].items()}
    if kind in ("efficiency", "sticky"):
        if er >= params["high"]:
            return params["trend"], "過去の純変化が往復幅に比べて大きく、方向追随を選択"
        if er <= params["low"]:
            return params["range"], "過去の往復が多く、吸収またはフロー転換を選択"
        if kind == "sticky":
            return selected, "境界の中間帯では直前系統を維持"
    elif kind == "agreement":
        own, other = control["own_ema"][index], control["peer_ema"][index]
        if own != 0 and own == other and er >= params["high"]:
            return params["trend"], "自銘柄と60秒遅延した相手の流れが一致"
        if er <= params["low"]:
            return params["range"], "低効率の帯内では突破失敗を選択"
    elif kind == "flow":
        if current[params["absorption"]] != 0:
            return params["absorption"], "強いフローが価格へ伝わらず短期反転"
        if current[params["persistent"]] != 0:
            return params["persistent"], "同方向のOFI・推定売買・価格が持続"
    elif kind == "shock":
        if abs(control["shock"][index]) >= params["shock_atr"]:
            if control["depth_ratio"][index] >= params["recovered"]:
                return params["recover"], "直前衝撃後に最良数量が回復"
            if control["depth_ratio"][index] <= params["depleted"]:
                return params["continue"], "直前衝撃後も最良数量が不足"
        if er >= params["high"]:
            return params["trend"], "衝撃状態ではなく流れの効率が高い"
    elif kind == "distance":
        bid, ask = control["refill_bid"][index], control["refill_ask"][index]
        refill = (bid - ask) / (bid + ask) if bid + ask > 0 else 0
        if abs(refill) >= params["refill"] and np.sign(refill) == control["short_change"][index]:
            return params["wall"], "同価格の補充側を背に価格が反発"
        near, far = control["pressure_near"][index], control["pressure_far"][index]
        flow_near, flow_far = control["dflow_near"][index], control["dflow_far"][index]
        if abs(near) >= params["pressure"] and abs(far) >= params["pressure"] and np.sign(near) == np.sign(far):
            return params["near"], "近い板と遠い板の圧力が一致"
        if abs(flow_far) >= params["flow"] and abs(flow_near) < params["flow"]:
            return params["far"], "遠い板の変化が近い板に先行"
    elif kind == "clock":
        if control["age_minutes"][index] < params["opening_minutes"]:
            return params["opening"], "セッション開始90分内は短いEMAで方向形成を追う"
        if 0 <= control["us_minutes"][index] < params["us_minutes"]:
            if er >= params["us_efficiency"]:
                return params["us_trend"], "米国開始後60分は高安突破を選択"
            return params["us_range"], "米国開始後60分でも効率が低ければ吸収を選択"
        if er >= params["high"]:
            return params["trend"], "通常時間で効率が高く、三系統多数決を選択"
    elif kind == "strength":
        trade = control["trade"][index]
        absorption = max(0.0, params["absorption_progress"] - np.sign(trade) * control["progress"][index]) / params["absorption_progress"]
        scores = [er / params["er_scale"], abs(control["ofi"][index]) / params["ofi_scale"],
                  absorption * abs(trade) / params["trade_scale"], abs(control["weighted"][index]) / params["micro_scale"]]
        eligible = [(min(params["score_cap"], float(score)), -i, identifier)
                    for i, (identifier, score) in enumerate(zip(params["choices"], scores))
                    if current[identifier] != 0 and np.isfinite(score) and score >= 1.0]
        if eligible:
            _, _, identifier = max(eligible)
            return identifier, "現在方向があり、固定基準に対する根拠強度が最大"
    elif kind == "market":
        # 共通売買候補F52と異なるF53は、吸収後の新しい方向である。
        turn, pressure = current[params["turn"]], current[params["pressure"]]
        if turn != 0 and turn != pressure:
            return params["turn"], "吸収反転を他市場も裏付けたため転換を優先"
        if pressure != 0 and turn == pressure:
            return params["pressure"], "両市場で売買・補充枯渇・価格応答が一致"
        if er >= params["high"]:
            return params["trend"], "共通板圧力の確証がなくても、効率の高い価格方向を利用"
        if er <= params["low"]:
            return params["range"], "共通板圧力が弱く低効率のためフロー転換を利用"
    return params["middle"], "決定的な局面条件がなく、最良板と直近価格を利用"


def _select(spec: dict, ready: dict, control: dict, base: dict) -> tuple[np.ndarray, list[dict]]:
    """機能: 継続確認と滞在時間を守って手法を選び、原本各行の方向へ展開する。

    引数: spec (dict)、ready (dict)、control (dict)、base (dict[str,ndarray]) は一つの区間の基礎方向。
    返り値: 機械的方向と全判断点の選択記録 (tuple[ndarray[int8],list[dict]])。
    """
    params = spec["params"]
    selected = params["middle"]
    pending, confirmations = selected, 0
    last_change, last_check = -np.inf, -np.inf
    chosen, events = [], []
    for i, (row, stamp, seq) in enumerate(zip(control["indices"], control["time_s"], control["seq"])):
        proposal, reason = _proposal(params, control, i, selected)
        if stamp - last_check > 90:
            pending, confirmations = selected, 0
        if proposal == selected:
            pending, confirmations = selected, 0
            state = "維持"
        else:
            confirmations = confirmations + 1 if proposal == pending else 1
            pending = proposal
            enough_time = stamp - last_change >= params["hold_minutes"] * 60
            enough_confirmations = confirmations >= params["confirm"]
            if enough_time and enough_confirmations:
                selected, last_change = proposal, float(stamp)
                state = "切替"
                pending, confirmations = selected, 0
            else:
                state = "継続確認待ち" if not enough_confirmations else "最低滞在時間待ち"
        chosen.append(selected)
        events.append(dict(selector_id=spec["id"], session=ready["session"], symbol=ready["symbol"],
                           time_s=float(stamp), timestamp=datetime.fromtimestamp(float(stamp), ZoneInfo("Asia/Tokyo")).isoformat(),
                           seq=int(seq), row_index=int(row), selected_signal_id=selected, proposed_signal_id=proposal,
                           reason=reason, state=state, confirmations=confirmations,
                           direction_at_selection=int(base[selected][row]),
                           efficiency=float(control["efficiency"][i]) if np.isfinite(control["efficiency"][i]) else None))
        last_check = float(stamp)
    # ----------------------------------------
    # 系統選択だけは毎分で固定し、その系統の基礎信号は各原本行で更新する。
    result = np.zeros(len(ready["seq"]), dtype=np.int8)
    decisions = np.searchsorted(control["indices"], np.arange(len(result)), side="right") - 1
    have = decisions >= 0
    if chosen:
        chosen_array = np.asarray(chosen)
        per_row = np.full(len(result), "", dtype="U3")
        per_row[have] = chosen_array[decisions[have]]
        for identifier in set(chosen):
            mask = per_row == identifier
            result[mask] = base[identifier][mask]
    assert np.isin(result, [-1, 0, 1]).all()
    return result, events


def build_all(inputs: dict, features: dict, directions: dict) -> tuple[list[dict], dict, list[dict]]:
    """機能: 10種類の選択器を因果的に適用し、方向と選択記録を返す。

    引数: inputs/features (dict) は (セッション,銘柄) 別入力、directions (dict) は基礎手法ID別の同キー方向列。
    返り値: 固定仕様、選択器ID別方向、全選択記録 (tuple[list[dict],dict,list[dict]])。
    注意: 返済・反転の実施は共通管理の仕様に従う。選択変更そのものは強制返済注文ではない。
    """
    specs = catalog()
    controls = _controls(inputs, features, directions)
    result, events = {}, []
    for spec in specs:
        result[spec["id"]] = {}
        for key, ready in inputs.items():
            base = {identifier: values[key] for identifier, values in directions.items() if identifier.startswith("F")}
            values, decisions = _select(spec, ready, controls[key], base)
            assert len(values) == len(ready["seq"])
            result[spec["id"]][key] = values
            events.extend(decisions)
    return specs, result, events


if __name__ == "__main__":
    target = OUT / "探索前の選択条件.json"
    fixed = dict(時刻=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 選択条件=catalog(),
                 固定根拠="相場状態と観測可能な売買仮説で固定。セッションの未来価格や利益順位から閾値を調整しない。",
                 責任範囲="実行するアルゴリズムは機械的な信号手法選択と共通注文管理の組合せ。手法選択の変更だけでは既存玉を強制返済しない。",
                 因果性="確定1分足は120秒遅延、解放済み板は原本seqで対応、相手銘柄は60秒追加遅延。各分最初の観測行で選択する。",
                 現在取得回数=0)
    target.write_text(json.dumps(fixed, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"選択仕様を固定しました: {len(catalog())}条件")
