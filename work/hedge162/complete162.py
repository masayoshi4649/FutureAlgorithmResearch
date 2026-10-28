"""前40場・後13場の完了と選択不変を記録する。"""
from pathlib import Path
from datetime import datetime

from register162 import HERE, MANIFEST, FREEZE, read, sha, record, save, verify_receipt
from allow162 import check_freeze
from freeze162 import verify_proof


def main() -> None:
    """全53場×26の完成証跡を照合し、凍結資料を変更せず閉じる。

    引数: なし。返り値: None。新しい順位選択・金融再生は行わない。
    """
    verify_receipt()
    frozen = read(FREEZE)
    check_freeze(frozen)
    manifest = read(MANIFEST)
    proofs = []
    for stage, count in (("train_validation",40),("locked_test",13)):
        folder = HERE/"results"/stage
        path = folder/("再生完了162_"+stage+".json")
        proof = read(path)
        verify_proof(proof, stage, count)
        expected = {s["session"] for s in manifest["sessions"] if (s["split"] == "test") == (stage == "locked_test")}
        assert {r["session"] for r in proof["results"]} == expected
        if stage == "locked_test":
            assert proof["stage"]["freeze_sha256"] == sha(FREEZE)
            assert proof["stage"]["selected"] == frozen["selected"]
        for item in proof["results"]:
            target = Path(item["path"]).resolve()
            assert target == (folder/(item["session"]+".json")).resolve()
            assert sha(target) == item["sha256"]
        proofs.append(record(path))
    save(HERE/"再生全完了162.json", dict(completed=True, returncode=0, sessions=53, cases=53*26,
        selected=frozen["selected"], freeze=record(FREEZE), proofs=proofs,
        known_confirmation=True, reselection_after_confirmation=False,
        created_at=datetime.now().astimezone().isoformat()))
    print("全53場×26条件の完了を照合。後半による再選択はありません。")


if __name__ == "__main__":
    main()
