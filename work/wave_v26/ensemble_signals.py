"""窓と相手遅延を分散した4基礎信号を、損益によらない合意規則で合成する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V25 = HERE.parent / "wave_v25"
_import = importlib.util.spec_from_file_location("v26_fixed_components", V25 / "discovery_signals.py")
COMPONENTS = importlib.util.module_from_spec(_import)
sys.modules[_import.name] = COMPONENTS
_import.loader.exec_module(COMPONENTS)
BASE_NAMES = ("F32", "D016", "D056", "P02")
MODES = (
    ("F32", "微価格方向の窓合意", "F32の120秒窓を3通りに分散し、反対票がなく必要票数が一致した方向だけを採る。"),
    ("D016", "フローと価格の不一致の合意", "両市場の板フローと価格応答が逆向きになるD016を、窓と相手遅延の9通りで確認する。"),
    ("D056", "蓄積フロー反転の合意", "長いフローに対して短いフローと価格が反転するD056を、窓と相手遅延の9通りで確認する。"),
    ("P02", "価格の短期反転の合意", "両市場で長短の価格方向が逆になり短期方向が揃うP02を、窓と相手遅延の9通りで確認する。"),
    ("two_agree", "4基礎のうち2基礎以上で合意", "4基礎のうち2つ以上が同方向になり、反対の基礎がない場合だけ採る。"),
    ("D016_first", "価格不一致を優先し微価格へ切替", "D016が有効なら優先し、中立ならF32へ切り替える。他の基礎が反対なら中立に戻す。"),
    ("D056_first", "フロー反転を優先し微価格へ切替", "D056が有効なら優先し、中立ならF32へ切り替える。他の基礎が反対なら中立に戻す。"),
    ("price_and_flow", "価格と板の合意を優先", "P02とD016またはD056の方向が一致すれば採り、成立しなければF32へ切り替える。反対の基礎があれば中立に戻す。"),
)
_COMPONENT_CACHE: dict = {}
_MODEL_CACHE: dict = {}
_VOTE_CACHE: dict = {}


def catalog() -> list[dict]:
    """機能: 損益を見る前に定めた96通りの合意・確認・合成規則を返す。

    引数: なし。返り値: id/name/family/description/params の一覧 (list[dict])。
    """
    output = []
    for multipliers in ((.8, 1., 1.2), (.5, 1., 2.)):
        for numerator in (2, 3):
            for confirmation in (0, 10, 30):
                for mode, name, description in MODES:
                    output.append(dict(id=f"E{len(output):03d}", name=f"{name}・{numerator}/3・{confirmation}秒確認",
                                       family=name, description=description,
                                       params=dict(mode=mode, window_multipliers=list(multipliers),
                                                   required_fraction=numerator / 3, confirmation_seconds=confirmation,
                                                   clock_multiplier=1., peer_multiplier=1.)))
    return output


def uses_peer(spec: dict) -> bool:
    """機能: 構造上、相手銘柄を判断に利用する条件かを返す。

    引数: spec (dict) は基準または診断仕様。返り値: 利用する場合 True (bool)。
    """
    return spec["params"]["mode"] != "F32"


def neighbor_specs(spec: dict) -> list[dict]:
    """機能: 全窓・全相手遅延・連続確認秒を各±20%にする事前固定の6診断を返す。

    引数: spec (dict) は固定カタログ1件。
    返り値: diagnostic_category/applied/skip_reasonを含む診断仕様 (list[dict])。
    注意: 構造上使わないpeerや0秒確認はapplied=False。データ上の方向不変とは区別する。
    """
    output = []
    for category, parameter in (("clock", "clock_multiplier"), ("peer", "peer_multiplier"), ("confirmation", "confirmation_seconds")):
        for label, factor in (("M20", .8), ("P20", 1.2)):
            params = dict(spec["params"])
            params[parameter] *= factor
            applied = category != "peer" or uses_peer(spec)
            reason = "" if applied else "F32単独は相手市場を判断に使わない"
            if category == "confirmation" and spec["params"][parameter] == 0:
                applied, reason = False, "0秒確認を倍率変更しても確認秒数は同じ"
            output.append(dict(spec, id=f"{spec['id']}_{category.upper()}_{label}", params=params,
                               diagnostic_parent=spec["id"], diagnostic_category=category, applied=applied, skip_reason=reason,
                               description=spec["description"] + f" {category}を{factor:.1f}倍にする一律反証。"))
    return output


def clear_cache() -> None:
    """機能: 切断・将来改変監査の前に全ての特徴・投票キャッシュを解除する。

    引数: なし。返り値: なし (None)。
    """
    _COMPONENT_CACHE.clear()
    _MODEL_CACHE.clear()
    _VOTE_CACHE.clear()
    COMPONENTS.clear_cache()


def design() -> dict:
    """機能: 96条件、未使用変数の扱い、機械的な選択順を保存用に明示する。

    引数: なし。返り値: 損益に依存しない完全な設計仕様 (dict)。
    """
    return dict(
        目的="単一の時計窓や相手遅延への依存を複数条件の合意で減らせるかを反証する。複数票は独立標本ではなく、合意だけで収益や有意性は保証しない。",
        条件数=96, 条件=catalog(),
        窓集合=[[.8, 1., 1.2], [.5, 1., 2.]],
        F32="元120秒の集計窓×3倍率。元の微価格閾値0.06、価格進行確認、開始20分を維持。相手市場なし。",
        D016="元60秒の板集計窓×3倍率、相手60秒追加遅延×3倍率を独立に組み合わせる9票。OFI閾値0.03、逆向き価格閾値0.03ATR、OFI方向の60秒進行上限0.35ATRは固定。",
        D056="元60秒の板集計窓×3倍率、相手60秒追加遅延×3倍率の9票。過去フローは集計窓の3倍、比較時点も集計窓だけ遅らせる。短いフローと価格が過去フローと逆で、相手が逆方向でなければ成立。",
        P02="両市場で集計窓の価格符号と短い価格窓の符号が逆、かつ両市場の短い価格符号が一致。集計窓と相手遅延の9票。OFIや数量を入口・撤回へ使わず、価格だけで撤回する。板イベント由来の観測時刻は残る。",
        短期価格窓="元30秒に集計窓と同じ倍率を掛ける。相手側も同じ集計窓・短期価格窓を使用する。",
        票の単位="D016/D056/P02は、各変形の元の120秒保持・撤回を適用した後の方向を1票とする。F32は保持しない元方向が1票。全て同じ自市場原本seqへ後方展開する。",
        基礎合意="F32は2/3または3/3、残りは6/9または9/9。反対票が1つでもあれば中立。中立票は賛成に数えない。",
        合成規則=[dict(mode=mode, name=name, rule=rule) for mode, name, rule in MODES],
        合成の反対基礎="単独4方式では指定基礎以外を判断に使わない。複合4方式では4基礎のいずれかが採用方向の反対なら中立。優先元が中立なら固定した次候補へ移る。損益や事後の相場分類で切替先を変えない。",
        連続確認="合成後の方向が同じまま0/10/30秒続いた時に有効化する。原本行数ではなくCurrentPriceTimeの経過秒を使う。同値時刻の行数では進まない。中立・逆向きで確認を再開始し、隣接原本時刻の間隔が120秒超でも再開始。",
        固定時間="方向保持TTL120秒・特徴最大観測間隔120秒・開始20分待機は倍率を掛けない。連続確認は開始20分待機を適用した後に開始する。",
        丸め="集計窓、短期価格窓、相手遅延はfloor(秒+0.5)で整数秒へ四捨五入し最低1秒。連続確認秒は数値のまま経過時間と比較する。",
        近傍反証="clock_multiplier±20%は集計・短期価格・D056過去窓と参照差へ一律適用。peer_multiplier±20%は全相手遅延へ独立適用。confirmation_seconds±20%も記録。TTLや開始待機は不変。",
        重複="全入力方向をSHA256で数える。構造上不使用（F32単独peer、0秒確認）と、有効な変形でも今回のデータで方向が不変になる場合を分けて記録する。",
        データ限界="過去の既知期間のみ。CurrentPriceTimeは受信時刻ではなく、二市場の実到着順は復元できない。特徴素材は次の異時刻群の先頭で解放し、自銘柄seqと相手時刻＋遅延の後方参照を守る。",
        禁止="原本とv25凍結コードの変更、現在API取得、新しい売買損益の計算・閲覧、過去損益を用いた切替。")


def freeze_design() -> None:
    """機能: 実装・検証前に固定設計を保存し、既存固定と違えば停止する。

    引数: なし。返り値: なし (None)。
    """
    HERE.mkdir(exist_ok=True)
    payload = design()
    destination = HERE / "ensemble_design_fixed.json"
    if destination.exists():
        old = json.loads(destination.read_text(encoding="utf-8"))
        if old["仕様"] != payload:
            raise ValueError("固定した設計と一致しません")
    else:
        destination.write_text(json.dumps(dict(固定日時=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 新損益参照=False, 仕様=payload), ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 第2反復の合意方向設計", "", "96条件を損益計算前に固定する。基礎はF32、D016、D056、価格だけのP02。時間窓を変えても判断が揃う場面を採るが、似た計算を重ねた票を独立証拠とは数えない。", "",
             "狭い3倍率〔0.8・1・1.2〕または広い3倍率〔0.5・1・2〕で窓を変える。F32は3票。残りは集計窓と相手遅延を独立に動かして9票。2/3以上または全票一致が必要で、反対票があれば中立。短い価格窓30秒も集計窓と同率にする。保持期限120秒は固定。", "",
             "## 8つの機械的な採用方法", ""]
    lines += [f"- {name}：{rule}" for _, name, rule in MODES]
    lines += ["", "## 連続確認と因果性", "", payload["連続確認"], "", payload["票の単位"], "", payload["固定時間"], "", payload["丸め"], "", payload["データ限界"], "",
              "## 事前固定の反証", "", payload["近傍反証"], "", payload["重複"], "", "価格P02にも板イベント由来の観測時刻が残る。板数量・OFIを使わない比較であり、時計足だけの比較ではない。各基礎の売買を後から選別せず、同じ行までに利用可能な方向から合成する。", "", payload["禁止"]]
    (HERE / "ensemble_design.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seconds(value: float) -> int:
    """機能: 固定規則で時間窓と遅延を整数秒へ丸める。

    引数: value (float) は正の秒数。返り値: 四捨五入した1秒以上の値 (int)。
    """
    return max(1, int(np.floor(value + .5)))


def _identity(inputs: dict, features: dict) -> tuple:
    """機能: 入力の同一性と切断終端をキャッシュ識別子へまとめる。

    引数: inputs/features (dict)。返り値: 全入力の識別子 (tuple)。
    注意: 同じ配列を直接変更する監査では、明示的に clear_cache を呼ぶ。
    """
    return tuple((key, id(ready), id(features[key]), id(ready["atr"]), len(ready["seq"]),
                  int(ready["seq"][-1]), float(ready["time_s"][-1])) for key, ready in sorted(inputs.items()))


def _model(ready: dict, frame, seconds: int, short_seconds: int) -> dict:
    """機能: 板の公開済み特徴と因果ATRだけから必要な窓特徴を作る。

    引数: ready (dict)、frame (DataFrame)、seconds/short_seconds (int) は集計と短期価格の秒数。
    返り値: 板モデルと短期価格応答 (dict)。足ファイルやROOTは参照しない。
    """
    key = (id(ready), id(frame), id(ready["atr"]), len(ready["seq"]), int(ready["seq"][-1]), seconds, short_seconds)
    if key not in _MODEL_CACHE:
        model = dict(COMPONENTS.LEGACY._board(ready, frame, seconds))
        prior = COMPONENTS._asof(model["time_s"], model["mid"], model["time_s"] - short_seconds, np.nan)
        model["price_short"] = (model["mid"] - prior) / model["atr"]
        _MODEL_CACHE[key] = model
    return _MODEL_CACHE[key]


def _price_candidate(own: dict, peer: dict) -> tuple[np.ndarray, np.ndarray]:
    """機能: P02の価格だけの入口と撤回を、元定義どおりに作る。

    引数: own/peer (dict) は自市場・遅延相手の窓別価格特徴。
    返り値: 入口方向と価格による撤回方向 (tuple[ndarray[int8],ndarray[int8]])。
    """
    short = COMPONENTS._sign(own["price_short"], .03)
    long = COMPONENTS._sign(own["progress"], .03)
    peer_short = COMPONENTS._sign(peer["price_short"], .03)
    peer_long = COMPONENTS._sign(peer["progress"], .03)
    good = (short != 0) & (long == -short) & (short == peer_short) & (peer_long == -peer_short)
    candidate = np.where(good, short, 0).astype(np.int8)
    veto = np.where(long == short, short, 0).astype(np.int8)
    return candidate, veto


def _components(inputs: dict, features: dict, params: dict) -> dict:
    """機能: 各窓と相手遅延の基礎方向を、原本より小さい解放イベント列で保存する。

    引数: inputs/features/params (dict) は入力と固定合意設定。
    返り値: 各入力の公開seqと4基礎の票行列を持つ辞書 (dict)。
    注意: 自市場特徴へ相手特徴を遅延対応してから、各変形の保持・撤回を行う。
    """
    multipliers = tuple(params["window_multipliers"])
    key = (_identity(inputs, features), multipliers, params["clock_multiplier"], params["peer_multiplier"])
    if key in _COMPONENT_CACHE:
        return _COMPONENT_CACHE[key]
    original_d = {item["id"]: item for item in COMPONENTS.catalog()}
    original_f = next(item for item in COMPONENTS.LEGACY.catalog() if item["id"] == "F32")
    result = {item: {name: [] for name in BASE_NAMES} for item in inputs}
    for multiplier in multipliers:
        window = _seconds(60 * multiplier * params["clock_multiplier"])
        short_window = _seconds(30 * multiplier * params["clock_multiplier"])
        f_window = _seconds(120 * multiplier * params["clock_multiplier"])
        models = {item: _model(ready, features[item], window, short_window) for item, ready in inputs.items()}
        slow = {item: _model(ready, features[item], window * 3, short_window * 3) for item, ready in inputs.items()}
        for item, ready in inputs.items():
            model, f_direction = COMPONENTS.LEGACY._board_signal(dict(original_f["params"], seconds=f_window), ready, features[item])
            np.testing.assert_array_equal(model["seq"], models[item]["seq"])
            result[item]["seq"] = model["seq"]
            result[item]["time_s"] = model["time_s"]
            result[item]["F32"].append(f_direction)
        for peer_multiplier in multipliers:
            delay = _seconds(60 * peer_multiplier * params["peer_multiplier"])
            for item, ready in inputs.items():
                peer_key = (item[0], "TOPIX" if item[1] == "NK225" else "NK225")
                if peer_key not in models:
                    raise ValueError("同じセッションの相手市場入力が必要です")
                own = models[item]
                peer = COMPONENTS._peer(own, models[peer_key], ("ofi", "progress", "price_short"), delay)
                short_side = COMPONENTS._sign(own["price_short"], .03)
                flow_side = COMPONENTS._sign(own["ofi"], .03)
                flow_veto = np.where(flow_side == short_side, short_side, 0).astype(np.int8)
                for name in ("D016", "D056"):
                    condition = dict(original_d[name]["params"], seconds=window)
                    candidate = COMPONENTS._candidate(condition, ready, own, peer, slow[item], own)
                    direction = COMPONENTS._hold(candidate, flow_veto, own["time_s"], 120, 120)
                    result[item][name].append(direction)
                candidate, price_veto = _price_candidate(own, peer)
                result[item]["P02"].append(COMPONENTS._hold(candidate, price_veto, own["time_s"], 120, 120))
    for item in result:
        for name in BASE_NAMES:
            result[item][name] = np.stack(result[item][name]).astype(np.int8)
    _COMPONENT_CACHE[key] = result
    return result


def _vote(values: np.ndarray, fraction: float) -> np.ndarray:
    """機能: 必要数の同方向票があり反対票が一つもない時だけ採る。

    引数: values (ndarray[int8]) は票×イベント、fraction (float) は必要同意率。
    返り値: 合意後の方向 (ndarray[int8])。
    """
    required = int(np.ceil(len(values) * fraction - 1e-9))
    positive, negative = (values > 0).sum(axis=0), (values < 0).sum(axis=0)
    return np.where((positive >= required) & (negative == 0), 1,
                    np.where((negative >= required) & (positive == 0), -1, 0)).astype(np.int8)


def _basis(inputs: dict, features: dict, params: dict) -> dict:
    """機能: 4基礎それぞれの投票をまとめ、合成前の方向を共用する。

    引数: inputs/features/params (dict)。返り値: 各入力の基礎4方向 (dict)。
    """
    key = (_identity(inputs, features), tuple(params["window_multipliers"]), params["clock_multiplier"],
           params["peer_multiplier"], params["required_fraction"])
    if key not in _VOTE_CACHE:
        components = _components(inputs, features, params)
        _VOTE_CACHE[key] = {item: dict(seq=part["seq"], values=np.stack([_vote(part[name], params["required_fraction"]) for name in BASE_NAMES]))
                            for item, part in components.items()}
    return _VOTE_CACHE[key]


def _combine(values: np.ndarray, mode: str) -> np.ndarray:
    """機能: 同時点の4基礎方向から、固定した8方式のいずれかで採用方向を作る。

    引数: values (ndarray[int8]) は基礎4種×イベント、mode (str) は合成方式。
    返り値: 合成方向 (ndarray[int8])。
    """
    if mode in BASE_NAMES:
        return values[BASE_NAMES.index(mode)].copy()
    positive, negative = (values > 0).sum(axis=0), (values < 0).sum(axis=0)
    if mode == "two_agree":
        return np.where((positive >= 2) & (negative == 0), 1,
                        np.where((negative >= 2) & (positive == 0), -1, 0)).astype(np.int8)
    if mode in ("D016_first", "D056_first"):
        preferred = values[1 if mode == "D016_first" else 2]
        chosen = np.where(preferred != 0, preferred, values[0]).astype(np.int8)
    elif mode == "price_and_flow":
        aligned = (values[3] != 0) & ((values[3] == values[1]) | (values[3] == values[2]))
        chosen = np.where(aligned, values[3], values[0]).astype(np.int8)
    else:
        raise ValueError(f"未定義の合成方式です: {mode}")
    chosen[((chosen > 0) & (negative > 0)) | ((chosen < 0) & (positive > 0))] = 0
    return chosen


def _confirm(candidate: np.ndarray, times: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 同方向の経過秒だけを確認し、同値時刻の原本行数を数えない。

    引数: candidate (ndarray[int8])、times (ndarray)、seconds (float) は必要継続秒数。
    返り値: 継続を確認した方向 (ndarray[int8])。
    """
    if len(candidate) == 0:
        return candidate.copy()
    begins = np.r_[True, (candidate[1:] != candidate[:-1]) | (np.diff(times) > 120)]
    origins = np.maximum.accumulate(np.where(begins, np.arange(len(candidate)), 0))
    confirmed = times - times[origins] >= seconds
    return np.where(confirmed, candidate, 0).astype(np.int8)


def build(spec: dict, inputs: dict, features: dict) -> dict:
    """機能: 固定した合意条件を、当時公開済みの板情報だけから生成する。

    引数: spec (dict) はcatalogまたはneighbor_specsの1件、inputs/features (dict) は両市場の入力。
    返り値: 原本と同じキー・長さの方向列 (dict[tuple[str,str],ndarray[int8]])。
    注意: 新規発注は別の注文管理器で次行以降へ送る。ここでは売買損益を計算しない。
    """
    fixed = {item["id"]: item for item in catalog()}
    expected = fixed.get(spec.get("id"))
    if expected is None and spec.get("diagnostic_parent") in fixed:
        expected = {item["id"]: item for item in neighbor_specs(fixed[spec["diagnostic_parent"]])}.get(spec.get("id"))
    if expected is None or expected["params"] != spec.get("params"):
        raise ValueError("損益前に固定した合成規則または一律近傍と一致しません")
    params, output = spec["params"], {}
    basis = _basis(inputs, features, params)
    for key, ready in inputs.items():
        voted = _combine(basis[key]["values"], params["mode"])
        direction = COMPONENTS._asof(basis[key]["seq"], voted, ready["seq"]).astype(np.int8)
        direction[ready["time_s"] < ready["start"] + 1200] = 0
        direction[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
        direction = _confirm(direction, ready["time_s"], params["confirmation_seconds"])
        if len(direction) != len(ready["seq"]) or not np.isin(direction, [-1, 0, 1]).all():
            raise ValueError("合成方向の長さまたは値が不正です")
        output[key] = direction
    return output


def direction_hash(directions: dict) -> str:
    """機能: 全入力の方向列を比較し、重複を数えるためのハッシュを返す。

    引数: directions (dict) は原本方向。返り値: SHA256 の十六進文字列 (str)。
    """
    value = hashlib.sha256()
    for key, direction in sorted(directions.items()):
        value.update(repr(key).encode("utf-8"))
        value.update(np.asarray(direction.shape, dtype=np.int64).tobytes())
        value.update(np.asarray(direction, dtype=np.int8).tobytes())
    return value.hexdigest()


if __name__ == "__main__":
    freeze_design()
    print(f"{len(catalog())}条件の固定設計を確認しました。売買損益は計算しません。")

