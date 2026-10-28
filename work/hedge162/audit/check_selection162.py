"""凍結候補の順位と段階順を別計算する再現検算。金融結果は新たに生成しない。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parents[1]


def read(path: Path):
    """明示した資料を有限JSONとして読む。

    引数: path(Path)。返り値: dict 又は list。
    """
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    json.dumps(value, allow_nan=False)
    return value


def sha(path: Path) -> str:
    """資料を逐次読み内容指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_record(path: Path) -> dict:
    """監査対象ファイルを相対パスと指紋で記録する。

    引数: path(Path)。返り値: dict。
    """
    return dict(path=path.resolve().relative_to(ROOT).as_posix(), sha256=sha(path))


def verify_reference(item: dict) -> None:
    """登録根拠と現在の内容が一致することを確認する。

    引数: item(dict)。返り値: None。
    """
    path = (ROOT/item["path"]).resolve()
    assert path.is_relative_to(ROOT)
    assert sha(path) == item["sha256"], item["path"]


def quarter(values: list[float]) -> float:
    """25%点を順序統計量の線形補間式で独立計算する。

    引数: values(list[float])。返り値: float。numpyや元の選択関数は使わない。
    """
    ordered = sorted(values)
    assert ordered and all(math.isfinite(x) for x in ordered)
    position = (len(ordered)-1)/4
    lower = math.floor(position)
    upper = math.ceil(position)
    weight = position-lower
    return ordered[lower]*(1-weight)+ordered[upper]*weight


def same(a, b) -> bool:
    """整数は完全一致、数値集計は浮動小数の丸めだけを許して比較する。

    引数: a/b(int 又は float)。返り値: bool。
    """
    return a == b if isinstance(a, int) and isinstance(b, int) else math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-8)


def run() -> None:
    """全金融の完了後にだけ前40順位と後13の固定選択を監査する。

    引数: なし。返り値: None。新再生・採用変更・試行台帳更新は行わない。
    """
    out = HERE/"audit/selection_audit162.json"
    assert not out.exists(), "監査証跡を上書きしない"
    receipt_path = HERE/"登録受領162.json"
    receipt = read(receipt_path)
    assert receipt.get("registered") is True and type(receipt.get("returncode")) is int and receipt["returncode"] == 0
    for item in receipt["sources"]+[receipt["plan"],receipt["implementation"],receipt["preflight"]]:
        verify_reference(item)
    manifest_path, config_path, spec_path = HERE/"inputs162.json", HERE/"engine/configs162.json", HERE/"計画162.md"
    manifest, configs = read(manifest_path), read(config_path)
    expected_shas = {"manifest_sha256":sha(manifest_path),"configs_sha256":sha(config_path),"spec_sha256":sha(spec_path)}
    config_ids = {c["id"] for c in configs}
    cover_ids = {c["id"] for c in configs if c["cover"]}
    assert len(config_ids) == 26 and len(cover_ids) == 24
    records, completed, proofs, ranking_input = [], {}, [], []
    totals = {key: [] for key in cover_ids}
    troughs = {key: [] for key in cover_ids}
    for stage, count in (("train_validation",40),("locked_test",13)):
        folder = HERE/"results"/stage
        proof_path = folder/("再生完了162_"+stage+".json")
        proof = read(proof_path)
        assert proof.get("completed") is True and type(proof.get("returncode")) is int and proof["returncode"] == 0
        assert proof["sources_unchanged"] is True
        assert proof["sessions"] == count and proof["cases"] == count*26
        assert proof["stage"]["stage"] == stage
        assert all(proof["stage"].get(k) == v for k,v in expected_shas.items())
        expected_names = {s["session"] for s in manifest["sessions"] if (s["split"] == "test") == (stage == "locked_test")}
        assert len(expected_names) == count
        assert len(proof["results"]) == count and {r["session"] for r in proof["results"]} == expected_names
        for item in proof["results"]:
            path = Path(item["path"])
            path = (path if path.is_absolute() else ROOT/path).resolve()
            assert path == (folder/(item["session"]+".json")).resolve()
            assert item["cases"] == 26 and sha(path) == item["sha256"]
            records.append(local_record(path))
            if stage == "train_validation":
                data = read(path)
                assert data["session"] == item["session"] and data["split"] in ("train","validation")
                assert len(data["cases"]) == 26 and {c["id"] for c in data["cases"]} == config_ids
                for case in data["cases"]:
                    if case["id"] not in cover_ids:
                        continue
                    summary = case["summary"]
                    totals[case["id"]].append(float(summary["realized"]))
                    troughs[case["id"]].append(float(summary["minimum_equity"]))
                ranking_input.append(local_record(path))
        for name, expected in proof["sources"].items():
            source_path = Path(name)
            source_path = source_path if source_path.is_absolute() else ROOT/source_path
            assert sha(source_path) == expected, name
        completed[stage] = proof
        proofs.append(local_record(proof_path))
    # ----------------------------------------
    # 後13場の価格・損益内容は順位計算へ読まない。
    independent = []
    for key in cover_ids:
        assert len(totals[key]) == len(troughs[key]) == 40
        independent.append(dict(id=key,sessions=40,
            losing_sessions=sum(value < 0 for value in totals[key]),
            session_net_q25=quarter(totals[key]),minimum_equity=min(troughs[key]),
            total_net=math.fsum(totals[key])))
    independent.sort(key=lambda r:(r["losing_sessions"],-r["session_net_q25"],-r["minimum_equity"],-r["total_net"],r["id"]))
    freeze_path = HERE/"results/selection_frozen162.json"
    frozen = read(freeze_path)
    selected = [r["id"] for r in independent[:3]]
    assert frozen["selected"] == selected
    assert [r["id"] for r in frozen["ranking"]] == [r["id"] for r in independent]
    for mine, prior in zip(independent,frozen["ranking"]):
        assert all(same(mine[k],prior[k]) for k in ("sessions","losing_sessions","session_net_q25","minimum_equity","total_net"))
    assert frozen["test_opened"] is False and frozen["known_confirmation"] is True
    assert all(frozen.get(k) == v for k,v in expected_shas.items())
    content = {k:v for k,v in frozen.items() if k != "content_sha256"}
    content_hash = hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
    assert frozen["content_sha256"] == content_hash
    assert {r["path"]:r["sha256"] for r in frozen["results"]} == {r["path"]:r["sha256"] for r in ranking_input}
    for item in (frozen["complete_proof"],frozen["registration"],frozen["selection_implementation"]):
        verify_reference(item)
    permission_path = HERE/"locked_test_許可162.json"
    permission = read(permission_path)
    assert permission["freeze_sha256"] == sha(freeze_path)
    assert completed["locked_test"]["stage"]["freeze_sha256"] == sha(freeze_path)
    assert completed["locked_test"]["stage"]["selected"] == selected
    # ----------------------------------------
    # 保存時計は認証済みの外部時刻ではないが、手順内で前後逆転がないことを確認する。
    clock_values = [completed["train_validation"]["finished_at"],frozen["created_at"],
        permission["created_at"],completed["locked_test"]["started_at"],completed["locked_test"]["finished_at"]]
    clocks = [datetime.fromisoformat(value) for value in clock_values]
    assert clocks == sorted(clocks)
    report_path = HERE/"report_data162.json"
    report_record = None
    if report_path.exists():
        report = read(report_path)
        assert report["selected"] == selected
        assert {m["id"] for m in report["methods"] if m["selected"]} == set(selected)
        report_record = local_record(report_path)
    value = dict(passed=True, selected=selected, independently_recomputed_ranking=independent,
        selection_input_sessions=40, confirmation_sessions=13, verified_result_files=len(records),
        selection_uses_confirmation_values=False, reselection_after_confirmation=False,
        registered_sources_unchanged=True, independent_computation=True,
        scope="別式での再現検算。作成者は制御器と同じで、別人による独立監査・新しい有効性証拠ではない。",
        known_confirmation=True, timeline=dict(zip(("前半完了","選択凍結","後半許可","後半開始","後半完了"),clock_values)),
        ranking_inputs=ranking_input, verified_results=records,
        sources=[local_record(receipt_path),local_record(freeze_path),local_record(permission_path),*proofs,local_record(Path(__file__))],
        report=report_record)
    with out.open("x",encoding="utf-8") as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print("選択順位の別式再現検算PASS。前40場だけで "+", ".join(selected)+" を選択。")


def main() -> None:
    """金融終了後の明示実行だけを受け付ける。

    引数: CLI の --after-completion。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--after-completion",action="store_true",required=True)
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
