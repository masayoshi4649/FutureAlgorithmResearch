"""D07の保存約定を変えず、親・玉・追加前後の清算価値を独立診断する。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
from statistics import mean, median

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT/"work/research145_roles"
CACHE = ROOT/"work/research145_engine/cache"
JST = timezone(timedelta(hours=9))
ROLES = ["基本CG", "追加担当A", "別入口CS"]


def read(path: Path):
    """既存JSONを読む。

    引数: path(Path)。返り値: dict又はlist。原資料へ書き込まない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> dict:
    """全文指紋を確認する。

    引数: path(Path)。返り値: dictは位置、バイト数、SHA256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest}


def stamp(value: float) -> str:
    """価格時計を日本時間で表示する。

    引数: value(float)はUNIX秒。返り値: strはISO形式。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def event(row: np.ndarray, ready: dict) -> dict:
    """保存注文の判断・約定原行を明記する。

    引数: row(ndarray)は10列注文、ready(dict)は保存時計。
    返り値: dictは原注文参照。新しい判断は生成しない。
    """
    i, d, pid, side, qty = map(int, row[:5])
    return {"index": i, "decision_index": d, "parent_id": pid, "side": side, "quantity": qty,
            "price": float(row[5]), "reason": int(row[6]), "new": bool(row[7]), "uid": int(row[8]),
            "decision_at": stamp(ready["time_s"][d]), "fill_at": stamp(ready["time_s"][i]),
            "decision_raw_line": int(ready["seq"][d])+1, "fill_raw_line": int(ready["seq"][i])+1}


def summarize(parents: list[dict], lots: list[dict]) -> dict:
    """保存親と玉を同じ定義で集約する。

    引数: parents/lots(list[dict])は対象のみの会計。
    返り値: dictは収支・利益返し・追加直後損失。未来極値は診断専用。
    """
    positive = [p for p in parents if p["peak_equity"]["value"] > 0]
    small = [p for p in parents if p["small_peak_equity"] is not None and p["small_peak_equity"]["value"] > 0]
    adds = [lot for lot in lots if lot["type"] == "保有中の追撃"]
    return {"parents": len(parents), "tickets": len(lots), "profit": sum(max(p["net"], 0) for p in parents),
            "loss": sum(max(-p["net"], 0) for p in parents), "net": sum(p["net"] for p in parents),
            "positive_peak_parents": len(positive), "positive_peak_then_negative": sum(p["net"] < 0 for p in positive),
            "positive_peak_then_nonpositive": sum(p["net"] <= 0 for p in positive),
            "small_positive_peak_parents": len(small), "small_positive_peak_then_negative": sum(p["net"] < 0 for p in small),
            "small_positive_peak_then_nonpositive": sum(p["net"] <= 0 for p in small),
            "giveback_sum_diagnostic_only": sum(p["peak_equity"]["value"]-p["net"] for p in parents),
            "initial_ticket_net": sum(lot["net"] for lot in lots if lot["type"] == "初回玉"),
            "additional_tickets": len(adds), "additional_quantity": sum(lot["initial_quantity"] for lot in adds),
            "additional_profit": sum(max(lot["net"], 0) for lot in adds), "additional_loss": sum(max(-lot["net"], 0) for lot in adds),
            "additional_net": sum(lot["net"] for lot in adds),
            "additional_wins": sum(lot["net"] > 0 for lot in adds), "additional_losses": sum(lot["net"] < 0 for lot in adds),
            "additional_negative_within_60_seconds": sum(lot["net"] < 0 and lot["seconds_to_final_close"] <= 60 for lot in adds),
            "additional_negative_within_300_seconds": sum(lot["net"] < 0 and lot["seconds_to_final_close"] <= 300 for lot in adds),
            "additional_no_favorable_negative": sum(lot["net"] < 0 and lot["mfe_points"] <= 0 for lot in adds)}


def examine_parent(orders: np.ndarray, data: dict, scene: str) -> tuple[dict, list[dict]]:
    """一親の保存約定とその間の正常気配を独立会計する。

    引数: orders(ndarray)、data(dict)、scene(str)。
    返り値: tuple[dict,list[dict]]は親と個別玉。約定列・出口条件は変えない。
    """
    ready, quotes = data["ready"], data["quotes"]
    times, bid, ask = ready["time_s"], quotes["bid"], quotes["ask"]
    valid = np.asarray(quotes["quote_valid"], bool)
    pid, direction = int(orders[0, 2]), int(orders[0, 3])
    owner = ROLES[pid//10_000_000]
    tickets, references = {}, []
    cash = realized = 0.0
    held = maximum = 0
    peaks = {"equity": None, "unrealized": None, "small_equity": None, "small_unrealized": None}

    def record(values: np.ndarray, indices: np.ndarray, kind: str, quantity: int, phase: str) -> None:
        """既約定の清算価値の最大地点を記録する。

        引数: values/indices(ndarray)、kind/phase(str)、quantity(int)。返り値: None。
        """
        good = np.isfinite(values) & valid[indices]
        if not np.any(good):
            return
        chosen, amounts = indices[good], values[good]
        position = int(np.argmax(amounts))
        value, idx = float(amounts[position]), int(chosen[position])
        if peaks[kind] is None or value > peaks[kind]["value"]:
            peaks[kind] = {"value": value, "index": idx, "time": stamp(times[idx]), "raw_line": int(ready["seq"][idx])+1,
                           "quantity": quantity, "phase": phase}

    def observe(indices: np.ndarray, phase: str) -> None:
        """親の確定済みと残玉の含みを分けて評価する。

        引数: indices(ndarray)は保存添字、phase(str)は約定前後。返り値: None。
        """
        prices = bid[indices] if direction > 0 else ask[indices]
        equity = cash+direction*held*prices*100
        unrealized = equity-realized
        record(equity, indices, "equity", held, phase)
        if held:
            record(unrealized, indices, "unrealized", held, phase)
        if 1 <= held <= 2:
            record(equity, indices, "small_equity", held, phase)
            record(unrealized, indices, "small_unrealized", held, phase)

    indices = sorted(set(orders[:, 0].astype(int)))
    for cursor, idx in enumerate(indices):
        if held:
            observe(np.array([idx]), "当行約定前")
        for row in orders[orders[:, 0] == idx]:
            ref = event(row, ready)
            i, d, _, side, qty = map(int, row[:5])
            price, uid = float(row[5]), int(row[8])
            assert 0 <= d < i < len(times) and valid[i] and row[9] == 0
            assert price == (ask[i] if side > 0 else bid[i])
            before_value = cash+direction*held*(bid[i] if direction > 0 else ask[i])*100
            before_unrealized = before_value-realized
            cash -= side*qty*price*100
            if row[7]:
                assert side == direction and uid not in tickets
                kind = "初回玉" if not tickets else "保有中の追撃" if held else "同親の再新規"
                tickets[uid] = {"session": scene, "owner": owner, "parent_id": pid, "uid": uid, "type": kind,
                                "side": side, "initial_quantity": qty, "remaining": qty, "price": price, "net": 0.,
                                "entry": ref, "closes": [], "quantity_before": held,
                                "parent_equity_before_entry": before_value, "unrealized_before_entry": before_unrealized,
                                "entry_spread": float(ask[i]-bid[i]), "immediate_spread_cost": float(qty*(ask[i]-bid[i])*100)}
                held += qty
            else:
                ticket = tickets[uid]
                assert side == -direction and ticket["remaining"] >= qty
                pnl = direction*(price-ticket["price"])*qty*100
                ticket["remaining"] -= qty
                ticket["net"] += pnl
                ref["realized"] = pnl
                ticket["closes"].append(ref)
                held -= qty
                realized += pnl
            maximum = max(maximum, held)
            assert 0 <= held <= [5, 3, 2][pid//10_000_000]
            references.append(ref)
            observe(np.array([idx]), "個別約定後")
        stop = indices[cursor+1] if cursor+1 < len(indices) else idx+1
        observe(np.arange(idx, stop), "保有観測")
    assert held == 0 and abs(cash-realized) < 1e-6
    lots = []
    for ticket in tickets.values():
        assert ticket["remaining"] == 0 and ticket["closes"]
        begin, end = ticket["entry"]["index"], ticket["closes"][-1]["index"]
        window = np.arange(begin, end+1)
        window = window[valid[window]]
        mark = bid[window] if direction > 0 else ask[window]
        gain = direction*(mark-ticket["price"])
        imax, imin = int(np.argmax(gain)), int(np.argmin(gain))
        ticket.update(mfe_points=float(gain[imax]), mae_points=float(gain[imin]), mfe_at=stamp(times[window[imax]]),
                      mae_at=stamp(times[window[imin]]), mfe_raw_line=int(ready["seq"][window[imax]])+1,
                      seconds_to_first_close=float(times[ticket["closes"][0]["index"]]-times[begin]),
                      seconds_to_final_close=float(times[end]-times[begin]))
        lots.append(ticket)
    assert abs(sum(lot["net"] for lot in lots)-cash) < 1e-6
    return {"session": scene, "kind": scene.split("_")[1], "owner": owner, "parent_id": pid, "side": direction,
            "net": cash, "initial_quantity": lots[0]["initial_quantity"], "maximum_quantity": maximum,
            "entry": references[0], "exit": references[-1], "orders": references,
            "peak_equity": peaks["equity"], "peak_unrealized": peaks["unrealized"],
            "small_peak_equity": peaks["small_equity"], "small_peak_unrealized": peaks["small_unrealized"],
            "giveback_to_final": peaks["equity"]["value"]-cash,
            "additions": sum(lot["type"] == "保有中の追撃" for lot in lots)}, lots


def main() -> None:
    """50場の保存D07だけを再会計して、入力再利用目録と診断を保存する。

    引数: なし。返り値: None。新金融再生、API取得、原資料変更は0回。
    """
    official = read(OLD/"役割分離の全場結果145.json")
    previous = {row["session"]: row for row in official["rows"] if row["method"] == "D07"}
    original_orders = {Path(item["path"]).stem: item for item in official["sources"]}
    original_cache = {item["session"]: item["cache"] for item in read(OLD/"保存入力145.json")["sessions"]}
    assert len(previous) == 50
    manifest, parents, lots, sessions = [], [], [], []
    for scene in sorted(previous):
        path, cache_path = OLD/"orders"/f"{scene}.npz", CACHE/f"{scene}.pkl"
        order_ref, cache_ref = sha(path), sha(cache_path)
        assert order_ref == original_orders[scene] and cache_ref == original_cache[scene]
        with cache_path.open("rb") as stream:
            _, data, _, _, label = pickle.load(stream)
        with np.load(path) as source:
            orders = source["D07"]
        chosen, tickets = [], []
        for pid in np.unique(orders[:, 2]):
            parent, leg = examine_parent(orders[orders[:, 2] == pid], data, scene)
            chosen.append(parent); tickets.extend(leg)
        values = summarize(chosen, tickets)
        for key in ("net", "profit", "loss"):
            assert abs(values[key]-previous[scene][key]) < 1e-6, (scene, key)
        parents.extend(chosen); lots.extend(tickets)
        sessions.append({"session": scene, "kind": scene.split("_")[1], "direction": label["direction"], **values})
        manifest.append({"session": scene, "orders": order_ref, "cache": cache_ref,
                         "raw_rows": len(data["ready"]["time_s"]), "features_shape": list(data["features"].shape),
                         "seq_is_zero_based_raw_line": True, "observed_start": stamp(data["ready"]["time_s"][0]),
                         "observed_end": stamp(data["ready"]["time_s"][-1]),
                         "first_last_proxy": {k: label[k] for k in ("first_price", "first_price_time", "final_price", "final_price_time", "basis", "book_sha256")}})
        print(scene+" 保存D07照合済み", flush=True)
    raw_manifest = read(ROOT/"work/ma153/data/入力目録153.json")
    raw_checks = []
    for scene in raw_manifest["sessions"]:
        for source in scene["fingerprints"]:
            path = Path(source["path"])
            stat = path.stat()
            unchanged = stat.st_size == source["bytes"] and stat.st_mtime_ns == source["mtime_ns"]
            raw_checks.append({"path": source["path"], "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                               "prior_sha256": source["sha256"], "metadata_unchanged_since_153": unchanged})
    available = {symbol: sorted(path.name for path in (ROOT.parent/"JP_OSE_Data/future"/symbol).iterdir() if path.is_dir()) for symbol in ("NK225", "TOPIX")}
    record = {"financial_replays": 0, "API": 0, "saved_method": "00145保存D07・費用0経路", "sessions": manifest,
              "raw_153_manifest": sha(ROOT/"work/ma153/data/入力目録153.json"), "raw_metadata_checks": raw_checks,
              "saved_directories_now": available, "not_in_145": {symbol: sorted(set(items)-set(previous)) for symbol, items in available.items()},
              "current_go_is_not_proven_identical": True,
              "note": "145は不正BBO除外済みcache・旧Python模型。現Go原板の状態更新・境界・時刻切替と同値と称さない。現在の原資料は153時点の全文SHAと今回size/mtimeを照合。"}
    (HERE/"保存結果と再利用目録154.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    groups = {"全体": summarize(parents, lots)}
    for owner in ROLES:
        groups[owner] = summarize([p for p in parents if p["owner"] == owner], [lot for lot in lots if lot["owner"] == owner])
        for kind in ("Day", "Night"):
            groups[owner+"_"+kind] = summarize([p for p in parents if p["owner"] == owner and p["kind"] == kind], [lot for lot in lots if lot["owner"] == owner and lot["session"].endswith("_"+kind)])
    report = {"definition": "保存D07の全約定固定。利益/損失は完結親、個別玉の利益/損失も分離。最高清算価値と利益返しは未来を使う診断値で実現可能額ではない。少枚数は実保有1〜2枚。追加担当Aと保有中の追撃を区別。",
              "sessions": sessions, "summary": groups, "parents": parents, "lots": lots,
              "worst_givebacks": sorted(parents, key=lambda p: p["giveback_to_final"], reverse=True)[:12],
              "small_positive_to_loss": sorted((p for p in parents if p["small_peak_equity"] and p["small_peak_equity"]["value"] > 0 and p["net"] < 0), key=lambda p: p["small_peak_equity"]["value"]-p["net"], reverse=True),
              "fast_additional_losses": sorted((lot for lot in lots if lot["type"] == "保有中の追撃" and lot["net"] < 0 and lot["seconds_to_final_close"] <= 300), key=lambda lot: lot["net"]),
              "script": sha(Path(__file__)), "source_account": sha(OLD/"役割分離の全場結果145.json")}
    (HERE/"保存D07の利益返しと追加玉154.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"state": "全会計一致", "summary": groups, "unchanged_raw": sum(x["metadata_unchanged_since_153"] for x in raw_checks), "raw_count": len(raw_checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
