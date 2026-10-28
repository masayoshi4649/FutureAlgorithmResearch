"""第二巡の保存結果を再集計し、具体的な救済・利益消失を原板へ照合する。新金融再生は行わない。"""

from pathlib import Path
from datetime import datetime, timezone, timedelta
from statistics import mean, median
import hashlib
import json
import math

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
JST = timezone(timedelta(hours=9))
IDS = ("N00", "N04", "R00", "R01", "R02", "R03")
FOCUS = ("2026-10-12_Night", "2026-10-14_Night", "2026-10-16_Night", "2026-10-19_Night", "2026-10-26_Night")


def read(path):
    """保存JSONを読み取る。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clock(at):
    """秒時計を日本時間の表示へ変換する。

    引数: at(float)。返り値: str。
    """
    return datetime.fromtimestamp(at, JST).isoformat()


def summary(case):
    """完結親収支と既存時価記録から場別数値を取り出す。

    引数: case(dict)。返り値: dict。売買判断は再実行しない。
    """
    actual = case["actual"]
    values = [v["Realized"] for v in actual["Parents"].values()]
    assert all(v["Quantity"] == 0 for v in actual["Parents"].values())
    assert sum(values) == actual["Realized"]
    risk = actual["Risk"]
    return {"収支": sum(values), "利益": sum(v for v in values if v > 0), "損失": -sum(v for v in values if v < 0), "場内最低時価": risk["Minimum"], "場内最大DD": risk["MaxDD"], "最低時価の時刻": clock(risk["MinimumAt"]["Time"]), "最低時価の内訳": risk["MinimumAt"]}


def raw_exact(scene, indices):
    """約定・時価の既存観測番号を原板の物理行へ照合する。

    引数: scene(dict)、indices(set[int])。返り値: dict[int,dict]。
    正常な価格時計の採用順は凍結エンジンと同じ。抽出のみで注文は作らない。
    """
    results = {}
    previous = scene["start"]
    counter = -1
    with Path(scene["books"]["NK225"]).open(encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            board = json.loads(line)
            stamp = board.get("CurrentPriceTime")
            if not stamp:
                continue
            at = datetime.fromisoformat(stamp).timestamp()
            last = board.get("CurrentPrice") or 0
            if at < scene["start"] or at < previous or last <= 0:
                continue
            previous = at
            counter += 1
            if counter not in indices:
                continue
            bid, ask = board.get("Buy1") or {}, board.get("Sell1") or {}
            bp, ap = bid.get("Price") or 0, ask.get("Price") or 0
            assert 0 < bp < ap and math.isfinite(bp + ap)
            results[counter] = {"観測番号": counter, "原板物理行": line_no, "時刻": clock(at), "Time": at, "Bid": bp, "Ask": ap, "買数量": bid.get("Qty"), "売数量": ask.get("Qty"), "原板": board}
            if len(results) == len(indices):
                break
    assert set(results) == indices
    return results


def main():
    """全26夜の比較と五夜の具体的約定を診断資料へ保存する。

    引数: なし。返り値: None。結果・原データ・凍結コードは変更しない。
    """
    sessions, details = [], []
    for path in sorted((HERE.parent / "results_go").glob("*Night.json")):
        current = read(path)
        original_path = ROOT / "work/night159/results_go" / path.name
        original = read(original_path)
        cases = {c["config"]["id"]: c for c in original["cases"] if c["config"]["id"] in IDS}
        cases.update({c["config"]["id"]: c for c in current["cases"]})
        assert current["control"] == cases["N00"]
        entry = {"セッション": path.stem, "各手法": {key: summary(cases[key]) for key in IDS}}
        sessions.append(entry)
        if path.stem not in FOCUS:
            continue
        all_events = [e for c in cases.values() for e in c["actual"]["Events"] if e["Order"]["Parent"].startswith("後半/")]
        indices = {e["FillIndex"] for e in all_events}
        indices.update(c["actual"]["Risk"]["MinimumAt"]["Index"] for c in cases.values())
        boards = raw_exact(current["scene"], indices)
        for event in all_events:
            b = boards[event["FillIndex"]]
            assert (b["Time"], b["Bid"], b["Ask"]) == (event["FillTime"], event["Bid"], event["Ask"])
        parents = {}
        for parent in sorted(set(p for c in cases.values() for p in c["actual"]["Parents"] if p.startswith("後半/"))):
            parents[parent] = {}
            for key in IDS:
                case = cases[key]
                events = [e for e in case["actual"]["Events"] if e["Order"]["Parent"] == parent]
                parents[parent][key] = {"親収支": case["actual"]["Parents"].get(parent, {}).get("Realized", 0), "注文と約定": [{**e, "日本時間": clock(e["FillTime"]), "原板物理行": boards[e["FillIndex"]]["原板物理行"]} for e in events], "超過返済の判断": [e for e in case.get("excess_exits", []) if e["Parent"] == parent], "数量の判断": [e for e in case.get("requests") or [] if e["Parent"] == parent]}
        details.append({**entry, "親別": parents, "原板照合": list(boards.values()), "結果指紋": {str(path): hashlib.sha256(path.read_bytes()).hexdigest(), str(original_path): hashlib.sha256(original_path.read_bytes()).hexdigest()}})
        print(path.stem, "原板照合", len(boards), flush=True)

    totals = {}
    for key in IDS:
        rows = [x["各手法"][key] for x in sessions]
        losing = [-x["収支"] for x in rows if x["収支"] < 0]
        gains = sorted([x["収支"] for x in rows if x["収支"] > 0], reverse=True)
        total = sum(x["収支"] for x in rows)
        totals[key] = {"場数": len(rows), "収支": total, "利益": sum(x["利益"] for x in rows), "損失": sum(x["損失"] for x in rows), "赤字場数": len(losing), "平均赤字": mean(losing), "中央赤字": median(losing), "最大場末赤字": max(losing), "場内最低時価": min(x["場内最低時価"] for x in rows), "場内最大DD": max(x["場内最大DD"] for x in rows), "上位3黒字除外": total - sum(gains[:3])}
    differences = [{"セッション": x["セッション"], "R02収支": x["各手法"]["R02"]["収支"], "R03収支": x["各手法"]["R03"]["収支"], "R03差": x["各手法"]["R03"]["収支"] - x["各手法"]["R02"]["収支"]} for x in sessions if x["各手法"]["R03"]["収支"] != x["各手法"]["R02"]["収支"]]
    output = {"範囲": "保存済み26完了夜の再集計。新金融再生0。原板は既存約定の照合と事後診断だけ。10/26夜は途中まで既知の追加完了版であり独立未見ではない。", "総計": totals, "全場": sessions, "R03追加返済による差": differences, "注目五夜": details}
    (HERE / "第二巡の救済と利益消失159.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("総計", json.dumps(totals, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
