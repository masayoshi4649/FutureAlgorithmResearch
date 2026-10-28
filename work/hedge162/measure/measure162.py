"""train 原板の逆行局面を記述する。売買シミュレーションと損益計算は行わない。"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "work/entry161/features"))
from features161 import read_market

OUT = Path(__file__).resolve().parent
PICKS = {"Day": "R02", "preUS": "GL01", "postUS": "GL02"}
HORIZONS = (1, 5, 15, 30, 60)
QS = (0, .25, .5, .75, .9, .95, .99, 1)


def sha(path: Path) -> str:
    """ファイル内容を識別する。

    引数: path(Path)。返り値: str は SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dist(values: list) -> dict:
    """観測値の分位と欠測数を計算する。

    引数: values(list)。返り値: dict は有限値数・分位・平均。
    """
    a = np.asarray(values, dtype=float)
    good = a[np.isfinite(a)]
    return dict(count=len(a), known=len(good), missing=len(a)-len(good),
                mean=float(np.mean(good)) if len(good) else None,
                quantiles={str(q): float(v) for q, v in zip(QS, np.quantile(good, QS))} if len(good) else {})


def native(value):
    """NumPy 値と欠測を JSON に適した型へ写す。

    引数: value(object)。返り値: object は Python 基本型。
    """
    if isinstance(value, dict):
        return {str(k): native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [native(v) for v in value]
    if isinstance(value, np.generic):
        return native(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def window(market: dict, anchor: int, side: int, horizon: int, good: np.ndarray) -> dict:
    """逆玉方向の実観測変化と途中の戻しを固定秒窓で記述する。

    引数: market(dict)、anchor/side/horizon(int)、good(ndarray)。返り値: dict。
    """
    t = market["time"]
    target = t[anchor]+horizon
    j = np.searchsorted(t[good], target, side="right")-1
    end = int(good[j]) if j >= 0 else -1
    outside = target > t[-1]
    newer = end > anchor and t[end] > t[anchor]
    age = target-t[end] if end >= 0 else np.nan
    quality = "場末不足" if outside else "新価格時計なし" if not newer else "端点1秒内" if age <= 1 else "端点15秒内" if age <= 15 else "端点15秒超"
    row = dict(horizon=horizon, quality=quality, endpoint_age_s=age, elapsed_s=t[end]-t[anchor] if end >= 0 else None)
    if outside or not newer or age > 15:
        return row
    ix = good[np.searchsorted(good, anchor):np.searchsorted(good, end, side="right")]
    # ----------------------------------------
    # 正は元玉の逆方向へ進んだ幅。実注文や気配差込みの損益ではない。
    path = -side*(market["mid"][ix]-market["mid"][anchor])
    high = np.maximum.accumulate(path)
    draw = high-path
    draw_end = int(np.argmax(draw))
    peak = int(np.argmax(path[:draw_end+1]))
    elapsed = t[ix[draw_end]]-t[ix[peak]]
    jumps = np.diff(t[ix])
    row.update(change_pt=path[-1], abs_change_pt=abs(path[-1]),
               cover_direction_excursion_pt=max(0, float(np.max(path))),
               against_cover_excursion_pt=max(0, float(-np.min(path))),
               peak_giveback_pt=float(draw[draw_end]),
               giveback_clock_s=elapsed,
               giveback_speed_pt_s=float(draw[draw_end]/elapsed) if elapsed > 0 else None,
               same_clock_giveback=bool(draw[draw_end] > 0 and elapsed == 0),
               max_clock_gap_s=float(max(jumps, default=0)),
               bad_bbo_rows=int(np.sum(~market["valid"][anchor:end+1])),
               observations=len(ix), endpoint_spread=market["ask"][end]-market["bid"][end])
    return row


def summarize(rows: list) -> dict:
    """固定された窓観測を phase・母集団別に集計する。

    引数: rows(list[dict])。返り値: dict。
    """
    answer = {}
    for phase in PICKS:
        answer[phase] = {}
        for cohort in ("entry", "first_minus50", "adverse_grid60"):
            group = [r for r in rows if r["phase"] == phase and r["cohort"] == cohort]
            by_h = {}
            for h in HORIZONS:
                windows = [r["windows"][str(h)] for r in group]
                strict = [w for w in windows if w["quality"] == "端点1秒内" and w.get("max_clock_gap_s", 999) <= 15 and w.get("bad_bbo_rows", 1) == 0]
                loose = [w for w in windows if "change_pt" in w]
                names = ("change_pt", "abs_change_pt", "cover_direction_excursion_pt", "against_cover_excursion_pt", "peak_giveback_pt", "giveback_clock_s", "giveback_speed_pt_s", "endpoint_spread")
                by_h[str(h)] = dict(all=len(windows), quality=dict(Counter(w["quality"] for w in windows)),
                    clean_strict_count=len(strict), observed_count=len(loose),
                    clean_strict={k: dist([w.get(k, np.nan) if w.get(k) is not None else np.nan for w in strict]) for k in names},
                    observed={k: dist([w.get(k, np.nan) if w.get(k) is not None else np.nan for w in loose]) for k in names},
                    same_clock_giveback_count=sum(w.get("same_clock_giveback", False) for w in strict))
            answer[phase][cohort] = dict(anchors=len(group), sessions=len(set(r["session"] for r in group)),
                spread=dist([r["spread"] for r in group]), windows=by_h)
    return answer


def run():
    """train 30 場のみを読み、価格尺度の記述成果を保存する。

    引数: なし。返り値: なし。新戦略・新損益は計算しない。
    """
    manifest_path = ROOT / "work/entry161/inputs161.json"
    source_path = ROOT / "work/entry161/results/train_validation161.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))["events"]["train"]
    events = [e for phase, key in PICKS.items() for e in source[phase][key]]
    assert all(e["split"] == "train" for e in events)
    scenes = [s for s in manifest["sessions"] if s["split"] == "train"]
    assert len(scenes) == 30
    event_summaries, anchor_rows, sources = [], [], []
    for scene in scenes:
        market, proof = read_market(scene, "NK225")
        sources.append(proof)
        good = np.flatnonzero(market["valid"])
        observations = market["observations"]
        feature_path = ROOT / "work/entry161/data/features/train" / (scene["session"]+".npz")
        with np.load(feature_path, allow_pickle=False) as fp:
            features = {str(k): fp["features"][:, i] for i, k in enumerate(fp["feature_names"])}
            feature_index = {int(ix): r for r, ix in enumerate(fp["decision_index"])}
        dedup = set()
        for event in [e for e in events if e["session"] == scene["session"]]:
            entry, side = event["entry_index"], event["side"]
            if entry < 0:
                event_summaries.append(dict(session=scene["session"], phase=event["phase"], unfilled=True))
                continue
            # ----------------------------------------
            # 未来経路は train 記述だけに使用し、入口の選択・指標へ戻さない。
            ix = good[good >= entry]
            mark = side*((market["bid"] if side > 0 else market["ask"])[ix]-event["entry_price"])
            hit = np.flatnonzero(mark >= 100)
            stop_pos = int(hit[0]) if len(hit) else len(ix)-1
            ix, mark = ix[:stop_pos+1], mark[:stop_pos+1]
            end = int(ix[-1])
            adverse = np.flatnonzero(mark <= -50)
            first50 = int(ix[adverse[0]]) if len(adverse) else -1
            reaches_zero_after50 = False
            recovery_seconds = np.nan
            additional_dip = np.nan
            if first50 >= 0:
                after = np.flatnonzero(ix >= first50)
                hits_zero = after[mark[after] >= 0]
                zero_stop = int(hits_zero[0]) if len(hits_zero) else len(ix)-1
                reaches_zero_after50 = bool(len(hits_zero))
                recovery_seconds = market["time"][ix[zero_stop]]-market["time"][first50] if reaches_zero_after50 else np.nan
                additional_dip = max(0, float(mark[adverse[0]]-np.min(mark[adverse[0]:zero_stop+1])))
            summary = dict(session=scene["session"], phase=event["phase"], side=side,
                decision_index=event["decision_index"], entry_index=entry, entry_time=event["entry_time"],
                entry_price=event["entry_price"], original_status=event["status"], first100_or_end_index=end,
                reaches100=bool(len(hit)), first_minus50_index=first50, first_minus50_time=market["time"][first50] if first50 >= 0 else None,
                mae_until_first100_or_end=float(max(0, -np.min(mark))),
                additional_dip_after50_until_zero=additional_dip, recovered_zero_after50=reaches_zero_after50,
                recovery_seconds=recovery_seconds, duration_seconds=market["time"][end]-event["entry_time"],
                clock_gaps15=int(np.sum(np.diff(market["time"][ix]) > 15)),
                bad_bbo_rows=int(np.sum(~market["valid"][entry:end+1])))
            event_summaries.append(summary)
            anchors = [("entry", entry)]
            if first50 >= 0:
                anchors.append(("first_minus50", first50))
            # ----------------------------------------
            # 逆行中の同一場・phase・方向・原行は重複させない。
            grid = observations[(observations >= entry) & (observations <= end)]
            last_anchor_time = -np.inf
            for at in grid:
                price = market["bid"][at] if side > 0 else market["ask"][at]
                if side*(price-event["entry_price"]) < 0 and market["time"][at]-last_anchor_time >= 60:
                    key = (event["phase"], side, int(at))
                    if key not in dedup:
                        anchors.append(("adverse_grid60", int(at)))
                        dedup.add(key)
                    last_anchor_time = market["time"][at]
            for cohort, anchor in anchors:
                row = dict(session=scene["session"], phase=event["phase"], cohort=cohort, side=side,
                    source_decision_index=event["decision_index"], anchor_index=anchor, physical_line=int(market["line"][anchor]),
                    time=market["time"][anchor], spread=market["ask"][anchor]-market["bid"][anchor],
                    windows={str(h): window(market, anchor, side, h, good) for h in HORIZONS})
                # 当該原行そのものが判断観測でなければ直前の特徴だけを対応する。
                fi = np.searchsorted(observations, anchor, side="right")-1
                feature_row = feature_index.get(int(observations[fi])) if fi >= 0 else None
                selected_features = ("ret5_pt", "ret15_pt", "ret60_pt", "ofi15", "depth_imb", "bid_refill15", "ask_refill15", "known5", "known15", "known60")
                row["past_features"] = {k: features[k][feature_row] if feature_row is not None else np.nan for k in selected_features}
                anchor_rows.append(row)
        print(json.dumps(dict(session=scene["session"], events=sum(e["session"] == scene["session"] for e in event_summaries), anchors=sum(r["session"] == scene["session"] for r in anchor_rows)), ensure_ascii=False), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "逆行局面の観測162.jsonl").open("w", encoding="utf-8") as f:
        for row in anchor_rows:
            f.write(json.dumps(native(row), ensure_ascii=False, allow_nan=False)+"\n")
    event_stats = {}
    for phase in PICKS:
        group = [e for e in event_summaries if e["phase"] == phase]
        failed = [e for e in group if e.get("first_minus50_index", -1) >= 0]
        event_stats[phase] = dict(events=len(group), first50=len(failed), reaches100=sum(e.get("reaches100", False) for e in group),
            recovered_zero_after50=sum(e["recovered_zero_after50"] for e in failed),
            mae_until_first100_or_end=dist([e["mae_until_first100_or_end"] for e in group]),
            additional_dip_after50_until_zero=dist([e["additional_dip_after50_until_zero"] for e in failed]),
            recovery_seconds=dist([e["recovery_seconds"] for e in failed]))
    report = dict(scope="train30場の非金融記述。validation/testを数値設定に不使用。新戦略損益計算0。",
        source_sha=sha(source_path), manifest_sha=sha(manifest_path), source_raw=sources,
        inputs_split="train", selected=PICKS, events=event_summaries,
        event_stats=event_stats, anchor_summaries=summarize(anchor_rows),
        limitations=["既存100/50決着後の入口は重複し得る。独立回収・同時保有可能な取引数ではない。",
          "予測phaseは入口時の区分。米国前入口の経路は米国後にも及ぶ。",
          "CurrentPriceTimeは価格時計であり受信時計ではない。時計欠測中の連続経路は不明。",
          "戻し幅は板中値の観測範囲であり、注文約定・実現損益ではない。",
          "逆行格子は同一原行を重複排除しても同じ波が複数側・複数事象へ含まれ得る。場単位の記述が主。"])
    (OUT / "train尺度の集計162.json").write_text(json.dumps(native(report), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    run()
