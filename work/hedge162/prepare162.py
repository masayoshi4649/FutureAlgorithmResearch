"""先行研究の凍結済み入力・特徴・入口モデルを新研究の目録へ接続する。"""

from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT/"work/entry161"


def read(path: Path) -> dict:
    """UTF-8の目録を読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path: Path) -> dict:
    """再利用する情報源の内容指紋を返す。

    引数: path(Path)。返り値: dictは相対パスとSHA256。
    """
    with path.open("rb") as stream:
        fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": fingerprint}


def main() -> None:
    """将来ラベルを含めず、53場の原板と当時特徴を目録にする。

    引数: なし。返り値: None。新しい売買再生はしない。
    """
    source = read(BASE/"inputs161.json")
    scene_records = []
    for split in ("train", "validation", "test"):
        proof = read(BASE/"data"/("features_"+split+"_extraction161.json"))
        expected = {row["session"]: row["saved"]["sha256"] for row in proof["results"]}
        for scene in source["sessions"]:
            if scene["split"] != split:
                continue
            feature_path = BASE/"data/features"/split/(scene["session"]+".npz")
            feature_record = record(feature_path)
            assert feature_record["sha256"] == expected[scene["session"]]
            scene_records.append(dict(scene, features=str(feature_path), feature_fingerprint=feature_record))
    scene_records.sort(key=lambda scene: (scene["start"], scene["session"]))
    assert len(scene_records) == 53
    frozen = BASE/"results/selection_frozen161.json"
    assert read(frozen)["selected"] == {"Day": "R02", "preUS": "GL01", "postUS": "GL02"}
    value = {"purpose": "当時特徴から主玉とカバーを連続運転。将来ラベルを入口に含めない。",
             "sessions": scene_records, "counts": source["counts"],
             "source_manifest": record(BASE/"inputs161.json"), "signal_source": record(frozen),
             "signal_implementation": [record(BASE/"search"/name) for name in ("rules161.py", "engine161.py", "spec161.json")],
             "market_reader": record(BASE/"features/features161.py"),
             "product": "NK225mini", "max_per_side": 10, "multiplier": 100, "fee": 0,
             "maximum_end_quote_age_s": 360, "known_development": True}
    with (HERE/"inputs162.json").open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print("53場の入力・特徴・固定入口モデルの指紋を接続しました。", flush=True)


if __name__ == "__main__":
    main()
