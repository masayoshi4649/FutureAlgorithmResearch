"""登録成功後だけ原板の特徴又は分離ラベルを作る。候補や成績の集計はしない。"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np

from features161 import read_market, build_features

ROOT = Path(__file__).resolve().parents[3]


def read(path: Path) -> dict:
    """JSONをUTF-8で読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def permit(path: Path) -> None:
    """登録成功の両項目が明示された場合だけ実資料処理を許す。

    引数: path(Path)。返り値: None。不足又は失敗は例外。
    """
    receipt = read(path)
    if receipt.get("registered") is not True or type(receipt.get("returncode")) is not int or receipt["returncode"] != 0:
        raise ValueError("登録成功が確認できないため実資料処理を停止")


def permit_extraction(path: Path, split: str, manifest_path: Path, spec_path: Path, freeze_path: Path | None) -> dict:
    """段階許可と指紋を検査し、testでは候補・学習済みモデル凍結を必須にする。

    引数: path/manifest_path/spec_path(Path)、split(str)、freeze_path(Path|None)。
    返り値: dictは許可・凍結の指紋。test特徴とtestラベルへ同じ制限を適用する。
    """
    permit(path)
    receipt = read(path)
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    stage = "locked_test" if split == "test" else "train_validation"
    if stage not in receipt.get("allowed_stages", []):
        raise ValueError("この分割の抽出を許可されていない")
    if receipt.get("manifest_sha256") != manifest_sha or receipt.get("spec_sha256") != spec_sha:
        raise ValueError("許可された資料又は選択仕様と指紋が一致しない")
    proof = {"permission_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "allowed_stage": stage,
             "manifest_sha256": manifest_sha, "search_spec_sha256": spec_sha}
    if split == "test":
        if freeze_path is None:
            raise ValueError("test抽出には--freezeによる候補凍結が必要")
        frozen = read(freeze_path)
        freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
        content = {key: value for key, value in frozen.items() if key != "content_sha256"}
        content_sha = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        if frozen.get("test_opened") is not False or not isinstance(frozen.get("selected"), dict) or not isinstance(frozen.get("models"), dict):
            raise ValueError("未開封の選択・モデル凍結を確認できない")
        if set(frozen["selected"])-{"Day", "preUS", "postUS"}:
            raise ValueError("凍結対象の時間帯が不正")
        if frozen.get("manifest_sha256") != manifest_sha or frozen.get("spec_sha256") != spec_sha:
            raise ValueError("凍結した資料・選択仕様と一致しない")
        if frozen.get("content_sha256") != content_sha or receipt.get("freeze_sha256") != freeze_sha:
            raise ValueError("凍結した選択・モデルの内容指紋が一致しない")
        proof.update(freeze_sha256=freeze_sha, freeze_content_sha256=content_sha)
    return proof


def save_npz(path: Path, arrays: dict, metadata: dict) -> dict:
    """既存成果を上書きせず配列とメタデータを保存する。

    引数: path(Path)、arrays/metadata(dict)。返り値: dictは保存指紋。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        np.savez_compressed(stream, **arrays, metadata=np.asarray(json.dumps(metadata, ensure_ascii=False)))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}


def process_scene(scene: dict, stage: str, output: str, manifest_sha: str) -> dict:
    """指定一場を特徴かラベルのどちらかだけへ変換する。

    引数: scene(dict)、stage/output/manifest_sha(str)。返り値: dictは資料処理証跡。結果率を含めない。
    """
    market, own_evidence = read_market(scene, "NK225")
    evidence = [own_evidence]
    if stage == "features":
        peer, peer_evidence = read_market(scene, "TOPIX")
        evidence.append(peer_evidence)
        arrays = build_features(market, peer, scene)
    else:
        from labels161 import make_labels
        arrays = make_labels(market, market["observations"], scene)
    metadata = {"session": scene["session"], "split": scene["split"], "kind": scene["kind"], "start": scene["start"], "end": scene["end"],
                "cutoff": scene["cutoff"], "us_open": scene.get("us_open", 0), "stage": stage, "manifest_sha256": manifest_sha,
                "phase_mapping": {"0": "Day", "1": "preUS", "2": "postUS"}, "status_mapping": {"1": "100先着", "-1": "50逆行先着", "0": "未到達", "-2": "次正常板なし"},
                "clock": "CurrentPriceTime代理。実受信時計ではない。", "rows": len(market["observations"]), "raw": evidence}
    target = Path(output)/stage/scene["split"]/(scene["session"]+".npz")
    saved = save_npz(target, arrays, metadata)
    return {"session": scene["session"], "split": scene["split"], "stage": stage, "observations": len(market["observations"]), "saved": saved, "raw": evidence}


def main() -> None:
    """段階と分割を明示し、実資料の抽出を実行する。

    引数: CLIのmanifest/registration/stage/split/out/workers。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=Path(__file__).resolve().parents[1]/"search/spec161.json")
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--stage", choices=("features", "labels"), required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    permission = permit_extraction(args.registration, args.split, args.manifest, args.spec, args.freeze)
    assert 1 <= args.workers <= 8
    manifest = read(args.manifest)
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    scenes = [s for s in manifest["sessions"] if s["split"] == args.split]
    assert len(scenes) == {"train": 30, "validation": 10, "test": 13}[args.split]
    for scene in scenes:
        assert not (args.out/args.stage/args.split/(scene["session"]+".npz")).exists(), "既存抽出を上書きしない"
    results = []
    started = datetime.now().astimezone().isoformat()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(process_scene, s, args.stage, str(args.out), digest): s["session"] for s in scenes}
        for task in as_completed(jobs):
            result = task.result()
            results.append(result)
            print(json.dumps({k: result[k] for k in ("session", "stage", "split", "observations")}, ensure_ascii=False), flush=True)
    assert digest == hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    assert permission == permit_extraction(args.registration, args.split, args.manifest, args.spec, args.freeze)
    proof = {"completed": True, "financial_replays": 0, "candidate_evaluations": 0, "stage": args.stage, "split": args.split,
             "started_at": started, "finished_at": datetime.now().astimezone().isoformat(), "manifest_sha256": digest, "permission": permission, "results": results}
    destination = args.out/(args.stage+"_"+args.split+"_extraction161.json")
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
