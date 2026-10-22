"""00131固定手法の追加場用に、旧126と同じ原時計・公開時計で非金融入力だけを作る。"""

import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "work/stability126_20261019"
PREVIOUS = OLD / "update_20261020"
ADAPTER = ROOT / "work/stability124_20261019/e01c"
INVENTORY = ROOT / "work/selected131_input_audit_20261021/最新素材の棚卸し.json"
SESSIONS = ("2026-10-20_Night", "2026-10-21_Day")
sys.dont_write_bytecode = True


def digest(path: Path) -> str:
    """
    機能: ファイル内容の同一性を確認する指紋を計算する。
    引数: path(Path)は原本又は所有資料。
    返り値: strはSHA256。対象を変更しない。
    """
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def read(path: Path) -> dict:
    """
    機能: 既存の小さなJSON目録を読む。
    引数: path(Path)は目録位置。
    返り値: dictは目録内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: dict) -> None:
    """
    機能: 本作業所有域へ、既存成果を上書きせず有限JSONを保存する。
    引数: path(Path)、value(dict)は保存位置と値。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def original_function(path: Path, name: str, namespace: dict) -> object:
    """
    機能: 旧実装の必要な関数だけを同じASTで接続する。
    引数: path(Path)、name(str)、namespace(dict)は数値源・関数名・依存。
    返り値: objectは式や条件を変更しない元関数。
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(functions) == 1, name
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), str(path), "exec"), namespace)
    return namespace[name]


def module(name: str, path: Path) -> object:
    """
    機能: 保存済みの入力資格モジュールを読む。
    引数: name(str)、path(Path)は登録名と数値源。
    返り値: objectは読み込んだモジュール。金融関数は実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def select_materials(inventory: dict, sessions: tuple[str, ...]) -> list[dict]:
    """
    機能: 棚卸し済みの追加場12素材だけを選び、種類・二市場・終端資格を確認する。
    引数: inventory(dict)、sessions(tuple[str,...])は棚卸しと追加場。
    返り値: list[dict]はセッション・商品・区分を付けた指紋付き原本一覧。
    """
    assert set(sessions) <= set(inventory["new_complete_file_sets"])
    selected = []
    for scene in sessions:
        for symbol in ("TOPIX", "NK225"):
            for category, suffix in (("book", ".jsonl"), ("candle_1min", ".csv"), ("candle_5min", ".csv")):
                relative = f"{category}/{symbol}/{scene}{suffix}"
                matches = [row for row in inventory["materials"] if row["path"] == relative]
                assert len(matches) == 1, relative
                item = dict(matches[0], session=scene, symbol=symbol, kind=category)
                assert item["unchanged_during_read"]
                if category == "book":
                    assert item["reaches_force_close"], relative
                source = ROOT / relative
                stat = source.stat()
                assert (stat.st_size, stat.st_mtime_ns) == (item["bytes"], item["mtime_ns"]), relative
                selected.append(item)
    assert len(selected) == len(sessions) * 6
    return selected


def copy_fixed_sources(output: Path) -> dict:
    """
    機能: 旧43場に使用した凍結指紋と一致する数値源を新所有域へ同bytes複写する。
    引数: output(Path)は本作業内の未使用出力領域。
    返り値: dictはコピー対応・補助源・元固定目録の指紋。
    """
    fixed_path = PREVIOUS / "数値源の同bytes接続.json"
    previous_path = PREVIOUS / "追加二場の非金融入力準備.json"
    fixed, previous = read(fixed_path), read(previous_path)
    assert fixed["passed"] and previous["passed"]
    copied = []
    sources = {}
    for item in fixed["files"]:
        source = ROOT / item["source"]
        assert source.resolve().is_relative_to(OLD / "engine")
        target = output / "engine" / source.relative_to(OLD / "engine")
        assert not target.exists()
        payload = source.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item["sha256"], str(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
        assert digest(target) == item["sha256"]
        sources[target.relative_to(ROOT).as_posix()] = item["sha256"]
        copied.append(dict(source=item["source"], path=target.relative_to(ROOT).as_posix(), sha256=item["sha256"]))
    for path in (ADAPTER / "clock_adapter.py", ADAPTER / "csv_view124.py", ADAPTER / "adapter_v6.py",
                 OLD / "input_audit/prepare126.py", OLD / "rearm126/adapter126.py"):
        relative = path.relative_to(ROOT).as_posix()
        actual = digest(path)
        assert actual == previous["sources"][relative], relative
        sources[relative] = actual
    sources[Path(__file__).relative_to(ROOT).as_posix()] = digest(Path(__file__))
    result = dict(passed=True, files=copied, sources=sources,
                  fixed_manifest=dict(path=fixed_path.relative_to(ROOT).as_posix(), sha256=digest(fixed_path)),
                  previous_prepare=dict(path=previous_path.relative_to(ROOT).as_posix(), sha256=digest(previous_path)),
                  numerical_change=False, financial_replays=0, API=0, real_orders=0)
    save(output / "source_manifest.json", result)
    return result


def input_views(output: Path, materials: list[dict]) -> list[dict]:
    """
    機能: 原時計高水位と旧場内窓だけで、原seqを保持したconsumer表示を作る。
    引数: output(Path)、materials(list[dict])は所有出力と指紋照合済み原本一覧。
    返り値: list[dict]は原本・表示の指紋と採否監査。原本へ書き込まない。
    """
    consumer = output / "engine/legacy_root"
    clock = module("clock_adapter", ADAPTER / "clock_adapter.py")
    csv_view = module("csv_view124", ADAPTER / "csv_view124.py")
    bounds = original_function(ADAPTER / "adapter_v6.py", "bounds",
                               dict(datetime=datetime, timedelta=timedelta, timezone=timezone))
    logs = []
    for item in materials:
        source = ROOT / item["path"]
        before = source.stat()
        start, end = bounds(item["session"])
        destination = consumer / item["path"]
        if item["kind"] == "book":
            proof = clock.write_view(source, destination, item["sha256"], start, end)
        else:
            proof = csv_view.write(source.read_bytes(), destination, item["sha256"], start, end)
            proof["clock_check"] = clock.validate_csv(destination, start, end)
        after = source.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) == (item["bytes"], item["mtime_ns"])
        logs.append(dict(path=destination.relative_to(ROOT).as_posix(), session=item["session"],
                         symbol=item["symbol"], kind=item["kind"], qualification=proof,
                         source_path=item["path"], source_sha256=item["sha256"],
                         source_bytes=item["bytes"], source_mtime_ns=item["mtime_ns"], original_reads=1))
        print(item["session"] + " " + item["kind"] + "/" + item["symbol"] + " 原時計資格確認", flush=True)
    save(output / "consumer_manifest.json", dict(passed=True, read_log=logs, financial_replays=0))
    return logs


def prepare(output: Path, sessions: tuple[str, ...], inventory_path: Path) -> None:
    """
    機能: 旧元入力・元信号・十列特徴・市場特徴・BBO・G許可だけを追加場へ生成する。
    引数: output(Path)、sessions(tuple[str,...])、inventory_path(Path)は所有先・場・棚卸し。
    返り値: None。通常影を含む金融再生・注文・API取得を一切実行しない。
    """
    assert output.resolve().is_relative_to(HERE) and not output.exists(), str(output)
    materials = select_materials(read(inventory_path), sessions)
    output.mkdir(parents=True, exist_ok=False)
    sources = copy_fixed_sources(output)
    save(output / "開始記録.json", dict(started_ns=time.time_ns(), sessions=list(sessions), financial_replays=0,
         inventory=dict(path=inventory_path.relative_to(ROOT).as_posix(), sha256=digest(inventory_path)),
         source_manifest_sha256=digest(output / "source_manifest.json")))
    logs = input_views(output, materials)
    # ----------------------------------------
    # 旧実装の所有コピーだけを接続し、キャッシュ出力も本作業域へ閉じる。
    engine, consumer = output / "engine", output / "engine/legacy_root"
    sys.path.insert(0, str(engine))
    import source126
    source126.ROOT = ROOT
    import legacy126 as legacy
    import policy126 as policy
    sys.path.insert(0, str(OLD / "rearm126"))
    import adapter126 as adapter
    legacy.CACHE = str(output / "jit_prepare")
    namespace = dict(np=np, hashlib=hashlib, policy=policy)
    helpers = {name: original_function(OLD / "input_audit/prepare126.py", name, namespace)
               for name in ("array_digest", "quote_mapping", "ready_record", "market_prefix")}
    packets = []
    with legacy.isolated(discover=False):
        runtime = legacy.runtime()
        assert runtime["extractor"].ROOT == consumer
        for scene in sessions:
            folder = consumer / "work/update132_prepared" / scene
            folder.mkdir(parents=True, exist_ok=False)
            runtime["extractor"].HERE = folder
            inputs, depth = runtime["extractor"].extract(scene)
            signals = runtime["extractor"].signal_audit(inputs, depth)
            signal_proof = read(folder / "信号監査.json")
            assert signal_proof["全合格"]
            features = policy.original_features(runtime, inputs, signals)
            markets = policy.make_market(inputs)
            prefix = helpers["market_prefix"](inputs, markets)
            quotes = {}
            for key, ready in inputs.items():
                with np.load(folder / "features" / f"約定系列_{key[1]}_{scene}.npz", allow_pickle=False) as archive:
                    quotes[key] = helpers["quote_mapping"](ready, dict(archive))
                assert np.any(quotes[key]["quote_valid"] & (ready["time_s"] > ready["limit"]))
                assert len(features[key]["columns"]) == 10
                assert all(len(column) == len(ready["last"]) for column in features[key]["columns"])
            packet = dict(session=scene, inputs=inputs, signals=signals, features=features, markets=markets, quotes=quotes)
            gated = adapter.make_gate(runtime, packet, consumer)
            packet["gates"] = {key: value["gate"] for key, value in gated.items()}
            records = [helpers["ready_record"](ready) for ready in inputs.values()]
            path = output / "prepared" / (scene + ".pkl")
            assert not path.exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = pickle.dumps(packet, protocol=5)
            with path.open("xb") as stream:
                stream.write(payload)
            record = dict(session=scene, path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest(),
                          bytes=len(payload), accounts=records, market_prefix=prefix,
                          signal_causal_audit=signal_proof, financial_replays=0)
            save(path.with_suffix(".json"), record)
            packets.append(record)
            print(scene + " 元入力・特徴・気配・入口許可の非金融準備完了", flush=True)
    assert all(digest(ROOT / name) == value for name, value in sources["sources"].items())
    for item in materials:
        stat = (ROOT / item["path"]).stat()
        assert (stat.st_size, stat.st_mtime_ns) == (item["bytes"], item["mtime_ns"])
    save(output / "input_manifest.json", dict(passed=True, sessions=list(sessions), packets=packets,
         sources=sources["sources"], source_manifest=dict(path=(output / "source_manifest.json").relative_to(ROOT).as_posix(),
         sha256=digest(output / "source_manifest.json")), consumer_root=consumer.relative_to(ROOT).as_posix(),
         read_log=logs, financial_replays=0, API=0, real_orders=0, conditions_changed=False,
         previous_sessions_replayed=0, raw_clock_repaired=False))
    print("追加入力目録: " + str(output / "input_manifest.json"), flush=True)


def main() -> None:
    """
    機能: 明示した追加場だけを非金融準備する。
    引数: 起動引数から--session/--output/--inventoryを読む。
    返り値: None。出力先の再利用は拒否する。
    """
    parser = argparse.ArgumentParser(description="00131固定候補の非金融入力準備")
    parser.add_argument("--session", action="append", choices=SESSIONS)
    parser.add_argument("--output", type=Path, default=HERE / "inputs_v1")
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    args = parser.parse_args()
    scenes = tuple(args.session or SESSIONS)
    assert len(set(scenes)) == len(scenes)
    prepare(args.output.resolve(), scenes, args.inventory.resolve())


if __name__ == "__main__":
    main()
