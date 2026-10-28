"""夜間の保存Source初回・実玉から支持校正用の行を作る。新売買再生は行わない。"""

from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import analyze159 as core


def features_night(support: dict, side: int, owner: str, phase: str) -> dict:
    """当時の支持を、担当と前後時間帯を持つ校正入力へ変換する。

    引数: support(dict)、side(int)、owner/phase(str)。返り値: dictは将来値を持たない特徴。
    """
    known = bool(support["Known"])
    components = support["components"]
    assert phase in ("前半", "後半") and owner in ("core", "addon", "episode")
    return {"core": float(owner == "core"), "addon": float(owner == "addon"), "post": float(phase == "後半"),
            "score": support["M"] * support["T"] if known else None,
            "M": support["M"] if known else None, "T": support["T"] if known else None,
            "change": side * (support["Own5"] / 5 - support["Own15"] / 15) if known else None,
            "agreement": float(side * support["Own120"] > 0 and side * support["Own15"] > 0) if known else None,
            "own_known": float(known), "peer_known": float(components["PeerKnown"]), "ofi_known": float(components["OFIKnown"])}


def adapt_saved(saved: dict) -> tuple[list[dict], list[dict]]:
    """元Sourceの全初回判断を、初回実玉と親会計へ対応させる。

    引数: saved(dict)は夜間再生器の保存JSON。返り値: tupleは完結初回玉と未完別欄。
    """
    scene = saved["scene"]
    assert scene["kind"] == "Night"
    full, partial, keys = [], [], set()
    for source in saved["sources"]:
        phase = source["Phase"]
        initials = source.get("Initials") or []
        events = source.get("Events") or []
        lots = source.get("Lots") or {}
        by_new = {}
        closes = {}
        for event in events:
            signal = event["Signal"]
            assert event["FillIndex"] > signal["source_index"]
            if signal["action"] == "new":
                by_new[signal["id"] + "-玉"] = event
            else:
                quantity, gross = 0, 0.
                for target in signal["targets"]:
                    lot = lots[target["id"]]
                    value = lot["Side"] * target["quantity"] * (event["Price"] - lot["Entry"]) * 100
                    quantity += target["quantity"]
                    gross += value
                    closes.setdefault(target["id"], []).append({"quantity": target["quantity"], "time": event["FillTime"],
                        "index": event["FillIndex"], "price": event["Price"], "gross": value})
                assert quantity == signal["quantity"] and abs(gross - event["Gross"]) < 1e-6
        assert set(by_new) == set(lots)
        for initial in initials:
            parent_id = phase + "/" + initial["Parent"]
            key = (scene["session"], parent_id)
            assert key not in keys
            keys.add(key)
            candidates = [(identity, event) for identity, event in by_new.items()
                          if event["Signal"]["owner"] == initial["Owner"]
                          and event["Signal"]["source_index"] == initial["Index"]
                          and event["Signal"]["time"] == initial["Time"]]
            if not candidates:
                assert scene.get("partial", False), "完了夜の初回が未約定。未来約定による標本選別は禁止"
                partial.append({"session": scene["session"], "parent": parent_id, "status": "初回未約定", "initial": initial})
                continue
            assert len(candidates) == 1, "初回分割約定は価格別の別計測が必要"
            identity, event = candidates[0]
            lot, sig = lots[identity], event["Signal"]
            assert sig["side"] == initial["Side"] and sig["quantity"] == initial["Quantity"] == lot["Quantity"]
            assert f'{lot["Owner"]}/{lot["Campaign"]}' == initial["Parent"]
            owned = [l for l in lots.values() if l["Owner"] == lot["Owner"] and l["Campaign"] == lot["Campaign"]]
            pieces = closes.get(identity, [])
            assert sum(p["quantity"] for p in pieces) + lot["Remaining"] == lot["Quantity"]
            assert abs(sum(p["gross"] for p in pieces) - lot["Gross"]) < 1e-6
            assert all(math.isfinite(lot[k]) for k in ["Entry", "At", "Gross", "Best", "Worst"])
            assert lot["Worst"] < 0, "正常な厳密BBOの新規直後spread損がWorstに含まれない"
            features = features_night(initial["Support"], initial["Side"], initial["Owner"], phase)
            parent_net = sum(l["Gross"] for l in owned)
            row = {"session": scene["session"], "parent": parent_id, "owner": initial["Owner"],
                "qualification": "既知途中場の完了版確認" if scene["session"] == "2026-10-26_Night" else "既知開発25夜",
                "phase": phase, "method": source["Method"], "side": initial["Side"],
                "decision_index": initial["Index"], "decision_time": initial["Time"], "initial_id": identity,
                "entry_time": event["FillTime"], "exit_time": max((p["time"] for p in pieces), default=None),
                "initial_qty_mini": lot["Quantity"], "initial_net": lot["Gross"],
                "initial_pt": lot["Gross"] / lot["Quantity"] / 100,
                "win": int(lot["Gross"] > 0), "flat": int(lot["Gross"] == 0),
                "mfe": lot["Best"], "mae": lot["Worst"], "mfe_time": lot.get("BestAt"), "mae_time": lot.get("WorstAt"),
                "parent_net": parent_net, "parent_pt_initial": parent_net / lot["Quantity"] / 100,
                "parent_pt_all": parent_net / sum(l["Quantity"] for l in owned) / 100,
                "score": features["score"], "known": bool(initial["Support"]["Known"]),
                "support": initial["Support"], "features": features,
                "remaining": lot["Remaining"], "parent_remaining": sum(l["Remaining"] for l in owned)}
            if scene.get("partial", False) or lot["Remaining"]:
                partial.append(row)
            else:
                assert row["parent_remaining"] == 0, "完了夜に親が未完"
                full.append(row)
    return full, partial


def execution_ok(execution: dict) -> bool:
    """2種類の完了証跡を厳格に確認する。

    引数: execution(dict)はrootの保存記録。返り値: bool。不足値・失敗を成功0へ補完しない。
    """
    if "exit_code" in execution:
        return (type(execution["exit_code"]) is int and execution["exit_code"] == 0
                and execution.get("sources_unchanged") is True
                and type(execution.get("raw_files_checked")) is int and execution["raw_files_checked"] == 162)
    return (type(execution.get("終了コード")) is int and execution["終了コード"] == 0
            and type(execution.get("参照改変数")) is int and execution["参照改変数"] == 0)


def main() -> None:
    """正常完了済みの夜間保存結果だけを分析する。

    引数: CLIのresults/実行証跡パス。返り値: None。未完了・資料改変なら停止。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    args = parser.parse_args()
    execution = core.read(args.execution)
    assert execution_ok(execution), "正常終了・参照不変の証跡を確認できない"
    rows, partial, fingerprints = [], [], []
    for path in sorted(args.results.glob("*.json")):
        saved = core.read(path)
        if saved["scene"]["kind"] != "Night":
            continue
        complete, unfinished = adapt_saved(saved)
        rows.extend(complete)
        partial.extend(unfinished)
        fingerprints.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    assert len({r["session"] for r in rows}) >= 9
    # ----------------------------------------
    # 同じ学習器を使うが、夜間は担当＋前後時間帯を全候補の基準とし、日中ラベルを含めない。
    core.MODELS = {name: fields[:2] + ["post"] + fields[2:] for name, fields in core.MODELS.items()}
    temporal = core.walk_forward(rows)
    for model, prediction in temporal["predictions"].items():
        lookup = {(r["session"], r["parent"]): r["phase"] for r in rows}
        temporal["models"][model]["phases"] = {phase: core.metrics([r for r in prediction if lookup[(r["session"], r["parent"])] == phase])
                                                        for phase in ["前半", "後半"]}
        temporal["models"][model]["qualification"] = {
            label: core.metrics([r for r in prediction if (r["session"] == "2026-10-26_Night") == added])
            for label, added in [("既知開発25夜", False), ("既知途中場の完了版確認", True)]}
    core.save(core.HERE / "夜間初回玉と支持の対応159.json", {"rows": rows, "partial": partial, "sources": fingerprints})
    core.save(core.HERE / "夜間支持校正159.json", {"scope": "先行Nightだけで学習。既知開発と既知途中場の完了版を含む。真正未見ではない。",
        "groups": core.describe_groups(rows),
        "known25_groups": core.describe_groups([r for r in rows if r["qualification"] == "既知開発25夜"]),
        "completion_check": [r for r in rows if r["qualification"] == "既知途中場の完了版確認"],
        "temporal": temporal,
        "source_files": fingerprints, "partial_count": len(partial)})
    print(json.dumps({"完了夜": len({r["session"] for r in rows}), "初回親": len(rows), "途中": len(partial)}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
