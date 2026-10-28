"""trainの保存特徴だけから板指標の分位を固定する。ラベル・validation・testは読まない。"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    """30train場だけの尺度と入力指紋を新しいJSONへ保存する。

    引数: CLI(manifest/data/out)。返り値: None。予測成績を算出しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    scenes = [scene for scene in manifest["sessions"] if scene["split"] == "train"]
    assert len(scenes) == 30
    values = defaultdict(lambda: defaultdict(list))
    counts, proof = defaultdict(int), []
    for scene in scenes:
        path = args.data / "features/train" / f"{scene['session']}.npz"
        with np.load(path, allow_pickle=False) as packed:
            names = list(packed["feature_names"].astype(str))
            matrix, phases = packed["features"], packed["phase"]
            phase_names = np.array(["Day", "preUS", "postUS"])[phases]
            spread = matrix[:, names.index("spread")]
            eligible = (spread > 0) & (spread <= 20)
            for phase in np.unique(phase_names):
                mask = eligible & (phase_names == phase)
                counts[phase] += int(mask.sum())
                for name in ("ofi15", "depth_imb", "bid_refill15", "ask_refill15"):
                    column = matrix[mask, names.index(name)]
                    column = column[np.isfinite(column)]
                    if name in ("ofi15", "depth_imb"):
                        column = np.abs(column)
                    values[phase][name].append(column)
        proof.append(dict(session=scene["session"], split="train", features=str(path),
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result = dict(source="30train場の正常気配差20円以下。ラベル、validation、testの読取0。",
                  method="特徴ごとに有限値をプールし、NumPyの線形補間分位50/75/90を固定。OFIとdepthは絶対値。",
                  thresholds={}, eligible_rows=dict(counts), input_features=proof)
    for phase, columns in values.items():
        result["thresholds"][phase] = {}
        for name, parts in columns.items():
            column = np.concatenate(parts)
            assert len(column) > 0
            result["thresholds"][phase][name] = dict(count=len(column),
                quantiles={str(q): max(1e-12, float(np.quantile(column, q))) for q in (.50, .75, .90)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps(result["thresholds"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
