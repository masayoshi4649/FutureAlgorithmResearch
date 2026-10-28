"""固定選択の開発事象と保存特徴だけで、無信号・スコア過信・先着失敗の内訳を記述する。"""

from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "search"))
from rules161 import model_matrix, transform, predict


def load(path):
    """保存された開発JSONを読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def quantiles(values):
    """有限の特徴分布を診断用の分位点にまとめる。

    引数: values(list[ndarray])。返り値: dict。独立標本の件数ではない。
    """
    x = np.concatenate(values) if values else np.array([])
    x = x[np.isfinite(x)]
    return dict(observations=len(x), percentiles={str(p): float(np.percentile(x, p)) for p in (50, 90, 95, 99, 99.9, 100)} if len(x) else {})


def main():
    """完成済みtrain/validationだけを読み、固定事象の追加診断を保存する。

    引数: なし。返り値: None。test・原板・新規売買エンジンを読まない。
    """
    report = load(HERE.parent / "results/train_validation161.json")
    frozen = load(HERE.parent / "results/selection_frozen161.json")
    access = {}
    for row in report["access"]:
        assert row["split"] in ("train", "validation")
        access[row["session"]] = row
    event_map = defaultdict(list)
    for stage in ("train", "validation"):
        for phase, candidate in frozen["selected"].items():
            for row in report["events"][stage][phase][candidate]:
                event_map[row["session"]].append(row)
    groups = defaultdict(lambda: defaultdict(int))
    feature_distribution = defaultdict(lambda: defaultdict(list))
    selected = []
    phase_map = np.array(["Day", "preUS", "postUS"])
    for session, paths in sorted(access.items()):
        stage = paths["split"]
        with np.load(paths["features"], allow_pickle=False) as packed:
            matrix = packed["features"]
            names = list(packed["feature_names"].astype(str))
            phases = packed["phase"]
            phases = phase_map[phases] if phases.dtype.kind in "iu" else phases.astype(str)
            f = {name: matrix[:, i] for i, name in enumerate(names)}
            feature_index = packed["decision_index"]
            times = packed["time"]
        # ----------------------------------------
        # 固定B01/S01の各門の成立頻度を記述します。閾値を変更して新採点しません。
        for phase in np.unique(phases):
            mask = phases == phase
            key = stage + "/" + phase
            g = groups[key]
            g["normal_decision_rows"] += int(mask.sum())
            for name in ("ofi15", "bid_refill15", "ask_refill15", "depth_imb"):
                feature_distribution[key][name].append(f[name][mask])
            for side in (1, -1):
                base = mask & (f["spread"] > 0) & (f["spread"] <= 20)
                b_gates = dict(depth=side*f["depth_imb"] >= .2, ofi=side*f["ofi15"] >= .1,
                               price=side*f["ret15_pt"] >= 0, position=(f["pos60"] if side == 1 else 1-f["pos60"]) >= .6)
                s_gates = dict(ofi=side*f["ofi15"] <= -.1, hold=side*f["ret15_pt"] >= -10,
                               rebound=side*f["ret5_pt"] >= 10, refill=f["bid_refill15" if side == 1 else "ask_refill15"] >= .2)
                for family, gates in (("B01", b_gates), ("S01", s_gates)):
                    total = base.copy()
                    for name, gate in gates.items():
                        g[family+"_"+name] += int((base & gate).sum())
                        total &= gate
                    g[family+"_all"] += int(total.sum())
        # ----------------------------------------
        # 選択済み事象だけ、同じラベルの順序と固定モデルの点数を読む再集計です。
        with np.load(paths["labels"], allow_pickle=False) as packed:
            labels = {name: packed[name] for name in packed.files if name != "metadata"}
        for event in event_map[session]:
            row, side = event["row"], event["side"]
            col = 0 if side == 1 else 1
            assert int(feature_index[row]) == event["decision_index"]
            assert int(labels["primary_status"][row, col]) == event["status"]
            up = int(labels["primary_first_up_index"][row, col])
            down = int(labels["primary_first_down_index"][row, col])
            value = dict(session=session, stage=stage, phase=event["phase"], candidate=event["candidate"],
                         decision_index=event["decision_index"], decision_time=event["decision_time"], side=side,
                         status=event["status"], first_up_index=up, first_down_index=down,
                         later_favorable_after_failure=event["status"] == -1 and up >= 0 and up > down,
                         model_score=None, entry_wait=float(labels["entry_price_clock_gap_s"][row]))
            if event["candidate"].startswith(("GL", "DT")):
                model = frozen["models"][event["phase"]]
                family = event["candidate"][:-2]
                features = {name: np.asarray([array[row]]) for name, array in f.items()}
                x = transform(model_matrix(features, side), model["preprocess"])
                value["model_score"] = float(predict(x, model[family])[0])
            selected.append(value)
    summary = {}
    for stage in ("train", "validation"):
        for phase, candidate in frozen["selected"].items():
            rows = [x for x in selected if x["stage"] == stage and x["phase"] == phase]
            failed = [x for x in rows if x["status"] == -1]
            scores = [x["model_score"] for x in rows if x["model_score"] is not None]
            summary[stage+"/"+phase] = dict(candidate=candidate, events=len(rows), success=sum(x["status"] == 1 for x in rows),
                failure=len(failed), failure_later_reached_100=sum(x["later_favorable_after_failure"] for x in failed),
                mean_model_score=float(np.mean(scores)) if scores else None,
                max_model_score=max(scores) if scores else None,
                entry_wait_p95=float(np.percentile([x["entry_wait"] for x in rows], 95)) if rows else None)
    output = dict(scope="固定train/validation結果の記述診断。test未閲覧、閾値変更0、新金融再生0。",
                  gate_counts={key: dict(value) for key, value in groups.items()},
                  feature_distributions={key: {name: quantiles(value) for name, value in columns.items()} for key, columns in feature_distribution.items()},
                  selected_summary=summary, selected_events=selected)
    path = HERE / "無信号と学習スコアの開発診断161.json"
    with path.open("x", encoding="utf-8") as out:
        json.dump(output, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
