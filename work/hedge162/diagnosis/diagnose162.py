"""完了済みの保存約定から、選択したカバー案の具体的な損益差を説明する。"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
JST = timezone(timedelta(hours=9))


def read(path: Path) -> dict:
    """保存JSONをUTF-8で読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """読取資料の内容指紋を計算する。

    引数: path(Path)。返り値: str。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(path: Path) -> dict:
    """監査用の相対パスと内容指紋を返す。

    引数: path(Path)。返り値: dict。
    """
    return {"path": path.resolve().relative_to(ROOT).as_posix(), "sha256": sha(path)}


def clock(at: float) -> str:
    """価格時計を日本時間へ変換する。

    引数: at(float)。返り値: str。
    """
    return datetime.fromtimestamp(at, JST).isoformat()


def completion_gate(work: Path) -> tuple[dict, list[dict], list[dict]]:
    """両段階の完了と全結果SHAを確認してから読取先を返す。

    引数: work(Path)。返り値: tupleは選択凍結、結果目録、出典指紋。
    """
    frozen_path = work / "results/selection_frozen162.json"
    frozen = read(frozen_path)
    payload = {k: v for k, v in frozen.items() if k != "content_sha256"}
    actual = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if frozen.get("test_opened") is not False or actual != frozen.get("content_sha256"):
        raise ValueError("選択時の凍結証跡が一致しない")
    selected = frozen["selected"]
    if not selected or len(selected) > 3 or len(set(selected)) != len(selected):
        raise ValueError("選択候補数が不正")
    expected = {"manifest_sha256": sha(work / "inputs162.json"),
                "configs_sha256": sha(work / "engine/configs162.json"),
                "spec_sha256": sha(work / "計画162.md")}
    if any(frozen.get(k) != v for k, v in expected.items()):
        raise ValueError("選択時の入力又は仕様が変更されている")
    records, sources = [], [fingerprint(frozen_path)]
    for stage, count in (("train_validation", 40), ("locked_test", 13)):
        folder = work / "results" / stage
        proof_path = folder / ("再生完了162_" + stage + ".json")
        proof = read(proof_path)
        if (proof.get("completed") is not True or type(proof.get("returncode")) is not int
                or proof["returncode"] != 0 or proof.get("sources_unchanged") is not True):
            raise ValueError("金融再生が正常完了していない")
        if proof["sessions"] != count or proof["cases"] != count * 26 or len(proof["results"]) != count:
            raise ValueError("段階の完了件数が不正")
        if proof["stage"]["stage"] != stage or any(proof["stage"].get(k) != v for k, v in expected.items()):
            raise ValueError("段階の仕様指紋が不一致")
        if stage == "locked_test" and proof["stage"].get("freeze_sha256") != sha(frozen_path):
            raise ValueError("後半の候補凍結指紋が不一致")
        sources.append(fingerprint(proof_path))
        for item in proof["results"]:
            path = Path(item["path"]).resolve()
            if path != (folder / (item["session"] + ".json")).resolve() or sha(path) != item["sha256"]:
                raise ValueError("結果の保存場所又は内容指紋が不一致")
            records.append({**item, "stage": stage})
            sources.append(fingerprint(path))
    if len({r["session"] for r in records}) != 53:
        raise ValueError("場の重複又は欠落")
    return frozen, sorted(records, key=lambda r: r["session"]), sources


def compact_event(event: dict, references: dict[int, dict]) -> dict:
    """判断と約定、代理価格の出典を小容量で記録する。

    引数: event(dict)、references(dict[int,dict])。返り値: dict。
    """
    order = event["order"]
    qindex = event.get("quote_index") if event.get("proxy") else event["fill_index"]
    quote = references[qindex]
    decision = references.get(order["decision_index"])
    return {"id": order["id"], "parent": order["parent"], "role": order["role"],
            "action": order["action"], "side": order["side"], "quantity": order["quantity"],
            "reason": order["reason"], "target": order.get("target"), "slot": order.get("slot"),
            "decision_index": order["decision_index"], "decision_time": order["decision_time"],
            "decision_jst": clock(order["decision_time"]), "decision_quote": decision,
            "fill_index": event["fill_index"], "fill_time": event["fill_time"],
            "fill_jst": clock(event["fill_time"]), "price": event["price"], "gross": event.get("gross", 0),
            "proxy": bool(event.get("proxy")), "quote": quote, "quote_age": event.get("quote_age", 0)}


def parent_records(case: dict) -> dict[tuple, dict]:
    """条件間で親IDを混ぜず、同じ主判断に属する主玉・全カバーを束ねる。

    引数: case(dict)。返り値: dictは判断原行・方向・時間帯をキーにした親明細。
    """
    parents = {p["id"]: p for p in case["parents"]}
    lots = {lot["id"]: lot for lot in case["lots"]}
    references = {r["index"]: r for r in case["reference"]}
    events_by_parent = {}
    for event in case["events"]:
        events_by_parent.setdefault(event["order"]["parent"], []).append(event)
    result = {}
    for pid, events in events_by_parent.items():
        mains = [e for e in events if e["order"]["action"] == "new" and e["order"]["role"] == "main"]
        assert len(mains) == 1
        first = mains[0]
        order = first["order"]
        key = (order["decision_index"], order["side"], parents[pid]["phase"])
        assert key not in result
        closes = [e for e in events if e["order"]["action"] == "close"]
        main_net = sum(e["gross"] for e in closes if e["order"]["role"] == "main")
        cover_net = sum(e["gross"] for e in closes if e["order"]["role"] == "cover")
        ordered = [compact_event(e, references) for e in events]
        details = []
        for event in events:
            if event["order"]["action"] != "new":
                continue
            ident = event["order"]["id"]
            lot = lots[ident]
            exits = [e for e in closes if e["order"]["target"] == ident]
            assert sum(e["order"]["quantity"] for e in exits) + lot["quantity"] == event["order"]["quantity"]
            net = sum(e["gross"] for e in exits)
            assert net == lot["realized"]
            details.append({"id": ident, "role": lot["role"], "side": lot["side"],
                            "quantity": event["order"]["quantity"], "entry": event["price"],
                            "entry_jst": clock(event["fill_time"]), "entry_index": event["fill_index"],
                            "best_gain": lot["best"], "worst_gain": lot["worst"],
                            "activated": lot["active"], "last_floor": lot["floor"], "net": net,
                            "profit_then_loss": lot["best"] > 0 and net < 0,
                            "never_positive_loss": lot["best"] <= 0 and net < 0,
                            "exits": [compact_event(e, references) for e in exits]})
        result[key] = {"key": list(key), "parent": pid, "phase": parents[pid]["phase"],
                       "side": order["side"], "quantity": order["quantity"],
                       "main_entry": compact_event(first, references), "main_net": main_net,
                       "cover_net": cover_net, "net": main_net + cover_net,
                       "cover_entries": sum(l["role"] == "cover" for l in details),
                       "proxy_net": sum(e["gross"] for e in closes if e.get("proxy")),
                       "lots": details, "events": ordered}
    assert sum(p["net"] for p in result.values()) == case["summary"]["realized"]
    return result


def compare(case: dict, base: dict) -> dict:
    """保存された同入口親を対応し、N00との差を四つの会計要因へ分ける。

    引数: case/base(dict)。返り値: dict。
    """
    own, original = parent_records(case), parent_records(base)
    same = own.keys() & original.keys()
    lost, added = original.keys() - own.keys(), own.keys() - original.keys()
    cover = sum(p["cover_net"] for p in own.values())
    common = sum(own[k]["main_net"] - original[k]["main_net"] for k in same)
    vanished = -sum(original[k]["main_net"] for k in lost)
    created = sum(own[k]["main_net"] for k in added)
    net = case["summary"]["realized"] - base["summary"]["realized"]
    assert net == cover + common + vanished + created
    changes = []
    for key in sorted(own.keys() | original.keys()):
        current, prior = own.get(key), original.get(key)
        changes.append({"key": list(key), "kind": "common" if key in same else "new" if key in added else "lost",
                        "net_delta": (current["net"] if current else 0) - (prior["net"] if prior else 0),
                        "main_net_delta": (current["main_net"] if current else 0) - (prior["main_net"] if prior else 0),
                        "cover_net": current["cover_net"] if current else 0,
                        "quantity": current["quantity"] if current else 0,
                        "base_quantity": prior["quantity"] if prior else 0,
                        "decision_jst": (current or prior)["main_entry"]["decision_jst"]})
    return {"net_delta": net, "cover_net": cover, "main_net_delta": common + vanished + created, "common_main_delta": common,
            "lost_main_effect": vanished, "new_main_effect": created,
            "common_parents": len(same), "lost_parents": len(lost), "new_parents": len(added),
            "changes": changes}


def case_row(scene: dict, case: dict, n00: dict, s00: dict) -> dict:
    """一場の比較額と場内リスクの根拠を抜く。

    引数: scene/case/n00/s00(dict)。返り値: dict。
    """
    s = case["summary"]
    return {"session": scene["session"], "kind": scene["kind"], "split": scene["split"],
            "id": case["id"], "net": s["realized"], "main_net": s["roles"]["main"]["net"],
            "cover_net": s["roles"]["cover"]["net"], "minimum_equity": s["minimum_equity"],
            "maximum_drawdown": s["maximum_drawdown"], "minimum_at": s["minimum_at"],
            "drawdown_from": s["drawdown_from"], "drawdown_to": s["drawdown_to"],
            "N00_net": n00["summary"]["realized"], "S00_net": s00["summary"]["realized"],
            "S00_delta": s["realized"] - s00["summary"]["realized"],
            "N00_minimum_equity": n00["summary"]["minimum_equity"],
            "N00_maximum_drawdown": n00["summary"]["maximum_drawdown"],
            "main_entries": s["main_entries"], "cover_entries": s["cover_entries"],
            "main_rejections": s["rejections"], "cover_capacity_rows": s["cover_capacity_evaluated_rows"],
            "end_quote_age": s["ending"]["age"], "comparison": compare(case, n00)}


def choose_examples(rows: list[dict]) -> list[dict]:
    """説明例として悪化最大3場と改善最大1場を固定規則で選ぶ。

    引数: rows(list[dict])。返り値: list[dict]。
    """
    worse = sorted((r for r in rows if r["comparison"]["net_delta"] < 0),
                   key=lambda r: (r["comparison"]["net_delta"], r["session"]))[:3]
    better = sorted((r for r in rows if r["comparison"]["net_delta"] > 0),
                    key=lambda r: (-r["comparison"]["net_delta"], r["session"]))[:1]
    return [{"example": "worse", **r} for r in worse] + [{"example": "better", **r} for r in better]


def detail_example(scene: dict, case: dict, base: dict, row: dict) -> dict:
    """悪化・改善の中心親と保存極値を説明可能な明細にする。

    引数: scene/case/base/row(dict)。返り値: dict。
    """
    own, old = parent_records(case), parent_records(base)
    changes = sorted(row["comparison"]["changes"], key=lambda r: (-abs(r["net_delta"]), r["key"]))[:3]
    selected = [{**change, "actual": own.get(tuple(change["key"])), "N00": old.get(tuple(change["key"]))}
                for change in changes]
    return {**row, "dominant_parents": selected, "configuration": case["configuration"],
            "cover_capacity": case["cover_capacity"], "risk_points": case["risk_points"],
            "notes": ["同入口でも共有枠により主数量が変わり、その後の入口列も変わる。",
                      "主のproxy退出は正式引け約定ではなく、最後の正常気配による場末代理。"]}


def summary_rows(rows: list[dict]) -> dict:
    """説明に必要な同じ場集合の差額を合計する。

    引数: rows(list[dict])。返り値: dict。
    """
    parts = ("net_delta", "cover_net", "main_net_delta", "common_main_delta", "lost_main_effect", "new_main_effect")
    return {"sessions": len(rows), "net": sum(r["net"] for r in rows),
            "N00_net": sum(r["N00_net"] for r in rows),
            "S00_net": sum(r["S00_net"] for r in rows),
            "losing_sessions": sum(r["net"] < 0 for r in rows),
            "improved": sum(r["comparison"]["net_delta"] > 0 for r in rows),
            "worsened": sum(r["comparison"]["net_delta"] < 0 for r in rows),
            "decomposition": {key: sum(r["comparison"][key] for r in rows) for key in parts}}


def markdown(report: dict) -> str:
    """全会計差と具体時刻を短い日本語表にする。

    引数: report(dict)。返り値: str。
    """
    lines = ["# 主玉と短期カバーの具体診断", "",
             "前40場で選択した条件を変更せず、保存約定だけでN00との差を分解した。後13場も既知資料の確認で、完全未見ではない。", "",
             "金額は円。N00は+100又は場末で主玉を返すカバーなし基準、S00は−50でも返す基準。", "",
             "|案|区間|場数|収支|N00差|カバー収支|主玉差|",
             "|---|---|---:|---:|---:|---:|---:|"]
    for method in report["methods"]:
        for name, label in (("train_validation", "前40"), ("locked_test", "後13"), ("all", "全53")):
            s = method["periods"][name]
            d = s["decomposition"]
            lines.append(f"|{method['id']}|{label}|{s['sessions']}|{s['net']:,.0f}|{d['net_delta']:,.0f}|{d['cover_net']:,.0f}|{d['main_net_delta']:,.0f}|")
    lines += ["", "カバーが共有枠を使うと反対主玉の初回量や後続入口も変わる。したがって、N00差をカバー単独の稼ぎとみなさない。以下は全53場から悪化最大3場と改善最大1場を各案で選んだ説明例。", ""]
    for method in report["methods"]:
        lines += [f"## {method['id']}", "", "|場|区分|収支|N00差|主玉|カバー|最悪時価|最大DD|", "|---|---|---:|---:|---:|---:|---:|---:|"]
        for item in method["examples"]:
            lines.append(f"|{item['session']}|{'悪化' if item['example']=='worse' else '改善'}|{item['net']:,.0f}|{item['comparison']['net_delta']:,.0f}|{item['main_net']:,.0f}|{item['cover_net']:,.0f}|{item['minimum_equity']:,.0f}|{item['maximum_drawdown']:,.0f}|")
    pool = [e for m in report["methods"] for e in m["examples"]]
    worsened = sorted((e for e in pool if e["example"] == "worse"), key=lambda e: (e["comparison"]["net_delta"], e["session"], e["id"]))
    improved = sorted((e for e in pool if e["example"] == "better"), key=lambda e: (-e["comparison"]["net_delta"], e["session"], e["id"]))
    detailed = []
    for item in worsened[:1] + improved[:1] + worsened[1:]:
        if item["session"] not in {e["session"] for e in detailed}:
            detailed.append(item)
        if len(detailed) == 3:
            break
    for item in detailed:
        lines += ["", f"## 具体例 {item['id']} {item['session']}", ""]
        at = item["minimum_at"]
        lines.append(f"最悪時価は{clock(at['time'])}、原行{at['index']}。確定{at['realized']:,.0f}円、含み{at['unrealized']:,.0f}円。主枠拒否{item['main_rejections'].get('capacity',0)}回、カバー枠不足{item['cover_capacity_rows']:,}原行。")
        for parent in item["dominant_parents"][:1]:
                record = parent["actual"] or parent["N00"]
                entry = record["main_entry"]
                exits = [e for e in record["events"] if e["role"] == "main" and e["action"] == "close"]
                ending = exits[-1] if exits else None
                exit_text = f"→{ending['fill_jst']} {ending['price']:g}（{ending['reason']}）" if ending else "未返済"
                lines.append(f"- {'N00だけに存在' if parent['actual'] is None else '当案'}：判断{entry['decision_jst']}、約定{entry['fill_jst']}、{'買' if record['side']==1 else '売'}{record['quantity']}枚 {entry['price']:g}{exit_text}。主{record['main_net']:,.0f}円、カバー{record['cover_net']:,.0f}円/{record['cover_entries']}玉、N00親対応差{parent['net_delta']:,.0f}円。")
                covers = [lot for lot in record["lots"] if lot["role"] == "cover"]
                for lot in sorted(covers, key=lambda l: (-abs(l["net"]), l["id"]))[:2]:
                    out = lot["exits"][-1]
                    lines.append(f"  - カバー{lot['id']}：{lot['entry_jst']} {'買' if lot['side']==1 else '売'}{lot['quantity']}枚 {lot['entry']:g}→{out['fill_jst']} {out['price']:g}、{lot['net']:,.0f}円。最高順行{lot['best_gain']:g}円幅、最大逆行{lot['worst_gain']:g}円幅、理由{out['reason']}。")
    lines += ["", "場末代理、次板での価格飛び、カバーの損失、消えた主玉の勝ちを全て計上した。具体例の未来経路・最高順行は説明用で、入口や選択には使っていない。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    """全完了後だけ選択3案の保存約定診断を新規保存する。

    引数: CLIの--work(Path)と--out(Path)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    destinations = [args.out / "具体売買診断162.json", args.out / "具体売買診断162.md"]
    if any(p.exists() for p in destinations):
        raise ValueError("完成済み診断を上書きしない")
    frozen, records, sources = completion_gate(args.work)
    rows = {ident: [] for ident in frozen["selected"]}
    source_by_session = {}
    for item in records:
        saved = read(Path(item["path"]))
        source_by_session[saved["session"]] = item["path"]
        cases = {c["id"]: c for c in saved["cases"]}
        for ident in frozen["selected"]:
            rows[ident].append(case_row(saved, cases[ident], cases["N00"], cases["S00"]))
    methods = []
    for ident, values in rows.items():
        examples = []
        for row in choose_examples(values):
            saved = read(Path(source_by_session[row["session"]]))
            cases = {c["id"]: c for c in saved["cases"]}
            examples.append(detail_example(saved, cases[ident], cases["N00"], row))
        methods.append({"id": ident, "rows": values, "examples": examples,
                        "periods": {"all": summary_rows(values),
                                    "train_validation": summary_rows([r for r in values if r["split"] != "test"]),
                                    "locked_test": summary_rows([r for r in values if r["split"] == "test"])}})
    report = {"selected": frozen["selected"], "methods": methods, "sources": sources,
              "implementation": fingerprint(Path(__file__)), "new_financial_replay": False,
              "selection_changed": False, "matching_key": ["main_decision_index", "side", "decision_phase"]}
    with destinations[0].open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with destinations[1].open("x", encoding="utf-8") as stream:
        stream.write(markdown(report))
    print(json.dumps({"completed": True, "selected": frozen["selected"], "files": [fingerprint(p) for p in destinations]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
