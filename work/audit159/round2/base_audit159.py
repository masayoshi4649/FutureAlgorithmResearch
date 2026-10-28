"""登録済み159の保存結果を全原板と独立現金会計で監査する。金融再生はしない。"""
from __future__ import annotations

from collections import defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "work/audit159/round2"
sys.path.insert(0, str(WORK))

from raw_result157 import close, read_market, support_arrays, raw_risk, reserved_cap
from raw_result1572 import support_at1572


def read(path: Path) -> dict:
    """保存JSONを読む。

    引数: path(Path)。返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value: dict) -> None:
    """監査証跡だけを保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def reference(path: Path) -> dict:
    """内容指紋を返す。

    引数: path(Path)。返り値: dict。
    """
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def support_check(saved: dict, index: int, side: int, own: dict, peer: dict, cache: dict) -> None:
    """当時までの原板から支持の値と個別既知を独立検算する。

    引数: saved/own/peer/cache(dict)、index/side(int)。返り値: None。
    """
    key = (index, side)
    if key not in cache:
        cache[key] = support_at1572(own, peer, index, side)
    expected = cache[key]
    assert saved["Known"] == expected["Known"], (key, saved, expected)
    for field in ("OwnAt", "PeerAt", "Own5", "Own15", "Own120", "Own300", "Peer120", "OFI30", "M", "T", "Opp"):
        close(saved[field], expected[field], "支持:" + field, 1e-7)
    for field in ("OwnKnown", "PeerKnown", "OFIKnown"):
        assert saved["components"][field] == expected["components"][field]
    assert set(saved["components"]["Windows"]) == set(expected["components"]["Windows"])
    for name, want in expected["components"]["Windows"].items():
        got = saved["components"]["Windows"][name]
        assert got["Known"] == want["Known"]
        for field in ("CurrentAt", "EndpointAt", "Elapsed", "Delay", "RawReturn", "Value", "IntermediateBad"):
            close(got[field], want[field], name + ":" + field, 1e-7)


def holding_check(raw: np.ndarray, case: dict, start: float) -> dict:
    """約定量の変化から保有積分と最大買売量を独立計算する。

    引数: raw(ndarray)、case(dict)、start(float)。返り値: dictは積分値。
    """
    changes = np.zeros((len(raw), 2), dtype=np.int64)
    held = [0, 0]
    maxima = [0, 0, 0, 0]
    for event in case["actual"]["Events"] or []:
        o = event["Order"]
        target_side = -o["Side"] if o.get("Targets") else o["Side"]
        side = 0 if target_side == 1 else 1
        q = -o["Quantity"] if o.get("Targets") else o["Quantity"]
        changes[event["FillIndex"], side] += q
        held[side] += q
        maxima = [max(maxima[0], held[0]), max(maxima[1], held[1]), max(maxima[2], sum(held)), max(maxima[3], abs(held[0]-held[1]))]
    before = np.cumsum(changes, axis=0) - changes
    elapsed = np.diff(np.r_[start, raw[:, 0]])
    gross, signed = before.sum(axis=1), before[:, 0]-before[:, 1]
    values = {"HeldSeconds": float(np.sum(elapsed * (gross > 0))), "GrossSeconds": float(elapsed @ gross), "NetAbsSeconds": float(elapsed @ np.abs(signed)), "NetSignedSeconds": float(elapsed @ signed), "HedgedSeconds": float(np.sum(elapsed * ((before[:,0] > 0) & (before[:,1] > 0))))}
    values.update(dict(zip(("MaxLong", "MaxShort", "MaxGross", "MaxNetAbs"), maxima)))
    for key, value in values.items():
        close(value, case["actual"]["Risk"][key], key)
    return values


def exact_and_phases(saved: dict) -> dict:
    """元Source全約定とN00の10倍換算・時間枠・末尾平坦を確認する。

    引数: saved(dict)。返り値: dictは確認件数。
    """
    scene = saved["scene"]
    base = next(c for c in saved["cases"] if c["config"]["id"] == "N00")
    events = base["actual"]["Events"] or []
    expected = [(source, e) for source in saved["sources"] for e in source["Events"] or []]
    assert len(events) == len(expected)
    for got, (source, old) in zip(events, expected):
        sig, phase = old["Signal"], source["Phase"]
        o = got["Order"]
        assert o["ID"] == phase + "/" + sig["id"]
        assert o["Owner"] == phase + "/" + sig["owner"]
        for value, want in ((o["Side"], sig["side"]), (o["Quantity"], sig["quantity"]*10), (o["DecisionIndex"], sig["source_index"]), (o["DecisionTime"], sig["time"]), (got["FillIndex"], old["FillIndex"]), (got["FillTime"], old["FillTime"]), (got["Price"], old["Price"]), (got["Gross"], old["Gross"])):
            close(value, want, "元Source同額約定")
        targets = [{"ID": phase+"/"+v["id"], "Quantity":v["quantity"]*10} for v in sig.get("targets", []) or []]
        assert (o.get("Targets") or []) == targets
        if sig["action"] == "new" and scene["kind"] == "Night":
            assert sig["time"] < scene["us_open"]-900 if phase == "前半" else sig["time"] >= scene["us_open"]+900
    close(sum(e["Gross"] for _,e in expected), base["actual"]["Realized"], "元Source確定合計")
    if scene["kind"] == "Night":
        assert [s["Method"] for s in saved["sources"]] == ["P05", "D07"]
        transition = saved["transitions"][1]
        assert transition["PreviousFlat"] and transition["At"] >= scene["us_open"]+900
        pre = saved["sources"][0]
        assert not pre["Pending"] and all(l["Remaining"] == 0 for l in pre["Lots"].values())
        assert all(e["FillIndex"] <= transition["Index"] for e in pre["Events"] or [])
    else:
        assert [s["Method"] for s in saved["sources"]] == ["S01"]
        assert [c["config"]["id"] for c in saved["cases"]] == ["N00", "N02"]
    return {"source_events":len(expected), "phases":len(saved["sources"])}


def main() -> None:
    """全314条件場の原板時価と保存判断を監査する。

    引数: なし。返り値: None。登録済みの売買条件・金融mainは再実行しない。
    """
    proof = {"passed":False, "new_financial_replays":0, "started_at":dt.datetime.now().astimezone().isoformat()}
    target = WORK / "金融結果の独立監査159.json"
    try:
        done = read(ROOT / "work/research159/金融実行159.json")
        assert done["exit_code"] == 0
        scenes = read(WORK / "inputs159.json")["sessions"]
        totals, evidence = defaultdict(int), []
        for scene in scenes:
            path = ROOT / "work/night159/results_go" / (scene["session"]+".json")
            before = reference(path)
            saved = read(path)
            source = exact_and_phases(saved)
            raw, raw_ref = read_market(scene, "NK225")
            peer_raw, peer_ref = read_market(scene, "TOPIX")
            own, peer, cache = support_arrays(raw), support_arrays(peer_raw), {}
            for src in saved["sources"]:
                for initial in src["Initials"] or []:
                    support_check(initial["Support"], initial["Index"], initial["Side"], own, peer, cache)
                    totals["source_initial_supports"] += 1
            rows = []
            for case in saved["cases"]:
                risk = raw_risk(raw, case["actual"], scene["start"])
                # 同原行の損切り→利確でも、途中の確定赤字を各約定順に残す。
                # 原行の終点だけを使う既存補助値はここで逐次会計へ置き換える。
                realized = minimum_realized = 0.0
                for event in case["actual"]["Events"] or []:
                    realized += event["Gross"]
                    minimum_realized = min(minimum_realized, realized)
                risk["min_realized"] = minimum_realized
                close(risk["min_realized"], case["actual"]["Risk"]["MinimumRealized"], "確定最小")
                assert risk["final_long"] == risk["final_short"] == 0
                assert not case["actual"]["Pending"]
                caps = reserved_cap(case["actual"])
                holding = holding_check(raw, case, scene["start"])
                for request in case.get("requests") or []:
                    side = case["parents"][request["Parent"]]["Side"]
                    support_check(request["Support"], request["Index"], side, own, peer, cache)
                    assert 0 <= request["Accepted"] <= request["Requested"]
                    totals["request_supports"] += 1
                rows.append({"id":case["config"]["id"], "risk":risk, "caps":caps, "holding":holding})
                totals["cases"] += 1
                totals["events"] += risk["event_checks"]
                totals["normal_marks"] += risk["normal_rows"]
            assert before == reference(path)
            evidence.append(before)
            save(WORK / "結果監査" / (scene["session"]+".json"), {"passed":True, "session":scene["session"], "source":source, "raw":[raw_ref,peer_ref], "rows":rows})
            print(json.dumps({"session":scene["session"], "passed":True, "cases":len(rows)},ensure_ascii=False), flush=True)
        assert totals["cases"] == 314
        proof.update(passed=True, totals=dict(totals), source_results=evidence, finished_at=dt.datetime.now().astimezone().isoformat())
        save(target,proof)
    except Exception as error:
        proof.update(error=repr(error), traceback=traceback.format_exc(), finished_at=dt.datetime.now().astimezone().isoformat())
        save(target,proof)
        raise


if __name__ == "__main__":
    main()
