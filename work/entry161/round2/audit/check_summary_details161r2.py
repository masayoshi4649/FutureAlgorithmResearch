"""保存済み第二巡の買売・観測品質・基準・判断時計を追加再集計する。"""

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

from audit_results161r2 import BASE, HERE, WORK, ROOT, common


def verify_extra(events, summary):
    """買売方向別と観測品質の正例数を全保存イベントから確認する。

    引数: events(list)、summary(dict)。返り値: None。
    """
    for side in (1, -1):
        selected = [e for e in events if e["side"] == side]
        expected = dict(events=len(selected), successes=sum(e["status"] == 1 for e in selected),
                        adverse_first=sum(e["status"] == -1 for e in selected))
        assert summary["by_side"][str(side)] == expected
    for key, values in summary["observation_quality"].items():
        available = [e for e in events if key in e]
        positive = [e for e in available if e[key] > 0]
        assert values == dict(recorded=len(available), positive=len(positive),
                              success_with_positive=sum(e["status"] == 1 for e in positive))


def main():
    """事後監査合格後に追加の集計だけを保存する。

    引数: なし。返り値: None。信号の生成や採用条件の変更をしない。
    """
    assert common.read(HERE / "audit161r2.json")["passed"]
    paths = [WORK / "results/train_validation161.json", WORK / "results/locked_test161.json"]
    before = {p: common.sha(p) for p in paths}
    development, confirmed = [common.read(p) for p in paths]
    scenes = common.read(BASE / "inputs161.json")["sessions"]
    summaries = 0; clocks = defaultdict(lambda: dict(events=0, adjacent_pairs=0, decision_under60=0, entry_under60=0,
                                                    min_decision_gap=None, min_entry_gap=None, max_entry_delay=0, examples=[]))
    for stage, phases in development["events"].items():
        for phase, candidates in phases.items():
            for candidate, events in candidates.items():
                verify_extra(events, development["reports"][phase][candidate][stage]); summaries += 1
                previous = {}
                for event in events:
                    value = clocks[stage]; value["events"] += 1
                    if event["entry_time"] is not None:
                        value["max_entry_delay"] = max(value["max_entry_delay"], event["entry_time"] - event["decision_time"])
                    old = previous.get(event["session"])
                    if old is not None:
                        value["adjacent_pairs"] += 1
                        gap = event["decision_time"] - old["decision_time"]
                        value["decision_under60"] += gap < 60
                        value["min_decision_gap"] = gap if value["min_decision_gap"] is None else min(value["min_decision_gap"], gap)
                        if old["entry_time"] is not None and event["entry_time"] is not None:
                            entry_gap = event["entry_time"] - old["entry_time"]
                            value["entry_under60"] += entry_gap < 60
                            value["min_entry_gap"] = entry_gap if value["min_entry_gap"] is None else min(value["min_entry_gap"], entry_gap)
                            if entry_gap < 60 and len(value["examples"]) < 3:
                                value["examples"].append(dict(phase=phase, candidate=candidate, session=event["session"],
                                                              prior_decision=old["decision_time"], decision=event["decision_time"],
                                                              prior_entry=old["entry_time"], entry=event["entry_time"]))
                    previous[event["session"]] = event
    for phase, events in confirmed["events"].items():
        verify_extra(events, confirmed["reports"][phase]); summaries += 1
    baseline_checks = 0
    for phase, baselines in confirmed["baselines"].items():
        kind = "Day" if phase == "Day" else "Night"
        names = [s["session"] for s in scenes if s["split"] == "test" and s["kind"] == kind]
        # ----------------------------------------
        # 基準の全イベントは結果へ保存されないため、第一巡の同一基準数値との完全一致を確認する。
        first = common.read(BASE / "results/locked_test161.json")["baselines"][phase]
        assert baselines == first
        baseline_checks += len(baselines)
    for path, expected in before.items():
        assert common.sha(path) == expected
    assert all(row["decision_under60"] == 0 for row in clocks.values())
    result = dict(passed=True, created_at=datetime.now().astimezone().isoformat(), extra_summaries=summaries,
                  baseline_same_as_first=baseline_checks, clock_details=dict(clocks), new_evaluations=0,
                  meaning="待機は判断から次判断まで60秒。実際の次正常原行約定間隔とは別。価格時計差は通信遅延そのものではない。",
                  sources=[dict(path=p.relative_to(ROOT).as_posix(), sha256=v) for p, v in before.items()])
    out = HERE / "買売と観測品質と待機時計161r2.json"
    with out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps(dict(passed=True, extra_summaries=summaries, baseline_checks=baseline_checks, clocks=dict(clocks)), ensure_ascii=False))


if __name__ == "__main__":
    main()
