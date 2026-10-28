"""00163の完了後だけ、保存注文と全正常原板から数量・会計を独立検算する。"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(ROOT / "work/allocation_157/audit"))
sys.path.insert(0, str(ROOT / "work/allocation_157"))
from raw_result157 import close, read_market, normal_mask, raw_risk, reserved_cap
from ledger_analysis157 import reconcile


def read(path: Path) -> dict:
    """保存JSONを読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path: Path) -> dict:
    """ファイル内容指紋を作る。

    引数: path(Path)。返り値: dict。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}


def save(path: Path, value: dict) -> None:
    """新しい監査証跡だけを保存する。

    引数: path(Path)、value(dict)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_check(saved: dict) -> dict:
    """元Source全通知とB00の同額、C50の厳密半額を別実装で照合する。

    引数: saved(dict)。返り値: dictは確認件数。元通知は再実行しない。
    """
    cases = {c["config"]["id"]: c for c in saved["cases"]}
    expected = {}
    for source in saved["sources"]:
        phase = source["Phase"]
        assert not source["Pending"] and all(l["Remaining"] == 0 for l in source["Lots"].values())
        for ev in source["Events"] or []:
            sig = ev["Signal"]
            key = phase + "/" + sig["id"]
            assert key not in expected
            expected[key] = (source, ev)
    base, half = cases["B00"]["actual"], cases["C50"]["actual"]
    assert len(base["Events"] or []) == len(half["Events"] or []) == len(expected)
    for ev, h in zip(base["Events"] or [], half["Events"] or []):
        order = ev["Order"]
        source, old = expected.pop(order["ID"])
        sig, phase = old["Signal"], source["Phase"]
        owner = sig["owner"]
        if sig["action"] == "close":
            owners = {source["Lots"][x["id"]]["Owner"] for x in sig["targets"]}
            assert len(owners) == 1
            owner = owners.pop()
        assert order["Owner"] == phase + "/" + owner
        for a, b in ((order["Side"], sig["side"]), (order["Quantity"], sig["quantity"] * 10),
                     (order["DecisionIndex"], sig["source_index"]), (order["DecisionTime"], sig["time"]),
                     (ev["FillIndex"], old["FillIndex"]), (ev["FillTime"], old["FillTime"]),
                     (ev["Price"], old["Price"]), (ev["Gross"], old["Gross"])):
            close(a, b, "元Source同額")
        expected_targets = {phase + "/" + t["id"]: t["quantity"] * 10 for t in sig.get("targets") or []}
        assert {t["ID"]: t["Quantity"] for t in order["Targets"] or []} == expected_targets
        ho = h["Order"]
        for name in ("ID", "Owner", "Side", "DecisionIndex", "DecisionTime", "Parent", "SourceID"):
            assert ho[name] == order[name]
        close(ho["Quantity"] * 2, order["Quantity"], "半量通知")
        for name in ("FillIndex", "FillTime", "Price"):
            close(h[name], ev[name], "半量約定同位置")
        close(h["Gross"] * 2, ev["Gross"], "半量実現")
        assert len(h["Pieces"] or []) == len(ev["Pieces"] or [])
        for p, hp in zip(ev["Pieces"] or [], h["Pieces"] or []):
            assert p["ID"] == hp["ID"]
            close(hp["Quantity"] * 2, p["Quantity"], "半量返済配賦")
            close(hp["Gross"] * 2, p["Gross"], "半量配賦実現")
    assert not expected
    for name in ("Minimum", "Peak", "MaxDD", "MinimumRealized", "MinimumUnrealized", "GrossSeconds", "NetAbsSeconds", "NetSignedSeconds", "MaxLong", "MaxShort", "MaxGross", "MaxNetAbs"):
        close(half["Risk"][name] * 2, base["Risk"][name], "厳密半額/" + name)
    for name in ("HeldSeconds", "HedgedSeconds"):
        close(half["Risk"][name], base["Risk"][name], "半量保有時間/" + name)
    close(sum(s["Gross"] for s in saved["sources"]), base["Realized"], "Source総確定")
    scene = saved["scene"]
    if scene["kind"] == "Night":
        assert [s["Method"] for s in saved["sources"]] == ["P05", "D07"]
        transition = saved["transitions"][1]
        assert transition["PreviousFlat"] and transition["At"] >= scene["us_open"] + 900
        assert all(e["FillIndex"] <= transition["Index"] for e in saved["sources"][0]["Events"] or [])
    else:
        assert [s["Method"] for s in saved["sources"]] == ["S01"]
    return {"source_events": len(base["Events"] or []), "phases": len(saved["sources"])}


def short_at(raw: np.ndarray, good: np.ndarray, index: int, width: int) -> dict:
    """当該原行までの過去正常端から円幅を独立計算する。

    引数: raw/good(ndarray)、index/width(int)。返り値: dictは既知と時計/幅。
    """
    now = raw[index, 0]
    answer = {"Known": False, "CurrentAt": float(now), "EndpointAt": 0., "Elapsed": 0., "Delay": 0., "RawPoints": 0., "Points": 0.}
    if not normal_mask(raw[index:index + 1])[0]:
        return answer
    pos = int(np.searchsorted(raw[good, 0], now - width, side="right")) - 1
    if pos < 0:
        return answer
    old = int(good[pos])
    assert old < index
    elapsed = now - raw[old, 0]
    delay = now - width - raw[old, 0]
    answer.update(EndpointAt=float(raw[old, 0]), Elapsed=float(elapsed), Delay=float(delay))
    if delay > 1 or elapsed <= 0:
        return answer
    delta = float(np.mean(raw[index, 2:4]) - np.mean(raw[old, 2:4]))
    answer.update(Known=True, RawPoints=delta, Points=delta * width / elapsed)
    return answer


def decision_check(scene: dict, raw: np.ndarray, good: np.ndarray, case: dict) -> dict:
    """保存された発注理由を原板prefixへ戻し、未来端点や終了ID復活がないか調べる。

    引数: scene/case(dict)、raw/good(ndarray)。返り値: dictは確認数。
    """
    events = case["actual"]["Events"] or []
    groups = defaultdict(list)
    for ev in events:
        groups[ev["Order"]["Parent"]].append(ev)
    decisions = defaultdict(list)
    config = case["config"]
    count = 0
    for d in case["decisions"] or []:
        decisions[d["Parent"]].append(d)
        p = case["parents"][d["Parent"]]
        i = d["Index"]
        assert normal_mask(raw[i:i + 1])[0]
        close(d["Time"], raw[i, 0], "数量判断時計")
        mid = float(np.mean(raw[i, 2:4]))
        close(mid, d["CurrentMid"], "数量判断現在中値")
        close(d["AnchorMid"], p["AnchorMid"], "固定親中値")
        side = p["Base"]["Side"]
        shorts = {}
        for h in (5, 15):
            expected = short_at(raw, good, i, h)
            saved = d["Short"][f"Own{h}"]
            assert saved["Known"] == expected["Known"]
            for key in ("CurrentAt", "EndpointAt", "Elapsed", "Delay", "RawPoints", "Points"):
                close(saved[key], expected[key], "短期円幅/" + key, 1e-7)
            shorts[h] = expected
        reason = "reduce163" if d["Action"] == "減枚" else "restore163"
        orders = [e["Order"] for e in groups[d["Parent"]] if e["Order"]["Reason"] == reason and e["Order"]["DecisionIndex"] == i]
        assert orders and sum(o["Quantity"] for o in orders) == d["Quantity"]
        if d["Action"] == "減枚":
            assert side * (mid - p["AnchorMid"]) <= -config["adverse"]
            if config["gate"]:
                assert shorts[5]["Known"] and shorts[15]["Known"]
                assert side * shorts[5]["Points"] <= 0 and side * shorts[15]["Points"] <= -20
        else:
            assert d["Action"] == "復元" and config["restore"] in ("entry", "extreme")
            assert shorts[5]["Known"] and shorts[15]["Known"] and side * shorts[5]["Points"] > 0 and side * shorts[15]["Points"] > 0
            j = p["ReductionFillIndex"]
            assert i > j >= 0
            eligible = good[(good >= j) & (good <= i)]
            mids = np.mean(raw[eligible, 2:4], axis=1)
            extreme = float(np.min(mids) if side == 1 else np.max(mids))
            close(extreme, d["ExtremeMid"], "空玉期間も含む減枚後極値")
            if config["restore"] == "extreme":
                assert side * (mid - extreme) >= 40
            else:
                assert side * (mid - p["AnchorMid"]) >= 0
            assert raw[i, 0] < scene["force_close"]
            if p["Phase"] == "前半":
                assert raw[i, 0] < scene["us_open"] - 900
            assert sum(d["SourceMini"].values()) > 0
            for order in orders:
                assert d["SourceMini"][order["SourceID"]] > 0
        count += 1
    for key, p in case["parents"].items():
        assert p["Ended"] and all(q == 0 for q in p["SourceMini"].values())
        first = next(e for e in groups[key] if e["Order"]["Kind"] == "initial")
        close(p["AnchorMid"], np.mean(raw[first["FillIndex"], 2:4]), "初回実約定中値")
        assert p["AnchorIndex"] == first["FillIndex"]
        own = decisions[key]
        assert sum(d["Action"] == "減枚" for d in own) == int(p["Reduced"])
        assert sum(d["Action"] == "復元" for d in own) == int(p["Restored"])
        assert len(own) <= 2
    return {"policy_decisions": count, "parents": len(case["parents"])}


def scene_check(scene: dict) -> dict:
    """一場の保存10台帳を全正常原板へ接続して監査する。

    引数: scene(dict)。返り値: dict。金融条件は再実行しない。
    """
    stage = "locked_test" if scene["split"] == "test" else "train_validation"
    path = WORK / "results" / stage / (scene["session"] + ".json")
    evidence = record(path)
    saved = read(path)
    assert {k: v for k, v in saved["scene"].items() if k != "fingerprints"} == {k: v for k, v in scene.items() if k != "fingerprints"}
    assert saved["scene"]["fingerprints"] == [{"path": f["path"], "sha256": f["sha256"]} for f in scene["fingerprints"]]
    assert saved["raw_files_checked"] == 6
    source = source_check(saved)
    raw, raw_reference = read_market(scene, "NK225")
    good = np.flatnonzero(normal_mask(raw))
    totals = Counter()
    rows = []
    for case in saved["cases"]:
        ledger = case["actual"]
        account = reconcile(ledger, scene["start"], case["observation_end"])
        assert not ledger["Pending"] and account["remaining_qty"] == 0 and account["open_parent_realized"] == 0
        risk = raw_risk(raw, ledger, scene["start"])
        cap = reserved_cap(ledger)
        assert cap["max_long_reserved"] == case["max_reserved_long"] and cap["max_short_reserved"] == case["max_reserved_short"]
        decision = decision_check(scene, raw, good, case)
        totals.update(cases=1, events=len(ledger["Events"] or []), lots=len(ledger["Lots"]), normal_marks=len(good), **decision)
        rows.append({"id": case["config"]["id"], "profit": account["allocation_profit"], "loss": account["allocation_loss"], "net": account["net"],
                     "parent_profit": account["profit"], "parent_loss": account["loss"], "risk": risk, "capacity": cap, "decisions": decision,
                     "new_orders": account["entries"], "quantity_time": account["quantities"]})
    assert evidence == record(path)
    result = {"passed": True, "session": scene["session"], "source": source, "result": evidence, "raw": raw_reference, "rows": rows, "totals": dict(totals)}
    save(HERE / "結果監査" / (scene["session"] + ".json"), result)
    return result


def main() -> None:
    """全完了と参照不変を先に確認し、530台帳を監査する。

    引数: なし。返り値: None。実注文・新金融再生・結果上書きはしない。
    """
    target = HERE / "audit163.json"
    proof = {"passed": False, "new_financial_replays": 0, "started_at": datetime.now().astimezone().isoformat()}
    try:
        complete = read(WORK / "再生全完了163.json")
        assert complete["completed"] and complete["returncode"] == 0 and complete["cases"] == 530
        receipt = read(WORK / "登録受領163r1.json")
        for ref in receipt["sources"]:
            assert record(ROOT / ref["path"])["sha256"] == ref["sha256"]
        manifest = read(WORK / "inputs163.json")
        assert len(manifest["sessions"]) == 53
        totals, results = Counter(), []
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(scene_check, s): s["session"] for s in manifest["sessions"]}
            for future in as_completed(futures):
                result = future.result()
                totals.update(result["totals"])
                results.append(result["result"])
                print(json.dumps({"session": result["session"], "passed": True}, ensure_ascii=False), flush=True)
        assert totals["cases"] == 530
        proof.update(passed=True, totals=dict(totals), results=sorted(results, key=lambda x: x["path"]),
                     inputs=record(WORK / "inputs163.json"), completed=record(WORK / "再生全完了163.json"),
                     sources=[record(Path(__file__))], finished_at=datetime.now().astimezone().isoformat(),
                     accounting="主表の利益/損失は返済配賦別。親合計は別値。全実玉時価を全正常原板で再計算。",
                     limits=["既知資料であり未見実証ではない。", "CurrentPriceTimeは受信時計ではない。", "15:35/05:50元返済を維持し場末proxyは使わない。"])
        save(target, proof)
        print(json.dumps({"passed": True, "totals": dict(totals), "sha256": record(target)["sha256"]}, ensure_ascii=False))
    except Exception as error:
        proof.update(error=repr(error), traceback=traceback.format_exc(), finished_at=datetime.now().astimezone().isoformat())
        save(target, proof)
        raise


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
