"""前40場だけからカバー候補を固定順位で3つ凍結する。"""
from datetime import datetime
from pathlib import Path
import numpy as np

from register162 import HERE, ROOT, MANIFEST, SPEC, CONFIGS, RECEIPT, FREEZE, RANKING
from register162 import read, sha, record, save, canonical, verify_receipt


def rank_candidates(summaries: list[dict], candidate_ids: list[str]) -> list[dict]:
    """場収支と場内全玉時価から事前固定順で順位を計算する。

    引数: summaries(list[dict])、candidate_ids(list[str])。返り値: list[dict]。
    """
    ranking = []
    for key in candidate_ids:
        group = [r for r in summaries if r["id"] == key]
        assert group and len({r["session"] for r in group}) == len(group)
        values = np.asarray([r["realized"] for r in group], dtype=float)
        risks = np.asarray([r["minimum_equity"] for r in group], dtype=float)
        assert np.all(np.isfinite(values)) and np.all(np.isfinite(risks))
        ranking.append(dict(id=key, sessions=len(group), losing_sessions=int(np.sum(values < 0)),
            session_net_q25=float(np.quantile(values, .25, method="linear")),
            minimum_equity=float(np.min(risks)), total_net=float(np.sum(values))))
    return sorted(ranking, key=lambda r: (r["losing_sessions"], -r["session_net_q25"], -r["minimum_equity"], -r["total_net"], r["id"]))


def verify_proof(proof: dict, stage: str, count: int) -> None:
    """再生完了の区間・件数・定義指紋を確認する。

    引数: proof(dict)、stage(str)、count(int)。返り値: None。
    """
    assert proof.get("completed") is True and type(proof.get("returncode")) is int and proof["returncode"] == 0
    assert proof.get("sources_unchanged") is True
    assert proof["sessions"] == count and proof["cases"] == count*26 and len(proof["results"]) == count
    assert proof["stage"]["stage"] == stage
    for key, path in (("manifest_sha256", MANIFEST), ("spec_sha256", SPEC), ("configs_sha256", CONFIGS)):
        assert proof["stage"][key] == sha(path), key


def main() -> None:
    """前40場の26条件を照合し、カバー24から最大3候補を保存する。

    引数: なし。返り値: None。後13場の数値を読まない。
    """
    verify_receipt()
    assert not FREEZE.exists(), "選択凍結を上書きしない"
    assert not list((HERE/"results/locked_test").glob("*.json")), "後半確認前に凍結する"
    folder = HERE/"results/train_validation"
    proof_path = folder/"再生完了162_train_validation.json"
    proof = read(proof_path)
    verify_proof(proof, "train_validation", 40)
    manifest, configs = read(MANIFEST), read(CONFIGS)
    expected_sessions = {s["session"] for s in manifest["sessions"] if s["split"] in ("train", "validation")}
    assert {r["session"] for r in proof["results"]} == expected_sessions
    ids = {c["id"] for c in configs}
    cover_ids = sorted(c["id"] for c in configs if c["cover"])
    assert len(ids) == 26 and len(cover_ids) == 24
    summaries, sources = [], []
    for item in proof["results"]:
        path = Path(item["path"]).resolve()
        expected_path = (folder/(item["session"]+".json")).resolve()
        assert path == expected_path and sha(path) == item["sha256"]
        result = read(path)
        assert result["session"] == item["session"] and result["split"] in ("train", "validation")
        assert result.get("label_input_used") is False
        assert {c["id"] for c in result["cases"]} == ids and len(result["cases"]) == 26
        for case in result["cases"]:
            s = case["summary"]
            assert s["ending"]["completed"] is True
            assert all(role["remaining_quantity"] == 0 for role in s["roles"].values())
            summaries.append(dict(session=result["session"], id=case["id"],
                realized=s["realized"], minimum_equity=s["minimum_equity"]))
        sources.append(record(path))
    ranking = rank_candidates(summaries, cover_ids)
    assert all(r["sessions"] == 40 for r in ranking)
    value = dict(selected=[r["id"] for r in ranking[:3]], test_opened=False,
        spec_sha256=sha(SPEC), configs_sha256=sha(CONFIGS), manifest_sha256=sha(MANIFEST),
        ranking_order=RANKING, quantile_method="linear", selection_sessions=40,
        selected_is_adoption=False, known_confirmation=True,
        scope="前30+次10場のみで選択。後13場は既知資料の追加確認で、全26を評価しても再選択しない。",
        ranking=ranking, complete_proof=record(proof_path), results=sources,
        registration=record(RECEIPT), selection_implementation=record(Path(__file__)),
        created_at=datetime.now().astimezone().isoformat())
    value["content_sha256"] = canonical(value)
    save(FREEZE, value)
    print("前40場から凍結: "+", ".join(value["selected"])+"。後半は未読。")


if __name__ == "__main__":
    main()
