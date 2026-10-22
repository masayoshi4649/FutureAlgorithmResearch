"""指定された4つの波を事後の要求適合診断として測り、方向と保有と損益を分ける。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V25 = HERE.parent / "wave_v25"
V27 = HERE.parent / "wave_v27"
V28 = HERE.parent / "wave_v28"
OLD = HERE.parent / "wave_v23"
JST = ZoneInfo("Asia/Tokyo")
EPISODES = (
    dict(id="W01", session="2026-09-21_Day", start="2026-09-21T10:45:00+09:00", end="2026-09-21T15:35:00+09:00", side=1, name="9/21デイ後半の上昇"),
    dict(id="W02", session="2026-09-22_Day", start="2026-09-22T09:20:00+09:00", end="2026-09-22T11:45:00+09:00", side=-1, name="9/22デイ前半の下落"),
    dict(id="W03", session="2026-09-23_Day", start="2026-09-23T09:05:00+09:00", end="2026-09-23T11:15:00+09:00", side=-1, name="9/23デイ前半の下落"),
    dict(id="W04", session="2026-09-22_Night", start="2026-09-23T00:40:00+09:00", end="2026-09-23T03:20:00+09:00", side=1, name="9/22ナイト深夜の上昇"),
)


def load_module(path: Path, name: str):
    """機能: 原本ソースを変更せず私有名で読み込む。

    引数: path (Path)、name (str)。返り値: 読み込んだモジュール (module)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def stamp(value: float) -> str:
    """機能: 記録時刻を日本時間の文字列へ整える。

    引数: value (float) はエポック秒。返り値: ISO形式の日本時間 (str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def digest(path: Path) -> str:
    """機能: 参照した固定仕様やソースを識別する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict:
    """機能: 波区間・計測方法・説明上の目安を、結果生成より前に保存する。

    引数: なし。返り値: 固定仕様 (dict)。既存と相違する場合は停止する。
    """
    rules = dict(
        目的="ユーザーが例示した4波への要求適合を事後に測る。既知の波を方向生成・エントリー・管理へ入力しない。",
        対象=list(EPISODES), 銘柄=["TOPIX", "NK225"],
        固定比較=["F32__G08", "D016__D065", "P02__D065", "H019__D273"],
        旧主案="H019__D273はv27凍結仕様とv27保存入口方向を使い、context=Noneで新エンジンを再生する。旧v23エンジンの全台帳・全行曲線と厳密一致を必須とする。",
        追加候補="事前固定した全84条件を --first-stage で追加する。一次合否と収益を使って間引かない。旧固定比較4条件を加え88条件704波区間。",
        二入力="実装元は二入力階層。入口はv30 directions/Hxxx.npz、保有管理はmainならv30 contexts/Hxxx.npz、ownならcontexts_own/Hxxx.npz、entryならNone。保存列を旧v28同ID/ID-1と照合する。",
        再生開始条件="--prepareは仕様固定のみ。実再生は一次反証結果または研究候補固定の明示と、対象となる全v30保存方向・必要contextの生成完了を要求する。",
        説明用目安="波と同方向のネット建玉が正である時間の合計20分以上。両建ての完全相殺だけでは達成としない。連続20分である必要はない。統計的有意性の判定ではない。",
        信号時間="CurrentPriceTimeで、各行の方向をその行から次行までの区間へ積分する。波区間との重なりだけを足す。同値時刻の行間は0秒。",
        管理方向時間="入口信号とは別に、実際に管理へ渡す主方向の正・逆・中立時間と変更点を保存する。context未指定時は入口方向と同じ。保有20分目安の定義は変えない。",
        保有時間="約定反映後の当該行在庫を次行の時刻まで維持したものとして積分する。次行で増減した在庫を前の時間帯へ遡及しない。正方向/逆方向のネット保有、各脚保有、枚数×分を分ける。",
        境界評価="開始・終了それぞれの時刻以前の最後の原本行を後方asofで選ぶ。cash＋net枚数×その行のlastを評価し、終点と始点の差を取る。前からの保有、区間内決済、未返済の損益を全て含む。",
        波時価差の意味="エピソード内に新規した玉だけの最終損益ではない。区間開始前から持つ玉の値動きも入る。実現差と含み差を別記する。",
        時間端点="時間積分は開始以上・終了未満。注文/返済一覧は開始以上・終了以下。境界評価は各境界時刻までの記録順の約定を反映した状態を用いる。",
        台帳="ordersは約定済み注文台帳であり、未約定注文一覧ではない。図示用に対象4セッションの全約定と全返済、方向の変更点を保存する。約定行と注文決定元行を区別する。",
        単位="TOPIXミニは1pt×1000円、NK225マイクロは1pt×10円。保有枚数は各管理器の設定どおり。費用0・指定価格約定の既定条件を変更しない。",
        データ限界="CurrentPriceTimeは受信時刻ではない。同値時刻内の原本順は保つが、経過秒と実際の受信順は完全には再現できない。",
        禁止="新規探索、数値やルールの変更、現在API取得、波区間を入力へ混入すること。")
    destination = HERE / "episode_audit_fixed.json"
    if destination.exists():
        fixed = json.loads(destination.read_text(encoding="utf-8"))
        if fixed["規則"] != rules or fixed["計測コードSHA256"] != digest(Path(__file__)):
            raise ValueError("事前固定した波診断の仕様と一致しません")
        for relative, expected in fixed["参照固定SHA256"].items():
            assert digest(HERE.parent / relative) == expected, relative
        return fixed
    checked = [V25 / "探索条件の固定.json", V27 / "探索条件の固定.json",
               V28 / "engine_context.py", HERE / "管理設計の固定.json", HERE / "context_comparison_fixed.json"]
    fixed = dict(固定日時=datetime.now(JST).isoformat(), 規則=rules, 結果生成前=True,
                 計測コードSHA256=digest(Path(__file__)),
                 参照固定SHA256={p.relative_to(HERE.parent).as_posix(): digest(p) for p in checked})
    destination.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
    return fixed


def methods(selected: Path | None, first_stage: Path | None = None) -> list[dict]:
    """機能: 固定比較3件・旧主案1件と、事前固定された全84固定条件だけを選ぶ。

    引数: selected (Path|None) は研究用固定候補、first_stage (Path|None) は完了した一次反証JSON。
    返り値: 方向仕様・管理仕様を持つ手法一覧 (list[dict])。
    """
    fixed = json.loads((V25 / "探索条件の固定.json").read_text(encoding="utf-8"))
    result = {}
    for signal_id, manager_id, source in (("F32", "G08", "既存板"), ("D016", "D065", "新規板"), ("P02", "D065", "価格P02")):
        signal = next(item for item in fixed["signals"] if item["id"] == ("D016" if signal_id == "P02" else signal_id))
        manager = next(item for item in fixed["managers"] if item["id"] == manager_id)
        identifier = signal_id + "__" + manager_id
        result[identifier] = dict(id=identifier, name=identifier, signal=dict(signal, 実装元=source), manager=manager)
    older = json.loads((V27 / "探索条件の固定.json").read_text(encoding="utf-8"))
    signal = next(item for item in older["signals"] if item["id"] == "H019")
    manager = next(item for item in older["managers"] if item["id"] == "D273")
    result["H019__D273"] = dict(id="H019__D273", name="第３反復の凍結主案", signal=dict(signal, 実装元="v27固定階層"), manager=manager)
    if selected is not None:
        raise ValueError("全84固定診断のため選抜候補だけへの限定は禁止")
    if first_stage is not None:
        tested = json.loads(first_stage.read_text(encoding="utf-8"))
        new_fixed = json.loads((HERE / "探索条件の固定.json").read_text(encoding="utf-8"))
        identifiers = sorted(s["id"] + "__" + m["id"] for s in new_fixed["signals"] for m in new_fixed["managers"])
        assert len(identifiers) == len(set(identifiers)) == 84
        assert {item["candidate"]["id"] for item in tested} == set(identifiers)
        extension_rule = dict(元の波診断固定SHA256=digest(HERE / "episode_audit_fixed.json"),
                              一次反証元=str(first_stage.resolve()), 一次反証SHA256=digest(first_stage),
                              追加対象=identifiers, 選び方="固定全84条件。一次合否・損益・波の結果で対象を選別しない。",
                              波区間と判定基準変更=False)
        destination = HERE / "episode_audit_first_stage_fixed.json"
        if destination.exists():
            assert json.loads(destination.read_text(encoding="utf-8"))["規則"] == extension_rule
        else:
            destination.write_text(json.dumps(dict(固定日時=datetime.now(JST).isoformat(), 規則=extension_rule), ensure_ascii=False, indent=2), encoding="utf-8")
        for signal in new_fixed["signals"]:
            for manager in new_fixed["managers"]:
                identifier = signal["id"] + "__" + manager["id"]
                result[identifier] = dict(id=identifier, name=signal["name"] + "／" + manager["name"],
                                         signal=dict(signal, 実装元="二入力階層"), manager=manager,
                                         用途="全84を一次合否に関係なく指定波へ照合")
    return list(result.values())


def directions(method: dict, inputs: dict, features: dict, signals) -> dict:
    """機能: 波区間を参照せず、固定手法のセッション全体の方向を得る。

    引数: method/inputs/features (dict)、signals (module) は固定済み方向モジュール。
    返り値: 原本行方向 (dict)。
    """
    identifier, source = method["signal"]["id"], method["signal"]["実装元"]
    if source in ("二入力階層", "v27固定階層"):
        root = HERE if source == "二入力階層" else V27
        path = root / "directions" / f"{identifier}.npz"
        if path.exists():
            with np.load(path) as archive:
                output = {key: archive["|".join(key)] for key in inputs}
            if source == "二入力階層":
                with np.load(V27 / "directions" / f"{identifier}.npz") as original:
                    for key in inputs:
                        np.testing.assert_array_equal(output[key], original["|".join(key)])
            return output
        raise FileNotFoundError("階層信号の保存方向が必要です。先に全探索を完了してください。")
    if source != "価格P02":
        with np.load(V25 / "directions" / f"{identifier}.npz") as archive:
            return {key: archive["|".join(key)] for key in inputs}
    models = {key: signals._model(ready, features[key], 60, 30) for key, ready in inputs.items()}
    result = {}
    for key, ready in inputs.items():
        peer_key = (key[0], "TOPIX" if key[1] == "NK225" else "NK225")
        own = models[key]
        peer = signals.COMPONENTS._peer(own, models[peer_key], ("ofi", "progress", "price_short"), 60)
        candidate, veto = signals._price_candidate(own, peer)
        held = signals.COMPONENTS._hold(candidate, veto, own["time_s"], 120, 120)
        value = signals.COMPONENTS._asof(own["seq"], held, ready["seq"]).astype(np.int8)
        value[ready["time_s"] < ready["start"] + 1200] = 0
        value[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
        result[key] = value
    return result


def management_context(method: dict, inputs: dict) -> dict | None:
    """機能: 主方向管理を指定したv30条件にだけ、保存済みの別管理方向を渡す。

    引数: method/inputs (dict)。返り値: 原本行ごとの管理方向または未指定 (dict|None)。
    """
    source = method["manager"].get("context_source", "entry")
    if source == "entry":
        return None
    if source not in ("main", "own") or method["signal"]["実装元"] != "二入力階層":
        raise ValueError("管理方向の実装元またはcontext_sourceが不正です")
    path = HERE / ("contexts" if source == "main" else "contexts_own") / f"{method['signal']['id']}.npz"
    with np.load(path) as archive:
        result = {key: archive["|".join(key)] for key in inputs}
    original_id = method['signal']['id'] if source == 'main' else f"H{int(method['signal']['id'][1:]) - 1:03d}"
    with np.load(V28 / 'contexts' / f'{original_id}.npz') as original:
        for key in inputs:
            np.testing.assert_array_equal(result[key], original['|'.join(key)])
    for key, ready in inputs.items():
        value = result[key]
        assert value.dtype == np.int8 and value.ndim == 1 and len(value) == len(ready["last"])
        assert np.isin(value, (-1, 0, 1)).all()
    return result


def require_saved_directions(items: list[dict]) -> None:
    """機能: 新しい方向列が未生成の状態では、基準を含む損益再生を開始しない。

    引数: items (list[dict]) は今回の比較対象。返り値: なし (None)。
    """
    for item in items:
        if item["signal"]["実装元"] == "二入力階層":
            identifier = item["signal"]["id"]
            assert (HERE / "directions" / f"{identifier}.npz").is_file(), f"未生成の入口方向: {identifier}"
            if item["manager"].get("context_source") in ("main", "own"):
                folder = "contexts" if item["manager"]["context_source"] == "main" else "contexts_own"
                assert (HERE / folder / f"{identifier}.npz").is_file(), f"未生成の管理方向: {identifier}"


def integrate(times: np.ndarray, values: np.ndarray, start: float, end: float) -> float:
    """機能: 直前の状態を次の観測まで保ち、波区間と重なる分だけ時間積分する。

    引数: times/values (ndarray)、start/end (float) は区間境界。
    返り値: 状態値×分の積分 (float)。同値時刻の寄与は0。
    """
    weights = np.maximum(0., np.minimum(times[1:], end) - np.maximum(times[:-1], start))
    return float(np.sum(weights * values[:-1]) / 60)


def boundary(ready: dict, curve: np.ndarray, time_s: float, point_value: float) -> dict:
    """機能: 境界以前の最後のlastと在庫で全建玉の時価を評価する。

    引数: ready (dict)、curve (ndarray)、time_s/point_value (float) は境界と契約倍率。
    返り値: 参照行、価格、保有、実現/含み/合計評価 (dict)。
    """
    index = int(np.searchsorted(ready["time_s"], time_s, side="right") - 1)
    if index < 0:
        raise ValueError("境界より前の観測価格がありません")
    row = curve[index]
    equity = float(row[5] + row[6] * ready["last"][index])
    np.testing.assert_allclose(equity, row[0], atol=1e-7)
    return dict(境界時刻=stamp(time_s), 参照時刻=stamp(ready["time_s"][index]), 参照行=index,
                seq=int(ready["seq"][index]), last=float(ready["last"][index]), 買い枚数=int(row[2]), 売り枚数=int(row[3]),
                ネット枚数=int(row[6]), 実現損益円=float(row[1] * point_value), 含み損益円=float((equity - row[1]) * point_value),
                時価損益円=float(equity * point_value))


def order_records(ready: dict, state: np.ndarray, result: dict, reasons: dict, context: np.ndarray | None = None) -> list[dict]:
    """機能: 全約定注文を売買マーカー向けの記録へ変換する。

    引数: ready/state/result/reasons (dict/ndarray/dict/dict)、context (ndarray|None) は保有管理方向。
    返り値: 新規・返済の約定時刻、決定元、数量、価格、理由 (list[dict])。
    """
    output = []
    management = state if context is None else context
    names = dict(reasons, **{})
    names.update({20: "主玉新規", 21: "カバー新規", 22: "追加新規", 23: "反転後の主玉補充"})
    for index, order in enumerate(result["orders"]):
        fill_row, source_row = int(order[0]), int(order[1])
        assert 0 <= source_row < fill_row
        output.append(dict(order_index=index, session=ready["session"], symbol=ready["symbol"],
                           time_s=float(ready["time_s"][fill_row]), 時刻=stamp(ready["time_s"][fill_row]), 原本行=fill_row, seq=int(ready["seq"][fill_row]),
                           発注元時刻=stamp(ready["time_s"][source_row]), 発注元行=source_row, 発注元seq=int(ready["seq"][source_row]),
                           種別="新規" if order[7] == 1 else "返済", direction=int(order[3]), 枚数=int(order[4]), 価格=float(order[5]),
                           組番号=int(order[2]), 理由番号=int(order[6]), 理由=names.get(int(order[6]), "その他"),
                           発注元信号=int(state[source_row]), 約定時信号=int(state[fill_row]),
                           発注元管理方向=int(management[source_row]), 約定時管理方向=int(management[fill_row])))
    return output


def trade_records(ready: dict, result: dict, point_value: float) -> list[dict]:
    """機能: 元建値と返済を結び、利益玉だけに偏らない図示用台帳を作る。

    引数: ready/result (dict)、point_value (float)。返り値: 全返済の記録 (list[dict])。
    """
    rows = []
    for trade in result["trades"]:
        entry, exit_row = int(trade[6]), int(trade[7])
        rows.append(dict(組番号=int(trade[0]), 元脚番号=int(trade[1]), direction=int(trade[2]), 枚数=int(trade[3]),
                         新規価格=float(trade[4]), 返済価格=float(trade[5]), 新規時刻=stamp(ready["time_s"][entry]), 返済時刻=stamp(ready["time_s"][exit_row]),
                         新規行=entry, 返済行=exit_row, 新規seq=int(ready["seq"][entry]), 返済seq=int(ready["seq"][exit_row]),
                         役割番号=int(trade[8]), 返済理由番号=int(trade[9]), 損益円=float(trade[10] * point_value)))
    return rows


def episode_metrics(method: dict, episode: dict, ready: dict, state: np.ndarray, result: dict, orders: list[dict], point_value: float, context: np.ndarray | None = None) -> dict:
    """機能: 信号時間、実際の保有時間、波の始終評価差を別々に測る。

    引数: method/episode/ready/result (dict)、state (ndarray)、orders (list[dict])、point_value (float)、context (ndarray|None)。
    返り値: 1手法×1波×1銘柄の診断 (dict)。
    """
    start, end = datetime.fromisoformat(episode["start"]).timestamp(), datetime.fromisoformat(episode["end"]).timestamp()
    times, side, curve = ready["time_s"], episode["side"], result["curve"]
    if times[0] > start or times[-1] < end:
        raise ValueError("指定波の境界を覆う観測がありません")
    first, last = boundary(ready, curve, start, point_value), boundary(ready, curve, end, point_value)
    aligned = curve[:, 2] if side > 0 else curve[:, 3]
    opposed = curve[:, 3] if side > 0 else curve[:, 2]
    net_aligned = curve[:, 6] * side
    forward = integrate(times, net_aligned > 0, start, end)
    reverse = integrate(times, net_aligned < 0, start, end)
    signal_forward = integrate(times, state == side, start, end)
    signal_reverse = integrate(times, state == -side, start, end)
    signal_neutral = integrate(times, state == 0, start, end)
    management = state if context is None else context
    context_forward = integrate(times, management == side, start, end)
    context_reverse = integrate(times, management == -side, start, end)
    context_neutral = integrate(times, management == 0, start, end)
    np.testing.assert_allclose(context_forward + context_reverse + context_neutral, (end - start) / 60, atol=1e-8)
    np.testing.assert_allclose(signal_forward + signal_reverse + signal_neutral, (end - start) / 60, atol=1e-8)
    in_orders = [row for row in orders if start <= row["time_s"] <= end]
    direction_changes = np.r_[True, state[1:] != state[:-1]]
    signals = [dict(時刻=stamp(times[index]), time_s=float(times[index]), seq=int(ready["seq"][index]), direction=int(state[index]))
               for index in np.flatnonzero(direction_changes & (times >= start) & (times <= end))]
    context_changes = np.r_[True, management[1:] != management[:-1]]
    contexts = [dict(時刻=stamp(times[index]), time_s=float(times[index]), seq=int(ready["seq"][index]), direction=int(management[index]))
                for index in np.flatnonzero(context_changes & (times >= start) & (times <= end))]
    return dict(method=method["id"], wave=episode["id"], session=episode["session"], symbol=ready["symbol"],
                波名=episode["name"], 波方向=side, 開始=episode["start"], 終了=episode["end"], 区間分=(end - start) / 60,
                正方向信号分=signal_forward, 逆方向信号分=signal_reverse, 中立信号分=signal_neutral,
                管理方向源=method["manager"].get("context_source", "entry"),
                正方向管理分=context_forward, 逆方向管理分=context_reverse, 中立管理分=context_neutral,
                正方向ネット保有分=forward, 逆方向ネット保有分=reverse, ネット中立分=integrate(times, net_aligned == 0, start, end),
                正方向脚保有分=integrate(times, aligned > 0, start, end), 逆方向脚保有分=integrate(times, opposed > 0, start, end),
                正方向枚数分=integrate(times, aligned, start, end), 逆方向枚数分=integrate(times, opposed, start, end),
                両建て保有分=integrate(times, (aligned > 0) & (opposed > 0), start, end),
                正方向ネット20分目安達成=forward >= 20 - 1e-9,
                開始境界=first, 終了境界=last, 時価損益差円=last["時価損益円"] - first["時価損益円"],
                実現損益差円=last["実現損益円"] - first["実現損益円"], 含み損益差円=last["含み損益円"] - first["含み損益円"],
                区間内新規=[row for row in in_orders if row["種別"] == "新規"], 区間内返済=[row for row in in_orders if row["種別"] == "返済"],
                区間内方向変更=signals, 区間内管理方向変更=contexts)


def write_markdown(report: dict) -> None:
    """機能: 指定波への未達を隠さず、短い日本語の一覧へまとめる。

    引数: report (dict) は全手法診断。返り値: なし (None)。
    """
    lines = ["# 指定4波への適合診断", "", "波区間は事後の確認にだけ使用し、入口・出口の計算には渡していない。○は同方向のネット保有が合計20分以上という説明用目安であり、統計的有意性ではない。", ""]
    for wave in EPISODES:
        lines.append(f"- {wave['id']}：{wave['name']}、{wave['start'][11:16]}〜{wave['end'][11:16]}、{'ロング' if wave['side'] > 0 else 'ショート'}。")
    for method in report["手法"]:
        rows = sorted([row for row in report["結果"] if row["method"] == method["id"]], key=lambda row: (row["wave"], row["symbol"]))
        matched = sum(row["正方向ネット20分目安達成"] for row in rows)
        absent = [f"{row['wave']} {row['symbol']}" for row in rows if row["正方向ネット保有分"] == 0]
        lines += ["", f"## {method['id']}", "", f"20分目安を満たしたのは **{matched}/8区間**。"]
        if absent:
            lines.append("**同方向を全く保有できなかった区間：" + "、".join(absent) + "。**")
        lines += ["", "|波|市場|正/逆入口 分|正/逆管理 分|正/逆ネット保有 分|波の時価損益差 円|目安|", "|---|---|---:|---:|---:|---:|---|"]
        for row in rows:
            lines.append(f"|{row['wave']}|{row['symbol']}|{row['正方向信号分']:.1f} / {row['逆方向信号分']:.1f}|{row['正方向管理分']:.1f} / {row['逆方向管理分']:.1f}|{row['正方向ネット保有分']:.1f} / {row['逆方向ネット保有分']:.1f}|{row['時価損益差円']:+,.0f}|{'○' if row['正方向ネット20分目安達成'] else '未達'}|")
    perfect = [item["method"] for item in report["方法別要約"] if item["目安達成区間数"] == 8]
    lines += ["", "## 要求例への結論", "", "8区間すべてで20分目安を満たした手法：" + ("、".join(perfect) if perfect else "なし") + "。",
              "時価損益差は開始前からの建玉と未返済の損益も含む。区間内新規だけの最終利益とは違う。正逆の脚を同時に持つ場合の脚別時間・枚数分はJSONに分離した。", "",
              "JSONには対象セッション全体の約定・返済と方向変更点を保存した。注文決定元と約定は別行。未約定注文は含まない。CurrentPriceTimeの同値行は時間0として扱い、受信時刻のない制限も残る。"]
    (HERE / "episode_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def accounting_checks(results: list[dict], ledgers: list[dict]) -> dict:
    """機能: 資産曲線とは独立に全約定を足し上げ、波の境界損益を確認する。

    引数: results/ledgers (list[dict]) は診断値と全約定台帳。
    返り値: 境界比較数と一致判定 (dict)。
    """
    mapped = {(item["method"], item["session"], item["symbol"]): item for item in ledgers}
    checked = 0
    for row in results:
        ledger = mapped[(row["method"], row["session"], row["symbol"])]
        point_value = 1000 if row["symbol"] == "TOPIX" else 10
        for name in ("開始境界", "終了境界"):
            boundary_value = row[name]
            executed = [order for order in ledger["全約定"] if order["原本行"] <= boundary_value["参照行"]]
            net = sum(order["direction"] * order["枚数"] for order in executed)
            cash = -sum(order["direction"] * order["枚数"] * order["価格"] for order in executed)
            expected = (cash + net * boundary_value["last"]) * point_value
            np.testing.assert_allclose(expected, boundary_value["時価損益円"], atol=1e-6)
            assert net == boundary_value["ネット枚数"]
            checked += 1
    return dict(全約定からの独立会計一致=True, 比較境界数=checked)


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 計測処理からの外部通信を強制拒否する。

    引数: args/kwargs (object) は任意の通信引数。返り値: なし (None)。必ず例外を送出する。
    """
    raise AssertionError("波の診断では通信を許可しません")


def main() -> None:
    """機能: 固定比較4基準と全84固定条件を、二入力の同じ4波で再生して診断する。

    引数: --prepare (bool) は仕様固定のみ、--selected (Path) は研究候補、--first-stage (Path) は一次反証全84の固定対象。
    返り値: なし (None)。現在APIや新しい探索は実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--selected", type=Path)
    parser.add_argument("--first-stage", nargs="?", const=HERE / "一次反証の結果.json", type=Path)
    args = parser.parse_args()
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    urllib.request.OpenerDirector.open = reject_network
    fixed = freeze()
    if args.prepare:
        print("4波の計測仕様と20分目安を結果生成前に固定しました。", flush=True)
        return
    if args.selected is None and args.first_stage is None:
        raise ValueError("実再生は --first-stage または --selected の固定結果を明示してください")
    selected_methods = methods(args.selected, args.first_stage)
    assert len(selected_methods) == 88, '固定比較4件と全84条件が必要です'
    require_saved_directions(selected_methods)
    all_inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    all_features = pickle.loads((OLD / "features_depth.pkl").read_bytes())
    sessions = {wave["session"] for wave in EPISODES}
    inputs = {key: ready for key, ready in all_inputs.items() if key[0] in sessions}
    features = {key: all_features[key] for key in inputs}
    signals = load_module(HERE.parent / "wave_v26" / "ensemble_signals.py", "episode_fixed_signals")
    sys.path.insert(0, str(V28))
    import engine_context as engine
    sys.path.insert(0, str(OLD))
    import engine as old_engine
    import managers
    assert Path(engine.__file__).resolve() == (V28 / "engine_context.py").resolve()
    assert Path(old_engine.__file__).resolve() == (OLD / "engine.py").resolve()
    checked_paths = [V27 / "hierarchy_signals.py", HERE.parent / "wave_v26" / "ensemble_signals.py",
                     V25 / "discovery_signals.py", OLD / "engine.py", V28 / "engine_context.py"]
    before = {str(path): digest(path) for path in checked_paths}
    results, ledger, summaries, baseline_checks = [], [], [], 0
    for method in selected_methods:
        state = directions(method, inputs, features, signals)
        context = management_context(method, inputs)
        for key, ready in sorted(inputs.items()):
            config = managers.make_config(method["manager"], key[1], ready)
            effective_context = None if context is None else context[key]
            replay = engine.run(ready, state[key], config, detail=True, context=effective_context)
            if method["id"] == "H019__D273" or method["id"].endswith('__L000'):
                assert effective_context is None
                old_replay = old_engine.run(ready, state[key], config, detail=True)
                for name in replay:
                    np.testing.assert_array_equal(replay[name], old_replay[name], err_msg="旧主案の" + name)
                baseline_checks += 1
            orders = order_records(ready, state[key], replay, engine.REASONS, effective_context)
            changes = np.flatnonzero(np.r_[True, state[key][1:] != state[key][:-1]])
            actual_context = state[key] if effective_context is None else effective_context
            context_changes = np.flatnonzero(np.r_[True, actual_context[1:] != actual_context[:-1]])
            ledger.append(dict(method=method["id"], session=key[0], symbol=key[1], 全約定=orders,
                               全返済=trade_records(ready, replay, config["point_value"]),
                               全方向変更=[dict(time_s=float(ready["time_s"][i]), 時刻=stamp(ready["time_s"][i]), 原本行=int(i), seq=int(ready["seq"][i]), direction=int(state[key][i])) for i in changes],
                               全管理方向変更=[dict(time_s=float(ready["time_s"][i]), 時刻=stamp(ready["time_s"][i]), 原本行=int(i), seq=int(ready["seq"][i]), direction=int(actual_context[i])) for i in context_changes]))
            for episode in EPISODES:
                if episode["session"] == key[0]:
                    results.append(episode_metrics(method, episode, ready, state[key], replay, orders, config["point_value"], effective_context))
        rows = [row for row in results if row["method"] == method["id"]]
        summary = dict(method=method["id"], 対象区間数=len(rows), 目安達成区間数=sum(row["正方向ネット20分目安達成"] for row in rows),
                       正方向保有0区間=[dict(wave=row["wave"], symbol=row["symbol"]) for row in rows if row["正方向ネット保有分"] == 0])
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    assert before == {str(path): digest(path) for path in checked_paths}
    assert len(results) == 704 and len(summaries) == 88
    report = dict(固定仕様=fixed, 手法=selected_methods, 結果=results, 方法別要約=summaries, 図示用セッション全台帳=ledger,
                  旧主案の全台帳曲線一致区間数=baseline_checks, 二入力対応=True,
                  境界損益の独立検算=accounting_checks(results, ledger),
                  候補追加元=str(args.selected) if args.selected else None, 候補固定SHA256=digest(args.selected) if args.selected else None,
                  一次反証追加元=str(args.first_stage) if args.first_stage else None, 一次反証固定SHA256=digest(args.first_stage) if args.first_stage else None,
                  API取得数=0, ルール変更=False, 参照コード不変=True, 参照コードSHA256=before)
    destination = HERE / "episode_audit.json"
    if destination.exists():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        for old in previous["結果"]:
            current = next((row for row in results if (row["method"], row["wave"], row["symbol"]) == (old["method"], old["wave"], old["symbol"])), None)
            if current is not None and current != old:
                raise AssertionError("候補追加により以前の固定波診断の値が変わりました")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_markdown(report)


if __name__ == "__main__":
    main()
