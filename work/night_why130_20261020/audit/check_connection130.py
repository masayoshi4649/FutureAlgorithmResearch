"""六条件の入力接続と部分返済の親合算を人工素材で独立照合する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
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
from check_exit130 import fixture, account, load


def read(path):
    """
    機能: 保存JSONを読み込む。
    引数: path(Path)は対象。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    """
    機能: 接続先を架空素材と代用核へ差し替え、固定条件・会計・集計を確認する。
    引数: なし。
    返り値: None。実市場の原行・金融核の金融再生・API取得は行わない。
    """
    run = load(WORK/"run130.py", "接続130独立")
    analysis = load(WORK/"analyze130.py", "集計130独立")
    configs = read(WORK/"第一巡条件.json")
    paths = [WORK/n for n in ("run130.py", "analyze130.py", "register130.py", "common130.py",
                              "night_exit130.py", "第一巡条件.json", "第一巡の変更根拠_確定.json")]
    paths += [PRIOR/"第一巡条件.json", PRIOR/"第七巡条件.json", Path(__file__)]
    paths += [ROOT/read(WORK/"第一巡の変更根拠_確定.json")["diagnosis"]["path"],
              PRIOR/"最終全場比較_確定.json"]
    paths += [ROOT/p for p in run.sources()]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    checks = []

    def check(name, action):
        """
        機能: 一つの検査と失敗理由を保存する。
        引数: name(str)、action(callable)は検査名と処理。
        返り値: None。
        """
        try:
            action()
            checks.append(dict(確認=name, 合格=True))
        except Exception as exc:
            checks.append(dict(確認=name, 合格=False, 詳細=f"{type(exc).__name__}: {exc}"))

    def control():
        """
        機能: 二つの保存入口と出口三条件だけの差であることを確認する。
        引数: なし。
        返り値: None。
        """
        originals = {}
        for path in (PRIOR/"第一巡条件.json", PRIOR/"第七巡条件.json"):
            originals.update({c["id"]: c for c in read(path)})
        assert [c["id"] for c in configs] == ["W01", "W02", "W03", "W04", "W05", "W06"]
        assert [c["exit_style"] for c in configs] == [1, 2, 3, 1, 2, 3]
        for config in configs:
            old = originals[config["base"]]
            for field in (*run.PARAMETERS, "price_source", "peer_delay"):
                assert config[field] == old[field], (config["id"], field)
            assert config["retest_mode"] == old.get("retest_mode", 0)
            assert config["kind"] == "Night"
        reason = read(WORK/"第一巡の変更根拠_確定.json")
        diagnosis = reason["diagnosis"]
        assert hashlib.sha256((ROOT/diagnosis["path"]).read_bytes()).hexdigest() == diagnosis["sha256"]
        assert "勝ち" in reason["observed"] and "無取引" in reason["selection"]
    check("NV01とNV25の入口保持と出口三対照及び診断指紋", control)

    def aggregate_parents():
        """
        機能: 部分返済が利益でも残玉込みの親損失を全額損失に集計する。
        引数: なし。
        返り値: None。
        """
        core = run.night_exit130.simulate.py_func
        for top in (False, True):
            for reflected in (False, True):
                args = fixture([2., 1., 1., -5., -5., -5., -5., -5., -5.],
                               top=top, reflected=reflected)
                out = core(*args, 1, 2)
                parents = account(args, out)
                ready = dict(session="人工_Night", symbol="TOPIX" if top else "NK225")
                row = run.summarize(*out, ready, configs[1])
                assert row["profit"] == 0 and row["loss"] == -parents[0]["net"]
                assert row["entries"] == 1 and row["parent_losses"] == 1 and row["parent_wins"] == 0
                assert row["quantity"] == args[12] and row["max_quantity"] == args[12]
                assert row["partial_exits"] == 1
                assert row["fees"] == (417 if top else 220)
    check("部分利益と残玉赤字は完結親の一敗へ集約", aggregate_parents)

    def aggregate_empty():
        """
        機能: 発注なしの会計をゼロ取引として集計する。
        引数: なし。
        返り値: None。
        """
        row = run.summarize(np.zeros((0, 8)), np.zeros((0, 15)), np.zeros((7, 4)),
                            dict(session="人工_Night", symbol="TOPIX"), configs[0])
        assert all(row[k] == 0 for k in ("profit", "loss", "net", "entries", "quantity",
                                         "parent_wins", "parent_losses", "max_quantity", "partial_exits"))
    check("無取引の親会計はゼロ", aggregate_empty)

    def separate_flat():
        """
        機能: 実取引の収支ゼロと無取引を集計で分ける。
        引数: なし。
        返り値: None。
        """
        rows = [dict(net=net, profit=max(0, net), loss=max(0, -net), fees=0, entries=entries)
                for net, entries in ((0, 0), (0, 1), (10, 1), (-3, 1))]
        stat = analysis.metrics(rows)
        assert (stat["sessions"], stat["black"], stat["red"], stat["flat"],
                stat["breakeven"], stat["active"]) == (4, 1, 1, 1, 1, 3)
        assert stat["without_top3"] == -3 and stat["net"] == 7
    check("収支ゼロ取引と無取引を分離して分母維持", separate_flat)

    def connection():
        """
        機能: 実mainへ人工packetと代用核を渡し、全六条件両商品の引数対応を確認する。
        引数: なし。
        返り値: None。代用核は新しい売買判断を行わない。
        """
        scene = "人工_Night"
        packet = dict(inputs={}, quotes={})
        for symbol in ("TOPIX", "NK225"):
            args = fixture(top=symbol == "TOPIX")
            packet["inputs"][scene, symbol] = dict(
                session=scene, symbol=symbol, time_s=args[0], last=args[1]-.25,
                atr=args[5], start=args[8], limit=args[9], us_open=args[10],
                tick=args[11], seq=np.arange(len(args[0])),
            )
            packet["quotes"][scene, symbol] = dict(
                bid=args[2], ask=args[3], quote_valid=args[4], seq=np.arange(len(args[0])),
            )
        expected = {kind: run.features129.build(packet, kind, 0.) for kind in ("last", "mid")}
        storage = HERE/f"接続人工素材_{time.time_ns()}"
        storage.mkdir()
        target = storage/"人工packet.pkl"
        target.write_bytes(pickle.dumps(packet))
        ref = dict(session=scene, path=target.relative_to(ROOT).as_posix(),
                   sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        source_map = run.sources()
        fixed = dict(sources=source_map, configs=configs, artificial=[], input_references=[])
        saves, archives, calls = {}, [], []
        original = (run.HERE, run.read, run.save, run.reference, run.sources,
                    run.night_exit130.simulate, np.savez_compressed, sys.argv[:])

        def reader(path):
            """
            機能: 実行計画と素材目録を人工資料に限定する。
            引数: path(Path)は予定読込先。
            返り値: dictは人工資料。
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
            機能: 出力をメモリに記録する。
            引数: path(Path)、value(dict)は出力。
            返り値: None。
            """
            saves[path.name] = deepcopy(value)

        def archiver(path, **values):
            """
            機能: 配列の保存名と全列をメモリに記録する。
            引数: path(Path)、values(dict[str,ndarray])。
            返り値: None。
            """
            archives.append((path.name, deepcopy(values)))

        def substitute(*args):
            """
            機能: 全入力対応を照合し、既定の架空注文だけを返す。
            引数: args(tuple)はrunnerから渡された18引数。
            返り値: tupleは三つの人工配列。
            """
            config = configs[len(calls)//2]
            symbol = ("TOPIX", "NK225")[len(calls) % 2]
            inputs, markets, history, _ = expected[config["price_source"]]
            ready, quote = inputs[scene, symbol], packet["quotes"][scene, symbol]
            expected_arrays = (ready["time_s"], ready["last"], quote["bid"], quote["ask"],
                               quote["quote_valid"], ready["atr"], history[scene, symbol],
                               markets[scene, symbol])
            assert len(args) == 18
            for actual, wanted in zip(args[:8], expected_arrays):
                np.testing.assert_array_equal(actual, wanted)
            top = symbol == "TOPIX"
            assert tuple(args[8:15]) == (ready["start"], ready["limit"], ready["us_open"],
                ready["tick"], 5 if top else 10, 1000. if top else 10., 418 if top else 110)
            np.testing.assert_array_equal(args[15], [config[k] for k in run.PARAMETERS])
            assert args[16:] == (config["retest_mode"], config["exit_style"])
            calls.append((config["id"], symbol))
            qty, multiplier, rate = args[12:15]
            entry = args[3][2]
            entry_fee = qty*rate//10
            remaining_fee = entry_fee
            orders = [[2., 1., 0., 1., qty, entry, 1., 1.]]
            trades = []
            allocations = [(6, qty, 93)] if args[17] == 1 else [(4, qty//2, 76), (6, qty-qty//2, 93)]
            for index, (row, amount, reason) in enumerate(allocations):
                value = (args[2][row]-entry)*amount*multiplier
                assigned = remaining_fee if index == len(allocations)-1 else entry_fee*amount//qty
                remaining_fee -= assigned
                fees = assigned+amount*rate//10
                orders.append([row, row-1, 0, -1, amount, args[2][row], reason, 0])
                trades.append([2, row, 1, amount, entry, args[2][row], value, fees, value-fees,
                               0, 0, 4, reason, 2, 0])
            orders, trades = np.array(orders, float), np.array(trades, float)
            curve = np.zeros((len(args[0]), 4))
            curve[2:4, 1] = qty
            if args[17] != 1:
                curve[4:6, 1] = qty-qty//2
            curve[-1] = [sum(trades[:, 8]), 0, sum(trades[:, 7]), sum(trades[:, 8])]
            return orders, trades, curve

        try:
            run.HERE, run.read, run.save = storage, reader, saver
            run.sources = lambda: source_map
            run.reference = lambda p: dict(path=str(p), sha256="人工資料")
            run.night_exit130.simulate = substitute
            np.savez_compressed = archiver
            sys.argv = ["接続人工", "--round", "人工"]
            run.main()
        finally:
            (run.HERE, run.read, run.save, run.reference, run.sources,
             run.night_exit130.simulate, np.savez_compressed, sys.argv) = original
        assert calls == [(c["id"], s) for c in configs for s in ("TOPIX", "NK225")]
        data = saves["全条件の会計.json"]
        assert len(data["rows"]) == 12 and len(archives) == 2
        assert all(row["entries"] == 1 and row["quantity"] in (5, 10) for row in data["rows"])
        assert all(set(values) == {c["id"]+"__"+name for c in configs
                                  for name in ("orders", "trades", "curve")} for _, values in archives)
        assert all(values[c["id"]+"__trades"].shape[1] == 15
                   for _, values in archives for c in configs)
    check("実main六条件二商品へ正常BBO原行と15列親番号を接続", connection)

    after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert before == after
    passed = all(x["合格"] for x in checks)
    destination = HERE/f"第一巡六条件の接続と親合算の独立人工_{time.time_ns()}.json"
    destination.write_text(json.dumps(dict(
        passed=passed, tests=checks, sources=after, financial_replays=0, api_calls=0,
        input_scope="架空packetと架空注文。実入力目録と生板は読み込まない",
    ), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=passed, cases=len(checks), path=str(destination),
                          failures=[x for x in checks if not x["合格"]]), ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
