"""登録済み不変実装に対して前40場又は選択後13場の実行段階を許可する。"""
import argparse
from datetime import datetime

from register163 import HERE, MANIFEST, SPEC, CONFIGS, RECEIPT, FREEZE, RANKING
from register163 import read, sha, record, save, canonical, verify_receipt, assert_fingerprint
from register163 import CANDIDATE_IDS


def check_freeze(value: dict) -> None:
    """後半確認前の固定選択と内容指紋を検査する。

    引数: value(dict)。返り値: None。
    """
    assert value.get("test_opened") is False and value.get("known_confirmation") is True
    selected = value["selected"]
    assert isinstance(selected, dict) and set(selected) == {"Day","Night"}
    assert value["ranking_order"] == RANKING and value["selection_sessions"] == 40
    assert value["quantile_method"] == "linear"
    assert value["selection_sessions_by_kind"] == {"Day":20,"Night":20}
    assert set(value["ranking"]) == {"Day","Night"}
    assert all(len(rows) == 8 and {r["id"] for r in rows} == CANDIDATE_IDS and all(r["sessions"] == 20 for r in rows) for rows in value["ranking"].values())
    assert selected == {kind:rows[0]["id"] for kind,rows in value["ranking"].items()}
    assert set(selected.values()).issubset(CANDIDATE_IDS)
    assert value["composition"]["id"] == "F00" and value["composition"]["new_financial_replay"] is False
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
    save(HERE/(args.stage+"_許可163.json"), value)
    print("登録不変と段階許可を保存: "+args.stage)


if __name__ == "__main__":
    main()
