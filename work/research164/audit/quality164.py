"""夜の品質フラグを原板から別計算し、無取引を品質評価と混同しない。"""
from concurrent.futures import ProcessPoolExecutor
from collections import Counter

import numpy as np

from audit_results164 import HERE, WORK, read, save, record, read_market, normal_mask


def check(scene: dict) -> dict:
    """保存判断の異常板数と正常板間空白数を確認する。

    引数: scene(dict)。返り値: dict。取引条件は再実行しない。
    """
    stage = "train_validation" if scene["split"] in ("train", "validation") else "confirmation"
    saved = read(WORK / "results" / stage / (scene["session"] + ".json"))
    raw, source = read_market(scene, "NK225")
    valid = normal_mask(raw)
    good = np.flatnonzero(valid)
    bad = np.cumsum(~valid)
    gap = np.zeros(len(raw), dtype=np.int64)
    gap[good[1:]] = np.diff(raw[good, 0]) > 15
    gap = np.cumsum(gap)
    totals = Counter()
    cases = []
    for case in saved["cases"]:
        counts = Counter()
        for trace in case["trigger_trace"] or []:
            f = trace["Features"]
            if not f["FirstNormal"]:
                continue
            i, at = trace["Index"], trace["Time"]
            for span in (15, 60, 120, 300):
                pos = int(np.searchsorted(raw[good, 0], at - span, side="right")) - 1
                if pos < 0:
                    continue
                k = good[pos]
                if at - span - raw[k, 0] > (1 if span == 15 else 15):
                    continue
                assert f["Invalid" + str(span)] == int(bad[i] - bad[k])
                assert f["Gaps" + str(span)] == int(gap[i] - gap[k])
                counts["checked_windows"] += 1
            counts["checked_traces"] += 1
            if trace["Kind"] == "新規":
                counts["new_decisions"] += 1
                counts["new_with_bad300"] += f["Invalid300"] > 0
                counts["new_with_gap300"] += f["Gaps300"] > 0
        totals.update(counts)
        cases.append(dict(id=case["config"]["id"], quality_checks=dict(counts), engine_counts=case["counts"]))
    return dict(session=scene["session"], passed=True, totals=dict(totals), cases=cases, raw=source)


def main() -> None:
    """金融完了後のみ品質の補足監査を出す。

    引数: なし。返り値: None。第一監査JSONは変更しない。
    """
    assert read(WORK / "再生全完了164.json")["completed"]
    assert read(HERE / "audit164.json")["passed"]
    scenes = [s for s in read(WORK / "inputs164.json")["sessions"] if s["kind"] == "Night"]
    with ProcessPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, scenes))
    totals = Counter()
    for result in results:
        totals.update(result["totals"])
    save(HERE / "夜の品質独立監査164.json", dict(passed=True, financial_replays=0, totals=dict(totals), scenes=results,
        accounting_audit=record(HERE / "audit164.json"), source=record(__import__('pathlib').Path(__file__))))
    print(dict(passed=True, totals=dict(totals)))


if __name__ == "__main__":
    main()
