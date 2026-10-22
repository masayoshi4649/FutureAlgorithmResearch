"""登録済みの追加二場だけへ、既存八公開選択を条件不変で接続する。"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
ENGINE = HERE/"engine"
SESSIONS = ("2026-10-19_Night", "2026-10-20_Day")
SYMBOLS = ("TOPIX", "NK225")
PAPER_IDS = ("E01", "E01_G", "E01_G_U")
BBO_IDS = ("GU_Q", "G_Q", "E01", "G_E01", "GU_E01")
RESULT_NAME = "追加二場の八公開選択会計.json"
READS = []


def sha(path: Path) -> str:
    """
    機能: 固定資料又は完成出力の同一性を確認する。
    引数: path(Path)は対象の保存位置。
    返り値: strはＳＨＡ２５６。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 計画又は登録の小さな日本語資料を読む。
    引数: path(Path)は対象位置。
    返り値: dictはＪＳＯＮ内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: dict) -> None:
    """
    機能: 今回の所有域の未使用位置だけへ有限ＪＳＯＮを保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。旧成果及び既存測定の上書きは行わない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def bound_bytes(item: dict) -> bytes:
    """
    機能: 登録に拘束された所有入力を一読し、同じｂｙｔｅｓで指紋照合する。
    引数: item(dict)はpathとsha256を持つ参照。
    返り値: bytesは照合済み内容。原市場領域・ＡＰＩは利用しない。
    """
    path = (ROOT/item["path"]).resolve()
    assert path.is_relative_to(ROOT/"work")
    assert item["path"] not in {v["path"] for v in READS}
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == item["sha256"], item["path"]
    READS.append(dict(path=item["path"], sha256=item["sha256"], bytes=len(payload), reads=1))
    return payload


def source_map() -> dict:
    """
    機能: 変更しない旧数値源と今回の接続源を正式固定用に指紋化する。
    引数: なし。
    返り値: dict[str,str]はプロジェクト相対位置とＳＨＡ２５６。
    """
    paths = list(ENGINE.rglob("*.py"))
    paths += [ENGINE/"legacy_root"/relative for relative in (
        "work/wave_v38/探索条件の固定.json", "work/wave_v44/探索条件の固定.json",
        "work/wave_v27/hierarchy_design_fixed.json")]
    paths += [TASK/relative for relative in (
        "design/catalog126.py", "rearm126/adapter126.py",
        "gated_bbo126/catalog126g.py", "gated_bbo126/feed_filter126.py")]
    paths.append(Path(__file__))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(paths))}


def configurations() -> dict:
    """
    機能: 保存済み条件カタログから公開済み八選択だけを取得する。
    引数: なし。
    返り値: dictはpaperとbboの条件列。追加閾値や成績による選び直しを含まない。
    """
    for folder in (TASK/"design", TASK/"rearm126", TASK/"gated_bbo126",
                   ENGINE, ENGINE/"bbo_next"):
        sys.path.insert(0, str(folder))
    import source126
    assert Path(source126.__file__).resolve().is_relative_to(ENGINE)
    source126.ROOT = ROOT
    from catalog126 import catalog as original_catalog
    from catalog126g import catalog as gated_catalog
    import adapter126
    adapter126.ENGINE = ENGINE
    original = next(v for v in original_catalog() if v["id"] == "E01")
    candidates = {v["id"]: v for v in gated_catalog()}
    candidates["E01"] = dict(original, paper_source="E01", policy_id="E01", quote_gate_enabled=False)
    paper = [dict(original)] + adapter126.catalog()
    assert tuple(v["id"] for v in paper) == PAPER_IDS
    return dict(paper=paper, bbo=[candidates[name] for name in BBO_IDS])


def validate_packet(packet: dict, scene: str) -> None:
    """
    機能: 元原行・時計・気配・特徴とＧ許可列の入力契約を金融前に検査する。
    引数: packet(dict)、scene(str)は追加場の所有素材と対象名。
    返り値: None。不一致や終端不足を零収支へ変換しない。
    """
    assert packet["session"] == scene
    keys = {(scene, symbol) for symbol in SYMBOLS}
    for field in ("inputs", "quotes", "features", "markets", "gates"):
        assert set(packet[field]) == keys, field
    for key, ready in packet["inputs"].items():
        assert ready["session"] == scene and ready["symbol"] == key[1]
        n = len(ready["last"])
        assert n > 0 and float(ready["time_s"][-1]) > float(ready["limit"])
        assert np.all(np.diff(ready["seq"]) > 0) and np.all(np.diff(ready["time_s"]) >= 0)
        for name in ("seq", "time_s", "last", "atr"):
            assert np.asarray(ready[name]).shape == (n,)
        quote = packet["quotes"][key]
        for name in ("seq", "time_s"):
            np.testing.assert_array_equal(ready[name], quote[name])
        for name in ("bid", "ask", "quote_valid"):
            assert np.asarray(quote[name]).shape == (n,)
        gate = np.asarray(packet["gates"][key])
        assert gate.dtype == np.dtype(bool) and gate.shape == (n,)
        feature = packet["features"][key]
        assert len(feature["columns"]) == 10
        assert all(np.asarray(value).shape == (n,) for value in feature["columns"])
        assert np.asarray(feature["valid"]).shape == (n,)
        assert np.asarray(packet["markets"][key]).shape == (n, 12)


def guard(fixed_path: Path, registered_path: Path) -> tuple[dict, dict]:
    """
    機能: 成功登録・源・独立人工・新二場入力・旧結果の拘束を確認する。
    引数: fixed_path/registered_path(Path)は親が作成する固定計画と登録証跡。
    返り値: tuple[dict,dict]は固定計画と入力目録。金融実行は行わない。
    """
    fixed, registered = read(fixed_path), read(registered_path)
    assert registered["終了コード"] == 0
    formal = json.loads(registered["stdout"])
    assert formal["spec"]["implementation"] == fixed["sources"]
    for relative, digest in source_map().items():
        assert fixed["sources"][relative] == digest, relative
    for relative, digest in fixed["sources"].items():
        assert sha(ROOT/relative) == digest, relative
    reference = fixed["input_manifest"]
    assert sha(ROOT/reference["path"]) == reference["sha256"]
    assert reference in formal["spec"]["data"]["input_manifests"]
    manifest = read(ROOT/reference["path"])
    assert manifest["passed"] and manifest["sessions"] == list(SESSIONS)
    assert len(manifest["packets"]) == 2
    assert {p["session"] for p in manifest["packets"]} == set(SESSIONS)
    proof_reference = fixed["artificial"]
    assert sha(ROOT/proof_reference["path"]) == proof_reference["sha256"]
    proof = read(ROOT/proof_reference["path"])
    assert proof.get("passed", proof.get("全合格", False))
    for relative, digest in source_map().items():
        assert proof["sources"][relative] == digest, ("独立人工の適用源", relative)
    assert fixed["specs"] == configurations()
    assert fixed["prior_results"], "旧四十一場を再生せず保存引用する根拠が必要"
    for item in fixed["prior_results"]:
        assert sha(ROOT/item["path"]) == item["sha256"]
        previous = read(ROOT/item["path"])
        assert previous["passed"]
        assert not (set(previous["sessions"]) & set(SESSIONS)), "追加場の重複再生は禁止"
    return fixed, manifest


def summary(result: dict, ready: dict, method: str, model: str) -> dict:
    """
    機能: 保存注文・返済脚・親組から利益損失と全返済・数量上限を検査する。
    引数: result/ready(dict)、method/model(str)は完成配列と当時入力・表示識別。
    返り値: dictは手数料零の商品場別会計。利益脚と完結親を混同しない。
    """
    mult = 1000. if ready["symbol"] == "TOPIX" else 10.
    orders, trades, cycles, stats = (np.asarray(result[name]) for name in ("orders", "trades", "cycles", "stats"))
    pnl, parent = trades[:, 10]*mult, cycles[:, 3]*mult
    entry = orders[:, 7] == 1.
    new_quantity, settled_quantity = int(orders[entry, 4].sum()), int(trades[:, 3].sum())
    cap = 10 if ready["symbol"] == "TOPIX" else 20
    assert new_quantity == settled_quantity and stats[9] == 0.
    assert stats[2] <= cap and stats[3] <= cap
    assert np.isclose(pnl.sum(), parent.sum(), atol=1e-6, rtol=1e-12)
    assert np.isclose(pnl.sum(), stats[0]*mult, atol=1e-6, rtol=1e-12)
    assert np.all(orders[:, 1] < orders[:, 0])
    return dict(method=method, model=model, session=ready["session"], symbol=ready["symbol"],
        profit=float(np.maximum(pnl, 0.).sum()), loss=float(np.maximum(-pnl, 0.).sum()),
        net=float(pnl.sum()), fees=0., groups=len(cycles), entry_orders=int(entry.sum()),
        entry_quantity=new_quantity, closed_quantity=settled_quantity, unclosed=0,
        parent_profit=float(np.maximum(parent, 0.).sum()), parent_loss=float(np.maximum(-parent, 0.).sum()),
        long_net=float(pnl[trades[:, 2] > 0].sum()), short_net=float(pnl[trades[:, 2] < 0].sum()),
        max_long=float(stats[2]), max_short=float(stats[3]))


def arrays_of(value: dict, prefix: str = "") -> dict:
    """
    機能: 完成結果の入れ子に含まれる全ＮｕｍＰｙ配列を独立保存用へ展開する。
    引数: value(dict)、prefix(str)は完成結果と内部階層名。
    返り値: dict[str,ndarray]はｏｂｊｅｃｔを含まない保存配列。
    """
    output = {}
    for key, item in value.items():
        name = prefix+str(key)
        if isinstance(item, np.ndarray):
            assert not item.dtype.hasobject, name
            output[name] = item
        elif isinstance(item, dict):
            output.update(arrays_of(item, name+"__"))
    return output


def execute(fixed_path: Path, registered_path: Path) -> None:
    """
    機能: 登録済みの追加二場だけへ元三紙上通知と五ＢＢＯ選択を適用し保存する。
    引数: fixed_path/registered_path(Path)は正式固定・登録の位置。
    返り値: None。同一商品場の同通知・方策は保存引用し、旧四十一場は再生しない。
    """
    fixed, manifest = guard(fixed_path, registered_path)
    assert not (HERE/"measurement").exists() and not (HERE/"金融実行開始.json").exists()
    assert not (HERE/"jit_financial").exists()
    configs = configurations()
    import legacy126
    import policy126
    import policy_bbo126
    import adapter126
    from feed_filter126 import filter_paper, economic_key
    # ----------------------------------------
    # 旧フィルタは旧源の探索位置も挿入するため、新しい同bytes所有核を再優先する。
    for folder in (ENGINE, ENGINE/"bbo_next"):
        sys.path.insert(0, str(folder))
    for module in (legacy126, policy126, policy_bbo126):
        assert Path(module.__file__).resolve().is_relative_to(ENGINE)
    legacy126.CACHE = str(HERE/"jit_financial")
    rows, caches, traces, aliases = [], [], [], []
    paper_count = paper_alias_count = bbo_count = bbo_alias_count = 0
    save(HERE/"金融実行開始.json", dict(start_ns=time.time_ns(), sessions=list(SESSIONS),
        registered_sha256=sha(registered_path), input_manifest=fixed["input_manifest"],
        displayed_accounts_expected=32, new_financial_accounts_completed=0,
        original_market_reads=0, API=0, real_orders=0))
    output = HERE/"measurement"
    output.mkdir()
    with legacy126.isolated(discover=False):
        runtime = legacy126.runtime()
        for reference in manifest["packets"]:
            scene = reference["session"]
            packet = pickle.loads(bound_bytes(reference))
            validate_packet(packet, scene)
            policy126.bind_runtime(runtime, packet["inputs"], packet["signals"])
            for symbol in SYMBOLS:
                key = scene, symbol
                ready, feature = packet["inputs"][key], packet["features"][key]
                market, quotes = packet["markets"][key], packet["quotes"][key]
                gated_feature = dict(feature, gate=packet["gates"][key])
                paper_results, paper_arrays, quiet_g = {}, {}, None
                # ----------------------------------------
                # 元紙上通知は通常影と出口影を維持し、ＢＢＯの実予算を混ぜない。
                for config in configs["paper"]:
                    identifier = config["id"]
                    canonical = identifier
                    if identifier == "E01":
                        result, settings = policy126.play(runtime, config, ready, feature, market, observed=True)
                    else:
                        quiet = runtime["old"].time_filter.features(ready, config["time_mode"])
                        same = identifier == "E01_G_U" and all(
                            np.array_equal(quiet[name], quiet_g[name]) for name in ("active", "force", "not_before"))
                        if same:
                            result, settings = paper_results["G"], paper_settings
                            canonical = "E01_G"
                            paper_alias_count += 1
                        else:
                            result, settings = adapter126.play(runtime, config, ready, gated_feature)
                        if identifier == "E01_G":
                            quiet_g, paper_settings = quiet, settings
                    if canonical == identifier:
                        paper_count += 1
                    feed_source = "GU" if identifier == "E01_G_U" else "G" if identifier == "E01_G" else "E01"
                    paper_results[feed_source] = result
                    policy_bbo126.make_feed(result)
                    row = summary(result, ready, identifier, "observed")
                    row.update(canonical_method=canonical,
                        calculation_origin="新規金融" if canonical == identifier else "今回同値条件引用",
                        settings=settings)
                    rows.append(row)
                    paper_arrays.update({identifier+"__"+name: value for name, value in arrays_of(result).items()})
                    aliases.append(dict(model="observed", session=scene, symbol=symbol, method=identifier,
                        canonical_method=canonical, origin=row["calculation_origin"],
                        reason="ＧとＧＵの当場の静観三配列が完全同値" if canonical != identifier else "当場初回"))
                paper_path = output/("Last_"+symbol+"_"+scene+".npz")
                np.savez_compressed(paper_path, **paper_arrays)
                caches.append(dict(model="observed", session=scene, symbol=symbol,
                    path=paper_path.relative_to(ROOT).as_posix(), sha256=sha(paper_path)))
                # ----------------------------------------
                # Ｑは通知公開行だけで採否を固定し、約定時点の未来気配を見ない。
                selected = {}
                for source in ("G", "GU"):
                    selected[source], trace = filter_paper(paper_results[source], ready, quotes, enabled=True)
                    traces.append(dict(session=scene, symbol=symbol, paper_source=source, parents=trace))
                memo, actual_arrays = {}, {}
                for config in configs["bbo"]:
                    method, source = config["id"], config["paper_source"]
                    paper = selected[source] if config["quote_gate_enabled"] else paper_results[source]
                    feed = policy_bbo126.make_feed(paper)
                    signature = economic_key(feed, policy126.policy_parameters(config))
                    if signature in memo:
                        found = memo[signature]
                        result, row, canonical = found["result"], deepcopy(found["row"]), found["method"]
                        bbo_alias_count += 1
                        origin = "今回同値条件引用"
                    else:
                        result = policy_bbo126.play(config, ready, quotes, market, paper)
                        row = summary(result, ready, method, "next_normal_bbo")
                        canonical, origin = method, "新規金融"
                        memo[signature] = dict(result=result, row=deepcopy(row), method=method)
                        bbo_count += 1
                    row.update(method=method, paper_source=source, policy_id=config["policy_id"],
                        quote_gate_enabled=config["quote_gate_enabled"], economic_key=signature,
                        calculation_origin=origin, canonical_method=canonical)
                    rows.append(row)
                    actual_arrays.update({method+"__"+name: value for name, value in arrays_of(result).items()})
                    aliases.append(dict(model="next_normal_bbo", session=scene, symbol=symbol, method=method,
                        canonical_method=canonical, origin=origin, economic_key=signature,
                        packet_sha256=reference["sha256"], end=float(ready["limit"]),
                        cap=10 if symbol == "TOPIX" else 20))
                actual_path = output/("BBO_"+symbol+"_"+scene+".npz")
                np.savez_compressed(actual_path, **actual_arrays)
                caches.append(dict(model="next_normal_bbo", session=scene, symbol=symbol,
                    path=actual_path.relative_to(ROOT).as_posix(), sha256=sha(actual_path)))
            save(output/(scene+".json"), dict(session=scene,
                rows=[r for r in rows if r["session"] == scene],
                new_financial_accounts=paper_count+bbo_count,
                reused_within_stage_accounts=paper_alias_count+bbo_alias_count))
            print(scene+" 八公開選択の追加場会計を保存", flush=True)
    assert len(rows) == 32 and len(caches) == 8 and len(READS) == 2
    assert len({(r["model"], r["method"], r["session"], r["symbol"]) for r in rows}) == 32
    assert paper_count+paper_alias_count == 12 and bbo_count+bbo_alias_count == 20
    for relative, digest in fixed["sources"].items():
        assert sha(ROOT/relative) == digest
    for item in fixed["prior_results"]:
        assert sha(ROOT/item["path"]) == item["sha256"]
    save(HERE/RESULT_NAME, dict(passed=True, sessions=list(SESSIONS), rows=rows, cache=caches,
        specs=configs, sources=fixed["sources"], input_manifest=fixed["input_manifest"],
        input_reads=READS, quote_gate_traces=traces, aliases=aliases,
        displayed_accounts=32, new_financial_accounts=paper_count+bbo_count,
        new_paper_accounts=paper_count, new_bbo_accounts=bbo_count,
        reused_within_stage_accounts=paper_alias_count+bbo_alias_count,
        reused_paper_accounts=paper_alias_count, reused_bbo_accounts=bbo_alias_count,
        old_financial_accounts=0, prior_results_unchanged=fixed["prior_results"],
        original_market_reads=0, API=0, real_orders=0,
        accounting="手数料零。利益損失は返済脚。全玉場内返済。元三紙上通知と実ＢＢＯ五選択を区別。",
        limitation="ラージＢＢＯ代理。小型実板・部分約定・真の受信時計は未再現。過去四十一場の選定は変更しない。"))
    print(json.dumps(dict(passed=True, displayed_accounts=32,
        new_financial_accounts=paper_count+bbo_count,
        aliases=paper_alias_count+bbo_alias_count), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--registered", type=Path, required=True)
    parser.add_argument("--root-run", action="store_true", required=True)
    arguments = parser.parse_args()
    assert arguments.root_run
    execute(arguments.fixed.resolve(), arguments.registered.resolve())
