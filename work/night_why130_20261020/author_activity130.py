"""活動入口の取消、旧互換、上下対称と未来不使用を架空原行で検査する。"""

from copy import deepcopy
import os
import pickle
import time

import numpy as np
from common130 import HERE, ROOT, save, reference, sha
from author_test130 import fixture
import night_exit130
import night_activity130
import run_activity130 as runner
import numba

numba.config.CACHE_DIR = str(HERE / "jit_activity_author")


def activity_for(n, side=1):
    """
    機能: 方向へ価格が進み、出来高方向代理が逆の適格な人工活動を作る。
    引数: n(int)は行数、side(int)は方向。
    返り値: ndarray[N,4]は中値差・正増分・符号付き増分・既知。
    """
    return np.tile(np.array([float(side), 10., -5.*side, 1.]), (n, 1))


def run(args, activity=None, mode=1, style=0, compiled=False):
    """
    機能: 架空入力のみを新核へ渡す。
    引数: args(tuple)、activity(ndarray又はNone)、mode/style(int)、compiled(bool)。
    返り値: tuple[ndarray,...]は注文・親内取引・時価。
    """
    engine = night_activity130.simulate if compiled else night_activity130.simulate.py_func
    return engine(*args, style, activity, mode)


def main():
    """
    機能: 元核と活動入口を人工比較し、非金融の接続も異常系まで照合する。
    引数: なし。
    返り値: None。証跡JSONだけを新規保存し、実市場の金融再生は行わない。
    """
    checks = []
    frozen = {name: sha(HERE/name) for name in ("night_exit130.py", "run130.py")}

    def check(label, passed=True):
        """
        機能: 成否を確認項目へ追加する。
        引数: label(str)、passed(bool)は検査名と結果。
        返り値: None。不一致は停止する。
        """
        assert passed, label
        checks.append(label)

    def equals(label, left, right):
        """
        機能: 三配列の全要素を厳密に照合する。
        引数: label(str)、left/right(tuple[ndarray,...])は比較対象。
        返り値: None。
        """
        for i, (a, b) in enumerate(zip(left, right)):
            np.testing.assert_array_equal(a, b)
            check(f"{label}・配列{i}")

    def fails(label, operation):
        """
        機能: 不正な接続が拒否されることを確かめる。
        引数: label(str)、operation(callable)は検査名と操作。
        返り値: None。
        """
        try:
            operation()
        except (AssertionError, KeyError):
            check(label)
        else:
            raise AssertionError(label)

    rng = np.random.default_rng(1302)
    for retest in (0, 1):
        initial = [100.5, 101.5, 102.] if not retest else [101., 104., 100.8, 102., 102.]
        for quantity in (5, 10):
            for case in range(8):
                prices = np.r_[initial, 102.+np.cumsum(rng.normal(0., 1.2, 35))]
                direct = fixture(prices, 1, quantity, retest)
                mirror = fixture(prices, -1, quantity, retest)
                n = len(prices)
                good = activity_for(n)
                reverse = activity_for(n, -1)
                for style in range(4):
                    prior = night_exit130.simulate.py_func(*direct, style)
                    equals(f"旧互換 {retest}/{quantity}/{case}/{style}", prior,
                           run(direct, np.full((n, 4), np.nan), 0, style))
                    result = run(direct, good, 1, style)
                    equals(f"全適格同値 {retest}/{quantity}/{case}/{style}", prior, result)
                    reflected = run(mirror, reverse, 1, style)
                    np.testing.assert_allclose(result[2][:, [0, 2, 3]], reflected[2][:, [0, 2, 3]], atol=1e-8)
                    np.testing.assert_array_equal(result[0][:, 3], -reflected[0][:, 3])
                    check("上下対称の注文方向と全行会計")
                    assert np.all(result[0][:, 0] > result[0][:, 1])
                    for parent in result[0][result[0][:, 7] == 1, 2]:
                        po = result[0][result[0][:, 2] == parent]
                        assert po[po[:, 7] == 1, 4].sum() == po[po[:, 7] == 0, 4].sum()
                    check("次原行と親数量保存")
                    # ----------------------------------------
                    # 変更の起点より後だけを汚す。入口活動だけでなく全価格経路も独立に変更する。
                    cut = 17
                    changed = prices.copy()
                    changed[cut:] += rng.normal(0., 20., n-cut)
                    poison = good.copy()
                    poison[cut:] = np.nan
                    modified = run(fixture(changed, 1, quantity, retest), poison, 1, style)
                    np.testing.assert_array_equal(result[2][:cut], modified[2][:cut])
                    np.testing.assert_array_equal(result[0][result[0][:, 0] < cut],
                                                  modified[0][modified[0][:, 0] < cut])
                    check("未来価格・未来活動毒化で過去不変")
                    if case == 0:
                        equals("JITと逐次人工一致", result, run(direct, good, 1, style, True))

    prices = np.array([101.,104.,100.8,102.,102.,102.,104.,100.8,102.,102.,105.,104.,98.,98.])
    args = fixture(prices, 1, retest=1)
    good = activity_for(len(prices))
    normal = run(args, good)
    check("元の再試験発注は判断3・新規4", normal[0][0, 1] == 3 and normal[0][0, 0] == 4)
    invalids = (
        [1.,10.,-5.,0.], [1.,10.,-5.,2.], [1.,10.,-5.,np.nan],
        [0.,10.,-5.,1.], [-1.,10.,-5.,1.], [1.,0.,-5.,1.],
        [1.,-1.,-5.,1.], [1.,10.,0.,1.], [1.,10.,5.,1.],
        [np.nan,10.,-5.,1.], [1.,np.nan,-5.,1.], [1.,10.,np.nan,1.],
        [np.inf,10.,-5.,1.],
    )
    for value in invalids:
        activities = np.tile(value, (len(prices), 1))
        check(f"未知又は不適格の全候補を取消 {value}", len(run(args, activities)[0]) == 0)
    bad_first = good.copy()
    bad_first[3, 3] = 0.
    reset = run(args, bad_first)
    check("未知候補は全段階再形成後のみ再参加", reset[0][0, 1] == 8 and reset[0][0, 0] == 9)
    bad_earlier = good.copy()
    bad_earlier[:3] = np.nan
    equals("旧発注資格前の未知は準備を取り消さない", normal, run(args, bad_earlier))
    bad_after = good.copy()
    bad_after[4:] = np.nan
    retained = run(args, bad_after)
    np.testing.assert_array_equal(normal[0][:1], retained[0][:1])
    check("判断後の未知で予約済み新規を取り消さない")
    gap_args = list(args)
    gap_args[4] = args[4].copy()
    gap_args[4][4] = False
    gap_result = run(tuple(gap_args), good)
    check("約定行の不正気配は次正常原行まで待つ", gap_result[0][0, 0] == 5 and gap_result[0][0, 1] == 3)
    equals("活動なしmode0は旧完全互換", night_exit130.simulate.py_func(*args, 0), run(args, None, 0))
    equals("活動なしmode0のJIT互換", night_exit130.simulate.py_func(*args, 0), run(args, None, 0, compiled=True))
    fails("mode1の活動なし拒否", lambda: run(args, None, 1))
    fails("行数不一致拒否", lambda: run(args, good[:-1], 1))
    fails("列数不一致拒否", lambda: run(args, good[:, :3], 1))
    fails("未知の活動モード拒否", lambda: run(args, good, 2))

    # ----------------------------------------
    # 実板を開かない架空NPZで、runnerの指紋・原行・時計・件数の検査を確かめる。
    material = HERE / "activity_author" / f"人工接続_{time.time_ns()}"
    material.mkdir(parents=True)
    scene = "人工_Night"
    packet = dict(inputs={}, quotes={})
    for symbol in ("TOPIX", "NK225"):
        rd = dict(time_s=args[0].copy(), seq=np.arange(len(prices)))
        packet["inputs"][scene, symbol] = rd
        packet["quotes"][scene, symbol] = deepcopy(rd)
    packet_path = material / "packet.pkl"
    packet_path.write_bytes(pickle.dumps(packet))
    packet_ref = dict(session=scene, **reference(packet_path))
    entries = {}
    for symbol in ("TOPIX", "NK225"):
        target = material / (symbol+".npz")
        np.savez_compressed(target, activity=good, time_s=args[0], seq=np.arange(len(prices)))
        entries[scene, symbol] = dict(session=scene, symbol=symbol, packet=packet_ref,
            output=reference(target), rows=len(prices), known=len(prices))
    loaded = runner.load_activity(packet, packet_ref, entries)
    for symbol, value in loaded.items():
        np.testing.assert_array_equal(value, good)
        check("活動NPZの架空接続 "+symbol)
    bad = deepcopy(packet)
    bad["inputs"][scene, "TOPIX"]["seq"][3] += 1
    fails("原行不一致は拒否", lambda: runner.load_activity(bad, packet_ref, entries))
    bad = deepcopy(packet)
    bad["inputs"][scene, "TOPIX"]["time_s"][3] += 1
    fails("時計不一致は拒否", lambda: runner.load_activity(bad, packet_ref, entries))
    bad = deepcopy(packet)
    bad["quotes"][scene, "TOPIX"]["seq"][3] += 1
    fails("気配との原行不一致は拒否", lambda: runner.load_activity(bad, packet_ref, entries))
    bad_entries = deepcopy(entries)
    bad_entries[scene, "TOPIX"]["output"]["sha256"] = "0"*64
    fails("保存活動の指紋違い拒否", lambda: runner.load_activity(packet, packet_ref, bad_entries))
    bad_entries = deepcopy(entries)
    bad_entries[scene, "TOPIX"]["packet"]["sha256"] = "0"*64
    fails("保存packet参照の不一致拒否", lambda: runner.load_activity(packet, packet_ref, bad_entries))
    manifest = material / "活動.json"
    save(manifest, dict(passed=True, financial_replays=0, source=reference(HERE/"activity130.py"),
                        inputs=list(entries.values())))
    original_manifest = runner.ACTIVITY_MANIFEST
    runner.ACTIVITY_MANIFEST = manifest
    try:
        fixed = dict(input_references=[reference(manifest)])
        _, proof = runner.validate_manifest(fixed, [packet_ref], 2)
        check("金融前の全活動対応検査", proof["products"] == 2 and proof["rows"] == 2*len(prices))
        fails("未固定活動マニフェスト拒否", lambda: runner.validate_manifest(dict(input_references=[]), [packet_ref], 2))
        fails("期待42商品場不足拒否", lambda: runner.validate_manifest(fixed, [packet_ref]))
    finally:
        runner.ACTIVITY_MANIFEST = original_manifest
    check("旧固定核とrunnerを変更していない", frozen == {name: sha(HERE/name) for name in frozen})
    target = HERE / "activity_author" / f"入口活動の作者人工_{time.time_ns()}.json"
    save(target, dict(passed=True, checks=len(checks), items=checks, financial_replays=0,
         real_market_data_reads=0, API=0, sources=runner.sources(),
         author=reference(HERE/"author_activity130.py"),
         frozen=frozen, fixture_reference=reference(HERE/"author_test130.py")))
    print(target, "合格", len(checks), flush=True)


if __name__ == "__main__":
    main()
