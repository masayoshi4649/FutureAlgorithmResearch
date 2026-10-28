"""完了後の保存値だけを別式で検算し、前40場の固定選択が維持されたことを記録する。"""
from datetime import datetime
import math
from pathlib import Path

from register163 import ROOT, HERE, MANIFEST, FREEZE, RECEIPT
from register163 import read, sha, record, save, verify_receipt


def quantile25(values: list[float]) -> float:
    """並べた値の間を線形補間して25%点を別式で算出する。

    引数: values(list[float])。返り値: float。元の順位関数やnumpyを呼ばない。
    """
    ordered = sorted(values)
    assert ordered and all(math.isfinite(v) for v in ordered)
    position = (len(ordered)-1)/4
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def independent_ranking(rows: list[dict]) -> list[dict]:
    """対象8条件の赤字数・25%点・最低時価・合計を再計算する。

    引数: rows(list[dict])は前40のうち昼又は夜20場。返り値: list[dict]。
    """
    candidates = ["D40", "D80", "G40", "G80", "R40", "R80", "E40", "E80"]
    ranking = []
    for identity in candidates:
        group = [r for r in rows if r["id"] == identity]
        assert len(group) == len({r["session"] for r in group}) == 20
        amounts = [r["net"] for r in group]
        ranking.append(dict(id=identity, sessions=20,
            losing_sessions=sum(value < 0 for value in amounts),
            session_net_q25=quantile25(amounts),
            minimum_equity=min(r["minimum"] for r in group), total_net=sum(amounts)))
    ranking.sort(key=lambda r: (r["losing_sessions"], -r["session_net_q25"], -r["minimum_equity"], -r["total_net"], r["id"]))
    return ranking


def timestamp(value: str) -> datetime:
    """タイムゾーン付き証跡時刻を比較可能な日時にする。

    引数: value(str)。返り値: datetime。
    """
    result = datetime.fromisoformat(value)
    assert result.tzinfo is not None
    return result


def main() -> None:
    """全金融完了を先に要求し、別計算と凍結時刻の照合だけを保存する。

    引数: なし。返り値: None。金融再生・候補変更・台帳更新は行わない。
    """
    completed_path = HERE/"再生全完了163.json"
    completed = read(completed_path)
    assert completed.get("completed") is True and type(completed.get("returncode")) is int and completed["returncode"] == 0
    assert completed["sessions"] == 53 and completed["cases"] == 530
    assert completed["reselection_after_confirmation"] is False
    verify_receipt()
    manifest, frozen = read(MANIFEST), read(FREEZE)
    assert completed["freeze"]["sha256"] == sha(FREEZE)
    assert frozen["known_confirmation"] is True and frozen["test_opened"] is False
    expected_ids = {"B00", "C50", "D40", "D80", "G40", "G80", "R40", "R80", "E40", "E80"}
    source_scenes = {s["session"]:s for s in manifest["sessions"]}
    all_rows, result_refs, proof_values = [], [], {}
    for stage, count in (("train_validation", 40), ("locked_test", 13)):
        folder = HERE/"results"/stage
        proof_path = folder/("再生完了163_"+stage+".json")
        proof = read(proof_path)
        assert proof["completed"] is True and type(proof["returncode"]) is int and proof["returncode"] == 0
        assert proof["sources_unchanged"] is True
        assert proof["sessions"] == count and proof["cases"] == count*10
        proof_values[stage] = proof
        expected = {name for name, scene in source_scenes.items() if (scene["split"] == "test") == (stage == "locked_test")}
        assert len(proof["results"]) == count and {r["session"] for r in proof["results"]} == expected
        for item in proof["results"]:
            path = Path(item["path"])
            path = (path if path.is_absolute() else ROOT/path).resolve()
            assert path == (folder/(item["session"]+".json")).resolve() and sha(path) == item["sha256"]
            result = read(path)
            scene = source_scenes[item["session"]]
            assert result["scene"]["session"] == scene["session"] and result["scene"]["kind"] == scene["kind"]
            assert len(result["cases"]) == 10 and {c["config"]["id"] for c in result["cases"]} == expected_ids
            for case in result["cases"]:
                actual = case["actual"]
                assert not actual["Active"] and not actual["Pending"]
                assert all(lot["Remaining"] == 0 for lot in actual["Lots"].values())
                row = dict(session=scene["session"], kind=scene["kind"], stage=stage,
                    id=case["config"]["id"], net=actual["Realized"], minimum=actual["Risk"]["Minimum"])
                assert math.isfinite(row["net"]) and math.isfinite(row["minimum"])
                all_rows.append(row)
            result_refs.append(record(path))
    # ----------------------------------------
    # 後半の値は完了・残玉の照合だけ。順位算出には前40場の値だけを渡す。
    before = [r for r in all_rows if r["stage"] == "train_validation"]
    rankings = {kind: independent_ranking([r for r in before if r["kind"] == kind]) for kind in ("Day", "Night")}
    assert rankings == frozen["ranking"]
    selected = {kind: ranking[0]["id"] for kind, ranking in rankings.items()}
    assert selected == frozen["selected"] == completed["selected"]
    after = proof_values["locked_test"]
    assert after["stage"]["selected"] == selected and after["stage"]["freeze_sha256"] == sha(FREEZE)
    permit_path = HERE/"locked_test_許可163.json"
    permit = read(permit_path)
    assert permit["freeze_sha256"] == sha(FREEZE)
    times = dict(front_finished=proof_values["train_validation"]["finished_at"],
        frozen_at=frozen["created_at"], confirmation_permitted_at=permit["created_at"],
        confirmation_started=after["started_at"], confirmation_finished=after["finished_at"])
    ordered = [timestamp(value) for value in times.values()]
    assert all(a <= b for a,b in zip(ordered, ordered[1:]))
    assert completed["composition"]["id"] == "F00" and completed["composition"]["new_financial_replay"] is False
    save(HERE/"audit/selection_audit163.json", dict(passed=True,
        selected=selected, rankings=rankings, results_verified=len(result_refs), cases_verified=len(all_rows),
        selection_uses_confirmation_values=False, reselection_after_confirmation=False,
        independent_formula=True, independent_person=False, evidence_kind="同一担当者による別式の再現検算。新たな有効性証拠ではない。",
        financial_replays=0, registry_writes=0, sources_unchanged=True,
        known_development=True, timeline=times, results=result_refs,
        sources=[record(p) for p in (Path(__file__), FREEZE, MANIFEST, RECEIPT, completed_path, permit_path)],
        created_at=datetime.now().astimezone().isoformat()))
    print("前40場の昼夜固定順位を別式で再現。後13場による再選択なし。")


if __name__ == "__main__":
    main()
