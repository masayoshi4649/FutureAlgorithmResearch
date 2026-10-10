"""前半選定を独立会計から再計算し、実入口確認と幅別管理の未来不変性を検査する。"""

from __future__ import annotations

import importlib.util
import sys

import numpy as np

from audit_all import read, digest, material, ROOT, WORK, HERE
from audit_engine import ENGINE, ENGINE_SHA
from independent_account import near, save


FIELDS = ("kind", "stop", "activation", "trail", "hold_seconds", "grid", "step_fraction",
    "cover_activation", "cover_trail", "basket_stop", "basket_activation", "basket_trail",
    "flip_fraction", "partial_level", "partial_fraction", "tighten_minutes", "ratchet_step", "ratchet_keep", "grid_mode")


def module(name: str, path: object) -> object:
    """機能: 読み取り専用の既存エンジン又は入口関数を別名前空間へ取得する。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


ENTRY = module("core", WORK / "inputs/core.py")
NET = module("audit71_net", ROOT / "work/wave_v70/net.py")


def selection(proof: dict, selected: dict) -> dict:
    """機能: 前16別会計だけから最低数・候補順位・主選定・非採用を再確認する。

    引数: proof/selected(dict)。返り値: 一致確認した選定指標(dict)。
    """
    candidates = [r for r in proof["条件"] if r["設定"]["method"] == "H" and r["設定"]["gate_level"] in (1, 2) and r["設定"]["width_id"] != "W0"]
    enough = lambda r: all(r["期間"]["前16"][s]["campaigns"] >= 20 and r["期間"]["前16"][s]["active_sessions"] >= 8 for s in ("TOPIX", "NK225"))
    qualified = [r for r in candidates if enough(r)]
    samples = qualified or [r for r in candidates if all(r["期間"]["前16"][s]["campaigns"] > 0 for s in ("TOPIX", "NK225"))]
    score = lambda r: min(r["期間"]["前16"][s]["mean_net_ticks"] for s in ("TOPIX", "NK225"))
    samples.sort(key=lambda r: (-score(r), r["ID"]))
    best = samples[0]
    c = best["設定"]
    assert len(candidates) == selected["主選定条件数"] == 60
    assert len(qualified) == selected["最低数充足候補数"] == 35
    assert [r["ID"] for r in samples] == selected["前半候補順位"]
    assert best["ID"] == selected["比較代表"] == "T2L0_G2_W2_H"
    assert enough(best) == selected["最低数充足"] is True
    eligible = enough(best) and all(best["期間"]["前16"][s]["net"] > 0 and (best["期間"]["前16"][s]["campaign_payoff"] or 0) > 1 for s in ("TOPIX", "NK225"))
    assert eligible == selected["採用条件充足"] is False
    near(score(best), selected["前半スコア"], "前16の最低銘柄平均呼値")
    ids = [f'{c["source"]}_G{c["gate_level"]}_W0_H', f'{c["source"]}_G0_{c["width_id"]}_H', c["id"]]
    assert ids == [r["id"] for r in selected["代表"]]
    assert selected["基準"] == c["source"] + "_G0_W0_H"
    assert selected["G3主選定除外"] and not selected["後半再選定"] and not selected["追加場再選定"]
    return dict(代表=best["ID"], 順位一致=True, 主選定数=60, 最低数充足候補=35,
        最低数充足=True, 採用条件=False, 前半スコア=score(best), 前半指標=best["期間"]["前16"], G3除外=True)


def replay(config: dict, key: tuple, ready: dict, features: dict, bases: dict,
    cut: int | None = None, modified: int | None = None) -> tuple:
    """機能: 実G2候補の確認と親予約を再生成し、幅六通り又はN/Dを再生する。

    引数: config/ready/features/bases(dict)、key(tuple)、cut/modified(int|None)。
    返り値: 注文・決済・曲線・統計(tuple)。
    """
    r, f = ready[key], features[key]
    names = ("time_s", "bid", "ask", "mid", "best_ofi", "valid", "reset")
    own = {name: np.asarray(f[name]).copy() for name in names}
    base = bases[key][config["source_index"]].copy()
    if cut is not None:
        own = {name: array[:cut] for name, array in own.items()}
        base = base[:cut]
    if modified is not None:
        own["bid"][modified:] = own["bid"][modified] + (500 + np.arange(len(base)-modified)) * r["tick"]
        own["ask"][modified:] = own["bid"][modified:] + 7 * r["tick"]
        own["mid"][modified:] = (own["bid"][modified:] + own["ask"][modified:]) / 2
        own["best_ofi"][modified:] *= -1
        own["time_s"][modified:] = own["time_s"][modified] + np.arange(len(base)-modified) * 60
        own["reset"][modified:] = True
        base[modified:] *= -1
    gates = ENTRY.own_gates(*[own[name] for name in names], r["tick"])[0]
    allowed = np.where(base > 0, gates[1, 0], gates[1, 1])
    signal = np.where(allowed, base, 0).astype(np.int8)
    local_ready = dict(r, time_s=own["time_s"])
    timetable = ENTRY.sparse_schedule(local_ready, own, signal)[0]
    cap, value, fee = (10, 1000., 41.8) if key[1] == "TOPIX" else (20, 10., 11.)
    args = (own["time_s"], own["bid"], own["ask"], signal, timetable, r["tick"], r["limit"], cap, value, fee,
        *[config[name] for name in FIELDS])
    result = ENGINE.simulate(*args)
    if config["paired"]:
        return NET.pair(*args[:3], result[0], cap, value, fee)
    return result


def main() -> None:
    """機能: 前半独立選定と80原本設定・320切断変更の一致を保存する。

    引数: なし。返り値: なし(None)。
    """
    fixed = read(WORK / "事前固定.json")
    proof = read(HERE / "全条件の独立監査.json")
    selected = read(WORK / "前半選定.json")
    chosen = selection(proof, selected)
    ready, features = material()
    bases = read(ROOT / "work/wave_v70/inputs/signals.pkl")
    bases.update(read(WORK / "prepared/extra_base_signals.pkl"))
    sessions = {"2026-09-21_Day", "2026-09-30_Day", "2026-10-02_Day", "2026-10-08_Night", "2026-10-09_Day"}
    wanted = [f"T2L0_G2_W{w}_H" for w in range(6)] + ["T2L0_G2_W2_N", "T2L0_G2_W2_D"]
    configs = {c["id"]: c for c in fixed["条件"]}
    records = []
    for identifier in wanted:
        config = configs[identifier]
        ledger = read(WORK / "ledgers" / (identifier + ".pkl"))
        for key in sorted(key for key in ready if key[0] in sessions):
            normal = replay(config, key, ready, features, bases)
            np.testing.assert_array_equal(normal[0], ledger[key]["orders"])
            np.testing.assert_array_equal(normal[1], ledger[key]["trades"])
            cuts = sorted({int(len(ready[key]["time_s"]) * fraction) for fraction in (.33, .71)})
            for cut in cuts:
                for altered in (replay(config, key, ready, features, bases, cut=cut),
                    replay(config, key, ready, features, bases, modified=cut)):
                    np.testing.assert_array_equal(normal[0][normal[0][:, 0] < cut], altered[0][altered[0][:, 0] < cut])
                    np.testing.assert_array_equal(normal[1][normal[1][:, 2] < cut], altered[1][altered[1][:, 2] < cut])
                    np.testing.assert_array_equal(normal[2][:cut], altered[2][:cut])
            records.append(dict(ID=identifier, セッション=key[0], 銘柄=key[1], 切断行=cuts,
                入口確認と親を再生成=True, 過去一致=True))
    assert len(records) == 80
    assert digest(ROOT / "work/wave_v70/engine.py") == ENGINE_SHA
    save(HERE / "実設定の因果検査と前半選定照合.json", dict(合格=True, 独立選定=chosen,
        実原本設定数=80, 切断変更組数=320, 結果=records, engine_SHA256=ENGINE_SHA,
        選定SHA256=digest(WORK / "前半選定.json")))
    print("前半60候補・35最低数・選定一致、8実設定80口座320切断変更: 合格", flush=True)


if __name__ == "__main__":
    main()
