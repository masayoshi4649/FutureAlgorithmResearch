"""独立監査済み実返済会計を手法別のExcel入力へ整形する。"""
from __future__ import annotations

from collections import defaultdict
import statistics

from audit_results164 import HERE, WORK, read, save, record


def summary(rows: list[dict]) -> dict:
    """累計と一場平均、最悪時価を区別して集計する。

    引数: rows(list[dict])。返り値: dict。
    """
    nets = [r["net"] for r in rows]
    losses = [-x for x in nets if x < 0]
    return dict(sessions=len(rows), profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
        net=sum(nets), average=statistics.mean(nets) if nets else None,
        negative_sessions=len(losses), no_entries=sum(r["new_orders"] == 0 for r in rows),
        mean_loss=statistics.mean(losses) if losses else 0., maximum_loss=max(losses, default=0.),
        minimum_equity=min((r["minimum_equity"] for r in rows), default=0.), maximum_dd=max((r["maximum_dd"] for r in rows), default=0.),
        excluding_top3=sum(sorted(nets)[:-3]) if len(nets) > 3 else None)


def groups(rows: list[dict]) -> dict:
    """前半と確認、追加一場を混ぜず集計する。

    引数: rows(list[dict])。返り値: dict。
    """
    return {"全場":summary(rows), "前40内":summary([r for r in rows if r["split"] in ("train", "validation")]),
        "確認14内":summary([r for r in rows if r["split"] not in ("train", "validation")]),
        "追加夜":summary([r for r in rows if r["session"] == "2026-10-27_Night"])}


def main() -> None:
    """540条件場の監査を必須に、20手法と合成IDのない夜時間割を出す。

    引数: なし。返り値: None。金融再生なし。
    """
    audit = read(HERE / "audit164.json")
    assert audit["passed"] and audit["totals"]["cases"] == 540
    frozen = read(WORK / "results/selection_frozen164.json")
    definitions = read(WORK / "engine/configs164.json")
    scenes = read(WORK / "inputs164.json")["sessions"]
    by_method, scene_results = defaultdict(list), {}
    for scene in scenes:
        checked = read(HERE / "結果監査" / (scene["session"] + ".json"))
        assert checked["passed"]
        scene_results[scene["session"]] = checked
        for r in checked["rows"]:
            row = dict(session=scene["session"], kind=scene["kind"], split=scene["split"], direction=checked["direction"],
                profit=r["profit"], loss=r["loss"], net=r["net"], minimum_equity=r["risk"]["min_equity"], maximum_dd=r["risk"]["max_drawdown"],
                peak_equity=r["peak_equity"], new_orders=r["new_orders"])
            assert abs(row["profit"] - row["loss"] - row["net"]) < 1e-6
            by_method[r["id"]].append(row)
    methods = []
    for config in definitions:
        rows = sorted(by_method[config["id"]], key=lambda x:x["session"])
        assert len(rows) == 27
        total = 0.
        for row in rows:
            total += row["net"]
            row["cumulative"] = total
        description = config.get("description")
        if description is None:
            description = ("旧" + config["native"]) if config.get("native") else ("反転入口" if config["scope"] == "PreUS" else "押戻り再加速入口") + "・" + config["protection"] + ("・新波再参加" if config["reentry"] else "")
        methods.append(dict(id=config["id"], scope=config["scope"], description=description, selected=frozen["selected"][config["scope"]] == config["id"], configuration=config, rows=rows, summary=groups(rows)))
    indexed = {m["id"]:{r["session"]:r for r in m["rows"]} for m in methods}
    schedules = []
    for name, pre, post in (("基準の時間割", "NK225_P164_00", "NK225_U164_00"), ("前40で固定した時間割", frozen["selected"]["PreUS"], frozen["selected"]["PostUS"])):
        rows, total = [], 0.
        for session in sorted(indexed[pre]):
            a, b = indexed[pre][session], indexed[post][session]
            check = next(x for x in scene_results[session]["schedule_overlap"] if x["pre"] == pre and x["post"] == post)
            assert check["no_overlap"] and check["shared_cap_ok"], "時間割合算は実保有非重複が必要"
            total += a["net"] + b["net"]
            rows.append(dict(session=session, split=a["split"], direction=a["direction"], profit=a["profit"] + b["profit"], loss=a["loss"] + b["loss"],
                net=a["net"] + b["net"], cumulative=total,
                minimum_equity=min(a["minimum_equity"], a["net"] + b["minimum_equity"]),
                maximum_dd=max(a["maximum_dd"], b["maximum_dd"], a["peak_equity"] - a["net"] - b["minimum_equity"]),
                new_orders=a["new_orders"] + b["new_orders"]))
        schedules.append(dict(name=name, pre=pre, post=post, synthetic_method_id=None, rows=rows, summary=groups(rows)))
    save(WORK / "report_data164.json", dict(methods=methods, schedules=schedules, selected=frozen["selected"], sources=[record(HERE / "audit164.json"), record(WORK / "results/selection_frozen164.json")],
        accounting="実返済Piece別の正負。損失は正額、収支=利益−損失。", new_financial_replays=0))
    print("20手法と2時間割を保存。売買再生0。")


if __name__ == "__main__":
    main()
