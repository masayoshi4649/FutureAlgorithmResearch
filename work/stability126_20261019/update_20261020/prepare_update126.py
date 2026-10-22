"""追加二場だけを、旧Ｅ０１の原時計資格と同じ数値源で非金融準備する。"""

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
TASK = HERE.parent
ROOT = HERE.parents[2]
ENGINE = HERE / "engine"
CONSUMER = ENGINE / "legacy_root"
SCENES = ("2026-10-19_Night", "2026-10-20_Day")


def digest(path: Path) -> str:
    """
    機能: 所有資料又は数値源の内容指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 今回所有域の未使用位置へ有限ＪＳＯＮを保存する。
    引数: path(Path)、value(dict)は保存位置と内容。
    返り値: None。過去の結果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_copy() -> None:
    """
    機能: 凍結済み数値源と小設定だけを完全同一バイトで今回所有域へ複写する。
    引数: なし。
    返り値: None。市場データ、旧会計およびＪＩＴをコピーしない。
    """
    target = HERE / "数値源の同bytes接続.json"
    assert not target.exists() and not ENGINE.exists()
    origin = TASK / "engine"
    paths = sorted(origin.rglob("*.py")) + [origin / "legacy_root" / name for name in (
        "work/wave_v27/hierarchy_design_fixed.json", "work/wave_v38/探索条件の固定.json",
        "work/wave_v44/探索条件の固定.json")]
    records = []
    for path in paths:
        copied = ENGINE / path.relative_to(origin)
        copied.parent.mkdir(parents=True, exist_ok=True)
        payload = path.read_bytes()
        copied.write_bytes(payload)
        assert digest(copied) == hashlib.sha256(payload).hexdigest()
        records.append(dict(source=path.relative_to(ROOT).as_posix(), path=copied.relative_to(ROOT).as_posix(),
                            sha256=digest(copied)))
    save(target, dict(passed=True, files=records, numerical_change=False, financial_replays=0))
    print("旧数値源と小設定を同bytesで接続", len(records), "ファイル", flush=True)


def module(name: str, path: Path) -> object:
    """
    機能: 指定した既存の入力資格実装だけを固有名で読み込む。
    引数: name(str)、path(Path)はモジュール名と位置。
    返り値: objectは読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def original_function(path: Path, name: str, namespace: dict) -> object:
    """
    機能: 元実装の指定した関数を、文を変更せず純粋な名前空間へ接続する。
    引数: path(Path)、name(str)、namespace(dict)は元源・関数名・必要な依存。
    返り値: objectは同じＡＳＴの関数。
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    functions = [v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name == name]
    assert len(functions) == 1, name
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), str(path), "exec"), namespace)
    return namespace[name]


def prepare() -> None:
    """
    機能: 原時計表示、元入力・信号・Ｇ入口許可と気配を、追加二場だけ保存する。
    引数: なし。
    返り値: None。紙上売買と実売買の金融再生は開始しない。
    """
    target = HERE / "追加二場の非金融入力準備.json"
    assert not target.exists() and not (HERE / "準備開始.json").exists()
    material = json.loads((HERE / "終了済み追加二場の取得.json").read_text(encoding="utf-8"))
    copied = json.loads((HERE / "数値源の同bytes接続.json").read_text(encoding="utf-8"))
    assert material["passed"] and material["sessions"] == list(SCENES)
    for item in copied["files"]:
        assert digest(ROOT / item["path"]) == item["sha256"] == digest(ROOT / item["source"])
    sources = {item["path"]: item["sha256"] for item in copied["files"]}
    previous_adapter = ROOT / "work/stability124_20261019/e01c"
    for path in (Path(__file__), previous_adapter / "clock_adapter.py", previous_adapter / "csv_view124.py",
                 previous_adapter / "adapter_v6.py", TASK / "input_audit/prepare126.py", TASK / "rearm126/adapter126.py"):
        sources[path.relative_to(ROOT).as_posix()] = digest(path)
    save(HERE / "準備開始.json", dict(financial_replays=0, started_ns=time.time_ns(), sources=sources,
                                     material_sha256=digest(HERE / "終了済み追加二場の取得.json")))
    clock = module("clock_adapter", previous_adapter / "clock_adapter.py")
    csv_view = module("csv_view124", previous_adapter / "csv_view124.py")
    bounds = original_function(previous_adapter / "adapter_v6.py", "bounds", dict(datetime=datetime, timedelta=timedelta, timezone=timezone))
    logs = []
    for item in material["files"]:
        origin = ROOT / item["path"]
        relative = origin.relative_to(HERE / "stage")
        scene = origin.stem
        assert scene in SCENES
        start, end = bounds(scene)
        destination = CONSUMER / relative
        if relative.parts[0] == "book":
            proof = clock.write_view(origin, destination, item["sha256"], start, end)
        else:
            payload = origin.read_bytes()
            proof = csv_view.write(payload, destination, item["sha256"], start, end)
            proof["clock_check"] = clock.validate_csv(destination, start, end)
        logs.append(dict(path=destination.relative_to(ROOT).as_posix(), session=scene,
                         symbol=relative.parts[1], kind=relative.parts[0], qualification=proof,
                         source_path=item["path"], source_sha256=item["sha256"]))
        print(scene + " " + "/".join(relative.parts[:2]) + " の旧時計資格を確認", flush=True)
    save(HERE / "追加十二素材のconsumer資格表示.json", dict(passed=True, read_log=logs, financial_replays=0))

    # ----------------------------------------
    # 同bytes数値源を接続し、入力特徴と公開時計を確認する。
    sys.path.insert(0, str(ENGINE))
    import source126
    source126.ROOT = ROOT
    import legacy126 as legacy
    import policy126 as policy
    sys.path.insert(0, str(TASK / "rearm126"))
    import adapter126 as adapter
    legacy.CACHE = str(HERE / "jit_prepare")
    namespace = dict(np=np, hashlib=hashlib, policy=policy)
    support = TASK / "input_audit/prepare126.py"
    helpers = {name: original_function(support, name, namespace) for name in
               ("array_digest", "quote_mapping", "ready_record", "market_prefix")}
    packets = []
    with legacy.isolated(discover=False):
        runtime = legacy.runtime()
        assert runtime["extractor"].ROOT == CONSUMER
        for scene in SCENES:
            folder = CONSUMER / "work/update_20261020_prepared" / scene
            folder.mkdir(parents=True, exist_ok=False)
            runtime["extractor"].HERE = folder
            inputs, depth = runtime["extractor"].extract(scene)
            signals = runtime["extractor"].signal_audit(inputs, depth)
            signal_proof = json.loads((folder / "信号監査.json").read_text(encoding="utf-8"))
            assert signal_proof["全合格"]
            features = policy.original_features(runtime, inputs, signals)
            markets = policy.make_market(inputs)
            prefix = helpers["market_prefix"](inputs, markets)
            quotes = {}
            for key, ready in inputs.items():
                with np.load(folder / "features" / f"約定系列_{key[1]}_{scene}.npz", allow_pickle=False) as archive:
                    quotes[key] = helpers["quote_mapping"](ready, dict(archive))
                assert np.any(quotes[key]["quote_valid"] & (ready["time_s"] > ready["limit"]))
            packet = dict(session=scene, inputs=inputs, signals=signals, features=features,
                          markets=markets, quotes=quotes)
            gated_features = adapter.make_gate(runtime, packet, CONSUMER)
            packet["gates"] = {key: value["gate"] for key, value in gated_features.items()}
            records = [helpers["ready_record"](ready) for ready in inputs.values()]
            path = HERE / "prepared" / (scene + ".pkl")
            assert not path.exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = pickle.dumps(packet, protocol=5)
            path.write_bytes(payload)
            reference = dict(session=scene, path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest(),
                             bytes=len(payload), accounts=records, market_prefix=prefix,
                             signal_causal_audit=signal_proof, financial_replays=0)
            save(path.with_suffix(".json"), reference)
            packets.append(reference)
            print(scene + " の元入力・両市場特徴・Ｇ許可・同原行ＢＢＯを保存", flush=True)
    assert all(digest(ROOT / name) == value for name, value in sources.items())
    save(target, dict(passed=True, sessions=list(SCENES), packets=packets, sources=sources,
                      consumer_root=CONSUMER.relative_to(ROOT).as_posix(),
                      source_copy=dict(path=(HERE / "数値源の同bytes接続.json").relative_to(ROOT).as_posix(),
                                       sha256=digest(HERE / "数値源の同bytes接続.json")),
                      read_log=logs, financial_replays=0, API=0, real_orders=0,
                      conditions_changed=False, previous_sessions_replayed=0))
    print("追加二場四商品場の非金融準備が完了", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-only", action="store_true")
    args = parser.parse_args()
    source_copy() if args.sources_only else prepare()
