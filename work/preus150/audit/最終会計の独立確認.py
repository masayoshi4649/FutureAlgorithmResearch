"""保存済み約定だけから00150の会計・後半不変・活動を独立検算する。"""

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
OLD = ROOT / "work/preus149"


def same(actual, expected, context):
    """機能: 浮動小数の丸めだけを許し保存値と独立計算を照合する。

    引数: actual/expected(float)は比較値、context(any)は検査場所。
    返り値: なし。不一致ではAssertionError。
    """
    assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-6), (context, actual, expected)


def signature(case, phase="後半", owner=None):
    """機能: 後半の約定列を運転ID以外の売買意味で比較する。

    引数: case(dict)は保存条件、phase(str)は前後区分、owner(str|None)は任意の担当。
    返り値: list[tuple]は理由・リスク・注文段まで含めた約定列。
    """
    result = []
    for event in case["events"] or []:
        if event["phase"] != phase or (owner is not None and event["signal"]["owner"] != owner):
            continue
        s, f = event["signal"], event["fill"]
        result.append((s["owner"], s["action"], s["side"], s["time"],
                       f["Time"], f["Quantity"], f["Price"], event["decision_index"],
                       event["fill_index"], s["reason_code"], s["risk"],
                       s["boundary"], s.get("ticket", 0), event["gross"]))
    return result


def summary(rows):
    """機能: 場単位の黒字赤字と親単位の総利益総損失を集計する。

    引数: rows(list[dict])は独立会計。
    返り値: dictは合計・損失の深さ・大勝ち除外収支。
    """
    net = sum(r["net"] for r in rows)
    losses = [-r["net"] for r in rows if r["net"] < 0]
    wins = sorted((r["net"] for r in rows if r["net"] > 0), reverse=True)
    return dict(net=net, profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
                entries=sum(r["entries"] for r in rows), wins=len(wins), losses=len(losses),
                maxloss=max(losses, default=0), avgloss=mean(losses) if losses else 0,
                medianloss=median(losses) if losses else 0, ex3=net-sum(wins[:3]),
                zero_entries=sum(r["entries"] == 0 for r in rows))


def last_quote(scene):
    """機能: 途中場の保存原板から最終正常気配だけを読み、時価検算へ使う。

    引数: scene(dict)は保存元と時計範囲。
    返り値: tuple[float,float]は買気配と売気配。売買判断や価格再生は行わない。
    """
    previous = scene["start"]
    quote = None
    with Path(scene["books"]["NK225"]).open(encoding="utf-8-sig") as stream:
        for line in stream:
            raw = json.loads(line)
            stamp = raw.get("CurrentPriceTime")
            if not stamp:
                continue
            try:
                at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if at < previous or at < scene["start"] or at > scene["end"] or at >= scene["cutoff"]:
                continue
            price = raw.get("CurrentPrice")
            if price is None or not math.isfinite(price) or price <= 0:
                continue
            previous = at
            bid, ask = raw.get("Buy1", {}) or {}, raw.get("Sell1", {}) or {}
            values = [bid.get("Price"), ask.get("Price"), bid.get("Qty"), ask.get("Qty")]
            if all(v is not None and math.isfinite(v) for v in values) and 0 < bid["Price"] < ask["Price"] and min(bid["Qty"], ask["Qty"]) > 0:
                quote = bid["Price"], ask["Price"]
    assert quote is not None
    return quote


def account(scene, case):
    """機能: 所有IDを順に追い、現金差・親損益・前半保有時間を再計算する。

    引数: scene(dict)は場の時刻、case(dict)は保存約定。
    返り値: dictは会計、方向・担当別損益、検査件数。注文判断は生成しない。
    """
    lots, parents = {}, {}
    cash = realized = plus = minus = 0
    largest = events = evidence = 0
    last_time = scene["start"]
    end = scene["us_open"] - 900
    if scene["partial"]:
        end = min(end, scene["cutoff"])
    duration = end - scene["start"]
    exposure = held_seconds = quantity_seconds = 0
    first_pre = None
    previous_activity = scene["start"]
    for e in case["events"] or []:
        s, f = e["signal"], e["fill"]
        side, qty, price, at = s["side"], f["Quantity"], f["Price"], f["Time"]
        assert side in (-1, 1) and qty > 0 and qty == s["quantity"] and f["Fee"] == 0
        assert e["fill_index"] > e["decision_index"] == s["source_index"]
        assert at >= s["time"] and at >= last_time
        last_time = at
        stop = min(at, end)
        dt = max(0, stop - previous_activity)
        held_seconds += dt if exposure > 0 else 0
        quantity_seconds += exposure * dt
        previous_activity = max(previous_activity, stop)
        # ----------------------------------------
        cash -= side * qty * price * 100
        gain = 0
        if s["action"] == "new":
            key = f["HoldID"]
            assert key not in lots
            parent = (e["phase"], s["owner"], s["campaign"])
            segment = "pre" if at < scene["us_open"] else "post"
            p = parents.setdefault(parent, dict(net=0, side=side, owner=s["owner"], segment=segment, entries=0))
            assert p["side"] == side
            p["entries"] += 1
            lots[key] = [side, qty, price, parent]
            exposure += qty
            if first_pre is None and at < end:
                first_pre = at
            if case["config"].get("reset"):
                if e["phase"] == "前半":
                    assert s["time"] < scene["us_open"] - case["config"]["close_before_minutes"]*60
                else:
                    assert s["time"] >= scene["us_open"] + case["config"]["restart_wait_minutes"]*60
        else:
            assert s["action"] == "close"
            closed = 0
            for target in f["Closed"]:
                lot = lots[target["id"]]
                q = target["quantity"]
                assert lot[0] == -side and 0 < q <= lot[1]
                value = lot[0] * q * (price-lot[2]) * 100
                gain += value
                parents[lot[3]]["net"] += value
                lot[1] -= q
                closed += q
            assert closed == qty
            exposure -= qty
        assert exposure >= 0
        same(gain, e["gross"], "部分返済損益")
        realized += gain
        plus += max(gain, 0)
        minus += max(-gain, 0)
        largest = max(largest, *(sum(x[1] for x in lots.values() if x[0] == d) for d in (-1, 1)))
        assert largest <= 10
        obs = s.get("evidence", {}).get("observation")
        if obs:
            assert obs["Time"] == s["time"] and obs["Index"] == s["source_index"]
            for name in ("main_available", "peer_available", "atr_available"):
                assert obs["E01"][name] <= obs["Time"]
            for name in ("DayMarket", "LastMarket", "MidMarket"):
                if obs[name]["Known"]:
                    assert obs[name]["PeerTime"] < obs["Time"]
            evidence += 1
        events += 1
    # ----------------------------------------
    dt = max(0, end-previous_activity)
    held_seconds += dt if exposure > 0 else 0
    quantity_seconds += exposure*dt
    for actual, expected in ((realized, case["Gross"]), (plus, case["Profit"]), (minus, case["Loss"]), (largest, case["max_per_side"])):
        same(actual, expected, "条件会計")
    assert case["cancelled_new"] == 0
    if not scene["partial"]:
        assert all(x[1] == 0 for x in lots.values()) and not case["positions"] and not case["final_pending"]
        assert case["Unrealized"] == 0
        same(cash, realized, "全決済現金差")
        if case["config"].get("reset"):
            assert 0 < case["pre_flat_at"] <= case["post_started"] and case["post_started"] >= scene["us_open"]
    else:
        assert {key for key, lot in lots.items() if lot[1] > 0} == set(case["positions"])
        for key, lot in lots.items():
            if lot[1] > 0:
                saved = case["positions"][key]
                assert (saved["Side"], saved["Quantity"], saved["Price"]) == tuple(lot[:3])

    def group(items):
        """機能: 選択した親を集計する。引数: items(list[dict])。返り値: dict。"""
        return dict(net=sum(x["net"] for x in items), profit=sum(max(x["net"], 0) for x in items),
                    loss=sum(max(-x["net"], 0) for x in items), entries=sum(x["entries"] for x in items))

    values = list(parents.values())
    result = group(values)
    result.update(max_per_side=largest, events=events, evidence=evidence)
    for phase in ("pre", "post"):
        result[phase] = group([x for x in values if x["segment"] == phase])
    result["pre_buy"] = group([x for x in values if x["segment"] == "pre" and x["side"] == 1])
    result["pre_sell"] = group([x for x in values if x["segment"] == "pre" and x["side"] == -1])
    result["pre_owners"] = {owner: group([x for x in values if x["segment"] == "pre" and x["owner"] == owner]) for owner in ("core", "addon", "episode")}
    result["activity"] = dict(seconds=held_seconds, denominator_seconds=duration, holding_ratio=held_seconds/duration,
                              average_quantity=quantity_seconds/duration, first_entry_delay_minutes=(first_pre-scene["start"])/60 if first_pre else None)
    return result


def main():
    """機能: 完成した保存26夜の初巡20／最終26条件表示を検算して監査JSONを残す。

    引数: なし。
    返り値: なし。保存約定の読取りのみで新たな金融再生はしない。
    """
    receipt = json.loads((STUDY/"登録受領150.json").read_text("utf-8"))
    assert receipt["registered"] and receipt["returncode"] == 0
    registration_artifacts = 0
    for key in ("plan", "implementation", "inputs"):
        artifact = receipt[key]
        assert hashlib.sha256((ROOT/artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"], key
        registration_artifacts += 1
    frozen = json.loads((STUDY/"凍結ソース150.json").read_text("utf-8"))
    for item in frozen:
        assert hashlib.sha256((ROOT/item["path"]).read_bytes()).hexdigest() == item["sha256"], item["path"]
    report = json.loads((STUDY/"report150.json").read_text("utf-8"))
    methods = {m["id"]: m for m in report["methods"]}
    first_ids = {f"A{i:02d}" for i in range(17)}
    round2_ids = {f"B{i:02d}" for i in range(1, 7)} if "B01" in methods else set()
    new_ids = first_ids | round2_ids
    assert set(methods) == {"C00", "S04", "S02"} | new_ids
    round2_hashes = 0
    if round2_ids:
        second_receipt = json.loads((STUDY/"round2/登録受領.json").read_text("utf-8"))
        assert second_receipt["registered"] and second_receipt["returncode"] == 0
        for item in second_receipt["sources"]:
            assert hashlib.sha256((ROOT/item["path"]).read_bytes()).hexdigest() == item["sha256"], item["path"]
            round2_hashes += 1
        for key in ("plan", "implementation", "inputs", "previous_result"):
            item = second_receipt[key]
            assert hashlib.sha256((ROOT/item["path"]).read_bytes()).hexdigest() == item["sha256"], key
            registration_artifacts += 1
    manifest = json.loads((OLD/"data/原資料一覧149.json").read_text("utf-8"))
    complete = [s for s in manifest["sessions"] if not s["partial"]]
    assert len(complete) == 25 and len(manifest["sessions"]) == 26
    records, cases_by_scene = {}, {}
    for scene in manifest["sessions"]:
        session = scene["session"]
        new = json.loads((STUDY/"results_go"/f"{session}.json").read_text("utf-8"))
        assert len(new["cases"]) == 17
        byid = {c["config"]["id"]: c for c in new["cases"]}
        if round2_ids:
            second = json.loads((STUDY/"results_round2"/f"{session}.json").read_text("utf-8"))
            assert len(second["cases"]) == 6
            byid.update({c["config"]["id"]: c for c in second["cases"]})
        for folder in ("results_go", "results_round2"):
            old = json.loads((OLD/folder/f"{session}.json").read_text("utf-8"))
            byid.update({c["config"]["id"]: c for c in old["cases"] if c["config"]["id"] in ("C00", "S04", "S02")})
        cases_by_scene[session] = byid
        for ident, case in byid.items():
            records[(session, ident)] = account(scene, case)
        if scene["partial"]:
            bid, ask = last_quote(scene)
            for ident, case in byid.items():
                unrealized = sum(lot["Side"]*lot["Quantity"]*((bid if lot["Side"] > 0 else ask)-lot["Price"])*100 for lot in case["positions"].values())
                same(case["Unrealized"], unrealized, (session, ident, "途中時価"))

    exact = events = evidence = episode_exact = second_unchanged_addon = 0
    summaries = {}
    for ident, method in methods.items():
        assert [r["session"] for r in method["rows"]] == [s["session"] for s in complete]
        rows = []
        for row in method["rows"]:
            checked = records[(row["session"], ident)]
            for key in ("net", "profit", "loss", "entries", "max_per_side"):
                same(row[key], checked[key], (ident, row["session"], key))
            for phase in ("pre", "post"):
                for key in ("net", "profit", "loss", "entries"):
                    same(row[phase][key], checked[phase][key], (ident, row["session"], phase, key))
            for key in ("seconds", "denominator_seconds", "holding_ratio", "average_quantity"):
                same(row["pre_activity"][key], checked["activity"][key], (ident, row["session"], "保有", key))
            assert row["pre_activity"]["first_entry_delay_minutes"] == checked["activity"]["first_entry_delay_minutes"]
            rows.append(checked)
            events += checked["events"]
            evidence += checked["evidence"]
            if ident in new_ids:
                byid = cases_by_scene[row["session"]]
                assert signature(byid[ident]) == signature(byid["S04"]), (ident, row["session"], "後半約定不一致")
                assert byid[ident]["post_started"] == byid["S04"]["post_started"]
                exact += 1
                assert signature(byid[ident], "前半", "episode") == signature(byid["A00"], "前半", "episode")
                episode_exact += 1
                if ident in round2_ids:
                    assert signature(byid[ident], "前半", "addon") == signature(byid["A00"], "前半", "addon")
                    second_unchanged_addon += 1
        for key, value in summary(rows).items():
            same(method["summary"][key], value, (ident, "総計", key))
        for phase in ("pre", "post"):
            for key, value in summary([r[phase] for r in rows]).items():
                same(method[phase][key], value, (ident, phase, key))
        differences = [checked["pre"]["net"]-records[(row["session"], "A00")]["pre"]["net"] for row, checked in zip(method["rows"], rows)]
        summaries[ident] = dict(all=summary(rows), pre=summary([r["pre"] for r in rows]),
                               pre_buy=summary([r["pre_buy"] for r in rows]), pre_sell=summary([r["pre_sell"] for r in rows]),
                               pre_owners={owner: summary([r["pre_owners"][owner] for r in rows]) for owner in ("core", "addon", "episode")},
                               active_nights=sum(r["activity"]["first_entry_delay_minutes"] is not None for r in rows),
                               mean_holding_ratio=mean(r["activity"]["holding_ratio"] for r in rows),
                               mean_quantity=mean(r["activity"]["average_quantity"] for r in rows),
                               improvement_nights=sum(x > 0 for x in differences), worsening_nights=sum(x < 0 for x in differences),
                               equal_nights=sum(x == 0 for x in differences), delta=sum(differences),
                               delta_ex3=sum(differences)-sum(sorted([x for x in differences if x > 0], reverse=True)[:3]))
        for direction, subtotal in method["by_direction"].items():
            selected = [checked for row, checked in zip(method["rows"], rows) if row["direction"] == direction]
            for key, value in summary(selected).items():
                same(subtotal[key], value, (ident, direction, key))
        summaries[ident]["by_session_direction"] = method["by_direction"]

    assert exact == len(new_ids)*25
    assert len(report["partial"]) == len(methods)
    for row in report["partial"]:
        checked = records[(row["session"], row["id"])]
        for key in ("net", "profit", "loss", "entries", "max_per_side"):
            same(row[key], checked[key], (row["id"], "途中表", key))
        saved = cases_by_scene[row["session"]][row["id"]]
        same(row["unrealized"], saved["Unrealized"], "途中表含み損益")
        same(row["equity"], row["net"]+row["unrealized"], "途中表収支と含み")
    output = dict(financial_replays=0, frozen_source_hashes_checked=len(frozen), source_hashes_unchanged=True,
                  round2_source_hashes_checked=round2_hashes, registration_artifacts_checked=registration_artifacts,
                  new_methods=len(new_ids), reused_controls=3, complete_nights=25, new_method_nights=len(new_ids)*25,
                  complete_display_method_nights=len(methods)*25, partial_method_nights=len(methods),
                  event_rows=events, evidence_rows=evidence, s04_post_exact_method_nights=exact,
                  unchanged_episode_method_nights=episode_exact, round2_unchanged_addon_method_nights=second_unchanged_addon,
                  all_checks_passed=True, methods=summaries)
    (HERE/"最終会計の独立確認.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({k: v for k, v in output.items() if k != "methods"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
