"""train の価格尺度記録を実際の観測時間帯へ分け直す。"""
from collections import Counter
import json
from pathlib import Path

from measure162 import ROOT, OUT, HORIZONS, dist, native, summarize


def run():
    """保存済みの非金融観測を重複排除し、時間帯別分布を出す。

    引数: なし。返り値: なし。
    """
    manifest = json.loads((ROOT / "work/entry161/inputs161.json").read_text(encoding="utf-8"))
    scenes = {s["session"]: s for s in manifest["sessions"] if s["split"] == "train"}
    rows, seen = [], set()
    cross = Counter()
    with (OUT / "逆行局面の観測162.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            s = scenes[r["session"]]
            actual = "Day" if s["kind"] == "Day" else "preUS" if r["time"] < s["us_open"] else "postUS"
            cross[(r["phase"], actual, r["cohort"])] += 1
            r["entry_phase"], r["phase"] = r["phase"], actual
            key = (r["session"], actual, r["cohort"], r["side"], r["anchor_index"])
            if r["cohort"] == "adverse_grid60" and key in seen:
                continue
            seen.add(key)
            for h in HORIZONS:
                r["windows"][str(h)]["cross_us_open"] = s["kind"] == "Night" and r["time"] < s["us_open"] <= r["time"]+h
            rows.append(r)
    result = summarize(rows)
    for phase, cohorts in result.items():
        group = [r for r in rows if r["phase"] == phase and r["cohort"] == "adverse_grid60"]
        sessions = sorted({r["session"] for r in group})
        result[phase]["adverse_grid60"]["past_cover_direction"] = {
            k: dist([(-r["side"]*r["past_features"][k]) if r["past_features"].get(k) is not None else float("nan") for r in group])
            for k in ("ret5_pt", "ret15_pt", "ret60_pt", "ofi15", "depth_imb")}
        result[phase]["adverse_grid60"]["each_session"] = {
            session: {
                str(h): {
                    k: dist([r["windows"][str(h)][k] for r in group if r["session"] == session
                        and r["windows"][str(h)]["quality"] == "端点1秒内"
                        and r["windows"][str(h)].get("max_clock_gap_s", 999) <= 15
                        and r["windows"][str(h)].get("bad_bbo_rows", 1) == 0])
                    for k in ("abs_change_pt", "cover_direction_excursion_pt", "peak_giveback_pt")}
                for h in HORIZONS}
            for session in sessions}
    out = dict(scope="trainのみ。入口phaseと当該観測phaseを分離。後者で格子原行を再重複排除。損益計算なし。",
               phase_cross_counts={"/".join(k): v for k, v in cross.items()}, actual_phase=result)
    (OUT / "観測時間帯別の尺度162.json").write_text(json.dumps(native(out), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    for phase in ("Day", "preUS", "postUS"):
        s = result[phase]["adverse_grid60"]
        print(phase, "anchors", s["anchors"], "spread", s["spread"]["quantiles"])
        for h in HORIZONS:
            w = s["windows"][str(h)]
            print(h, "known", w["clean_strict_count"], "/", w["all"],
                  "abs", w["clean_strict"]["abs_change_pt"]["quantiles"],
                  "exc", w["clean_strict"]["cover_direction_excursion_pt"]["quantiles"],
                  "return", w["clean_strict"]["peak_giveback_pt"]["quantiles"])


if __name__ == "__main__":
    run()
