"""両市場確認付き部分返済を、独立した架空原行と実runner接続で検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np
from check_exit130 import fixture, account, load

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))


def read(path):
    """
    機能: 保存済み設定又は診断参照を読む。
    引数: path(Path)は対象。
    返り値: dict又はlistは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path):
    """
    機能: 実装と証跡の内容指紋を計算する。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 旧互換、確認待機、閾値、優先順位、会計、未来不使用と引数接続を検証する。
    引数: なし。
    返り値: None。架空素材だけで証跡を作成する。金融再生は0。
    """
    core = load(WORK/"night_confirm130.py", "両市場部分返済独立核")
    previous = load(WORK/"night_exit130.py", "両市場部分返済旧比較核")
    runner = load(WORK/"run_confirm130.py", "両市場部分返済独立接続")
    configs = read(WORK/"第三巡条件.json")
    paths = [WORK/name for name in ("night_confirm130.py", "run_confirm130.py", "night_exit130.py",
                                    "第三巡条件.json", "第三巡の変更根拠.json")]
    paths += [ROOT/path for path in runner.sources()]
    paths += [Path(__file__), HERE/"check_exit130.py"]
    reason = read(WORK/"第三巡の変更根拠.json")
    paths += [ROOT/reason["diagnosis"]["path"]]
    before = {str(p.relative_to(ROOT)): fingerprint(p) for p in paths}
    tests = []

    def check(label, action):
        """
        機能: 個々の検査結果と失敗理由を記録する。
        引数: label(str)、action(callable)は検査名と処理。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=label, 合格=True))
        except Exception as exc:
            tests.append(dict(確認=label, 合格=False, 詳細=f"{type(exc).__name__}: {exc}"))

    def case(reflected=False, top=True, moves=None, quantity=None):
        """
        機能: 旧入口判断3・新規4で幅4となる独立した原行を作る。
        引数: reflected/top(bool)、moves(list又はNone)、quantity(int又はNone)。
        返り値: listは16引数。原行6から両30秒を建玉の逆へ向ける。
        """
        args = fixture(moves=moves or [2., 1., 1.5, 1.5, 3., 2., 1.5, 1.5, 1.5, 1.5],
                       top=top, reflected=reflected, quantity=quantity)
        direction = -1 if reflected else 1
        args[7][6:, 4] = args[7][6:, 6] = -.1*direction
        return args

    def check_case(args, expected_decision=6, expected_fill=7, expected_reason=76):
        """
        機能: 最初の返済行・半数と全会計を独立に確認する。
        引数: args(list)、expected_decision/fill/reason(int)は人工入力と期待値。
        返り値: tupleは三つの出力配列。
        """
        result = core.simulate.py_func(*args, 1, 4)
        exits = result[0][result[0][:, 7] == 0]
        assert len(exits) > 0
        assert tuple(exits[0, [1, 0, 6]]) == (expected_decision, expected_fill, expected_reason), exits
        assert exits[0, 4] == (args[12]//2 if expected_reason == 76 else args[12])
        assert (exits[:, 6] == 76).sum() <= 1
        account(args, result)
        return result

    # ----------------------------------------
    # 既存四出口は、活動入口や新しい二市場資格の影響を受けない。
    for top in (False, True):
        for reflected in (False, True):
            for retest in (0, 1):
                for style in range(4):
                    def compatible(top=top, reflected=reflected, retest=retest, style=style):
                        """
                        機能: 旧0～3の全注文・取引・原行会計が厳密一致することを確認する。
                        引数: top/reflected(bool)、retest/style(int)は固定値。
                        返り値: None。
                        """
                        args = case(top=top, reflected=reflected)
                        if not retest:
                            args[15][10] = 3.
                        old = previous.simulate.py_func(*args, retest, style)
                        new = core.simulate.py_func(*args, retest, style)
                        for a, b in zip(old, new):
                            np.testing.assert_array_equal(a, b)
                        account(args, new)
                    check(f"旧出口互換 商品{top} 反転{reflected} 再試験{retest} 出口{style}", compatible)
            check(f"両30秒逆行で半数を次行返済 商品{top} 反転{reflected}",
                  lambda top=top, reflected=reflected: check_case(case(top=top, reflected=reflected)))
            for label, own, peer, known in (
                ("両方支持", .1, .1, 1.), ("自己だけ逆行", -.1, .1, 1.),
                ("相手だけ逆行", .1, -.1, 1.), ("両方中立", 0., 0., 1.),
                ("自己中立", 0., -.1, 1.), ("相手中立", -.1, 0., 1.),
                ("自己不明", np.nan, -.1, 1.), ("相手不明", -.1, np.nan, 1.),
                ("自己無限", -np.inf, -.1, 1.), ("相手無限", -.1, -np.inf, 1.),
                ("既知偽", -.1, -.1, 0.), ("既知不明", -.1, -.1, np.nan),
                ("既知2", -.1, -.1, 2.),
            ):
                def rejected(top=top, reflected=reflected, own=own, peer=peer, known=known):
                    """
                    機能: 不適格又は未知を逆向きの証拠として採用しないことを確認する。
                    引数: top/reflected(bool)、own/peer/known(float)は人工条件。
                    返り値: None。
                    """
                    args = case(top=top, reflected=reflected)
                    direction = -1 if reflected else 1
                    args[7][6:, 4] = direction*own
                    args[7][6:, 6] = direction*peer
                    args[7][6:, 11] = known
                    result = core.simulate.py_func(*args, 1, 4)
                    assert not np.any(result[0][:, 6] == 76)
                    account(args, result)
                check(f"{label}では部分返済しない 商品{top} 反転{reflected}", rejected)

    def unknown_wait():
        """
        機能: 一時的未知では待機し、後に確認できた当行で判断する。
        引数: なし。
        返り値: None。
        """
        args = case(moves=[2.,1.,1.,1.,1.,1.,1.,1.,1.,1.])
        args[7][6:8, 11] = 0.
        check_case(args, 8, 9)
    check("未知で待ってから既知の両逆行で発注", unknown_wait)

    def waiting_rechecks_price():
        """
        機能: 未知の間に値幅条件が消えたら、方向確認だけでは後追い返済しない。
        引数: なし。
        返り値: None。
        """
        args = case()
        args[7][6:8, 11] = 0.
        check_case(args, 10, 11)
    check("待機後も現在の押し返し幅を毎原行で再確認", waiting_rechecks_price)

    for label, moves in (
        ("順行0.5R直前", [1.99, .5, .5, .5, .5, .5, .5, .5, .5, .5]),
        ("戻り0.25R直前", [2., 1.01, 1.01, 1.01, 1.01, 1.01, 1.01, 1.01, 1.01, 1.01]),
    ):
        def below_threshold(moves=moves):
            """
            機能: 両市場逆行だけで所定の順行・押し返し幅を省略しないことを確かめる。
            引数: moves(list[float])は閾値直前の人工幅。
            返り値: None。
            """
            args = case(moves=moves)
            result = core.simulate.py_func(*args, 1, 4)
            assert not np.any(result[0][:, 6] == 76)
            account(args, result)
        check(label+"では部分返済しない", below_threshold)

    def pending_persists():
        """
        機能: 判断済み半返済を、以後の支持回復や資料欠測では取り消さない。
        引数: なし。
        返り値: None。
        """
        args = case()
        args[4][7:9] = False
        args[7][7:, 4] = args[7][7:, 6] = .2
        args[7][7:, 11] = 0.
        check_case(args, 6, 9)
    check("発注後の未知と逆行解消でも予約は次正常原行へ", pending_persists)

    for mode, expected in (("損切り", 32), ("追尾", 70), ("場末", 93), ("米開始", 94), ("境界破綻", 72)):
        def priority(mode=mode, expected=expected):
            """
            機能: 半返済条件と同時成立した旧全返済条件が先になることを確かめる。
            引数: mode(str)、expected(int)は人工条件名と期待理由。
            返り値: None。
            """
            moves = [2., -4., -4., -4., -4., -4., -4., -4., -4., -4.]
            if mode == "追尾":
                moves = [5., 1., 1., 1., 1., 1., 1., 1., 1., 1.]
            elif mode in ("場末", "米開始"):
                moves = [2., 1., 1., 1., 1., 1., 1., 1., 1., 1.]
            elif mode == "境界破綻":
                moves = [2., -3.75, -3.75, -3.75, -3.75, -3.75, -3.75, -3.75, -3.75, -3.75]
            args = case(moves=moves)
            if mode == "場末":
                args[9] = args[0][6]
            elif mode == "米開始":
                args[10] = args[0][6]
                args[15][7] = .5
            elif mode == "境界破綻":
                args[6][6:, 11] = -1.
            check_case(args, expected_reason=expected)
        check(mode+"は部分返済に優先", priority)

    for quantity in (1, 3, 5, 10):
        def quantity_check(quantity=quantity):
            """
            機能: 1枚では半返済せず、奇数の切捨てと手数料配賦を確認する。
            引数: quantity(int)は初期枚数。
            返り値: None。
            """
            args = case(quantity=quantity)
            result = core.simulate.py_func(*args, 1, 4)
            account(args, result)
            partial = result[0][result[0][:, 6] == 76]
            if quantity == 1:
                assert len(partial) == 0
            else:
                assert len(partial) == 1 and partial[0, 4] == quantity//2
        check(f"数量{quantity}の切捨て半分と残玉配賦", quantity_check)

    def parent_loss():
        """
        機能: 半分利益でも残玉込みの赤字を親単位の損失として集計する。
        引数: なし。
        返り値: None。
        """
        args = case(moves=[2.,1.,1.,-5.,-5.,-5.,-5.,-5.,-5.,-5.])
        result = core.simulate.py_func(*args, 1, 4)
        parents = account(args, result)
        row = runner.summarize(*result, dict(session="人工_Night", symbol="TOPIX"), configs[0])
        assert result[1][0, 8] > 0. and parents[0]["net"] < 0.
        assert row["profit"] == 0. and row["loss"] == -parents[0]["net"]
        assert row["parent_losses"] == 1 and row["parent_wins"] == 0
    check("部分利益と残玉損失を親赤字として合算", parent_loss)

    def causal_and_compiled():
        """
        機能: 未来の価格・気配・市場資料を変更しても過去は変わらずJITとも一致する。
        引数: なし。
        返り値: None。
        """
        args = case()
        original = core.simulate.py_func(*args, 1, 4)
        changed = deepcopy(args)
        cut = 8
        changed[1][cut:] -= 50.
        changed[2][cut:] -= 50.
        changed[3][cut:] -= 50.
        changed[7][cut:] = np.nan
        result = core.simulate.py_func(*changed, 1, 4)
        np.testing.assert_array_equal(result[2][:cut], original[2][:cut])
        np.testing.assert_array_equal(result[0][result[0][:, 0] < cut], original[0][original[0][:, 0] < cut])
        for left, right in zip(original, core.simulate(*args, 1, 4)):
            np.testing.assert_array_equal(left, right)
        reflected = core.simulate.py_func(*case(reflected=True), 1, 4)
        np.testing.assert_array_equal(original[0][:, 3], -reflected[0][:, 3])
        np.testing.assert_array_equal(original[2][:, [0,2,3]], reflected[2][:, [0,2,3]])
    check("未来毒化・上下対称・JIT一致", causal_and_compiled)

    def fixed_conditions():
        """
        機能: 第三巡が入口単独対照を保ち、変更根拠の指紋も一致するか確認する。
        引数: なし。
        返り値: None。
        """
        old = {c["base"]: c for c in read(WORK/"第一巡条件.json")}
        assert [c["id"] for c in configs] == ["W09", "W10"]
        for config in configs:
            assert config["exit_style"] == 4 and "activity_mode" not in config
            for field in (*runner.PARAMETERS, "retest_mode", "price_source", "peer_delay"):
                assert config[field] == old[config["base"]][field]
        ref = reason["diagnosis"]
        assert fingerprint(ROOT/ref["path"]) == ref["sha256"]
    check("旧入口固定と新活動を混ぜない二対照及び根拠指紋", fixed_conditions)

    def connection():
        """
        機能: 実runnerへ人工packetと代用核を接続して全引数・条件・保存名を確認する。
        引数: なし。
        返り値: None。実市場素材・金融核の市場再生は行わない。
        """
        scene = "人工_Night"
        packet = dict(inputs={}, quotes={})
        for symbol in ("TOPIX", "NK225"):
            args = case(top=symbol == "TOPIX")
            packet["inputs"][scene, symbol] = dict(session=scene, symbol=symbol, time_s=args[0],
                last=args[1]-.25, atr=args[5], start=args[8], limit=args[9], us_open=args[10],
                tick=args[11], seq=np.arange(len(args[0])))
            packet["quotes"][scene, symbol] = dict(bid=args[2], ask=args[3], quote_valid=args[4],
                seq=np.arange(len(args[0])), time_s=args[0])
        expected = {kind: runner.features129.build(packet, kind, 0.) for kind in ("last", "mid")}
        storage = HERE/f"両市場出口接続人工_{time.time_ns()}"
        storage.mkdir()
        path = storage/"人工packet.pkl"
        path.write_bytes(pickle.dumps(packet))
        ref = dict(session=scene, path=path.relative_to(ROOT).as_posix(), sha256=fingerprint(path))
        source_map = runner.sources()
        fixed = dict(sources=source_map, configs=configs, artificial=[], input_references=[])
        saves, archives, calls = {}, [], []
        original = (runner.HERE, runner.read, runner.save, runner.reference, runner.sources,
                    runner.night_confirm130.simulate, np.savez_compressed, sys.argv[:])

        def reader(path):
            """
            機能: 読込先を人工計画と人工packetだけへ限定する。
            引数: path(Path)は読込予定先。
            返り値: dictは架空資料。
            """
            if path.name == "固定計画.json":
                return fixed
            if path.name == "登録.json":
                return dict(returncode=0)
            if path.name == "入力準備.json":
                return dict(packets=[dict(session="人工_Day"), ref])
            raise AssertionError(path)

        def saver(path, value):
            """
            機能: runner出力を実結果に保存せずメモリへ控える。
            引数: path(Path)、value(dict)は保存名と内容。
            返り値: None。
            """
            saves[path.name] = deepcopy(value)

        def archiver(path, **values):
            """
            機能: NPZ予定内容をメモリに保持する。
            引数: path(Path)、values(dict[str,ndarray])は予定出力。
            返り値: None。
            """
            archives.append((path.name, deepcopy(values)))

        def substitute(*args):
            """
            機能: 引数を独立に照合し、既定の架空部分返済を返す。
            引数: args(tuple)はrunnerからの18引数。
            返り値: tupleは架空注文・取引・時価。
            """
            config = configs[len(calls)//2]
            symbol = ("TOPIX", "NK225")[len(calls) % 2]
            inputs, markets, history, _ = expected[config["price_source"]]
            ready, quotes = inputs[scene, symbol], packet["quotes"][scene, symbol]
            wanted = (ready["time_s"], ready["last"], quotes["bid"], quotes["ask"], quotes["quote_valid"],
                      ready["atr"], history[scene, symbol], markets[scene, symbol])
            assert len(args) == 18
            for left, right in zip(args[:8], wanted):
                np.testing.assert_array_equal(left, right)
            top = symbol == "TOPIX"
            assert args[8:15] == (ready["start"], ready["limit"], ready["us_open"], ready["tick"],
                                    5 if top else 10, 1000. if top else 10., 418 if top else 110)
            np.testing.assert_array_equal(args[15], [config[k] for k in runner.PARAMETERS])
            assert args[16:] == (config["retest_mode"], 4)
            calls.append((config["id"], symbol))
            qty, multiplier, rate = args[12:15]
            entry = args[3][2]
            entry_fee = qty*rate//10
            remaining_fee = entry_fee
            orders = [[2.,1.,0.,1.,qty,entry,1.,1.]]
            trades = []
            for index, (fill, amount, code) in enumerate(((4, qty//2, 76), (6, qty-qty//2, 93))):
                gross = (args[2][fill]-entry)*amount*multiplier
                portion = remaining_fee if index == 1 else entry_fee*amount//qty
                remaining_fee -= portion
                costs = portion+amount*rate//10
                orders.append([fill,fill-1,0,-1,amount,args[2][fill],code,0])
                trades.append([2,fill,1,amount,entry,args[2][fill],gross,costs,gross-costs,0,0,4,code,2,0])
            curve = np.zeros((len(args[0]), 4))
            curve[2:4, 1] = qty
            curve[4:6, 1] = qty-qty//2
            curve[-1] = [sum(r[8] for r in trades),0,sum(r[7] for r in trades),sum(r[8] for r in trades)]
            return np.array(orders,float), np.array(trades,float), curve

        try:
            runner.HERE, runner.read, runner.save = storage, reader, saver
            runner.sources = lambda: source_map
            runner.reference = lambda path: dict(path=str(path), sha256="人工")
            runner.night_confirm130.simulate = substitute
            np.savez_compressed = archiver
            sys.argv = ["人工接続", "--round", "人工"]
            runner.main()
        finally:
            (runner.HERE, runner.read, runner.save, runner.reference, runner.sources,
             runner.night_confirm130.simulate, np.savez_compressed, sys.argv) = original
        assert calls == [(c["id"], s) for c in configs for s in ("TOPIX","NK225")]
        output = saves["全条件の会計.json"]
        assert len(output["rows"]) == 4 and len(archives) == 2
        assert all(r["partial_exits"] == 1 and r["entries"] == 1 for r in output["rows"])
        for _, values in archives:
            assert set(values) == {c["id"]+"__"+key for c in configs for key in ("orders","trades","curve")}
            assert all(values[c["id"]+"__trades"].shape[1] == 15 for c in configs)
    check("実main二条件二商品・価格源・全引数・部分会計・保存列の接続", connection)

    after = {str(p.relative_to(ROOT)): fingerprint(p) for p in paths}
    assert before == after
    passed = all(t["合格"] for t in tests)
    target = HERE/f"両市場確認出口の独立人工と接続_{time.time_ns()}.json"
    output = dict(passed=passed, tests=tests, checks=len(tests), sources=after,
                  financial_replays=0, real_market_data_reads=0, API=0,
                  scope="架空原行と架空packetのみ。先の保存実績は再生せず診断の内容指紋のみ照合。")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    print(json.dumps(dict(passed=passed, checks=len(tests), path=str(target),
                         failures=[t for t in tests if not t["合格"]]), ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
