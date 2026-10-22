"""00131の採用済み条件だけを追加場へ接続する。実行前の登録と内容指紋を必須とする。"""

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, time
import hashlib
import importlib
import json
import os
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "work/daynight128_20261020"
PREV = ROOT / "work/visual_pdca129_20261020"
STUDY = ROOT / "work/regime131_20261020"
ENGINE = ROOT / "work/stability126_20261019/engine"
REARM = ROOT / "work/stability126_20261019/rearm126"
OLD_RESULT = STUDY / "公開候補の43場統合.json"
SELECTION = {"Day": {"TOPIX": "round3::T06", "NK225": "round3::T06"},
             "Night": {"TOPIX": "round3::T04", "NK225": "round4::U06"}}
PARAMETERS = ("mode", "stop", "trail_start", "trail_width", "phase", "cooldown",
              "entry_bounce", "opening_buffer", "minimum_efficiency", "band_distance",
              "entry_confirm", "exit_mode", "rearm", "maximum_extension")
ORDER_FIELDS = ("約定原行", "判断原行", "親番号", "売買方向", "枚数", "価格", "理由番号", "新規", "料金", "約定時計", "判断時計", "時間帯")


def read(path):
    """
    機能: 指定JSONを読み取る。
    引数: path(Path又はstr)は保存位置。
    返り値: dict又はlistは内容。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def reference(path):
    """
    機能: 原実装・入力・比較資料の内容指紋を求める。
    引数: path(Path又はstr)はプロジェクト内の保存位置。
    返り値: dict[str,str]は相対位置とSHA256。
    """
    path = Path(path).resolve()
    assert path.is_relative_to(ROOT)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    """
    機能: 今回の所有域へJSONを新規保存する。
    引数: path(Path)、value(dict又はlist)は保存先と内容。
    返り値: None。旧測定・原入力は上書きしない。
    """
    path = Path(path).resolve()
    assert path.is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def original_functions(path, names, namespace):
    """
    機能: 主処理の保存先変更を避け、旧実装の必要関数だけを同じASTで読み込む。
    引数: path(Path)、names(tuple[str])、namespace(dict)は元実装と必要依存。
    返り値: dict[str,callable]は計算式を変更しない関数。
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(path), "exec"), namespace)
    return {name: namespace[name] for name in names}


def configurations():
    """
    機能: 旧固定計画から採用済み4系統だけを取得する。
    引数: なし。
    返り値: dictは主担当と追加担当の固定条件。新場の成績で選び直さない。
    """
    output = {}
    for kind in ("Day", "Night"):
        for symbol in ("TOPIX", "NK225"):
            if kind == "Day":
                folder, identifier = "day_round2", "DV07" if symbol == "TOPIX" else "DV05"
            else:
                folder, identifier = ("round1", "NV01") if symbol == "TOPIX" else ("round7", "NV25")
            cores = read(PREV / folder / "固定計画.json")["configs"]
            core = next(item for item in cores if item["id"] == identifier)
            extra_folder, extra_id = SELECTION[kind][symbol].split("::")
            extras = read(STUDY / extra_folder / "固定計画.json")["configs"]
            extra = next(item for item in extras if item["id"] == extra_id)
            output[kind + ":" + symbol] = {"core": core, "extra": extra}
    return output


def source_fingerprints():
    """
    機能: 使用数値源・小設定・固定計画・旧公開結果を登録用に固定する。
    引数: なし。
    返り値: dict[str,str]は位置と内容指紋。
    """
    paths = [Path(__file__), REARM / "adapter126.py"] + list(ENGINE.rglob("*.py"))
    paths += [ENGINE / "legacy_root" / item for item in (
        "work/wave_v27/hierarchy_design_fixed.json", "work/wave_v38/探索条件の固定.json", "work/wave_v44/探索条件の固定.json")]
    paths += [BASE / name for name in ("common128.py", "features128.py", "prepare128.py", "adapter5.py", "day_core2.py", "night5.py", "bbo_order_kernel126.py")]
    paths += [PREV / name for name in ("common129.py", "features129.py", "day129b.py", "night_retest129c.py", "bbo_order_kernel126.py")]
    paths += [STUDY / name for name in ("common131.py", "features131.py", "baseline131.py", "run_exit131.py", "participation_exit131.py", "participation_risk131.py")]
    paths += [PREV / folder / "固定計画.json" for folder in ("day_round2", "round1", "round7")]
    paths += [STUDY / folder / "固定計画.json" for folder in ("round3", "round4")]
    paths += [OLD_RESULT]
    return {item["path"]: item["sha256"] for item in (reference(path) for path in sorted(set(paths)))}


def validate_packet(packet, scene):
    """
    機能: 原行対応・公開特徴・終端の次正常行が揃うことを再生前に確認する。
    引数: packet(dict)、scene(str)は固定入力と場ID。
    返り値: None。不足場を零収支や最終値による強制利確へ置換しない。
    """
    assert packet["session"] == scene
    keys = {(scene, symbol) for symbol in ("TOPIX", "NK225")}
    for field in ("inputs", "signals", "features", "markets", "quotes", "gates"):
        assert set(packet[field]) == keys, field
    for key in keys:
        ready, quotes = packet["inputs"][key], packet["quotes"][key]
        n = len(ready["time_s"])
        assert n > 0 and ready["session"] == scene and ready["symbol"] == key[1]
        assert np.isfinite(ready["time_s"]).all() and (np.diff(ready["time_s"]) >= 0).all()
        assert (np.diff(ready["seq"]) > 0).all()
        for field in ("seq", "time_s"):
            np.testing.assert_array_equal(ready[field], quotes[field])
        for field in ("last", "atr"):
            assert np.asarray(ready[field]).shape == (n,)
        for field in ("bid", "ask", "quote_valid"):
            assert np.asarray(quotes[field]).shape == (n,)
        normal = quotes["quote_valid"] & np.isfinite(quotes["bid"]) & np.isfinite(quotes["ask"]) & (quotes["bid"] > 0) & (quotes["ask"] > quotes["bid"])
        assert np.any(normal & (ready["time_s"] > ready["limit"])), (scene, key[1], "場内返済期限後の正常気配不足")
        assert np.asarray(packet["gates"][key]).dtype == np.dtype(bool)
        assert np.asarray(packet["gates"][key]).shape == (n,)
        assert np.asarray(packet["markets"][key]).shape == (n, 12)
        assert len(packet["features"][key]["columns"]) == 10
        assert all(np.asarray(value).shape == (n,) for value in packet["features"][key]["columns"])


@contextmanager
def modules(cache):
    """
    機能: 元Pythonを変更せず接続し、通信禁止・JIT保存先を今回域へ限定する。
    引数: cache(Path)は今回のJIT保存先。
    返り値: contextmanager[dict]は既存数値核と同ASTの会計関数。
    """
    old_path, old_bytecode = list(sys.path), sys.dont_write_bytecode
    old_env = os.environ.get("NUMBA_CACHE_DIR")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ENGINE), str(REARM), str(STUDY), str(PREV), str(BASE)]
    import numba
    old_cache = numba.config.CACHE_DIR
    numba.config.CACHE_DIR = str(cache)
    os.environ["NUMBA_CACHE_DIR"] = str(cache)
    legacy = importlib.import_module("legacy126")
    legacy.CACHE = str(cache)
    names = ("policy126", "adapter126", "features128", "features129", "features131", "baseline131",
             "adapter5", "day129b", "night5", "night_retest129c", "participation_exit131", "participation_risk131")
    loaded = {name: importlib.import_module(name) for name in names}
    loaded["adapter126"].ENGINE = ENGINE
    namespace = {"np": np, "datetime": datetime, "time": time, "features131": loaded["features131"]}
    loaded.update(original_functions(STUDY / "run_exit131.py", ("activation", "standardize", "combine"), namespace))
    loaded.update(original_functions(BASE / "prepare128.py", ("q_feed",), {"np": np}))
    try:
        with legacy.isolated(discover=False):
            loaded["runtime"] = legacy.runtime()
            yield loaded
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode
        numba.config.CACHE_DIR = old_cache
        if old_env is None:
            os.environ.pop("NUMBA_CACHE_DIR", None)
        else:
            os.environ["NUMBA_CACHE_DIR"] = old_env


def core_orders(loaded, packet, symbol, config, history):
    """
    機能: 指定場の採用主担当だけを元数値核で再生する。
    引数: loaded/packet/config(dict)、symbol(str)、history(dict)は依存・固定入力・固定条件・日中履歴。
    返り値: tuple[ndarray,dict]は8列注文と紙上通知等の監査配列。
    """
    scene = packet["session"]
    key = scene, symbol
    ready, quotes = packet["inputs"][key], packet["quotes"][key]
    if scene.endswith("_Day"):
        rt = loaded["runtime"]
        loaded["policy126"].bind_runtime(rt, packet["inputs"], packet["signals"])
        feature = dict(packet["features"][key], gate=packet["gates"][key])
        paper, _ = loaded["adapter126"].play(rt, {"id": "E01_G", "mask": 1, "time_mode": ""}, ready, feature)
        feed = loaded["q_feed"](paper, ready, quotes)
        market = packet["markets"][key]
        accepted = loaded["adapter5"].day_filter(feed, ready, market, history[key], 5)
        result = loaded["day129b"].simulate(ready["time_s"], ready["last"], quotes["bid"], quotes["ask"],
            quotes["quote_valid"], accepted, ready["limit"], 10 if symbol == "TOPIX" else 20,
            market, np.array([0., .5, 0., 0., .75, .5]), ready["atr"], history[key], 1,
            config["withdrawal_width"], config["allow_reentry"], config["withdrawal_persistence_seconds"])
        return result[0], {"paper_orders": paper["orders"], "paper_cycles": paper["cycles"], "accepted_feed": accepted}
    inputs, markets, histories, _ = loaded["features129"].build(packet, config["price_source"], config["peer_delay"])
    ready = inputs[key]
    top = symbol == "TOPIX"
    args = (ready["time_s"], ready["last"], quotes["bid"], quotes["ask"], quotes["quote_valid"],
            ready["atr"], histories[key], markets[key], ready["start"], ready["limit"], ready["us_open"], ready["tick"],
            5 if top else 10, 1000. if top else 10., 418 if top else 110,
            np.array([config[name] for name in PARAMETERS], dtype=float))
    if top:
        orders, trades, _ = loaded["night5"].simulate(*args)
    else:
        orders, trades, _ = loaded["night_retest129c"].simulate(*args, config["retest_mode"])
    return orders, {"core_native_trades": trades}


def replay(loaded, packet, configs):
    """
    機能: 同じ原行上で主担当と一回追加を合算し、方向別枚数・全返済・費用を検査する。
    引数: loaded/packet/configs(dict)は依存・一場入力・採用条件。
    返り値: list[tuple[dict,dict]]は二商品の会計行と監査配列。
    """
    scene = packet["session"]
    kind = scene.rsplit("_", 1)[1]
    inputs, _, extra_history, phases = loaded["features131"].build(packet)
    day_history = loaded["features128"].build(packet) if kind == "Day" else None
    results = []
    for symbol in ("TOPIX", "NK225"):
        key = scene, symbol
        chosen = configs[kind + ":" + symbol]
        ready, quotes = inputs[key], packet["quotes"][key]
        top = symbol == "TOPIX"
        multiplier, fee = (1000., 41.8) if top else (10., 11.)
        orders, audit = core_orders(loaded, packet, symbol, chosen["core"], day_history)
        ledger = loaded["baseline131"].revalue(ready["time_s"], quotes["bid"], quotes["ask"], quotes["quote_valid"], orders, multiplier, fee)
        saved = {"orders": orders, "fee": fee}
        co, ct = loaded["standardize"](saved, ledger, ready, phases[key])
        core = co, ct, ledger, chosen["core"]["id"]
        starts = np.diff(np.r_[0, ledger["entries_so_far"]]).astype(np.int64)
        extra = chosen["extra"]
        args = (ready["time_s"], quotes["bid"], quotes["ask"], quotes["quote_valid"], ready["atr"],
                extra_history[key], phases[key], starts, loaded["activation"](ready, extra["schedule"]),
                ready["limit"], ready["tick"], 5 if top else 10, multiplier, fee,
                extra["style"], extra["trail_start"], extra["trail_width"])
        if "budget_ticks" in extra:
            actual = loaded["participation_risk131"].simulate(*args, extra["budget_ticks"])
        else:
            actual = loaded["participation_exit131"].simulate(*args)
        row, arrays = loaded["combine"](core, actual, ready, phases[key], extra)
        row["selected_round"] = SELECTION[kind][symbol].split("::")[0]
        row["session_start"], row["force_close"] = float(ready["start"]), float(ready["limit"])
        arrays.update(audit)
        arrays["input_seq"] = packet["inputs"][key]["seq"]
        arrays["input_time_s"] = ready["time_s"]
        np.testing.assert_allclose(row["profit"] - row["loss"], row["net"], rtol=0, atol=1e-7)
        assert row["max_long"] <= (10 if top else 20) and row["max_short"] <= (10 if top else 20)
        results.append((row, arrays))
    return results


def compare_golden(row, arrays):
    """
    機能: 既存一場の再現結果を00131の公開採用列と全注文で照合する。
    引数: row(dict)、arrays(dict[str,ndarray])は新計算の一商品場。
    返り値: dictは元参照と照合結果。新しい優位性の証拠とは扱わない。
    """
    old = read(OLD_RESULT)
    found = [item for item in old["rows"] if item["session"] == row["session"] and item["symbol"] == row["symbol"]]
    assert len(found) == 1
    prior = found[0]
    for field in ("profit", "loss", "net", "gross", "fees", "entries", "quantity", "max_long", "max_short"):
        np.testing.assert_allclose(row[field], prior[field], rtol=0, atol=1e-7, err_msg=field)
    folder, method = SELECTION[row["kind"]][row["symbol"]].split("::")
    account = read(STUDY / folder / "全条件の会計.json")
    ref = next(item for item in account["cache"] if item["session"] == row["session"] and item["symbol"] == row["symbol"])
    assert reference(ROOT / ref["path"])["sha256"] == ref["sha256"]
    fields = ("orders", "trades", "curve", "long_quantity", "short_quantity", "core_orders", "core_trades", "extra_orders", "extra_trades", "extra_curve")
    with np.load(ROOT / ref["path"], allow_pickle=False) as archive:
        for field in fields:
            np.testing.assert_allclose(arrays[field], archive[method + "__" + field], rtol=0, atol=1e-7, equal_nan=True, err_msg=field)
    return {"passed": True, "session": row["session"], "symbol": row["symbol"], "reference": ref,
            "fields": list(fields), "scope": "固定条件の移植接続の同値検査。新たな有効性の証拠に数えない。"}


def execute(args):
    """
    機能: 登録・指紋一致後に指定追加場だけを再生し、旧43場の結果を変更せず保存する。
    引数: args(argparse.Namespace)はCLI入力。
    返り値: None。未登録・入力不足・再利用済み出力は拒否する。
    """
    plan, registered = read(args.plan), read(args.registered)
    assert registered["returncode"] == 0, "正式登録が成功していません"
    assert plan["sources"] == source_fingerprints(), "固定した数値源と異なります"
    assert plan["input_manifest"] == reference(args.manifest)
    assert plan["selection"] == SELECTION and plan["configs"] == configurations()
    scenes = sorted(set(args.session))
    assert scenes == sorted(plan["sessions"]) and len(scenes) == len(args.session)
    assert plan["mode"] == ("golden" if args.golden else "additional")
    manifest = read(args.manifest)
    refs = {item["session"]: item for item in manifest["packets"]}
    assert all(scene in refs for scene in scenes)
    prior_scenes = {row["session"] for row in read(OLD_RESULT)["rows"]}
    assert all((scene in prior_scenes) == args.golden for scene in scenes)
    folder = args.output.resolve()
    assert folder.is_relative_to(HERE) and not folder.exists(), folder
    folder.mkdir(parents=True)
    save(folder / "金融実行開始.json", {"sessions": scenes, "mode": plan["mode"], "plan": reference(args.plan),
         "registered": reference(args.registered), "API": 0, "real_orders": 0})
    rows, cache, proofs = [], [], []
    with modules(folder / "jit") as loaded:
        for scene in scenes:
            ref = refs[scene]
            path = ROOT / ref["path"]
            payload = path.read_bytes()
            assert hashlib.sha256(payload).hexdigest() == ref["sha256"]
            packet = pickle.loads(payload)
            validate_packet(packet, scene)
            for row, arrays in replay(loaded, packet, plan["configs"]):
                if args.golden:
                    proofs.append(compare_golden(row, arrays))
                target = folder / "measurement" / (row["symbol"] + "_" + scene + ".npz")
                target.parent.mkdir(exist_ok=True)
                assert not target.exists()
                np.savez_compressed(target, **arrays)
                rows.append(row)
                cache.append({"session": scene, "symbol": row["symbol"], **reference(target)})
            print(scene + " 固定2商品の再生完了", flush=True)
    assert source_fingerprints() == plan["sources"], "数値源が実行中に変わりました"
    save(folder / "追加セッションの会計.json", {"passed": True, "rows": rows, "cache": cache,
        "selection": SELECTION, "configs": plan["configs"], "sources": plan["sources"],
        "input_manifest": reference(args.manifest), "input_packets": [refs[s] for s in scenes],
        "prior_result": reference(OLD_RESULT), "golden": proofs, "orders_columns": ORDER_FIELDS,
        "API": 0, "real_orders": 0, "fees": "立会手数料込み・注文ごと1円未満切捨て・親単位利益損失",
        "limitations": ["ラージ次正常原行BBOでmini/micro約定を代理", "原価格時計であり実受信時計を再現しない", "場頭起動の固定条件、Goアプリの実約定結果ではない"]})


def main():
    """
    機能: 登録用の非金融仕様表示、又は登録済み固定条件の実行を選択する。
    引数: CLIは--describe、又は--manifest/--session/--output/--plan/--registeredを指定。
    返り値: None。--goldenは旧一場の同値確認に限定する。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--session", action="append")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--registered", type=Path)
    parser.add_argument("--golden", action="store_true")
    args = parser.parse_args()
    if args.describe:
        print(json.dumps({"selection": SELECTION, "configs": configurations(), "sources": source_fingerprints(), "financial_replays": 0}, ensure_ascii=False, indent=2))
        return
    if any(getattr(args, name) is None for name in ("manifest", "session", "output", "plan", "registered")):
        parser.error("実行には--manifest/--session/--output/--plan/--registeredが必要です")
    execute(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
