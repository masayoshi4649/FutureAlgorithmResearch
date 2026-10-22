"""第二巡の独立接続検査を第四巡の21引数へ拡張する。旧検査源は変更しない。"""

from copy import deepcopy
import json
from pathlib import Path
import pickle
import sys
import time
import numpy as np
from check_activity_entry130 import fixture, activities

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]

def connection(runner, configs):
        """
        機能: 実mainへ架空packetと代用核を接続して全21引数と保存を照合する。
        引数: runner(module)、configs(list[dict])は第四巡の接続対象。
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
                    runner.night_budget130.simulate, np.savez_compressed, sys.argv[:])

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
            引数: args(tuple)は実mainの21引数。
            返り値: tuple[ndarray,...]は空注文・空返済・ゼロ時価。
            """
            config = configs[len(calls)//2]
            symbol = ("TOPIX", "NK225")[len(calls) % 2]
            inputs, markets, history, _ = expected[config["price_source"]]
            ready = inputs[scene, symbol]
            quote = packet["quotes"][scene, symbol]
            wanted = (ready["time_s"], ready["last"], quote["bid"], quote["ask"], quote["quote_valid"],
                      ready["atr"], history[scene, symbol], markets[scene, symbol])
            assert len(args) == 21
            for left, right in zip(args[:8], wanted):
                np.testing.assert_array_equal(left, right)
            top = symbol == "TOPIX"
            assert tuple(args[8:15]) == (ready["start"], ready["limit"], ready["us_open"],
                ready["tick"], 5 if top else 10, 1000. if top else 10., 418 if top else 110)
            np.testing.assert_array_equal(args[15], [config[k] for k in runner.PARAMETERS])
            assert tuple(args[16:18]) == (config["retest_mode"], 0)
            np.testing.assert_array_equal(args[18], data[symbol])
            assert args[19] == 1 and args[20] == config["budget_mode"]
            calls.append((config["id"], symbol))
            return np.zeros((0, 8)), np.zeros((0, 15)), np.zeros((n, 4))

        try:
            runner.read, runner.save = reader, saver
            runner.sources = lambda: source_map
            runner.ACTIVITY_MANIFEST = manifest_path
            runner.validate_manifest = validate
            runner.reference = reference
            runner.night_budget130.simulate = substitute
            np.savez_compressed = archiver
            sys.argv = ["独立接続", "--round", storage.relative_to(WORK).as_posix()]
            runner.main()
        finally:
            (runner.HERE, runner.read, runner.save, runner.reference, runner.sources,
             runner.ACTIVITY_MANIFEST, runner.validate_manifest,
             runner.night_budget130.simulate, np.savez_compressed, sys.argv) = original
        assert calls == [(c["id"], s) for c in configs for s in ("TOPIX", "NK225")]
        result = saves["全条件の会計.json"]
        assert len(result["rows"]) == 4 and len(archives) == 2
        assert all(r["entries"] == 0 and r["net"] == 0 for r in result["rows"])
        assert saves["活動原行の接続確認.json"]["products"] == 2
        assert all(set(values) == {c["id"]+"__"+name for c in configs
                                  for name in ("orders", "trades", "curve")} for _, values in archives)
