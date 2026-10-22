"""市場なしで、四つの復帰仮説・固定参照・欠測と未来非依存を検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

import catalog_v2 as catalog


HERE = Path(__file__).resolve().parent
CHECKS = 0
GROUPS = []


# ----------------------------------------


def check(condition: bool, note: str) -> None:
    """
    機能: 意味の異なる人工期待を確認して不一致で停止する。
    引数: condition(bool)、note(str) は期待条件と説明。
    返り値: None。
    """
    global CHECKS
    assert bool(condition), note
    CHECKS += 1


def bars(prices: np.ndarray, scale: float = 1., center: float = 1000.) -> dict:
    """
    機能: 合成価格を格子・公開row付きの一分足へ変換する。
    引数: prices(ndarray[float])、scale/center(float) は人工価格と商品間変換。
    返り値: dict は118型の人工足。市場も受信時計も読まない。
    """
    value = center + (np.asarray(prices) - 1000.) * scale
    n = len(value)
    return dict(t_s=np.arange(1, n + 1, dtype=float) * 60., open=value.copy(), high=value + .125 * scale,
                low=value - .125 * scale, close=value.copy(), volume=np.ones(n), volume_known=np.ones(n, dtype=bool),
                valid=np.ones(n, dtype=bool), anchor=value.copy(), pub_raw_row=np.arange(n, dtype=np.int64) * 2 + 1,
                pub_price_time_s=np.arange(1, n + 1, dtype=float) * 60. + .25)


def scenario(tail: list[float], size: int = 100) -> tuple[dict, dict]:
    """
    機能: 60分平坦の後に指定した進行・停止・戻りだけが起こる人工場を作る。
    引数: tail(list[float]) は1000からの差、size(int) は分数。
    返り値: tuple[dict,dict] はTOPIX尺度と20倍のNK尺度の人工足。
    """
    price = np.full(size, 1000.)
    price[60:60 + len(tail)] += np.asarray(tail)
    if 60 + len(tail) < size:
        price[60 + len(tail):] += tail[-1]
    return bars(price), bars(price, scale=20., center=20000.)


def part(source: dict, end: int) -> dict:
    """
    機能: 人工公開情報をprefixへ切り、元の配列を変えない。
    引数: source(dict)、end(int) は人工足と切断点。
    返り値: dict は所有copy。
    """
    return {key: value[:end].copy() for key, value in source.items()}


def mirror(source: dict, twice_center: float) -> dict:
    """
    機能: 人工価格を鏡像にし、買売の向きだけを反転する。
    引数: source(dict)、twice_center(float) は人工足と中心の2倍。
    返り値: dict は高安を正しく入れ替えた人工足。
    """
    out = {key: value.copy() for key, value in source.items()}
    for key in ("open", "close", "anchor"):
        out[key] = twice_center - source[key]
    out["high"], out["low"] = twice_center - source["low"], twice_center - source["high"]
    return out


def make_missing(source: dict, row: int) -> None:
    """
    機能: 一つの人工足を118の欠測形へ変える。
    引数: source(dict)、row(int) は所有人工足と欠測位置。
    返り値: None。
    """
    for key in ("open", "high", "low", "close", "anchor", "volume", "pub_price_time_s"):
        source[key][row] = np.nan
    source["valid"][row] = source["volume_known"][row] = False
    source["pub_raw_row"][row] = -1


def main() -> None:
    """
    機能: 四入口の発火理由・仮説終端・prefix・未来置換・鏡像と欠測を純人工で確認する。
    引数: なし。
    返り値: None。市場新読・cache読・金融再生・APIを行わない。
    """
    own, peer = scenario([6., 7., 7., 7., 6.75, 5.25, 3.75, 1., -.5])
    result = catalog.build(own, peer, "TOPIX")
    specs = result["specs"]
    lookup = {spec["id"]: i for i, spec in enumerate(specs)}
    check(len(specs) == 8 and len(lookup) == 8, "四入口×二尺度")
    for length in (20, 40):
        expected = {"A": 66, "C": 61, "D": 65}
        for family, row in expected.items():
            k = lookup[f"{family}_L{length}"]
            fired = np.flatnonzero(result["entry"][k, :70])
            check(fired.tolist() == [row] and result["entry"][k, row] == -1,
                  f"{family}は定義どおりの段階で一回だけ売り")
        check(61 < 65 < 66, "即逆張り・自己確認・両市場確認を別時点へ分離")
    check(result["entry"][lookup["C_L20"], 81] == 1, "中心到達後に新成立した逆方向の進行は別の波として扱う")
    GROUPS.append("共同進行即逆張り61、自己停止復帰65、共同停止復帰66の独立期待")

    center_own, center_peer = scenario([6., 5., 4.5, 4., 3.5, 3., 2., 1., 0.])
    center = catalog.build(center_own, center_peer, "TOPIX")
    for length in (20, 40):
        k = lookup[f"B_L{length}"]
        check(np.flatnonzero(center["entry"][k]).tolist() == [64], "中心復帰は相手3本の実復帰が出る64まで待つ")
        check(center["entry"][k, 64] == -1 and center["exit_short"][k, 68], "中心到達で売り仮説を撤回")
    GROUPS.append("Bは乖離の大きさだけで入らず、相手の実復帰から64で発火")

    flat_own, flat_peer = scenario([6., 7., 7., 7., 6.75, 7., 7., 7., 7.])
    stalled = catalog.build(flat_own, flat_peer, "TOPIX")
    for family in ("A", "D"):
        for length in (20, 40):
            check(not np.any(stalled["entry"][lookup[f"{family}_L{length}"]]), "停止だけでは反転と呼ばない")
    GROUPS.append("停止だけでA/Dを発火しない")

    # ----------------------------------------
    # 各prefixと未来の価格だけを差し替えた場合の既知列を、全出力で照合する。
    for cut in (1, 20, 40, 60, 62, 65, 66, 67, 69, 90):
        short = catalog.build(part(own, cut), part(peer, cut), "TOPIX")
        for key in ("entry", "exit_long", "exit_short", "width", "valid"):
            np.testing.assert_allclose(short[key], result[key][:, :cut], equal_nan=True, rtol=0., atol=1e-10)
        check(True, "prefixの全出力は未来接尾に依存しない")
    changed_own = {key: value.copy() for key, value in own.items()}
    changed_peer = {key: value.copy() for key, value in peer.items()}
    for source in (changed_own, changed_peer):
        for key in ("open", "high", "low", "close", "anchor"):
            source[key][67:] += np.arange(len(source[key]) - 67) * 100.
    changed = catalog.build(changed_own, changed_peer, "TOPIX")
    for key in ("entry", "exit_long", "exit_short", "width", "valid"):
        np.testing.assert_allclose(changed[key][:, :67], result[key][:, :67], equal_nan=True, rtol=0., atol=1e-10)
    check(True, "未公開の自己と相手価格を替えても過去不変")
    GROUPS.append("10prefixと未来置換で全出力の因果性")

    for source_own, source_peer in ((own, peer), (center_own, center_peer)):
        base = catalog.build(source_own, source_peer, "TOPIX")
        reflected = catalog.build(mirror(source_own, 2000.), mirror(source_peer, 40000.), "TOPIX")
        np.testing.assert_array_equal(reflected["entry"], -base["entry"])
        np.testing.assert_array_equal(reflected["exit_long"], base["exit_short"])
        np.testing.assert_array_equal(reflected["exit_short"], base["exit_long"])
        np.testing.assert_array_equal(reflected["valid"], base["valid"])
        check(True, "全四仮説の買売鏡像")
    nk = catalog.build(peer, own, "NK225")
    check(np.any(nk["entry"][lookup["A_L20"]]) and np.any(nk["entry"][lookup["D_L40"]]), "NK側の呼値幅でも発火")
    GROUPS.append("買売鏡像とNK幅への接続")

    # ----------------------------------------
    # 欠測は未発火準備を切るが、発火済みの参照を消して既知の撤回を失わない。
    missing_own = {key: value.copy() for key, value in own.items()}
    make_missing(missing_own, 64)
    missing = catalog.build(missing_own, peer, "TOPIX")
    check(not np.any(missing["entry"][lookup["D_L20"], :68]), "準備途中の欠測で旧進行から発火しない")
    held_own = {key: value.copy() for key, value in own.items()}
    make_missing(held_own, 66)
    for key in ("open", "close", "anchor"):
        held_own[key][67] = 1008.
    held_own["high"][67], held_own["low"][67] = 1008.125, 1007.875
    held = catalog.build(held_own, peer, "TOPIX")
    for length in (20, 40):
        k = lookup[f"D_L{length}"]
        check(held["entry"][k, 65] == -1 and not held["valid"][k, 67], "欠測後は新規warmup不成立")
        check(held["exit_short"][k, 67], "旧保有の極値反証は欠測後も維持")
    missing_peer = {key: value.copy() for key, value in peer.items()}
    make_missing(missing_peer, 65)
    peer_gap = catalog.build(own, missing_peer, "TOPIX")
    check(not np.any(peer_gap["entry"][lookup["A_L20"], :70]), "同じ相手足を再利用して停止本数を増やさない")
    GROUPS.append("未発火準備の欠測破棄と発火済み参照の保持・相手欠測")

    # ----------------------------------------
    # 発火済み中心へ戻らない二度目の進行でも、同方向参照を上書きせず再発火しない。
    repeat_own, repeat_peer = scenario([6., 7., 7., 7., 6.75, 5.25, 3.75, 1., 6.5, 6.75, 6.75, 6.75, 5.25, 3.75, 2., 2.])
    repeated = catalog.build(repeat_own, repeat_peer, "TOPIX")
    for length in (20, 40):
        k = lookup[f"A_L{length}"]
        check(np.flatnonzero(repeated["entry"][k, :80]).tolist() == [66], "同じ未終端仮説の再発火を禁止")
        check(not np.any(repeated["exit_short"][k, 67:80]), "未終端の中心と極値参照を維持")
    GROUPS.append("早期TP又は未約定を知らないcatalogでも同じ仮説の参照を上書きしない")

    indexes = catalog.SOURCE.peer_index(own, peer)
    history = catalog.SOURCE.historical(own, 20, .5)
    other = catalog.SOURCE.historical(peer, 20, 10.)
    altered_history = {key: value.copy() for key, value in history.items()}
    altered_other = {key: value.copy() for key, value in other.items()}
    altered_history["width"][62:] = 100.
    altered_other["width"][62:] = 2000.
    state = catalog.signals(own, peer, altered_history, altered_other, indexes, "A")
    check(state["entry"][66] == -1 and np.all(state["width"][61:67] == 2.5), "準備後の幅変化でarm幅を変更しない")
    GROUPS.append("逐次stateの自己・相手arm幅固定")
    proof = dict(全合格=True, 検査数=CHECKS, 検査群=GROUPS, 市場新読=0, cache読取=0, 金融再生=0, API=0,
                 人工期待値訂正="最初の上昇波一回と、仮説終端後の新しい下落波を区別。初回Falseと両源はcatalog_pure_archive/attempt1に保全。経済源は同一。",
                 source_SHA256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in (HERE / "catalog_v2.py", Path(__file__), catalog.SOURCE_PATH)})
    output = HERE / "四入口の段階確認と因果性及び仮説固定参照の純人工検査.json"
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == "__main__":
    main()
