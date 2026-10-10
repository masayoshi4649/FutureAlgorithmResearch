"""D016 の方向条件を別計算で読み直し、全期間の過去不変性と発注起点を監査する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "wave_v23"
JST = ZoneInfo("Asia/Tokyo")


def load_module(path: Path, name: str):
    """機能: 既存ソースを変更せず私有名で読み込む。

    引数: path (Path)、name (str) はファイルと私有モジュール名。
    返り値: 読み込んだモジュール (module)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    """機能: 凍結ファイルが変わっていないか照合する。

    引数: path (Path)。返り値: SHA256 の十六進文字列 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value: float) -> str:
    """機能: 記録時刻を日本時間へ整形する。

    引数: value (float) はエポック秒。返り値: 日本時間の ISO 表記 (str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def sign(values: np.ndarray, boundary: float) -> np.ndarray:
    """機能: 有限値の閾値超過だけを買い・売り方向へ写す。

    引数: values (ndarray)、boundary (float) は絶対値閾値。
    返り値: -1/0/1 の方向 (ndarray[int8])。
    """
    result = np.zeros(len(values), dtype=np.int8)
    result[np.isfinite(values) & (values > boundary)] = 1
    result[np.isfinite(values) & (values < -boundary)] = -1
    return result


def past_values(times: np.ndarray, values: np.ndarray, targets: np.ndarray, missing: float = np.nan) -> np.ndarray:
    """機能: 過去または同じ公開時刻の最後の値だけを対応する。

    引数: times/values/targets (ndarray)、missing (float) は未観測時の値。
    返り値: 対応した過去値 (ndarray[float])。
    """
    indices = np.searchsorted(times, targets, side="right") - 1
    result = np.full(len(targets), missing, dtype=float)
    valid = indices >= 0
    result[valid] = values[indices[valid]]
    return result


def independent_book(ready: dict, frame: pd.DataFrame) -> dict:
    """機能: 旧 _board や新 _book を呼ばず、D016 が使う特徴だけを再計算する。

    引数: ready (dict)、frame (DataFrame) は原本列と解放済み板特徴。
    返り値: 60秒 OFI、60秒価格進行、30秒価格応答、公開行など (dict)。
    """
    usable = frame.loc[(frame.seq <= ready["seq"][-1]) & (frame.time_s <= ready["time_s"][-1])].copy()
    times = usable.time_s.to_numpy(float)
    sequences = usable.seq.to_numpy(np.int64)
    index = pd.to_datetime(times, unit="s", utc=True)
    net = pd.Series(usable.ofi_signed.to_numpy(float), index=index).rolling("60s", min_periods=5).sum().to_numpy()
    absolute = pd.Series(usable.ofi_abs.to_numpy(float), index=index).rolling("60s", min_periods=5).sum().to_numpy()
    flow = np.divide(net, absolute, out=np.full(len(times), np.nan), where=absolute > 0)
    atr = past_values(ready["seq"], ready["atr"], sequences)
    mid = usable.source_mid_last.to_numpy(float)
    progress = (mid - past_values(times, mid, times - 60)) / atr
    short = (mid - past_values(times, mid, times - 30)) / atr
    return dict(time_s=times, seq=sequences, atr=atr, mid=mid, ofi=flow, progress=progress, price_short=short,
                source_time_s=usable.source_time_s.to_numpy(float), source_last_seq=usable.source_last_seq.to_numpy(np.int64))


def independent_direction(ready: dict, own: dict, other: dict) -> dict:
    """機能: D016 の必要条件と120秒保持を別の逐次計算で検査する。

    引数: ready/own/other (dict) は原本と両銘柄の独立再計算特徴。
    返り値: 生の条件成立、保持状態、原本方向、相手参照行、直前根拠行 (dict)。
    """
    times = own["time_s"]
    peer_indices = np.searchsorted(other["time_s"] + 60, times, side="right") - 1
    valid = peer_indices >= 0
    peer = {}
    for name in ("ofi", "progress", "price_short"):
        peer[name] = np.zeros(len(times))
        peer[name][valid] = other[name][peer_indices[valid]]
    own_flow, peer_flow = sign(own["ofi"], .03), sign(peer["ofi"], .03)
    own_short, peer_short = sign(own["price_short"], .03), sign(peer["price_short"], .03)
    common = (own_flow != 0) & (own_flow == peer_flow)
    limited = (own_flow * own["progress"] <= .35) & (peer_flow * peer["progress"] <= .35)
    reversed_price = (own_short == -own_flow) & (peer_short == -own_flow)
    candidate = np.zeros(len(times), dtype=np.int8)
    candidate[valid & common & limited & reversed_price] = -own_flow[valid & common & limited & reversed_price]
    held, support = np.zeros(len(times), dtype=np.int8), np.full(len(times), -1, dtype=np.int64)
    current, expiry, previous, source = 0, -np.inf, -np.inf, -1
    for index, current_time in enumerate(times):
        if current_time > expiry or current_time - previous > 120:
            current, source = 0, -1
        if current and own_flow[index] == own_short[index] and own_flow[index] == -current:
            current, source = 0, -1
        if candidate[index] != 0:
            current, source, expiry = int(candidate[index]), index, current_time + 120
        held[index], support[index] = current, source
        previous = current_time
    raw_indices = np.searchsorted(own["seq"], ready["seq"], side="right") - 1
    directions = np.zeros(len(ready["seq"]), dtype=np.int8)
    available = raw_indices >= 0
    directions[available] = held[raw_indices[available]]
    directions[ready["time_s"] < ready["start"] + 1200] = 0
    directions[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
    return dict(candidate=candidate, held=held, support=support, directions=directions, peer_indices=peer_indices,
                common=common, limited=limited, reversed_price=reversed_price)


def observation(key: tuple, index: int, own: dict, other: dict, logic: dict) -> dict:
    """機能: 条件成立時に利用可能だった両市場の数値と参照時刻を出力する。

    引数: key (tuple)、index (int)、own/other/logic (dict) は銘柄と確認対象。
    返り値: 記録時刻・OFI・価格差・遅延・条件判定の具体例 (dict)。
    """
    peer_index = int(logic["peer_indices"][index])
    assert peer_index >= 0
    side = int(logic["candidate"][index])
    flow = -side
    return dict(session=key[0], symbol=key[1], direction=side, 判定時刻=stamp(own["time_s"][index]),
                自分解放seq=int(own["seq"][index]), 自分素材末尾seq=int(own["source_last_seq"][index]),
                自分素材時刻=stamp(own["source_time_s"][index]), 自分OFI=float(own["ofi"][index]),
                自分60秒価格差ATR=float(own["progress"][index]), 自分30秒価格差ATR=float(own["price_short"][index]),
                相手解放時刻=stamp(other["time_s"][peer_index]), 相手利用可能時刻=stamp(other["time_s"][peer_index] + 60),
                相手素材時刻=stamp(other["source_time_s"][peer_index]), 相手解放seq=int(other["seq"][peer_index]),
                相手素材末尾seq=int(other["source_last_seq"][peer_index]), 相手OFI=float(other["ofi"][peer_index]),
                相手60秒価格差ATR=float(other["progress"][peer_index]), 相手30秒価格差ATR=float(other["price_short"][peer_index]),
                自分流れ方向の60秒進行=float(flow * own["progress"][index]),
                相手流れ方向の60秒進行=float(flow * other["progress"][peer_index]),
                相手情報の解放後経過秒=float(own["time_s"][index] - other["time_s"][peer_index]),
                条件一致=bool(side and logic["common"][index] and logic["limited"][index] and logic["reversed_price"][index]),
                参照順序一致=bool(own["source_last_seq"][index] < own["seq"][index] and
                                  other["source_last_seq"][peer_index] < other["seq"][peer_index] and
                                  other["time_s"][peer_index] + 60 <= own["time_s"][index]))


def load_engine():
    """機能: 再生器の計算を保ち、Numba のディスクキャッシュだけ無効にして読む。

    引数: なし。返り値: 私有エンジンと管理器 (tuple[module,module])。
    注意: ソースは変更しない。監査で凍結先へキャッシュを書かないための措置である。
    """
    import numba
    original = numba.njit

    def memory_jit(*args, **kwargs):
        """機能: コンパイル済み処理をメモリだけに保持する。

        引数: args (tuple)、kwargs (dict) は numba.njit の引数。
        返り値: キャッシュ保存なしの同じコンパイラ指定 (object)。
        """
        kwargs["cache"] = False
        return original(*args, **kwargs)

    try:
        numba.njit = memory_jit
        engine = load_module(OLD / "engine.py", "d016_private_engine")
    finally:
        numba.njit = original
    managers = load_module(OLD / "managers.py", "d016_private_managers")
    return engine, managers


def main() -> None:
    """機能: 全13セッションで独立再計算・prefix・発注起点監査を実行し日本語で保存する。

    引数: なし。返り値: なし (None)。現在APIは呼ばず、指定した監査JSONとMDだけを作る。
    """
    frozen_paths = [HERE / "discovery_signals.py", HERE / "signal_diagnostics.py", OLD / "signals.py", OLD / "engine.py", OLD / "managers.py"]
    hashes = {str(path): digest(path) for path in frozen_paths}
    diagnostics = load_module(HERE / "signal_diagnostics.py", "d016_private_diagnostics")
    inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    features = pickle.loads((OLD / "features_depth.pkl").read_bytes())
    spec = next(item for item in diagnostics.NEW.catalog() if item["id"] == "D016")
    native = diagnostics.NEW.build(spec, inputs, features)
    with np.load(HERE / "directions/D016.npz") as saved:
        for key in inputs:
            np.testing.assert_array_equal(native[key], saved["|".join(key)])
    models = {key: independent_book(ready, features[key]) for key, ready in inputs.items()}
    logic, summaries, examples = {}, [], []
    for key, ready in sorted(inputs.items()):
        other_key = (key[0], "TOPIX" if key[1] == "NK225" else "NK225")
        own, other = models[key], models[other_key]
        checked = independent_direction(ready, own, other)
        logic[key] = checked
        np.testing.assert_array_equal(native[key], checked["directions"])
        raw = diagnostics.NEW._candidate(spec["params"], ready, diagnostics.NEW._book(ready, features[key], 60),
                                         diagnostics.NEW._peer(models[key], models[other_key], ("ofi", "progress", "price_short"), 60),
                                         models[key], models[key])
        np.testing.assert_array_equal(raw, checked["candidate"])
        usable = (own["time_s"] >= ready["start"] + 1200) & np.isfinite(own["atr"]) & (own["atr"] > 0)
        fired = (checked["candidate"] != 0) & usable
        indices = np.flatnonzero(fired)
        for side in (-1, 1):
            selected = np.flatnonzero(fired & (checked["candidate"] == side))
            if len(selected):
                examples.append(observation(key, int(selected[0]), own, other, checked))
        q = checked["peer_indices"][indices]
        assert (other["time_s"][q] + 60 <= own["time_s"][indices]).all()
        summary = dict(session=key[0], symbol=key[1], 原本行数=len(ready["seq"]), 条件成立イベント数=len(indices),
                       売り成立=int(np.count_nonzero(fired & (checked["candidate"] < 0))), 買い成立=int(np.count_nonzero(fired & (checked["candidate"] > 0))),
                       非中立原本行数=int(np.count_nonzero(native[key])),
                       成立時の価格確認閾値が1ティック未満=int(np.count_nonzero(.03 * own["atr"][indices] < ready["tick"])),
                       独立計算一致=True, 保存方向一致=True, 素材順序と相手遅延一致=True)
        summaries.append(summary)
    assert all(item["条件一致"] and item["参照順序一致"] for item in examples)
    print("全26入力の独立方向再計算と発火条件照合が一致", flush=True)

    # ----------------------------------------
    # 取引は信号の初出と限らないため、約定行ではなく発注元行から根拠を遡る。
    engine, managers = load_engine()
    frozen = json.loads((HERE / "探索条件の固定.json").read_text(encoding="utf-8"))
    manager = next(item for item in frozen["managers"] if item["id"] == "D065")
    trade_examples, trade_counts = [], []
    for key, ready in sorted(inputs.items()):
        cfg = managers.make_config(manager, key[1], ready)
        result = engine.run(ready, native[key], cfg)
        orders = result["orders"][result["orders"][:, 7] == 1]
        same_time, retained, source_matches = 0, 0, 0
        other_key = (key[0], "TOPIX" if key[1] == "NK225" else "NK225")
        own, other, checked = models[key], models[other_key], logic[key]
        for number, order in enumerate(orders):
            fill_row, origin_row, campaign, side = int(order[0]), int(order[1]), int(order[2]), int(order[3])
            assert origin_row < fill_row and native[key][origin_row] == side
            event = int(np.searchsorted(own["seq"], ready["seq"][origin_row], side="right") - 1)
            support = int(checked["support"][event])
            assert support >= 0 and checked["candidate"][support] == side
            assert own["seq"][support] <= ready["seq"][origin_row]
            same_time += int(ready["time_s"][origin_row] == ready["time_s"][fill_row])
            retained += int(checked["candidate"][event] == 0)
            source_matches += 1
            if number < 3:
                evidence = observation(key, support, own, other, checked)
                closed = result["trades"][result["trades"][:, 0] == campaign]
                trade_examples.append(dict(session=key[0], symbol=key[1], 組番号=campaign, 方向=side,
                                           発注元時刻=stamp(ready["time_s"][origin_row]), 発注元行=origin_row, 発注元seq=int(ready["seq"][origin_row]),
                                           約定時刻=stamp(ready["time_s"][fill_row]), 約定行=fill_row, 約定seq=int(ready["seq"][fill_row]),
                                           約定価格=float(order[5]), 枚数=int(order[4]), 発注時の方向=int(native[key][origin_row]),
                                           約定時の方向=int(native[key][fill_row]), 発注時に生条件も成立=bool(checked["candidate"][event] == side),
                                           根拠から発注まで秒=float(ready["time_s"][origin_row] - own["time_s"][support]),
                                           条件成立の観測=evidence, 返済損益円=float(closed[:, 10].sum() * cfg["point_value"])))
        trade_counts.append(dict(session=key[0], symbol=key[1], 新規約定数=len(orders), 発注元方向一致数=source_matches,
                                 発注元と約定の記録時刻が同値=same_time, 生条件消失後の保持方向で発注=retained))
    print("全新規約定の発注元・当時方向・直前成立根拠を照合", flush=True)

    # ----------------------------------------
    # 損益を見た追加調整はせず、既定の近傍と相手対照を全期間で切断検査する。
    sessions = sorted({key[0] for key in inputs})
    prefix = diagnostics.prefix_checks(spec, inputs, features, sessions=sessions, fractions=(.27, .63), include_variants=True)
    assert prefix["passed"]
    assert hashes == {str(path): digest(path) for path in frozen_paths}
    report = dict(信号="D016", 管理="D065", 現在API取得数=0, 凍結コードSHA256=hashes, 凍結コード不変=True,
                  独立再計算一致=True, prefix=prefix, 各入力=summaries, 最初の方向別成立例=examples,
                  取引根拠監査=trade_counts, 各入力の最初3新規約定=trade_examples,
                  論理上の注意=["両市場の60秒OFIは同じ符号だが、両市場の30秒価格応答がその符号と逆という観測である。買い手や売り手の主体行動を観測したものではない。",
                            "OFIは板更新の需給代理であり、約定売買だけではなく取消や気配移動の影響を含む。",
                            "60秒価格進行の条件は OFI符号×価格差/ATR <= 0.35。絶対値 <= 0.35 ではないので、OFIと逆方向への大幅な価格進行も通過する。",
                            "相手市場は公開時刻に60秒加えた過去情報。両市場の同時点の観測一致ではない。",
                            "成立方向は最終成立から120秒保持する。成立が続けば期限も更新し、自市場フローと30秒価格が保持方向と逆へ揃った時は撤回する。",
                            "0.03ATRの価格確認は小さいため、多くの場合は1ティック程度の反対向き変化で満たす。",
                            "CurrentPriceTimeは受信時刻ではない。次の異時刻での素材群解放は確認済みだが、二市場の実際の到着順は復元できない。"])
    (HERE / "d016_signal_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    total_fires = sum(item["条件成立イベント数"] for item in summaries)
    tick_small = sum(item["成立時の価格確認閾値が1ティック未満"] for item in summaries)
    total_trades = sum(item["新規約定数"] for item in trade_counts)
    retained = sum(item["生条件消失後の保持方向で発注"] for item in trade_counts)
    notes = ["# D016 の因果監査と条件の読み直し", "", "**独立再計算と全13セッションの切断監査は一致した。** ただし条件名の『吸収』は行動の断定ではなく、フローと価格の不一致に付けた仮説名である。", "",
             "## 実際に判定していること", "", "1. 両市場の解放済み特徴を60秒窓で集計し、OFIをそれぞれ絶対フロー量で割る。ともに +0.03 超または −0.03 未満なら、同方向の板フローがあるとする。相手は公開済み情報をさらに60秒遅らせる。価格差は公開済みブロック末尾の仲値で測る。",
             "2. それぞれの60秒価格差をATRで割り、OFI方向の進行が0.35ATR以下であることを確かめる。逆方向へ大きく進んだ場合も条件を満たす。",
             "3. 両市場の直近30秒価格差が、それぞれ0.03ATRを超えてOFIと逆向きなら、価格の動いた側へ入る方向を出す。正のOFIなのに両方の価格が下がればショート。負のOFIなのに両方が上がればロング。", "",
             "成立後の方向は最終成立から120秒保持し、根拠が繰り返せば延長する。自市場のOFIと30秒価格が保持方向の逆へ揃えば撤回する。新規はセッション開始20分後から、D065では判断の次の原本行で1枚を成行約定する。方向保持の解除と、既存建玉の返済は別である。", "",
             "## 何を証明していないか", "", "この条件は、買い注文を特定の売り手が吸収したことや、返済注文・他のアルゴの意図を識別しない。OFIには取消・気配移動も入り、相手情報の公開時刻は少なくとも60秒古い。『流入方向に価格が伸びず、逆方向の価格変化が揃う』という反証可能な観測条件である。", "",
             f"0.03ATRの価格確認閾値は、成立イベント {total_fires:,} 件中 {tick_small:,} 件で1ティック未満だった。細かい反対向きの価格変化を拾う条件であり、強い反転を待つ条件とは言えない。", "",
             "## 検算", "", f"- 全26入力・原本 {sum(item['原本行数'] for item in summaries):,} 行で、独立計算・現行build・探索時保存方向が一致。",
             f"- 全13セッション×2切断×両銘柄×7条件で {prefix['comparisons']:,} 比較、{prefix['compared_rows']:,} 方向要素が一致。基準、4近傍、相手中立化、遅延自己置換を含む。",
             f"- D065 の新規 {total_trades:,} 約定すべてで、発注元行は約定行より前、発注元方向と直前の成立根拠は約定方向と一致。生条件消失後の保持方向からの発注は {retained:,} 件。",
             f"- 発注元と約定の `CurrentPriceTime` が同じ新規は {sum(item['発注元と約定の記録時刻が同値'] for item in trade_counts):,} 件。次の原本行での約定を、実受信後の経過秒と同一視できない。方向を1/5/15秒遅らせる別の反証結果と分けて扱う。",
             "- 凍結ソースは不変。現在データの追加取得なし。", "", "## 最初の成立例", "", "|市場・判定時刻|方向|自分 OFI / 30秒価格差ATR|相手 OFI / 30秒価格差ATR|相手の公開時刻|", "|---|---|---|---|---|"]
    for item in examples[:4]:
        notes.append(f"|{item['symbol']} {item['判定時刻']}|{'買い' if item['direction'] > 0 else '売り'}|{item['自分OFI']:.4f} / {item['自分30秒価格差ATR']:.4f}|{item['相手OFI']:.4f} / {item['相手30秒価格差ATR']:.4f}|{item['相手解放時刻']}|")
    notes += ["", "JSONには各入力の最初の買い・売り成立、最初3新規約定、その発注元行・素材seq・相手公開時刻・60秒価格差も記録した。", "",
              "記録時刻は最終約定時刻であり受信時刻ではない。切断監査は保存情報に対する因果性を確認するが、現実の二市場の到着順の完全再現を保証しない。"]
    (HERE / "d016_signal_audit.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    print(json.dumps(dict(独立一致=True, prefix比較数=prefix["comparisons"], 方向要素=prefix["compared_rows"], 新規約定=total_trades, 保持中発注=retained), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
