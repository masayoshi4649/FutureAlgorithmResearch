"""原板活動を追加した入口の取消順・旧互換・全接続を独立人工で検査する。"""

import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PRIOR = ROOT / "work/visual_pdca129_20261020"
sys.path.insert(0, str(WORK))
sys.path.insert(0, str(HERE))
from check_exit130 import fixture, account, load, prior_fixture

os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit_activity_entry_independent")
import numba
numba.config.CACHE_DIR = os.environ["NUMBA_CACHE_DIR"]


def read(path):
    """
    機能: UTF-8の保存資料を読み込む。
    引数: path(Path)はJSONの位置。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def activities(args, reflected=False):
    """
    機能: 上下対称で適格な架空活動を作る。
    引数: args(list)は原行、reflected(bool)は下方向。
    返り値: ndarray[N,4]は中値差・正出来高・符号量・既知。
    """
    side = -1. if reflected else 1.
    return np.tile([side, 20., -7.*side, 1.], (len(args[0]), 1))


def main():
    """
    機能: 人工核と実runnerの代用接続を確認し指紋付き証拠を保存する。
    引数: なし。
    返り値: None。実相場での金融再生・API取得は行わない。
    """
    runner = load(WORK / "run_activity130.py", "活動入口接続130独立")
    core = runner.night_activity130.simulate
    old = runner.run130.night_exit130.simulate.py_func
    configs = read(WORK / "第二巡条件.json")
    reason = read(WORK / "第二巡の変更根拠.json")
    paths = [ROOT/p for p in runner.sources()]
    paths += [WORK/"第二巡条件.json", WORK/"第二巡の変更根拠.json",
              ROOT/reason["diagnosis"]["path"], Path(__file__), HERE/"check_exit130.py",
              WORK/"原板活動の非金融準備.json", PRIOR/"第一巡条件.json",
              PRIOR/"第七巡条件.json"]
    before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    tests = []

    def check(name, action):
        """
        機能: 検査と失敗の反例を記録する。
        引数: name(str)、action(callable)は検査名と処理。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=name, 合格=True))
        except Exception as error:
            tests.append(dict(確認=name, 合格=False, 詳細=f"{type(error).__name__}: {error}"))

    def same(left, right):
        """
        機能: 全配列の要素を厳密照合する。
        引数: left/right(tuple[ndarray,...])は対象。
        返り値: None。
        """
        assert len(left) == len(right)
        for a, b in zip(left, right):
            np.testing.assert_array_equal(a, b)

    def simulate(args, activity, mode=1, retest=1, style=0, compiled=False):
        """
        機能: 架空の原行だけを核へ渡す。
        引数: args(list)、activity(ndarray|None)、mode/retest/style(int)、compiled(bool)。
        返り値: tuple[ndarray,...]は注文・完結返済・時価。
        """
        engine = core if compiled else core.py_func
        return engine(*args, retest, style, activity, mode)

    for top in (False, True):
        for reflected in (False, True):
            for confirm in range(7):
                def compatibility(top=top, reflected=reflected, confirm=confirm):
                    """
                    機能: 旧入口の全確認枝と全出口の活動無効互換を確認する。
                    引数: top/reflected(bool)、confirm(int)は架空条件。
                    返り値: None。
                    """
                    args = prior_fixture(top=top, reflected=reflected, confirm=confirm)
                    good = activities(args, reflected)
                    for retest in ((0, 1) if confirm < 4 else (1,)):
                        for style in range(4):
                            expected = old(*args, retest, style)
                            same(expected, simulate(args, None, 0, retest, style))
                            same(expected, simulate(args, good*np.nan, 0, retest, style))
                            same(expected, simulate(args, good, 1, retest, style))
                            account(args, expected)
                check(f"旧確認{confirm}全出口互換_商品{top}_反転{reflected}", compatibility)

    invalids = []
    for column in range(4):
        values = (0., -1., 2., np.nan, np.inf, -np.inf) if column == 3 else (
            0., np.nan, np.inf, -np.inf, -1. if column in (0, 1) else 1.)
        for value in values:
            invalids.append((column, value))
    for reflected in (False, True):
        for column, value in invalids:
            def rejection(reflected=reflected, column=column, value=value):
                """
                機能: 既知フラグと三量の厳密符号・有限性を方向対称で確認する。
                引数: reflected(bool)、column(int)、value(float)は不適格値。
                返り値: None。
                """
                args = fixture(reflected=reflected)
                data = activities(args, reflected)
                data[:, column] = value*(-1. if reflected and column in (0, 2) else 1.)
                out = simulate(args, data)
                assert len(out[0]) == 0
                account(args, out)
            check(f"活動不適格で無発注_反転{reflected}_列{column}_{value}", rejection)

        def strict_positive(reflected=reflected):
            """
            機能: 正負が厳密にゼロを越えた最小値にも後付け閾値がないと確認する。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            data = activities(args, reflected)
            data[:, :3] = [(-1 if reflected else 1)*1.e-200, 1.e-200,
                            (1 if reflected else -1)*1.e-200]
            out = simulate(args, data)
            assert tuple(out[0][0, :2]) == (4, 3)
            account(args, out)
        check(f"ゼロ境界のみで絶対量閾値なし_反転{reflected}", strict_positive)

        def reset_all(reflected=reflected):
            """
            機能: 不適格な完成候補を捨て、別の原行で全工程を再構築させる。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture([.5, -1.5, -.5, -.5, 3.5, -5., -5., -5.], reflected=reflected)
            args[0][5:] = [81., 101., 121., 122., 123., 124., 125., 126.]
            args[9] = 125.
            args[6][:, 5] = .5
            good = activities(args, reflected)
            normal = simulate(args, good)
            assert tuple(normal[0][0, :2]) == (4, 3)
            changed = good.copy()
            changed[3, 3] = 0.
            reset = simulate(args, changed)
            assert tuple(reset[0][0, :2]) == (8, 7)
            assert not (reset[0][:, 1] == 4).any()
            account(args, reset)
        check(f"取消後は全段階と新60秒を再形成_反転{reflected}", reset_all)

        for blocker in ("準備中", "30秒支持", "相手5分", "未知履歴", "気配", "距離"):
            def noncandidate(reflected=reflected, blocker=blocker):
                """
                機能: 旧発注資格に届かない行の活動欠測では準備を破棄しない。
                引数: reflected(bool)、blocker(str)は既存不適格理由。
                返り値: None。
                """
                args = fixture(reflected=reflected)
                good = activities(args, reflected)
                changed = good.copy()
                side = -1. if reflected else 1.
                for j in (1, 2, 3):
                    args[j][4] += .5*side
                if blocker == "準備中":
                    changed[:3] = np.nan
                    expected_row = 3
                else:
                    changed[3] = np.nan
                    expected_row = 4
                    if blocker == "30秒支持":
                        args[7][3, 4] = 0.
                    elif blocker == "相手5分":
                        args[6][3, 10] = 0.
                    elif blocker == "未知履歴":
                        args[6][3, 10] = np.nan
                    elif blocker == "気配":
                        args[2][3] -= 1.
                        args[3][3] += 1.
                    elif blocker == "距離":
                        args[15][13] = .625
                        for j in (1, 2, 3):
                            args[j][3] += .5*side
                expected = simulate(args, good)
                actual = simulate(args, changed)
                same(expected, actual)
                assert actual[0][0, 1] == expected_row
                account(args, actual)
            check(f"発注資格前の活動不適格は破棄しない_{blocker}_反転{reflected}", noncandidate)

        def pending(reflected=reflected):
            """
            機能: 判断後の未知や不利価格を見ても予約を取消さず次正常行で執行する。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            data = activities(args, reflected)
            data[4:] = np.nan
            args[4][4:6] = False
            side = -1 if reflected else 1
            args[1][6:] -= side*20.
            args[2][6:] -= side*20.
            args[3][6:] -= side*20.
            out = simulate(args, data)
            assert tuple(out[0][0, :2]) == (6, 3)
            assert out[0][0, 5] == (args[3] if side > 0 else args[2])[6]
            account(args, out)
        check(f"判断後未知と不利な次気配で新規取消なし_反転{reflected}", pending)

        def sameclock(reflected=reflected):
            """
            機能: 同秒の後続原行を現在の活動と混同しない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args = fixture(reflected=reflected)
            args[0][4] = args[0][3]
            data = activities(args, reflected)
            data[4:] = np.nan
            out = simulate(args, data)
            assert tuple(out[0][0, :2]) == (4, 3)
            account(args, out)
        check(f"同時計でも次原行約定_反転{reflected}", sameclock)

    for retest in (0, 1):
        for style in range(4):
            def future(retest=retest, style=style):
                """
                機能: 将来の価格・活動・履歴を改変しても過去の全出力が不変と確認する。
                引数: retest/style(int)は入口と出口。
                返り値: None。
                """
                args = fixture()
                args[15][10] = 3.
                data = activities(args)
                original = simulate(args, data, retest=retest, style=style)
                for cut in (0, 2, 3, 4, 6, 9):
                    changed = deepcopy(args)
                    changed_activity = data.copy()
                    changed_activity[cut+1:] = np.nan
                    for j in (1, 2, 3):
                        changed[j][cut+1:] += 19.
                    changed[6][cut+1:] = np.nan
                    modified = simulate(changed, changed_activity, retest=retest, style=style)
                    np.testing.assert_array_equal(original[0][original[0][:, 0] <= cut],
                                                  modified[0][modified[0][:, 0] <= cut])
                    np.testing.assert_array_equal(original[1][original[1][:, 1] <= cut],
                                                  modified[1][modified[1][:, 1] <= cut])
                    np.testing.assert_array_equal(original[2][:cut+1], modified[2][:cut+1])
            check(f"未来毒化で過去不変_再試験{retest}_出口{style}", future)

    for mode in (0, 1):
        for reflected in (False, True):
            def compiled(mode=mode, reflected=reflected):
                """
                機能: 別キャッシュのJITと逐次Pythonを全列比較する。
                引数: mode(int)、reflected(bool)は活動と方向。
                返り値: None。
                """
                args = fixture(reflected=reflected)
                data = activities(args, reflected) if mode else None
                same(simulate(args, data, mode=mode),
                     simulate(args, data, mode=mode, compiled=True))
            check(f"JIT全列一致_モード{mode}_反転{reflected}", compiled)

    def source_scope():
        """
        機能: 追加活動引数・資格確認以外の旧核構文が変わっていないと確認する。
        引数: なし。
        返り値: None。
        """
        old_source = (WORK/"night_exit130.py").read_text(encoding="utf-8-sig")
        new_source = (WORK/"night_activity130.py").read_text(encoding="utf-8-sig")
        old_ast = ast.parse(old_source)
        new_ast = ast.parse(new_source)
        old_fn = next(n for n in old_ast.body if isinstance(n, ast.FunctionDef))
        new_fn = next(n for n in new_ast.body if isinstance(n, ast.FunctionDef))
        new_fn.args.args = new_fn.args.args[:-2]
        new_fn.args.defaults = new_fn.args.defaults[:-2]
        new_fn.body[0] = old_fn.body[0]
        new_fn.body = [n for n in new_fn.body
                       if not (isinstance(n, ast.Assert) and "activity_mode" in ast.unparse(n.test))
                       and not (isinstance(n, ast.If) and ast.unparse(n.test) == "activity_mode == 1")]
        for node in ast.walk(new_fn):
            if isinstance(node, ast.If):
                node.body = [n for n in node.body
                             if not (isinstance(n, ast.If) and
                                     "activity_mode" in ast.unparse(n.test))]
        assert ast.dump(old_fn) == ast.dump(new_fn)
    check("活動資格と入力検証以外の旧核構文同値", source_scope)

    def fixed_control():
        """
        機能: 入口二対照・旧出口固定・根拠の現物指紋を確認する。
        引数: なし。
        返り値: None。
        """
        originals = {}
        for name in ("第一巡条件.json", "第七巡条件.json"):
            originals.update({c["id"]: c for c in read(PRIOR/name)})
        assert [c["id"] for c in configs] == ["W07", "W08"]
        for config in configs:
            previous = originals[config["base"]]
            for key in (*runner.PARAMETERS, "price_source", "peer_delay"):
                assert config[key] == previous[key], (config["id"], key)
            assert config["retest_mode"] == previous.get("retest_mode", 0)
            assert config["exit_style"] == 0 and config["activity_mode"] == 1
        assert hashlib.sha256((ROOT/reason["diagnosis"]["path"]).read_bytes()).hexdigest() == reason["diagnosis"]["sha256"]
        assert "既知" in reason["selection"] and "代理" in reason["counterexample"]
        for path in reason["extra_input_paths"]:
            assert (ROOT/path).is_file()
    check("二対照は既存入口出口維持で活動条件だけ追加", fixed_control)

    def connection():
        """
        機能: 実mainへ架空packetと代用核を接続して全20引数と保存を照合する。
        引数: なし。
        返り値: None。金融核は呼ばず、架空配列を返す。
        """
        scene = "人工_Night"
        packet = dict(inputs={}, quotes={})
        n = len(fixture()[0])
        data = {}
        for index, symbol in enumerate(("TOPIX", "NK225")):
            args = fixture(top=symbol == "TOPIX")
            packet["inputs"][scene, symbol] = dict(
                session=scene, symbol=symbol, time_s=args[0], last=args[1]-.25, atr=args[5],
                start=args[8], limit=args[9], us_open=args[10], tick=args[11], seq=np.arange(n))
            packet["quotes"][scene, symbol] = dict(
                bid=args[2], ask=args[3], quote_valid=args[4], seq=np.arange(n), time_s=args[0])
            data[symbol] = activities(args)
            data[symbol][:, 0] *= index+1
        expected = {kind: runner.run130.features129.build(packet, kind, 0.) for kind in ("last", "mid")}
        storage = HERE/f"活動入口の接続人工_{time.time_ns()}"
        storage.mkdir()
        packet_path = storage/"人工packet.pkl"
        packet_path.write_bytes(pickle.dumps(packet))
        packet_ref = dict(session=scene, **runner.reference(packet_path))
        entries = {}
        for symbol in data:
            path = storage/(symbol+".npz")
            np.savez_compressed(path, activity=data[symbol], time_s=packet["inputs"][scene, symbol]["time_s"],
                                seq=np.arange(n))
            entries[scene, symbol] = dict(session=scene, symbol=symbol, packet=packet_ref,
                rows=n, known=n, output=runner.reference(path))
        manifest_path = storage/"人工活動.json"
        manifest = dict(passed=True, financial_replays=0, source=runner.reference(WORK/"activity130.py"),
                        inputs=list(entries.values()))
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        manifest_ref = runner.reference(manifest_path)
        source_map = runner.sources()
        fixed = dict(sources=source_map, configs=configs, artificial=[], input_references=[manifest_ref])
        saves, archives, calls = {}, [], []
        original = (runner.HERE, runner.read, runner.save, runner.reference, runner.sources,
                    runner.ACTIVITY_MANIFEST, runner.validate_manifest,
                    runner.night_activity130.simulate, np.savez_compressed, sys.argv[:])

        def reader(path):
            """
            機能: 実行計画と入力目録を架空資料へ限定する。
            引数: path(Path)は読込対象。
            返り値: dictは架空資料。
            """
            if path.name == "固定計画.json":
                return fixed
            if path.name == "登録.json":
                return dict(returncode=0)
            if path.name == "入力準備.json":
                return dict(packets=[dict(session="人工_Day"), packet_ref])
            if path == manifest_path:
                return manifest
            raise AssertionError(path)

        def saver(path, value):
            """
            機能: 実mainの保存内容をメモリへ隔離する。
            引数: path(Path)、value(dict)は出力。
            返り値: None。
            """
            saves[path.name] = deepcopy(value)

        def archiver(path, **values):
            """
            機能: 配列保存をメモリへ隔離する。
            引数: path(Path)、values(dict[str,ndarray])は対象。
            返り値: None。
            """
            archives.append((path.name, deepcopy(values)))

        def validate(fixed_value, refs):
            """
            機能: 実接続検証の期待件数だけを人工二商品へ調整する。
            引数: fixed_value(dict)、refs(list)は固定入力。
            返り値: tupleは実検査結果。
            """
            return original[6](fixed_value, refs, 2)

        def reference(path):
            """
            機能: 実素材は真の指紋、メモリ隔離した保存先だけ架空指紋を返す。
            引数: path(Path)は対象。
            返り値: dictは参照情報。
            """
            if path.exists():
                return original[3](path)
            return dict(path=str(path), sha256="架空保存")

        def substitute(*args):
            """
            機能: 全入力が一致することを確認し架空の空会計を返す。
            引数: args(tuple)は実mainの20引数。
            返り値: tuple[ndarray,...]は空注文・空返済・ゼロ時価。
            """
            config = configs[len(calls)//2]
            symbol = ("TOPIX", "NK225")[len(calls) % 2]
            inputs, markets, history, _ = expected[config["price_source"]]
            ready = inputs[scene, symbol]
            quote = packet["quotes"][scene, symbol]
            wanted = (ready["time_s"], ready["last"], quote["bid"], quote["ask"], quote["quote_valid"],
                      ready["atr"], history[scene, symbol], markets[scene, symbol])
            assert len(args) == 20
            for left, right in zip(args[:8], wanted):
                np.testing.assert_array_equal(left, right)
            top = symbol == "TOPIX"
            assert tuple(args[8:15]) == (ready["start"], ready["limit"], ready["us_open"],
                ready["tick"], 5 if top else 10, 1000. if top else 10., 418 if top else 110)
            np.testing.assert_array_equal(args[15], [config[k] for k in runner.PARAMETERS])
            assert tuple(args[16:18]) == (config["retest_mode"], 0)
            np.testing.assert_array_equal(args[18], data[symbol])
            assert args[19] == 1
            calls.append((config["id"], symbol))
            return np.zeros((0, 8)), np.zeros((0, 15)), np.zeros((n, 4))

        try:
            runner.read, runner.save = reader, saver
            runner.sources = lambda: source_map
            runner.ACTIVITY_MANIFEST = manifest_path
            runner.validate_manifest = validate
            runner.reference = reference
            runner.night_activity130.simulate = substitute
            np.savez_compressed = archiver
            sys.argv = ["独立接続", "--round", storage.relative_to(WORK).as_posix()]
            runner.main()
        finally:
            (runner.HERE, runner.read, runner.save, runner.reference, runner.sources,
             runner.ACTIVITY_MANIFEST, runner.validate_manifest,
             runner.night_activity130.simulate, np.savez_compressed, sys.argv) = original
        assert calls == [(c["id"], s) for c in configs for s in ("TOPIX", "NK225")]
        result = saves["全条件の会計.json"]
        assert len(result["rows"]) == 4 and len(archives) == 2
        assert all(r["entries"] == 0 and r["net"] == 0 for r in result["rows"])
        assert saves["活動原行の接続確認.json"]["products"] == 2
        assert all(set(values) == {c["id"]+"__"+name for c in configs
                                  for name in ("orders", "trades", "curve")} for _, values in archives)
    check("実main二条件二商品へ原行気配と活動を20引数接続", connection)

    after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert before == after
    passed = all(t["合格"] for t in tests)
    target = HERE/f"原板活動入口と第二巡接続の独立人工_{time.time_ns()}.json"
    target.write_text(json.dumps(dict(passed=passed, tests=tests, sources=after,
        financial_replays=0, API=0, real_orders=0,
        scope="架空原行と代用mainのみ。活動素材の原板照合は別証拠。収益有効性は未判定。",
    ), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=passed, cases=len(tests), path=str(target),
                          failures=[t for t in tests if not t["合格"]]), ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
