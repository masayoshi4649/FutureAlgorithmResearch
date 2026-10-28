"""前40場だけから日中と夜間それぞれの比較候補を1つ凍結する。"""
from datetime import datetime
from pathlib import Path
import numpy as np

from register163 import HERE, ROOT, MANIFEST, SPEC, CONFIGS, RECEIPT, FREEZE, RANKING
from register163 import read, sha, record, save, canonical, verify_receipt
from register163 import CONFIG_IDS, CANDIDATE_IDS, config_id


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
    assert proof["sessions"] == count and proof["cases"] == count*10 and len(proof["results"]) == count
    assert proof["stage"]["stage"] == stage
    for key, path in (("manifest_sha256", MANIFEST), ("spec_sha256", SPEC), ("configs_sha256", CONFIGS)):
        assert proof["stage"][key] == sha(path), key


def scene_summaries(result: dict, expected_scene: dict) -> list[dict]:
    """Goの一場JSONから完済済み10条件の比較値だけを取り出す。

    引数: result/expected_scene(dict)。返り値: list[dict]。
    """
    scene = result["scene"]
    assert scene["session"] == expected_scene["session"] and scene["kind"] == expected_scene["kind"]
    assert len(result["cases"]) == 10 and {config_id(c["config"]) for c in result["cases"]} == CONFIG_IDS
    summaries = []
    for case in result["cases"]:
        ledger = case["actual"]
        assert not ledger["Active"] and not ledger["Pending"]
        assert all(lot["Remaining"] == 0 for lot in ledger["Lots"].values())
        summaries.append(dict(session=scene["session"], kind=scene["kind"], id=config_id(case["config"]),
            realized=ledger["Realized"], minimum_equity=ledger["Risk"]["Minimum"]))
    return summaries


def main() -> None:
    """前40場の10条件を照合し、基準を除く8案から昼夜各1を保存する。

    引数: なし。返り値: None。後13場の数値を読まない。
    """
    verify_receipt()
    assert not FREEZE.exists(), "選択凍結を上書きしない"
    assert not list((HERE/"results/locked_test").glob("*.json")), "後半確認前に凍結する"
    folder = HERE/"results/train_validation"
    proof_path = folder/"再生完了163_train_validation.json"
    proof = read(proof_path)
    verify_proof(proof, "train_validation", 40)
    manifest, configs = read(MANIFEST), read(CONFIGS)
    source_scenes = {s["session"]:s for s in manifest["sessions"] if s["split"] in ("train", "validation")}
    expected_sessions = set(source_scenes)
    assert {r["session"] for r in proof["results"]} == expected_sessions
    ids = {config_id(c) for c in configs}
    assert len(configs) == 10 and ids == CONFIG_IDS
    summaries, sources = [], []
    for item in proof["results"]:
        path = Path(item["path"])
        path = (path if path.is_absolute() else ROOT/path).resolve()
        expected_path = (folder/(item["session"]+".json")).resolve()
        assert path == expected_path and sha(path) == item["sha256"]
        result = read(path)
        summaries.extend(scene_summaries(result, source_scenes[item["session"]]))
        sources.append(record(path))
    ranking = {kind:rank_candidates([s for s in summaries if s["kind"] == kind], sorted(CANDIDATE_IDS)) for kind in ("Day","Night")}
    assert all(r["sessions"] == 20 for rows in ranking.values() for r in rows)
    value = dict(selected={kind:rows[0]["id"] for kind,rows in ranking.items()}, test_opened=False,
        spec_sha256=sha(SPEC), configs_sha256=sha(CONFIGS), manifest_sha256=sha(MANIFEST),
        ranking_order=RANKING, quantile_method="linear", selection_sessions=40, selection_sessions_by_kind={"Day":20,"Night":20},
        selected_is_adoption=False, known_confirmation=True,
        scope="前30+次10場を昼夜別に選択。後13場は既知資料の追加確認で、全10を評価しても再選択しない。F00は固定昼夜の保存場行を連結し追加金融なし。",
        composition={"id":"F00","rule":"各場kindに対応する固定selectedの完了ケースを1つだけ使用","new_financial_replay":False},
        ranking=ranking, complete_proof=record(proof_path), results=sources,
        registration=record(RECEIPT), selection_implementation=record(Path(__file__)),
        created_at=datetime.now().astimezone().isoformat())
    value["content_sha256"] = canonical(value)
    save(FREEZE, value)
    print("前40場から昼夜別に凍結: "+str(value["selected"])+"。後半は未読。")


if __name__ == "__main__":
    main()
