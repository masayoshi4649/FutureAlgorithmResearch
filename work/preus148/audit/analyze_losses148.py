"""P01/P06の保存赤字取引と確認時計を原板へ照合する。新しい売買再生はしない。"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import engine

JST = timezone(timedelta(hours=9))
REASONS = {1: "方向一致の新規", 2: "順行後の追加", 3: "初期100pt損切り", 4: "赤字玉の方向反証", 5: "利益到達後トレール", 6: "米国開始前の返済"}


def clock(value):
    """UNIX秒を日本時間へ変換する。

    引数: value(float)は時刻。
    返り値: strは日本時間ISO表記。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def gap_summary(times):
    """気配間の価格時計差を集計する。

    引数: times(ndarray)は正常気配の価格時刻。
    返り値: dictは閾値別の件数・比率・その間の時計経過。受信障害を推定しない。
    """
    gaps = np.diff(times)
    positive = gaps > 0
    elapsed = float(gaps.sum())
    return {"transitions": len(gaps), "clock_advances": int(positive.sum()), "elapsed_seconds": elapsed,
            "thresholds": {str(limit): {"count": int((gaps > limit).sum()), "all_transition_fraction": float((gaps > limit).mean()),
            "positive_clock_fraction": float((gaps > limit).sum() / max(1, positive.sum())),
            "clock_span_seconds": float(gaps[gaps > limit].sum()), "excess_seconds": float(np.maximum(0, gaps - limit).sum()),
            "excess_fraction": float(np.maximum(0, gaps - limit).sum() / elapsed) if elapsed else 0.}
            for limit in (5, 15, 30, 120)}}


def clock_episodes(data):
    """方向が一致する観測区間と価格時計差による確認不能を診断する。

    引数: data(dict)は既存の正常気配入力。
    返り値: dictは方向区間数と確認可能区間数。保有・連敗・冷却を見ないため失注件数ではない。
    """
    prepared = engine.prepare(data)
    times = prepared["times"]
    mask = prepared["valid"] & (times >= data["ready"]["start"]) & (times < data["ready"]["us_open"] - 900)
    indices = np.flatnonzero(mask)
    if not len(indices):
        return {"runs": []}
    t = times[indices]
    bar = prepared["bar_index"][indices]
    d = np.zeros(len(indices), np.int8)
    known = bar >= 0
    safe_bar = np.maximum(0, bar)
    fast = prepared["bars"][safe_bar, 1]
    slow = prepared["bars"][safe_bar, 2]
    known &= np.isfinite(fast) & np.isfinite(slow) & (t - prepared["bars"][safe_bar, 8] <= 120)
    d[known & (fast >= 4) & (slow >= 1)] = 1
    d[known & (fast <= -4) & (slow <= -1)] = -1
    boundaries = np.r_[0, np.flatnonzero(d[1:] != d[:-1]) + 1, len(d)]
    runs = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        if d[a] == 0:
            continue
        elapsed = float(t[b - 1] - t[a])
        max_span = {}
        for limit in (5, 15, 30, 120):
            cuts = np.r_[a, a + np.flatnonzero(np.diff(t[a:b]) > limit) + 1, b]
            max_span[str(limit)] = float(max(t[z - 1] - t[y] for y, z in zip(cuts[:-1], cuts[1:])))
        runs.append({"start": clock(t[a]), "end": clock(t[b - 1]), "direction": int(d[a]), "seconds": elapsed, "max_unbroken_seconds": max_span})
    return {"candidate_runs": len(runs), "confirmation": {str(confirm): {"duration_sufficient": sum(r["seconds"] >= confirm for r in runs),
            "possible_by_gap_threshold": {str(limit): sum(r["max_unbroken_seconds"][str(limit)] >= confirm for r in runs) for limit in (5, 15, 30, 120)},
            "blocked_only_by_5s": sum(r["seconds"] >= confirm and r["max_unbroken_seconds"]["5"] < confirm for r in runs)} for confirm in (15, 30)}, "runs": runs}


def ticket_analysis(data, orders, diagnostics):
    """保存約定の各玉について、入口の傾き・その前後・保有中最高最低を計測する。

    引数: data(dict)、orders(ndarray)、diagnostics(list[dict])は既存結果。
    返り値: tuple[list,set]は玉別記録と原板照合に必要な元連番。
    """
    r, q = data["ready"], data["quotes"]
    times = r["time_s"]
    good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
    mids = (q["bid"] + q["ask"]) / 2
    decisions = {(int(row["parent"]), int(row["ticket"]), int(row["reason_code"])): row for row in diagnostics if row["reason_code"] in (1, 2)}
    result, raw_indices = [], set()
    for opening in orders[orders[:, 7] == 1]:
        fill, decided, parent, side, qty = map(int, opening[:5])
        uid, px = int(opening[8]), float(opening[5])
        close_rows = orders[(orders[:, 2] == parent) & (orders[:, 8] == uid) & (orders[:, 7] == 0)]
        assert len(close_rows) == 1
        close = close_rows[0]
        end, close_decision = int(close[0]), int(close[1])
        liquidation = q["bid"] if side > 0 else q["ask"]
        valid = np.flatnonzero(good[fill:end + 1]) + fill
        gains = side * (liquidation[valid] - px)
        best, worst = int(valid[np.argmax(gains)]), int(valid[np.argmin(gains)])
        past = {}
        for seconds in (30, 60, 120, 300):
            ix = int(np.searchsorted(times, times[decided] - seconds, side="right") - 1)
            past[str(seconds)] = float(side * (mids[decided] - mids[ix])) if ix >= 0 else None
        diagnostic = decisions[parent, uid, int(opening[6])]
        details = {"parent": parent, "ticket": uid, "side": "買い" if side > 0 else "売り", "qty": qty,
                   "entry": clock(times[fill]), "entry_price": px, "exit": clock(times[end]), "exit_price": float(close[5]),
                   "holding_seconds": float(times[end] - times[fill]), "net": side * (float(close[5]) - px) * qty * 100,
                   "exit_reason": REASONS[int(close[6])], "entry_reason": REASONS[int(opening[6])],
                   "entry_fast_pt_per_min": diagnostic["fast_speed"], "entry_slow_pt_per_min": diagnostic["slow_speed"], "entry_acceleration": diagnostic["acceleration"],
                   "signed_move_before_entry": past, "mfe_pt": float(np.max(gains)), "mae_pt": float(np.min(gains)),
                   "mfe_time": clock(times[best]), "mae_time": clock(times[worst]),
                   "entry_fill_slippage_pt": float(side * (px - (q["ask"][decided] if side > 0 else q["bid"][decided]))),
                   "raw_seq": {"entry_decision": int(r["seq"][decided]), "entry_fill": int(r["seq"][fill]), "mfe": int(r["seq"][best]), "mae": int(r["seq"][worst]), "exit_decision": int(r["seq"][close_decision]), "exit_fill": int(r["seq"][end])}}
        for seconds in (60, 300):
            future = np.flatnonzero(good & (times >= times[fill]) & (times <= times[fill] + seconds))
            future_gains = side * (liquidation[future] - px)
            details[f"future_{seconds}s"] = {"best_pt": float(np.max(future_gains)), "worst_pt": float(np.min(future_gains))}
        raw_indices.update(details["raw_seq"].values())
        result.append(details)
    return result, raw_indices


def raw_records(scene, indices, data):
    """対象連番の原板を読み、キャッシュの気配と照合する。

    引数: scene(str)、indices(set[int])、data(dict)。
    返り値: dictは原板、行指紋、ファイル内容指紋。全原資料は読み取り専用。
    """
    source = ROOT.parent / "JP_OSE_Data/future/NK225" / scene / "book.jsonl"
    digest, rows = hashlib.sha256(), {}
    seq_map = {int(seq): i for i, seq in enumerate(data["ready"]["seq"])}
    with source.open("rb") as stream:
        for seq, line in enumerate(stream):
            digest.update(line)
            if seq not in indices:
                continue
            obj = json.loads(line)
            i = seq_map[seq]
            assert float(obj["Buy1"]["Price"]) == data["quotes"]["bid"][i]
            assert float(obj["Sell1"]["Price"]) == data["quotes"]["ask"][i]
            rows[str(seq)] = {"seq0": seq, "line_sha256": hashlib.sha256(line).hexdigest(), "fields": {key: obj.get(key) for key in ("CurrentPrice", "CurrentPriceTime", "TradingVolume", "TradingVolumeTime", "Buy1", "Buy2", "Buy3", "Sell1", "Sell2", "Sell3", "OverSellQty", "UnderBuyQty")}}
    assert len(rows) == len(indices)
    return {"path": str(source), "sha256": digest.hexdigest(), "rows": rows}


def main():
    """最悪場の約定原因と価格時計の確認制約を保存する。

    引数: なし。
    返り値: None。保存結果・価格系列の事後診断のみで、新規市場判断は生成しない。
    """
    report = json.loads((WORK / "report.json").read_text(encoding="utf-8"))
    selected = {method["id"]: sorted(method["pre_rows"], key=lambda row: row["net"])[:3] for method in report["methods"] if method["id"] in ("P01", "P06")}
    case_map = {}
    for method, rows in selected.items():
        for row in rows:
            case_map.setdefault(row["session"], []).append((method, row))
    losses, timing = [], []
    for path in sorted((WORK / "inputs").glob("*_Night.pkl")):
        payload = pickle.loads(path.read_bytes())
        data = payload["data"]
        scene = path.stem
        t = data["ready"]["time_s"]
        valid = data["quotes"]["quote_valid"]
        pre = valid & (t >= data["ready"]["start"]) & (t < data["ready"]["us_open"] - 900)
        timing.append({"session": scene, "partial": bool(payload.get("partial", False)), "full": gap_summary(t[valid]), "pre": gap_summary(t[pre]), "direction_intervals": clock_episodes(data)})
        if scene not in case_map:
            continue
        diagnostics = json.loads((WORK / "results" / f"{scene}.json").read_text(encoding="utf-8"))
        all_seq, group = set(), []
        with np.load(WORK / "orders" / f"{scene}.npz") as source:
            for method, row in case_map[scene]:
                tickets, seq = ticket_analysis(data, source[method], diagnostics[method]["diagnostics"])
                all_seq.update(seq)
                group.append({"method": method, "session": scene, "net": row["net"], "entries": row["entries"], "parents": row["parent_count"], "exit_reasons": dict(Counter(ticket["exit_reason"] for ticket in tickets)), "tickets": tickets})
        evidence = raw_records(scene, all_seq, data)
        assert evidence["sha256"] == payload["label"]["book_sha256"]
        for item in group:
            item["raw_evidence_file"] = f"raw_{scene}.json"
            losses.append(item)
        (HERE / f"raw_{scene}.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "P01とP06の最悪3夜.json").write_text(json.dumps(losses, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "正常気配の時計差と方向確認区間.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# P01とP06の最悪3夜の保存取引診断", "", "取引を変更せず、保存約定と原板を照合した。MFEは保有中に返済気配で得られた最大幅。確認時計の区間数は失注数や追加売買利益ではない。", ""]
    for item in losses:
        lines.extend([f"## {item['method']} {item['session']} 前段{item['net']:,.0f}円", "", "|新規|方向/枚数|価格|返済|価格|損益円|MFE pt|MAE pt|5分/10分傾き|理由|", "|---|---|---:|---|---:|---:|---:|---:|---|---|"])
        for t in item["tickets"]:
            lines.append(f"|{t['entry'][11:19]}|{t['side']}/{t['qty']}|{t['entry_price']:g}|{t['exit'][11:19]}|{t['exit_price']:g}|{t['net']:,.0f}|{t['mfe_pt']:g}|{t['mae_pt']:g}|{t['entry_fast_pt_per_min']:.1f}/{t['entry_slow_pt_per_min']:.1f}|{t['exit_reason']}|")
        lines.append("")
    (HERE / "P01とP06の最悪3夜.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"worst_cases": len(losses), "raw_files": len(case_map), "timing_sessions": len(timing), "new_financial_replays": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
