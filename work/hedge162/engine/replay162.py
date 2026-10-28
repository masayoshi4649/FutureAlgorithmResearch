"""登録後だけ凍結入口と全原行から26条件の状態売買を行う。先着ラベル不使用。"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np

from configs162 import configurations, make_case, export_configuration
from signals162 import make_signals, EXPECTED
from source161_features import read_market
from state162 import Engine, Quote


def sha(path: Path) -> str:
    """内容指紋を逐次計算する。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def read_json(path: Path) -> dict:
    """固定JSONをUTF-8で読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require_registration(path: Path) -> dict:
    """両方の登録成功項目がない限り原資料を読まない。

    引数: path(Path)。返り値: dictは登録受領。
    """
    receipt = read_json(path)
    if receipt.get("registered") is not True or type(receipt.get("returncode")) is not int or receipt["returncode"] != 0:
        raise ValueError("00162の登録成功を確認できない")
    return receipt


def validate_frozen(frozen: dict) -> None:
    """00161の選択とモデル内容が保存時の正規化指紋と一致するか調べる。

    引数: frozen(dict)。返り値: None。
    """
    payload = {k:v for k,v in frozen.items() if k != "content_sha256"}
    actual = hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
    if frozen.get("selected") != EXPECTED or frozen.get("content_sha256") != actual:
        raise ValueError("元入口・モデルの内容が変わっている")


def require_stage(receipt: dict, stage: str, manifest: Path, configs: Path, spec: Path, freeze: Path | None) -> dict:
    """前40場と選択後13場を、段階許可と資料指紋で分離する。

    引数: receipt(dict)、stage(str)、manifest/configs/spec(Path)、freeze(Path|None)。返り値: dictは段階証跡。
    """
    expected = {"manifest_sha256":sha(manifest),"configs_sha256":sha(configs),"spec_sha256":sha(spec)}
    if stage not in receipt.get("allowed_stages",[]) or any(receipt.get(k) != v for k,v in expected.items()):
        raise ValueError("段階許可又は登録指紋が一致しない")
    result = {"stage":stage,**expected}
    if stage == "locked_test":
        if freeze is None:
            raise ValueError("後13場にはカバー選択凍結が必要")
        chosen = read_json(freeze)
        selected = chosen.get("selected")
        if chosen.get("test_opened") is not False or not isinstance(selected,list) or len(selected) > 3 or len(set(selected)) != len(selected):
            raise ValueError("未開封の最大3候補を確認できない")
        allowed = {d["id"] for d in configurations() if d["cover"]}
        if not set(selected).issubset(allowed) or any(chosen.get(k) != v for k,v in expected.items()):
            raise ValueError("選択候補又は凍結指紋が不正")
        if receipt.get("freeze_sha256") != sha(freeze):
            raise ValueError("許可されたカバー選択と一致しない")
        result.update(freeze_sha256=sha(freeze),selected=selected)
    return result


def summarize(engine: Engine, ending: dict) -> dict:
    """主/カバーと親の全損益、口座時価、数量/予約上限を同じ帳簿から集計する。

    引数: engine(Engine)、ending(dict)。返り値: dict。
    """
    roles = {}
    for role in ("main","cover"):
        lots = [lot for lot in engine.lots.values() if lot.role == role]
        roles[role] = {"lots":len(lots),"initial_quantity":sum(e["order"].quantity for e in engine.events if e["order"].action == "new" and e["order"].role == role),
                       "net":sum(l.realized for l in lots),"profit":sum(max(0,l.realized) for l in lots),"loss":-sum(min(0,l.realized) for l in lots),
                       "remaining_quantity":sum(l.quantity for l in lots)}
    parents = []
    for parent in engine.parents.values():
        lots = [l for l in engine.lots.values() if l.parent == parent.id]
        if not lots:
            continue
        parents.append({"id":parent.id,"phase":parent.phase,"side":parent.side,"initial_quantity":parent.quantity,
                        "main_net":sum(l.realized for l in lots if l.role == "main"),"cover_net":sum(l.realized for l in lots if l.role == "cover"),
                        "net":sum(l.realized for l in lots),"remaining_quantity":sum(l.quantity for l in lots)})
    return {"realized":engine.realized,"roles":roles,"parents":parents,"minimum_equity":engine.minimum_equity,"maximum_drawdown":engine.max_drawdown,
            "peak_equity":engine.peak_equity,"final_mark":engine.last_mark,"long_quantity_seconds":engine.long_seconds,"short_quantity_seconds":engine.short_seconds,
            "net_abs_quantity_seconds":engine.net_abs_seconds,"maximum_quantities":engine.maximum_quantities,
            "initial_equity":{"time":engine.config.start,"index":-1,"equity":0},"peak_at":engine.peak_at,"minimum_at":engine.minimum_at,"drawdown_from":engine.drawdown_from,"drawdown_to":engine.drawdown_to,
            "main_entries":roles["main"]["lots"],"cover_entries":roles["cover"]["lots"],"rejections":dict(Counter(r["reason"] for r in engine.rejections)),
            "cover_capacity_evaluated_rows":engine.cover_capacity_rows,"cover_capacity_slot_rows":sum(r["rows"] for r in engine.cover_capacity.values()),
            "close_reasons":dict(Counter(e["order"].reason for e in engine.events if e["order"].action == "close")),
            "proxy_fills":sum(bool(e.get("proxy")) for e in engine.events),"ending":ending}


def run_market(scene: dict, market: dict, features: dict, frozen: dict, definitions: list[dict], skip_unchanged: bool = True) -> dict:
    """読取済みの一場を全条件へ渡す純時系列の処理を行う。

    引数: scene/market/features/frozen(dict)、definitions(list[dict])、skip_unchanged(bool)。返り値: dict。
    """
    observations = features["decision_index"]
    np.testing.assert_array_equal(observations,market["observations"])
    np.testing.assert_array_equal(features["time"],market["time"][observations])
    long_signal,short_signal = make_signals(features,frozen)
    lookup = np.full(len(market["time"]),-1,dtype=np.int64)
    lookup[observations] = np.arange(len(observations))
    engines,policies = [],[]
    for definition in definitions:
        config,policy = make_case(scene,definition)
        engines.append(Engine(config,skip_unchanged))
        policies.append(policy)
    for i,at in enumerate(market["time"]):
        row = int(lookup[i])
        phase = "Day" if scene["kind"] == "Day" else "preUS" if at < scene["us_open"] else "postUS"
        q = Quote(i,float(at),float(market["bid"][i]),float(market["ask"][i]),phase,row >= 0)
        buy,sell = (bool(long_signal[row]),bool(short_signal[row])) if row >= 0 else (False,False)
        for engine,policy in zip(engines,policies):
            engine.step(q,buy,sell,policy)
    cases = []
    for definition,engine in zip(definitions,engines):
        untriggered = [{"parent":p.id,**asdict(slot)} for p in engine.active_parents.values() for slot in p.slots if slot.state in ("armed","wait_inside","seed") and slot.pending is None and slot.lot is None]
        ending = engine.finish(scene["end"],360)
        if not ending["completed"]:
            raise ValueError(f"{scene['session']} {definition['id']} 場末の板が古く未解消")
        events = [{**e,"order":asdict(e["order"])} for e in engine.events]
        indices = {o.decision_index for o in engine.decisions if 0 <= o.decision_index < len(market["time"])}
        indices |= {e["fill_index"] for e in events if e["fill_index"] is not None}
        indices |= {e["quote_index"] for e in events if e.get("proxy")}
        indices |= {p["index"] for p in engine.risk_points if not p.get("proxy") and p["index"] >= 0}
        reference = [{"index":i,"physical_line":int(market["line"][i]),"time":float(market["time"][i]),"bid":float(market["bid"][i]),"ask":float(market["ask"][i]),"last":float(market["last"][i])} for i in sorted(indices)]
        cases.append({"id":definition["id"],"configuration":export_configuration(scene,definition),"summary":summarize(engine,ending),
                      "events":events,"decisions":[asdict(o) for o in engine.decisions],"lots":[asdict(l) for l in engine.lots.values()],
                      "parents":[asdict(p) for p in engine.parents.values()],"rejections":engine.rejections,
                      "cover_capacity":list(engine.cover_capacity.values()),
                      "risk_points":engine.risk_points,"cancelled_new":[{**c,"order":asdict(c["order"])} for c in engine.cancellations],
                      "untriggered_before_end":untriggered,"reference":reference,"skipped_unchanged_rows":engine.skipped_rows})
    return {"session":scene["session"],"kind":scene["kind"],"split":scene["split"],"start":scene["start"],"end":scene["end"],"us_open":scene.get("us_open",0),
            "source_observations":len(observations),"source_true_buy":int(long_signal.sum()),"source_true_sell":int(short_signal.sum()),
            "raw_rows":len(market["time"]),"cases":cases,"label_input_used":False}


def process_scene(scene: dict, feature_root: str, frozen: dict, definitions: list[dict], output: str) -> dict:
    """一場の原板と既存因果特徴だけを読んで新規ファイルへ保存する。

    引数: scene/frozen(dict)、feature_root/output(str)、definitions(list[dict])。返り値: dictは保存指紋。
    """
    market,raw_proof = read_market(scene,"NK225")
    feature_path = Path(scene["features"])
    feature_sha = sha(feature_path)
    assert feature_sha == scene["feature_fingerprint"]["sha256"], "固定した因果特徴NPZが変更されている"
    with np.load(feature_path,allow_pickle=False) as packed:
        features = {name:packed[name].copy() for name in packed.files}
    metadata = json.loads(str(features["metadata"]))
    assert metadata["session"] == scene["session"] and metadata["stage"] == "features"
    own_fingerprint = next(x["sha256"] for x in metadata["raw"] if Path(x["path"]) == Path(scene["books"]["NK225"]))
    assert own_fingerprint == raw_proof["sha256"]
    result = run_market(scene,market,features,frozen,definitions)
    result["input"] = {"raw":raw_proof,"feature_path":str(feature_path),"feature_sha256":feature_sha}
    target = Path(output)/(scene["session"]+".json")
    with target.open("x",encoding="utf-8") as stream:
        json.dump(result,stream,ensure_ascii=False,separators=(",",":"),allow_nan=False)
    assert feature_sha == sha(feature_path)
    return {"session":scene["session"],"path":str(target),"sha256":sha(target),"cases":len(result["cases"]),"raw_rows":result["raw_rows"]}


def main() -> None:
    """登録済みの26条件と固定元モデルで53場を一度だけ再生する。

    引数: CLIのmanifest/features/selection/configs/registration/out/workers。返り値: None。
    """
    parser = argparse.ArgumentParser()
    for name in ("manifest","selection","configs","spec","registration","out"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--features",type=Path)
    parser.add_argument("--freeze",type=Path)
    parser.add_argument("--stage",choices=("train_validation","locked_test"),required=True)
    parser.add_argument("--workers",type=int,default=8)
    args = parser.parse_args()
    receipt = require_registration(args.registration)
    stage_proof = require_stage(receipt,args.stage,args.manifest,args.configs,args.spec,args.freeze)
    if not 1 <= args.workers <= 8:
        raise ValueError("並列数は1〜8")
    manifest,definitions,frozen = read_json(args.manifest),read_json(args.configs),read_json(args.selection)
    if definitions != configurations():
        raise ValueError("事前固定26条件以外は再生しない")
    validate_frozen(frozen)
    all_scenes = manifest["sessions"]
    if len(all_scenes) != 53 or len({s["session"] for s in all_scenes}) != 53:
        raise ValueError("固定53場が必要")
    assert sha(args.selection) == manifest["signal_source"]["sha256"]
    assert sha(Path(__file__).parent/"source161_features.py") == manifest["market_reader"]["sha256"]
    assert sha(Path(__file__).parent/"source161_rules.py") == next(r["sha256"] for r in manifest["signal_implementation"] if r["path"].endswith("rules161.py"))
    scenes = [s for s in all_scenes if (s["split"] == "test") == (args.stage == "locked_test")]
    assert len(scenes) == (13 if args.stage == "locked_test" else 40)
    source_paths = [args.manifest,args.selection,args.configs,args.spec,args.registration]+([args.freeze] if args.freeze else [])
    sources = {str(p):sha(p) for p in source_paths}
    args.out.mkdir(parents=True,exist_ok=True)
    for scene in scenes:
        if (args.out/(scene["session"]+".json")).exists():
            raise ValueError("既存成果を上書きしない")
    started = datetime.now().astimezone().isoformat()
    completed = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = [pool.submit(process_scene,s,str(args.features),frozen,definitions,str(args.out)) for s in scenes]
        for future in as_completed(tasks):
            record = future.result()
            completed.append(record)
            print(json.dumps(record,ensure_ascii=False),flush=True)
    assert all(sha(Path(p)) == expected for p,expected in sources.items())
    proof = {"completed":True,"returncode":0,"stage":stage_proof,"started_at":started,"finished_at":datetime.now().astimezone().isoformat(),
             "sessions":len(completed),"cases":sum(x["cases"] for x in completed),"sources_unchanged":True,"sources":sources,"results":completed}
    with (args.out/("再生完了162_"+args.stage+".json")).open("x",encoding="utf-8") as stream:
        json.dump(proof,stream,ensure_ascii=False,indent=2)


if __name__ == "__main__":
    main()
