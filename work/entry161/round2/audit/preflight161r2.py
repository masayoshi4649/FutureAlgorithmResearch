"""第二巡の人工監査とtrain特徴だけの分位照合を登録前に確定する。"""

from collections import defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
BASE = WORK.parent
ROOT = BASE.parents[1]


def read(path):
    """UTF-8の小さい証跡を読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """ファイルのSHA256を読み取る。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_quantiles():
    """既存train特徴だけで正分位と母集団を独立に再計算する。

    引数: なし。返り値: dict。ラベル、validation、testは読まない。
    """
    saved = read(WORK / "search/thresholds161r2.json")
    scenes = [r for r in read(BASE / "inputs161.json")["sessions"] if r["split"] == "train"]
    assert len(scenes) == len(saved["input_features"]) == 30
    expected = {s["session"] for s in scenes}
    assert {r["session"] for r in saved["input_features"]} == expected
    columns = defaultdict(list)
    phase_counts = defaultdict(int)
    input_proofs = []
    for record in saved["input_features"]:
        assert record["split"] == "train"
        path = Path(record["features"])
        if not path.is_absolute():
            path = ROOT / path
        assert path.resolve() == (BASE / "data/features/train" / (record["session"] + ".npz")).resolve()
        assert sha(path) == record["sha256"]
        with np.load(path, allow_pickle=False) as data:
            names = list(data["feature_names"].astype(str))
            matrix, phases = data["features"], data["phase"]
            assert set(np.unique(phases)).issubset({0, 1, 2})
            spread = matrix[:, names.index("spread")]
            good = np.isfinite(spread) & (spread > 0) & (spread <= 20)
            for i, phase in enumerate(("Day", "preUS", "postUS")):
                mask = good & (phases == i)
                phase_counts[phase] += int(mask.sum())
                for column in ("ofi15", "depth_imb", "bid_refill15", "ask_refill15"):
                    values = matrix[mask, names.index(column)]
                    values = values[np.isfinite(values)]
                    if column in ("ofi15", "depth_imb"):
                        values = np.abs(values)
                    columns[(phase, column)].append(values)
        input_proofs.append(dict(session=record["session"], path=path.relative_to(ROOT).as_posix(), sha256=record["sha256"]))
    assert dict(phase_counts) == saved["eligible_rows"]
    checked = []
    for (phase, name), parts in columns.items():
        values = np.sort(np.concatenate(parts))
        target = saved["thresholds"][phase][name]
        assert len(values) == target["count"] and len(values) > 0
        for q in (.5, .75, .9):
            # ----------------------------------------
            # NumPy quantileを呼ばず、整列値の位置と線形補間から同じ定義を計算する。
            index = (len(values) - 1) * q
            lo, hi = int(np.floor(index)), int(np.ceil(index))
            value = max(1e-12, float(values[lo] + (values[hi] - values[lo]) * (index - lo)))
            expected_value = target["quantiles"][str(q)]
            assert np.isclose(value, expected_value, atol=1e-16, rtol=1e-13), (phase, name, q, value, expected_value)
            checked.append(dict(phase=phase, feature=name, quantile=q, value=value, count=len(values)))
    return dict(passed=True, files=30, quantiles=len(checked), eligible_rows=dict(phase_counts),
                inputs=input_proofs, comparisons=checked, labels_read=0, validation_read=0, test_read=0,
                note="有限値の原行プール分位。セッションを等加重する分位ではなく、更新の多い場の寄与が大きい。")


def main():
    """固定実装の人工試験と分位同一性を検査し、事前監査を新規保存する。

    引数: なし。返り値: None。候補の先着評価や登録は実行しない。
    """
    target = HERE / "preflight161r2.json"
    assert not target.exists() and not (WORK / "登録受領161r2.json").exists()
    assert not (WORK / "results").exists(), "第二巡の成績算出前に監査する"
    prior = read(BASE / "登録受領161.json")
    assert prior["registered"] is True and prior["returncode"] == 0
    for record in prior["sources"] + [prior["implementation"], prior["plan"]]:
        assert sha(ROOT / record["path"]) == record["sha256"], record["path"]
    specification = read(WORK / "search/spec161.json")
    assert specification["candidate_count"] == 24 and specification["learned_models"] is False
    for record in specification["implementation"]:
        assert sha(WORK / "search" / record["file"]) == record["sha256"], record["file"]
    files = sorted(p for p in (WORK / "search").rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".md"})
    files += [WORK / name for name in ("計画161r2.md", "register161r2.py", "allow161r2.py")]
    files += sorted(HERE.glob("*.py"))
    files += [BASE / "inputs161.json", BASE / "search/engine161.py", BASE / "search/rules161.py", BASE / "search/spec161.json"]
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in files}
    test_paths = [WORK / "search/test_round2161.py", BASE / "search/test_engine161.py", HERE / "test_independent161r2.py"]
    runs = []
    for index, path in enumerate(test_paths, 1):
        run = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                             text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = HERE / f"人工最終検査161r2_{index}.log"
        log.write_text(run.stdout, encoding="utf-8")
        count = re.search(r"Ran (\d+) tests?", run.stdout)
        assert run.returncode == 0 and count and re.search(r"\bOK\b", run.stdout), run.stdout[-4000:]
        runs.append(dict(path=path.relative_to(ROOT).as_posix(), tests=int(count.group(1)), returncode=run.returncode,
                         log=log.relative_to(ROOT).as_posix(), log_sha256=sha(log)))
    calibration = validate_quantiles()
    calibration_path = HERE / "train分位の独立照合161r2.json"
    calibration_path.write_text(json.dumps(calibration, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for path, value in before.items():
        assert sha(ROOT / path) == value, path
    output = dict(passed=True, created_at=datetime.now().astimezone().isoformat(), candidate_count=24,
                  candidate_financial_measurements=0, new_candidate_evaluations=0, financial_replays=0, api_calls=0,
                  reused_feature_extraction=True, known_confirmation=True, sources=[dict(path=p, sha256=v) for p, v in sorted(before.items())],
                  tests=runs, tests_total=sum(r["tests"] for r in runs), independent_tests=runs[-1]["tests"],
                  calibration=dict(path=calibration_path.relative_to(ROOT).as_posix(), sha256=sha(calibration_path), files=30, quantiles=36),
                  original_receipt_sources_unchanged=True,
                  checked=["8構造×3強度の全24条件・両方向を人工500行の独立逐次式で照合", "ゼロ分位1e-12下限と補充同量の非成立", "強度上昇で成立行を追加しない", "両巡の登録源不変・失敗受領の拒否・選択凍結前の後半禁止", "30train特徴だけの36分位をソートと補間の別式で再計算", "新学習器なし、既知後半の留保を全出力へ挿入"],
                  accepted_boundaries=["後半13場は第一巡結果が既知であり、独立未見の認証ではない", "表示数量変化は注文IDに基づく実補充や成行フローの直接観測ではない", "CurrentPriceTimeは受信時計でなく、同時計順序と厳密過去相手板による代理同期", "分位は有限特徴の原行プールであり日別等加重ではない。補充分位は買売別で方向対称の性能を保証しない", "候補×phaseの未決ロック、判断から次判断まで60秒。前後区分を合算した単一戦略ではない", "第一巡の特徴・ラベル・条件採点器を不変再利用し、板条件だけ別に比較"],
                  open_blockers=[])
    with target.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=True, tests=output["tests_total"], independent=output["independent_tests"], quantiles=36, sources=len(before), sha256=sha(target)), ensure_ascii=False))


if __name__ == "__main__":
    main()
