"""凍結済み方向条件の近傍・相手情報対照・過去不変性を損益と独立に診断する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
from threading import RLock

import numpy as np


sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("v25_diagnostic_discovery", OUT / "discovery_signals.py")
NEW = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = NEW
_spec.loader.exec_module(NEW)
OLD = NEW.LEGACY
_LOCK = RLock()
_LAST: dict = {}
_PEER_KINDS = {"dual", "leader", "ofi_peer", "board_leader", "market_consensus", "market_absorption"}
_WINDOW_KEYS = {"fast", "slow", "window", "short", "long", "fast_return", "seconds", "reference_seconds", "history_seconds", "events", "ttl"}
_LEVEL_KEYS = {"gap", "slope", "buffer", "threshold", "er_trend", "er_range", "deviation", "distance", "max_er", "ratio", "drift", "short_threshold", "long_threshold", "trade_threshold", "max_progress", "refill_ratio", "residual", "prior_threshold", "impact_ratio", "min_progress", "shock_atr", "depth_ratio", "supply_threshold"}


def last_diagnostics() -> dict:
    """機能: 直前の生成で採用・除外・未対応となった診断の記録を返す。

    引数: なし。
    返り値: 入力条件、基準ハッシュ、各変種の状態を持つ辞書の複製 (dict)。
    """
    with _LOCK:
        return deepcopy(_LAST)


def direction_hash(directions: dict) -> str:
    """機能: 全入力の方向とキーを順序によらない形でハッシュ化する。

    引数: directions (dict) は (セッション,銘柄) ごとの方向列。
    返り値: SHA256 の十六進文字列 (str)。
    """
    digest = hashlib.sha256()
    for key in sorted(directions):
        array = np.asarray(directions[key], dtype=np.int8)
        digest.update(repr(key).encode("utf-8"))
        digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
        digest.update(array.tobytes())
    return digest.hexdigest()


def _canonical(spec: dict) -> tuple[str | None, dict | None]:
    """機能: 固定カタログ内の基準条件を特定し、改変済み入力を拒否する。

    引数: spec (dict) は診断する基準仕様。
    返り値: 系統名と正規仕様、未対応なら各 None (tuple[str|None,dict|None])。
    """
    for source, module in (("D", NEW), ("F", OLD)):
        fixed = {item["id"]: item for item in module.catalog()}
        if spec.get("id") in fixed:
            canonical = fixed[spec["id"]]
            if canonical["params"] != spec.get("params"):
                raise ValueError("診断の起点は凍結済みカタログと同じパラメータに限定します")
            return source, deepcopy(canonical)
    return None, None


def _old_neighbors(spec: dict) -> tuple[list[dict], list[dict]]:
    """機能: 旧条件が実際に使う閾値群と窓群を各 ±20% にする。

    引数: spec (dict) は旧固定条件。
    返り値: 診断仕様一覧と生成できない群の説明 (tuple[list[dict],list[dict]])。
    注意: 公開遅延、準備時間、整数投票数は変更しない。整数窓は四捨五入する。
    """
    params, result, skipped = spec["params"], [], []
    allowed = set(params)
    if params["kind"] == "shock_recover":
        allowed -= {"threshold", "seconds"}
    if params["kind"] == "event_clock":
        allowed -= {"seconds"}
    if params["kind"] == "regime" and not params["range"]:
        allowed -= {"er_range"}
    for label, keys, title in (("LEVEL", _LEVEL_KEYS, "方向閾値"), ("WINDOW", _WINDOW_KEYS, "集計・保持窓")):
        selected = sorted(allowed & keys)
        if not selected:
            skipped.append(dict(id=f"{spec['id']}_{label}", kind="neighbor", status="未生成", reason=f"{title}に変更可能な明示パラメータがない"))
            continue
        for suffix, factor in (("M20", .8), ("P20", 1.2)):
            changed = dict(params)
            for key in selected:
                changed[key] = max(1, int(np.floor(params[key] * factor + .5))) if key in _WINDOW_KEYS else params[key] * factor
            result.append(dict(spec, id=f"{spec['id']}_{label}_{suffix}", params=changed,
                               description=f"{title} {factor:.1f}倍。対象: {'、'.join(selected)}。公開遅延と注文管理は固定。",
                               diagnostic_parent=spec["id"], changed_parameters=selected))
    return result, skipped


def _definitions(source: str, spec: dict) -> tuple[list[dict], list[dict]]:
    """機能: 重複除外前の変種を、成績に関係なく一律に定義する。

    引数: source (str) は D/F、spec (dict) は正規条件。
    返り値: 変種の定義と未生成記録 (tuple[list[dict],list[dict]])。
    """
    if source == "D":
        neighbors, skipped = NEW.neighbor_specs(spec), []
    else:
        neighbors, skipped = _old_neighbors(spec)
    definitions = [dict(id=item["id"], kind="neighbor", description=item["description"], spec=item) for item in neighbors]
    for mode, title in (("no_peer", "相手特徴を中立化"), ("self_peer", "相手特徴を自銘柄の過去特徴へ置換")):
        definitions.append(dict(id=f"{spec['id']}_{mode.upper()}", kind=mode, spec=spec,
                                description=f"{title}。原本価格は変更せず、既定の相手遅延を維持する。"))
    return definitions, skipped


def _old_build(spec: dict, inputs: dict, features: dict) -> dict:
    """機能: 非公開の旧モジュールで診断仕様を一時登録して再生する。

    引数: spec/inputs/features (dict) は診断条件と市場入力。
    返り値: 全入力の方向列 (dict)。
    注意: 厳密な catalog 照合のため当プロセスの私有モジュールだけ一時置換し、finally で必ず復元する。
    """
    original = OLD.catalog
    fixed = original()
    try:
        OLD.catalog = lambda: fixed + [spec]
        return OLD.build(spec, inputs, features)
    finally:
        OLD.catalog = original


def _new_peer(spec: dict, inputs: dict, features: dict, mode: str) -> dict:
    """機能: 新条件の相手特徴だけを中立または同じ遅延の自己系列へ差し替える。

    引数: spec/inputs/features (dict)、mode (str) は no_peer/self_peer。
    返り値: 原本価格・自銘柄特徴を変えない全方向列 (dict)。
    注意: 自己置換はゲート除去ではなく、他市場情報なしの遅延自己確認である。
    """
    original = NEW._peer

    def replacement(own: dict, other: dict, names: tuple, delay: float) -> dict:
        """機能: 相手参照の境界だけを差し替える。

        引数: own/other (dict)、names (tuple)、delay (float) は既定の相手遅延。
        返り値: 当該自市場の公開時刻と同じ長さの特徴辞書 (dict)。
        """
        if mode == "self_peer":
            return original(own, own, names, delay)
        return {name: np.zeros(len(own["time_s"]), dtype=np.asarray(own[name]).dtype) for name in names}

    try:
        NEW._peer = replacement
        return NEW.build(spec, inputs, features)
    finally:
        NEW._peer = original


def _old_peer(spec: dict, inputs: dict, features: dict, mode: str) -> dict:
    """機能: 旧6機序の相手参照を、その他の計算を保って再構成する。

    引数: spec/inputs/features (dict)、mode (str) は real/no_peer/self_peer。
    返り値: 全入力の方向列 (dict)。
    注意: real は旧 build との一致監査用。先行銘柄条件の自分自身への参照は no_peer でも残す。
    """
    params, output = spec["params"], {}
    kind = params["kind"]
    if kind not in _PEER_KINDS:
        return OLD.build(spec, inputs, features)
    models = {key: OLD._bars(ready) for key, ready in inputs.items()}
    boards = {key: OLD._board_signal(params, ready, features[key]) for key, ready in inputs.items()} if kind not in ("dual", "leader") else {}
    for key, ready in inputs.items():
        model = models[key]
        external = (key[0], params["leader"]) if kind == "leader" else (key[0], OLD.SYMBOLS[1 - OLD.SYMBOLS.index(key[1])])
        peer_key = key if mode == "self_peer" else external
        neutral = mode == "no_peer" and external != key

        def delayed(peer_model: dict, values: np.ndarray) -> np.ndarray:
            """機能: 相手がない対照以外で、既定遅延の後方参照を実行する。

            引数: peer_model (dict)、values (ndarray) は公開済み相手値。
            返り値: 自銘柄の原本時刻へ展開した値 (ndarray)。
            """
            if neutral:
                return np.zeros(len(ready["time_s"]), dtype=np.asarray(values).dtype)
            return OLD._expand(peer_model["time_s"] + params["peer_delay"], values, ready["time_s"])

        if kind == "dual":
            peer = models[peer_key]
            own_direction = OLD._ema(model) if params["mode"] == "ema" else OLD._signed(model["close"].diff(30) / model["atr"], .75)
            peer_direction = OLD._ema(peer) if params["mode"] == "ema" else OLD._signed(peer["close"].diff(30) / peer["atr"], .75)
            own = OLD._expand(model["time_s"], own_direction, ready["time_s"])
            other = delayed(peer, peer_direction)
            direction = np.where(own == other, own, 0).astype(np.int8)
        elif kind == "leader":
            leader = models[peer_key]
            lead = delayed(leader, OLD._ema(leader))
            own = OLD._expand(model["time_s"], OLD._signed(model["close"].diff(3)), ready["time_s"])
            direction = np.where(own == lead, lead, 0).astype(np.int8)
        else:
            board, own_values = boards[key]
            peer, peer_values = boards[peer_key]
            own = OLD._expand(board["seq"], own_values, ready["seq"])
            other = delayed(peer, peer_values)
            direction = np.where(own == other, own, 0).astype(np.int8)
            if kind == "board_leader":
                own_price = OLD._expand(model["time_s"], OLD._signed(model["close"].diff(3)), ready["time_s"])
                direction = np.where(own_price == other, other, 0).astype(np.int8)
            elif kind == "market_absorption":
                own_absorbed = OLD._expand(board["seq"], board["absorbed_direction"], ready["seq"])
                other_absorbed = delayed(peer, peer["absorbed_direction"])
                direction[(own_absorbed != 0) | (other_absorbed != 0)] = 0
                own_turn = (own_absorbed != 0) & ((own_absorbed == other_absorbed) | (own_absorbed == other))
                other_turn = (other_absorbed != 0) & (other_absorbed == own)
                direction[own_turn] = own_absorbed[own_turn]
                direction[other_turn] = other_absorbed[other_turn]
        direction[ready["time_s"] < ready["start"] + params["warmup_minutes"] * 60] = 0
        direction[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
        output[key] = np.asarray(direction, dtype=np.int8)
    return output


def _generate(source: str, definition: dict, inputs: dict, features: dict) -> dict:
    """機能: 定義した診断1件を再生し、必ず全入力と同じ長さにする。

    引数: source (str)、definition/inputs/features (dict) は系統・変種・入力。
    返り値: -1/0/1 の原本行方向 (dict)。
    """
    kind, spec = definition["kind"], definition["spec"]
    if kind == "neighbor" or kind == "baseline":
        result = NEW.build(spec, inputs, features) if source == "D" else _old_build(spec, inputs, features)
    else:
        result = _new_peer(spec, inputs, features, kind) if source == "D" else _old_peer(spec, inputs, features, kind)
    if set(result) != set(inputs):
        raise AssertionError("診断出力に入力キーの不足または余分があります")
    for key, ready in inputs.items():
        array = result[key]
        if array.dtype != np.int8 or len(array) != len(ready["seq"]) or not np.isin(array, [-1, 0, 1]).all():
            raise AssertionError(f"方向列の型・長さ・値が不正です: {key}")
    return result


def direction_variants(spec: dict, inputs: dict, features: dict) -> list[dict]:
    """機能: 一律の方向近傍と相手情報対照を作り、方向不変・重複を除いて返す。

    引数: spec (dict) は凍結済み D000〜D119/F00〜F53、inputs/features (dict) は全市場入力。
    返り値: id/description/directions/kind を持つ一覧 (list[dict])。
    注意: kind は neighbor/no_peer/self_peer。未対応の学習条件等は空一覧を返し理由を記録する。
          中立化で全停止になる結果も残すが、相手情報の有用性の証明とは扱わない。
          私有モジュールの一時置換はロック内だけで行い、ディスクには書き込まない。
    """
    global _LAST
    with _LOCK:
        source, canonical = _canonical(spec)
        _LAST = dict(id=spec.get("id"), input_count=len(inputs), records=[], supported=source is not None)
        if source is None:
            _LAST["records"].append(dict(id=spec.get("id"), status="未対応", reason="新Dおよび旧F00〜F53以外。学習条件・選択器は本診断で未実装。"))
            return []
        baseline = _generate(source, dict(kind="baseline", spec=canonical), inputs, features)
        baseline_hash = direction_hash(baseline)
        _LAST["baseline_hash"] = baseline_hash
        definitions, skipped = _definitions(source, canonical)
        _LAST["records"].extend(skipped)
        seen, output = {baseline_hash: "基準"}, []
        for definition in definitions:
            directions = _generate(source, definition, inputs, features)
            current_hash = direction_hash(directions)
            record = dict(id=definition["id"], kind=definition["kind"], hash=current_hash)
            record["changed_rows"] = sum(int(np.count_nonzero(directions[key] != baseline[key])) for key in inputs)
            record["active_rows"] = sum(int(np.count_nonzero(value)) for value in directions.values())
            if current_hash in seen:
                record.update(status="方向不変で除外" if current_hash == baseline_hash else "重複で除外", same_as=seen[current_hash])
            else:
                record["status"] = "生成"
                seen[current_hash] = definition["id"]
                output.append(dict(id=definition["id"], description=definition["description"], directions=directions, kind=definition["kind"]))
            _LAST["records"].append(record)
        _LAST["returned_count"] = len(output)
        return output


def _prefix_inputs(inputs: dict, features: dict, cutoff: float) -> tuple[dict, dict]:
    """機能: 同じ暦時刻で原本と解放済み特徴を切断する。

    引数: inputs/features (dict)、cutoff (float) はエポック秒。
    返り値: 原本列の型を保った入力と特徴の切断版 (tuple[dict,dict])。
    """
    shorter, frames = {}, {}
    for key, ready in inputs.items():
        length = len(ready["time_s"])
        count = int(np.searchsorted(ready["time_s"], cutoff, side="right"))
        if count == 0:
            raise ValueError("切断位置以前に両銘柄の観測が必要です")
        shorter[key] = {name: value[:count].copy() if isinstance(value, np.ndarray) and value.ndim > 0 and len(value) == length else value for name, value in ready.items()}
        frame = features[key]
        frames[key] = frame.loc[(frame.time_s <= shorter[key]["time_s"][-1]) & (frame.seq <= shorter[key]["seq"][-1])].copy()
    return shorter, frames


def prefix_checks(spec: dict, inputs: dict, features: dict, fractions: tuple = (.27, .63, .83), sessions: list | None = None, include_variants: bool = True) -> dict:
    """機能: 将来の原本・板を削除しても、以前の方向が全て同じか確認する。

    引数: spec/inputs/features (dict)、fractions (tuple) は期間内切断比率、sessions (list|None) は対象セッション、
          include_variants (bool) は近傍と相手対照も調べるか。未指定セッションは最初と最後。
    返り値: 基準・全変種・各切断・両銘柄の一致件数と不一致詳細 (dict)。
    注意: 無変化で除外された変種も検査する。完全に同一時刻の最後の原本行までを含む。
          各比較前に特徴キャッシュを破棄し、親の last_diagnostics 記録は変更しない。
    """
    with _LOCK:
        source, canonical = _canonical(spec)
        if source is None:
            return dict(id=spec.get("id"), supported=False, reason="この系統の方向生成は未対応")
        available = sorted({key[0] for key in inputs})
        chosen = sorted(set(sessions if sessions is not None else [available[0], available[-1]]))
        definitions = [dict(id=canonical["id"], kind="baseline", spec=canonical)]
        if include_variants:
            definitions.extend(_definitions(source, canonical)[0])
        result = dict(id=canonical["id"], supported=True, passed=True, comparisons=0, compared_rows=0, failures=[], cuts=[])
        for session in chosen:
            complete = {key: value for key, value in inputs.items() if key[0] == session}
            frames = {key: features[key] for key in complete}
            if len(complete) != 2:
                raise ValueError("同一セッションの両銘柄を指定してください")
            start = max(value["time_s"][0] for value in complete.values())
            end = min(value["time_s"][-1] for value in complete.values())
            NEW.clear_cache()
            full = {item["id"]: _generate(source, item, complete, frames) for item in definitions}
            for fraction in fractions:
                if not 0 < fraction < 1:
                    raise ValueError("切断比率は0超1未満です")
                cutoff = float(np.floor((start + (end - start) * fraction) / 60) * 60)
                shorter, short_frames = _prefix_inputs(complete, frames, cutoff)
                result["cuts"].append(dict(session=session, fraction=float(fraction), cutoff=cutoff))
                NEW.clear_cache()
                for item in definitions:
                    partial = _generate(source, item, shorter, short_frames)
                    for key, values in partial.items():
                        expected = full[item["id"]][key][:len(values)]
                        mismatch = np.flatnonzero(expected != values)
                        result["comparisons"] += 1
                        result["compared_rows"] += len(values)
                        if len(mismatch):
                            result["passed"] = False
                            row = int(mismatch[0])
                            result["failures"].append(dict(variant=item["id"], session=key[0], symbol=key[1], cutoff=cutoff,
                                                           count=len(mismatch), first_seq=int(shorter[key]["seq"][row])))
                NEW.clear_cache()
        NEW.clear_cache()
        return result
