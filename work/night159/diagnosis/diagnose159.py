"""保存済み夜間結果の悪化三場を、原板の具体行と初回支持へ対応付ける。金融再生は行わない。"""

from pathlib import Path
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def read(path):
    """JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clock(value):
    """UNIX秒を日本時間へ表示変換する。

    引数: value(float)。返り値: str。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


def raw_rows(path, start, end, scene_start):
    """対象区間の正常原板を物理行番号付きで抽出する。

    引数: path(Path)、start/end(float)。返り値: list[dict]。研究と同じ価格時計の限界を保持する。
    """
    result = []
    previous = scene_start
    counter = -1
    with path.open(encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            b = json.loads(line)
            stamp = b.get("CurrentPriceTime")
            if not stamp:
                continue
            at = datetime.fromisoformat(stamp).timestamp()
            if at < scene_start or at < previous:
                continue
            last = b.get("CurrentPrice") or 0
            if last <= 0:
                continue
            previous = at
            counter += 1
            if not start <= at <= end:
                continue
            bid, ask = b.get("Buy1") or {}, b.get("Sell1") or {}
            bp, ap = bid.get("Price") or 0, ask.get("Price") or 0
            if not 0 < bp < ap or not math.isfinite(bp + ap):
                continue
            result.append({"time": at, "clock": clock(at), "line": line_no, "observation_index": counter, "bid": bp, "ask": ap, "bid_qty": bid.get("Qty"), "ask_qty": ask.get("Qty"), "last": last, "raw": b})
    return result


def main():
    """悪化順位、全26場の原因群、三場の約定と原板を保存する。

    引数: なし。返り値: None。原結果・原データを変更しない。
    """
    sessions = []
    initials = []
    for path in sorted((ROOT / "work/night159/results_go").glob("*Night.json")):
        saved = read(path)
        cases = {c["config"]["id"]: c for c in saved["cases"]}
        before, after = cases["N00"], cases["N04"]
        sessions.append({"session": path.stem, "base": before["actual"]["Realized"], "N04": after["actual"]["Realized"], "delta": after["actual"]["Realized"] - before["actual"]["Realized"], "path": path, "saved": saved})
        for request in after["requests"] or []:
            if not request["Initial"]:
                continue
            key = request["Parent"]
            s = request["Support"]
            side = after["parents"][key]["Side"]
            b = before["actual"]["Parents"].get(key, {}).get("Realized", 0)
            a = after["actual"]["Parents"].get(key, {}).get("Realized", 0)
            initials.append({"session": path.stem, "parent": key, "known": s["Known"], "base": b, "N04": a, "delta": a-b, "quantity": request["Accepted"], "base_quantity": request["SourceQuantity"], "decelerated": s["Known"] and side*s["Own15"] > 0 and 3*side*s["Own5"] < .5*side*s["Own15"], "request": request})
    grouped = {}
    for label, keyfunc in (("支持既知", lambda x: "既知" if x["known"] else "未知"), ("担当", lambda x: x["parent"].split("/")[1]), ("短期失速", lambda x: "失速" if x["decelerated"] else "その他")):
        groups = defaultdict(list)
        for row in initials:
            groups[keyfunc(row)].append(row)
        grouped[label] = {key: {"parents": len(rows), "base": sum(x["base"] for x in rows), "N04": sum(x["N04"] for x in rows), "delta": sum(x["delta"] for x in rows), "base_wins": sum(x["base"] > 0 for x in rows), "base_losses": sum(x["base"] < 0 for x in rows)} for key, rows in groups.items()}
    top = []
    raw_samples = []
    for row in sorted(sessions, key=lambda x: x["delta"])[:3]:
        saved = row["saved"]
        cases = {c["config"]["id"]: c for c in saved["cases"]}
        actual = cases["N04"]["actual"]
        parents = []
        for parent, value in actual["Parents"].items():
            if not parent.startswith("後半/"):
                continue
            before = cases["N00"]["actual"]["Parents"][parent]
            lots = [lot for lot in actual["Lots"].values() if lot["Parent"] == parent]
            events = [event for event in actual["Events"] if event["Order"]["Parent"] == parent]
            requests = [request for request in cases["N04"]["requests"] or [] if request["Parent"] == parent]
            parents.append({"parent": parent, "base": before, "N04": value, "delta": value["Realized"]-before["Realized"], "lots": lots, "events": events, "requests": requests})
        times = [lot["At"] for p in parents for lot in p["lots"]] + [lot["BestAt"] for p in parents for lot in p["lots"]] + [event["FillTime"] for p in parents for event in p["events"]]
        boards = {}
        for ref in ("NK225", "TOPIX"):
            data = raw_rows(Path(saved["scene"]["books"][ref]), min(times)-150, max(times)+130, saved["scene"]["start"])
            if ref == "NK225":
                by_index = {b["observation_index"]: b for b in data}
                for parent in parents:
                    for event in parent["events"]:
                        raw = by_index[event["FillIndex"]]
                        assert (raw["time"],raw["bid"],raw["ask"]) == (event["FillTime"],event["Bid"],event["Ask"])
                        event["raw_exact_fill"] = {k:v for k,v in raw.items() if k != "raw"}
            ts = [b["time"] for b in data]
            samples = []
            for target in sorted(set(times)):
                for offset in (-120, -15, -5, 0, 5, 15, 60, 120):
                    i = bisect_right(ts, target+offset)-1
                    if i < 0:
                        continue
                    raw = data[i]
                    sample = {k:v for k,v in raw.items() if k != "raw"}
                    sample.update({"reference": ref, "target": clock(target), "offset": offset, "age": target+offset-raw["time"], "future_for_diagnosis_only": offset>0})
                    samples.append(sample)
                    raw_samples.append({"session": row["session"], **sample, "raw": raw["raw"]})
            boards[ref] = samples
        top.append({"session": row["session"], "base": row["base"], "N04": row["N04"], "delta": row["delta"], "parents": parents, "raw_samples": boards, "result_sha256": hashlib.sha256(row["path"].read_bytes()).hexdigest(), "book_paths": saved["scene"]["books"]})
        print(row["session"], row["base"], row["N04"], row["delta"], flush=True)
    output = {"scope": "保存済み26Nightの再集計。新金融再生0。原板サンプルは診断専用。未来に選んだ頂点や返済後の観測を売買条件へ渡していない。", "groups": grouped, "initials": initials, "worst_three": top, "ranking": [{k:v for k,v in x.items() if k not in ("path", "saved")} for x in sorted(sessions,key=lambda x:x["delta"])]}
    (HERE/"悪化三夜の保存会計と原板159.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (HERE/"悪化三夜の原板抜粋159.jsonl").open("w",encoding="utf-8") as out:
        for sample in raw_samples:
            out.write(json.dumps(sample,ensure_ascii=False)+"\n")


if __name__ == "__main__":
    main()
