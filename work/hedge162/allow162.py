"""登録済み不変実装に対して前40場又は選択後13場の実行段階を許可する。"""
import argparse
from datetime import datetime

from register162 import HERE, MANIFEST, SPEC, CONFIGS, RECEIPT, FREEZE, RANKING
from register162 import read, sha, record, save, canonical, verify_receipt, assert_fingerprint


def check_freeze(value: dict) -> None:
    """後半確認前の固定選択と内容指紋を検査する。

    引数: value(dict)。返り値: None。
    """
    assert value.get("test_opened") is False and value.get("known_confirmation") is True
    selected = value["selected"]
    assert isinstance(selected, list) and len(selected) == 3 and len(set(selected)) == 3
    assert value["ranking_order"] == RANKING and value["selection_sessions"] == 40
    assert value["quantile_method"] == "linear"
    assert selected == [r["id"] for r in value["ranking"][:3]]
    assert set(selected).issubset({c["id"] for c in read(CONFIGS) if c["cover"]})
    for key, path in (("manifest_sha256", MANIFEST), ("spec_sha256", SPEC), ("configs_sha256", CONFIGS)):
        assert value[key] == sha(path)
    assert canonical({k:v for k,v in value.items() if k != "content_sha256"}) == value["content_sha256"]
    for item in (value["complete_proof"], value["registration"], value["selection_implementation"]):
        assert_fingerprint(item)


def main() -> None:
    """明示stageの許可だけを新規保存する。

    引数: CLI のstage(str)。返り値: None。金融再生は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train_validation", "locked_test"))
    args = parser.parse_args()
    verify_receipt()
    folder = HERE/"results"/args.stage
    assert not list(folder.glob("*.json")), "再生前の空出力先にだけ許可する"
    value = dict(registered=True, returncode=0, allowed_stages=[args.stage],
        spec_sha256=sha(SPEC), configs_sha256=sha(CONFIGS), manifest_sha256=sha(MANIFEST),
        registration=record(RECEIPT), known_confirmation=True,
        created_at=datetime.now().astimezone().isoformat())
    if args.stage == "locked_test":
        chosen = read(FREEZE)
        check_freeze(chosen)
        value["freeze_sha256"] = sha(FREEZE)
    save(HERE/(args.stage+"_許可162.json"), value)
    print("登録不変と段階許可を保存: "+args.stage)


if __name__ == "__main__":
    main()
