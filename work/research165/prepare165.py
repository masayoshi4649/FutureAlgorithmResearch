"""既知の27夜を米国開始後の板研究用に固定し、保存済み基準会計を再利用する。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def read(path: Path):
    """UTF-8のJSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path: Path) -> dict:
    """既存ファイルの相対パスと内容指紋を返す。

    引数: path(Path)。返り値: dict[str,str]。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.resolve().relative_to(ROOT).as_posix(), "sha256": digest}


def save(path: Path, value) -> None:
    """成果を上書きせず保存する。

    引数: path(Path)、value(dict又はlist)。返り値: None。
    """
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def main() -> None:
    """入力の資料区分を維持し、基準ケースを原結果から抽出する。

    引数: なし。返り値: None。金融再生は行わない。
    """
    original = ROOT / "work/research164/r2/inputs164r2.json"
    manifest = read(original)
    scenes = [s for s in manifest["sessions"] if s["kind"] == "Night"]
    assert len(scenes) == 27 and len({s["session"] for s in scenes}) == 27
    assert sum(s["split"] in ("train", "validation") for s in scenes) == 20
    manifest.update(sessions=scenes, created_at=datetime.now().astimezone().isoformat(),
        development_round=1, known_development=True, independent_unseen=False,
        counts={"train": 15, "validation": 5, "test": 6, "extra": 1},
        us_market_data_used=False, scope="米国開始後のみ。元の国内二市場入力を保持し、新しい板特徴は日経ラージから計算。",
        selection="前20夜で候補を固定して後7夜で確認。全27夜は既知の追加開発資料。",
        note="総収支低下だけで不採用にしない。黒字を保ち損失頻度・深さ・場内リスクを評価。",
        sources=[fingerprint(original)])
    save(HERE / "inputs165.json", manifest)

    # ----------------------------------------
    # 既存U00の金融成果を抽出するだけで、新しい利益検証には数えない。
    baseline = []
    sources = []
    for stage in ("train_validation", "confirmation"):
        proof_path = ROOT / f"work/research164/results/{stage}/再生完了164_{stage}.json"
        proof = read(proof_path)
        assert proof["completed"] and proof["returncode"] == 0
        sources.append(fingerprint(proof_path))
        for source in proof["results"]:
            if not source["session"].endswith("Night"):
                continue
            path = Path(source["path"])
            actual = fingerprint(path)
            assert actual["sha256"] == source["sha256"]
            saved = read(path)
            case = next(c for c in saved["cases"] if c["config"]["id"] == "NK225_U164_00")
            baseline.append(dict(scene=saved["scene"], case=case, source=actual))
            sources.append(actual)
    baseline.sort(key=lambda b: b["scene"]["session"])
    assert [b["scene"]["session"] for b in baseline] == [s["session"] for s in scenes]
    save(HERE / "baseline165.json", dict(method_id="NK225_U164_00", new_financial_replays=0,
        cases=baseline, sources=sources, note="原ケースの抽出。ID・定義・価格・数量・損益は変更しない。"))
    print("既知27夜の入力と、保存U00の27ケースを固定しました。金融再生0回。")


if __name__ == "__main__":
    main()
