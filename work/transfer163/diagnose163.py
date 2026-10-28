"""保存した局所減枚比較を親単位へ戻し、改善と失った利益を対にする。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def read(path: Path):
    """保存済みの小さい成果JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stamp(at: float) -> str:
    """価格時計を日本時間文字列へ変換する。

    引数: at(float)。返り値: str。実受信時刻とは呼ばない。
    """
    return datetime.fromtimestamp(at, JST).isoformat(timespec="milliseconds")


def record(path: Path) -> dict:
    """根拠ファイルの指紋を保存する。

    引数: path(Path)。返り値: dict。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}


def parents(case: dict) -> dict:
    """元と改修の同じ親を比較できる台帳へ展開する。

    引数: case(dict)。返り値: dictは親IDごとの約定・決済損益。
    """
    answer = {}
    for key, parent in case["parents"].items():
        answer[key] = dict(parent=key, phase=parent["Phase"], side=parent["Base"]["Side"],
                           gross=0, events=[], decisions=[], state=parent)
    for ev in case["actual"]["Events"] or []:
        key = ev["Order"]["Parent"]
        item = answer[key]
        item["gross"] += ev["Gross"]
        item["events"].append(ev)
    for decision in case["decisions"] or []:
        answer[decision["Parent"]]["decisions"].append(decision)
    assert abs(sum(p["gross"] for p in answer.values())-case["actual"]["Realized"]) < .001
    return answer


def compact_event(ev: dict) -> dict:
    """発注・約定と所有IDを具体例のために短縮する。

    引数: ev(dict)。返り値: dict。
    """
    order = ev["Order"]
    return dict(action="返済" if order["Targets"] else "新規", side="買い" if order["Side"] > 0 else "売り",
                qty_micro=order["Quantity"], qty_mini_equivalent=order["Quantity"]/10,
                decision_time=stamp(order["DecisionTime"]), fill_time=stamp(ev["FillTime"]),
                decision_index=order["DecisionIndex"], fill_index=ev["FillIndex"],
                decision_bid=order["DecisionBid"], decision_ask=order["DecisionAsk"],
                bid=ev["Bid"], ask=ev["Ask"], price=ev["Price"], net=ev["Gross"],
                reason=order["Reason"], source_id=order["SourceID"], order_id=order["ID"],
                pieces=ev["Pieces"] or [])


def aggregate(rows: list[dict]) -> dict:
    """セッション会計と親の勝敗を混ぜずに比較統計を作る。

    引数: rows(list[dict])。返り値: dict。
    """
    values = [r["net"] for r in rows]
    red = [v for v in values if v < 0]
    return dict(sessions=len(rows), net=sum(values), positive_sessions=sum(v > 0 for v in values),
                negative_sessions=len(red), zero_sessions=sum(v == 0 for v in values),
                no_entries=sum(r["new_orders"] == 0 for r in rows),
                profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
                minimum_session=min(values), worst_equity=min(r["minimum_equity"] for r in rows),
                maximum_dd=max(r["maximum_dd"] for r in rows),
                excluding_top3=sum(values)-sum(sorted(values, reverse=True)[:3]),
                mean_red=sum(red)/len(red) if red else 0,
                entered_micro=sum(r["entered_micro"] for r in rows),
                reductions=sum(r["reductions"] for r in rows), restorations=sum(r["restorations"] for r in rows))


def main() -> None:
    """完了済み全53場の10案と固定合成を再集計する。

    引数: なし。返り値: None。新しい金融判断は実行しない。
    """
    manifest = read(HERE/"inputs163.json")
    frozen = read(HERE/"results/selection_frozen163.json")
    rows, contrasts, evidence = [], [], []
    for scene in manifest["sessions"]:
        stage = "locked_test" if scene["split"] == "test" else "train_validation"
        path = HERE/"results"/stage/(scene["session"]+".json")
        data = read(path)
        evidence.append(record(path))
        cases = {c["config"]["id"]: c for c in data["cases"]}
        native = parents(cases["B00"])
        for key, case in cases.items():
            ledger = case["actual"]
            ps = parents(case)
            pieces = [piece for ev in ledger["Events"] or [] for piece in ev["Pieces"] or []]
            profit = sum(max(0, p["Gross"]) for p in pieces)
            loss = -sum(min(0, p["Gross"]) for p in pieces)
            assert abs(profit-loss-ledger["Realized"]) < .001
            news = [ev for ev in ledger["Events"] or [] if not ev["Order"]["Targets"]]
            row = dict(session=scene["session"], kind=scene["kind"], split=scene["split"], id=key,
                       net=ledger["Realized"], profit=profit, loss=loss,
                       minimum_equity=ledger["Risk"]["Minimum"], maximum_dd=ledger["Risk"]["MaxDD"],
                       new_orders=len(news), entered_micro=sum(ev["Order"]["Quantity"] for ev in news),
                       reductions=sum(p["state"]["Reduced"] for p in ps.values()),
                       restorations=sum(p["state"]["Restored"] for p in ps.values()),
                       counts=case["counts"])
            rows.append(row)
            if key == frozen["selected"][scene["kind"]]:
                rows.append(dict(row, id="F00", selected_component=key))
            if key in ("B00", "C50"):
                continue
            assert set(ps) == set(native), "入口親が変わっている"
            for parent, p in ps.items():
                b = native[parent]
                contrasts.append(dict(session=scene["session"], kind=scene["kind"], split=scene["split"],
                    id=key, parent=parent, phase=p["phase"], side=p["side"], baseline=b["gross"],
                    net=p["gross"], delta=p["gross"]-b["gross"], reduced=p["state"]["Reduced"],
                    restored=p["state"]["Restored"], decisions=p["decisions"],
                    baseline_events=[compact_event(ev) for ev in b["events"]],
                    revised_events=[compact_event(ev) for ev in p["events"]]))
    assert len(rows) == 53*11
    groups = {}
    for ident in sorted({r["id"] for r in rows}):
        own = [r for r in rows if r["id"] == ident]
        for kind in ("全場", "Day", "Night"):
            for split in ("全場", "前40", "後13"):
                subset = [r for r in own if (kind == "全場" or r["kind"] == kind)
                          and (split == "全場" or (r["split"] == "test") == (split == "後13"))]
                groups[f"{ident}_{kind}_{split}"] = aggregate(subset)
    effects = {}
    phase_effects = {}
    examples = {}
    for ident in sorted({r["id"] for r in contrasts}):
        for kind in ("Day", "Night"):
            ps = [p for p in contrasts if p["id"] == ident and p["kind"] == kind]
            effects[f"{ident}_{kind}"] = dict(parents=len(ps), reduced=sum(p["reduced"] for p in ps),
                restored=sum(p["restored"] for p in ps), improved=sum(p["delta"] > 0 for p in ps),
                worsened=sum(p["delta"] < 0 for p in ps), unchanged=sum(p["delta"] == 0 for p in ps),
                avoided_losses=sum(p["delta"] for p in ps if p["baseline"] < 0 and p["delta"] > 0),
                lost_winning_profit=-sum(p["delta"] for p in ps if p["baseline"] > 0 and p["delta"] < 0),
                delta=sum(p["delta"] for p in ps),
                lost_wins=sum(p["baseline"] > 0 and p["net"] <= 0 for p in ps),
                rescued_losses=sum(p["baseline"] < 0 and p["net"] >= 0 for p in ps))
            examples[f"{ident}_{kind}_改善"] = sorted(ps, key=lambda p:p["delta"], reverse=True)[:2]
            examples[f"{ident}_{kind}_悪化"] = sorted(ps, key=lambda p:p["delta"])[:2]
        for phase in sorted({p["phase"] for p in contrasts}):
            ps = [p for p in contrasts if p["id"] == ident and p["phase"] == phase]
            phase_effects[f"{ident}_{phase}"] = dict(parents=len(ps), baseline=sum(p["baseline"] for p in ps),
                net=sum(p["net"] for p in ps), delta=sum(p["delta"] for p in ps),
                reduced=sum(p["reduced"] for p in ps), restored=sum(p["restored"] for p in ps))
    out = HERE/"diagnosis"
    out.mkdir(exist_ok=True)
    for name, value in (("比較集計163.json", dict(groups=groups, rows=rows, effects=effects, phase_effects=phase_effects, selected=frozen["selected"], sources=evidence+[record(Path(__file__))])),
                        ("具体親診断163.json", examples), ("全親差分163.json", contrasts)):
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k:v for k,v in groups.items() if k in ("B00_全場_全場", "C50_全場_全場", "F00_全場_全場", "F00_Day_全場", "F00_Night_全場")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
