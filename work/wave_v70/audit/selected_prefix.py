"""前半選定を別会計指標から再計算し、実選定設定で将来不変性を確認する。"""

from __future__ import annotations

import importlib.util
import sys

import numpy as np

from audit_all import read, digest, ROOT, WORK, HERE
from audit_engine import ENGINE, ENGINE_SHA
from independent_account import save, near


FIELDS = ("kind", "stop", "activation", "trail", "hold_seconds", "grid", "step_fraction",
    "cover_activation", "cover_trail", "basket_stop", "basket_activation", "basket_trail",
    "flip_fraction", "partial_level", "partial_fraction", "tighten_minutes", "ratchet_step", "ratchet_keep", "grid_mode")
SPEC = importlib.util.spec_from_file_location("management70_selected_net", WORK / "net.py")
NET = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = NET
SPEC.loader.exec_module(NET)


def verify_selection(proof: dict, selected: dict) -> list[dict]:
    """機能: 後12を使わず別会計前16の改善点数から二群順位と三代表を再選定する。

    引数: proof/selected(dict)。返り値: 一致確認した代表の前半指標(list[dict])。
    """
    all_rows = {r["ID"]: r for r in proof["条件"]}
    candidates = []
    for identifier, row in all_rows.items():
        config = row["設定"]
        if config["manager"] == "B00":
            continue
        front = row["期間"]["前16"]
        if not all(front[s]["campaigns"] >= 20 and front[s]["active_sessions"] >= 8 for s in ("TOPIX", "NK225")):
            continue
        base = all_rows[config["source"] + "_B00"]["期間"]["前16"]
        improvements = [front[s]["mean_net_ticks"] - base[s]["mean_net_ticks"] for s in ("TOPIX", "NK225")]
        score = (min(improvements), sum(improvements) / 2, identifier)
        candidates.append((score, row))
    hedge = sorted([pair for pair in candidates if pair[1]["設定"]["group"] == "保険両建て"], reverse=True, key=lambda pair: pair[0])
    other = sorted([pair for pair in candidates if pair[1]["設定"]["group"] not in ("保険両建て", "縮小復帰")], reverse=True, key=lambda pair: pair[0])
    assert [pair[1]["ID"] for pair in hedge] == selected["物理保険順位"]
    assert [pair[1]["ID"] for pair in other] == selected["その他管理順位"]
    insurance = hedge[0][1]["ID"]
    paired = insurance.rsplit("_H", 1)[0] + "_N" + insurance.rsplit("_H", 1)[1]
    ids = [insurance, paired, other[0][1]["ID"]]
    assert ids == [r["id"] for r in selected["代表"]]
    output = []
    score_by_id = {row["ID"]: score for score, row in candidates}
    for choice in selected["代表"]:
        row = all_rows[choice["id"]]
        front = row["期間"]["前16"]
        eligible = all(front[s]["net"] > 0 and front[s]["campaign_payoff"] is not None and front[s]["campaign_payoff"] > 1 for s in ("TOPIX", "NK225"))
        assert eligible == choice["eligible"]
        near(score_by_id[choice["id"]][0], choice["front_worst_delta"], "前16の弱い銘柄改善スコア")
        output.append(dict(ID=choice["id"], 前16=front, 有望条件=eligible,
            最弱改善呼値=score_by_id[choice["id"]][0], 選定一致=True))
    both_black = sorted(identifier for identifier, row in all_rows.items() if all(row["期間"]["全28"][s]["net"] > 0 for s in ("TOPIX", "NK225")))
    assert both_black == sorted(selected["両銘柄全28黒字"])
    assert selected["後半選び直し"] is False
    return output


def replay(config: dict, key: tuple, ready: dict, features: dict, signals: dict, schedule: dict,
    cut: int | None = None, modified: int | None = None) -> tuple:
    """機能: 実選定設定を原本切断又は未来変更で再生し、対照も同時写像する。

    引数: config/ready/features/signals/schedule(dict)、key(tuple)、cut/modified(int|None)。
    返り値: 注文・決済・全玉評価・統計(tuple)。
    """
    r, f = ready[key], features[key]
    arrays = [np.asarray(a).copy() for a in (r["time_s"], f["bid"], f["ask"], signals[key][config["source_index"]])]
    timetable = schedule[key][config["source_index"]].copy()
    if cut is not None:
        arrays = [a[:cut] for a in arrays]
        timetable = timetable[timetable[:, 0] < cut]
    if modified is not None:
        times, bid, ask, direction = arrays
        bid[modified:] = bid[modified] + (500 + np.arange(len(bid) - modified)) * r["tick"]
        ask[modified:] = bid[modified:] + 7 * r["tick"]
        direction[modified:] *= -1
        times[modified:] = times[modified] + np.arange(len(times) - modified) * 60
        timetable = timetable[timetable[:, 0] < modified]
    cap, value, fee = (10, 1000., 41.8) if key[1] == "TOPIX" else (20, 10., 11.)
    result = ENGINE.simulate(*arrays, timetable, r["tick"], r["limit"], cap, value, fee, *[config[name] for name in FIELDS])
    if config["paired"]:
        return NET.pair(*arrays[:3], result[0], cap, value, fee)
    return result


def main() -> None:
    """機能: 前半選定三代表の原本過去一致と独立選定の照合結果を保存する。

    引数: なし。返り値: なし(None)。
    """
    fixed = read(WORK / "事前固定.json")
    selected = read(WORK / "前半選定.json")
    proof = read(HERE / "全条件の独立監査.json")
    chosen = verify_selection(proof, selected)
    configs = {r["id"]: r for r in fixed["条件"]}
    ready = read(ROOT / "work/wave_v69/prepared/inputs.pkl")
    features = read(ROOT / "work/wave_v69/prepared/features.pkl")
    signals = read(WORK / "inputs/signals.pkl")
    schedules = read(WORK / "inputs/schedule.pkl")
    sessions = {"2026-09-21_Day", "2026-09-30_Day", "2026-10-02_Day", "2026-10-08_Night"}
    records = []
    for choice in chosen:
        config = configs[choice["ID"]]
        for key in sorted(key for key in ready if key[0] in sessions):
            normal = replay(config, key, ready, features, signals, schedules)
            cuts = sorted({int(len(ready[key]["time_s"]) * fraction) for fraction in (.33, .71)})
            for cut in cuts:
                for other in (replay(config, key, ready, features, signals, schedules, cut=cut),
                    replay(config, key, ready, features, signals, schedules, modified=cut)):
                    np.testing.assert_array_equal(normal[0][normal[0][:, 0] < cut], other[0][other[0][:, 0] < cut])
                    np.testing.assert_array_equal(normal[1][normal[1][:, 2] < cut], other[1][other[1][:, 2] < cut])
                    np.testing.assert_array_equal(normal[2][:cut], other[2][:cut])
            records.append(dict(ID=choice["ID"], セッション=key[0], 銘柄=key[1], 切断行=cuts, 過去一致=True))
    assert len(records) == 24
    assert digest(WORK / "engine.py") == ENGINE_SHA
    save(HERE / "実選定設定の因果検査と選定照合.json", dict(合格=True, 前半だけの独立選定=chosen,
        実原本因果検査=records, 切断変更組数=24 * 2 * 2, engine_SHA256=ENGINE_SHA,
        net_SHA256=digest(WORK / "net.py"), 選定SHA256=digest(WORK / "前半選定.json")))
    print("前半選定順位・3代表一致、実設定24口座・96切断変更組: 合格", flush=True)


if __name__ == "__main__":
    main()
