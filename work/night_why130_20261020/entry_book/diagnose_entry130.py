"""保存された全入口に対し、原板の公表活動を同じ窓で測る。売買再生は行わない。"""

import hashlib
import json
import pickle
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/daynight128_20261020"
PREV = ROOT / "work/visual_pdca129_20261020"
sys.path.insert(0, str(HERE.parent))
from common130 import read, reference


def save(path: Path, value: dict) -> None:
    """
    機能: 当調査の診断結果を日本語JSONで保存する。
    引数: path(Path)は出力先、value(dict)は結果。
    返り値: None。過去調査と原データは変更しない。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf8")


def clean(value: object) -> object:
    """
    機能: 既存診断に含まれる非有限値を欠測のnullとして保存する。
    引数: value(object)は入れ子の結果。
    返り値: objectはJSONで表現できる同じ内容。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def number(value: object) -> float:
    """
    機能: 原板数値を欠測を保って読み込む。
    引数: value(object)は公表値。
    返り値: floatは数値又はNaN。
    """
    return float(value) if isinstance(value, (float, int)) else np.nan


def rows() -> list[dict]:
    """
    機能: 比較する保存親を一つの母集団にまとめる。
    引数: なし。
    返り値: list[dict]はN36とNV25の完結親。
    """
    a = read(PREV / "night/夜間図の索引と全入口の当時特徴.json")["rows"]
    b = read(PREV / "night/強逆流準備破棄の全親差分と新準備.json")["rows"]
    return [r for r in a if r["method"] == "N36"] + [r for r in b if r["method"] == "NV25"]


def extract(scene: str, symbol: str, selected: list[dict], rd: dict) -> dict:
    """
    機能: 全入口の前後の原行だけを抽出し、十段板と公表出来高を保存する。
    引数: scene(str)、symbol(str)、selected(list[dict])、rd(dict)は対象と保存入力。
    返り値: dictは原行順の数値配列。未来行は図示のみで入口特徴に使わない。
    """
    cache = HERE / "cache" / f"{symbol}_{scene}.npz"
    if cache.exists():
        with np.load(cache) as loaded:
            return {k: loaded[k] for k in loaded.files}
    wanted = np.zeros(len(rd["seq"]), dtype=bool)
    ts = rd["time_s"]
    for row in selected:
        i = row["decision_row"]
        left = max(0, int(np.searchsorted(ts, ts[i] - 121., side="left")) - 1)
        right = min(len(ts), int(np.searchsorted(ts, ts[i] + 181., side="right")) + 1)
        wanted[left:right] = True
    idx = np.flatnonzero(wanted)
    seq_to_row = {int(rd["seq"][j]): int(j) for j in idx}
    seqmax = max(seq_to_row)
    source = ROOT / "book" / symbol / f"{scene}.jsonl"
    out = {k: [] for k in ("row", "seq", "time", "last", "volume", "vtime", "prices", "qty")}
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for seq, line in enumerate(handle):
            if seq > seqmax:
                break
            if seq not in seq_to_row:
                continue
            raw = json.loads(line)
            j = seq_to_row[seq]
            digest.update(line)
            assert raw["CurrentPrice"] == rd["last"][j]
            assert datetime.fromisoformat(raw["CurrentPriceTime"]).timestamp() == ts[j]
            out["row"].append(j)
            out["seq"].append(seq)
            out["time"].append(ts[j])
            out["last"].append(number(raw.get("CurrentPrice")))
            out["volume"].append(number(raw.get("TradingVolume")))
            vt = raw.get("TradingVolumeTime")
            out["vtime"].append(datetime.fromisoformat(vt).timestamp() if vt else np.nan)
            levels = [raw.get(f"{side}{n}", {}) for side in ("Buy", "Sell") for n in range(1, 11)]
            out["prices"].append([number(v.get("Price")) for v in levels])
            out["qty"].append([number(v.get("Qty")) for v in levels])
    data = {k: np.asarray(v, dtype=np.int64 if k in ("row", "seq") else np.float64) for k, v in out.items()}
    assert len(data["row"]) == len(idx)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **data)
    save(cache.with_suffix(".json"), dict(source=source.relative_to(ROOT).as_posix(),
        file_size=source.stat().st_size, selected_rows=len(idx), selected_lines_sha256=digest.hexdigest(),
        clock="CurrentPriceTime、受信時刻ではない", first_sequence=int(data["seq"][0]), last_sequence=int(data["seq"][-1])))
    return data


def window(data: dict, entry: dict, seconds: float, tick: float) -> dict:
    """
    機能: 判断行までの一定過去窓で表示数量・出来高・価格応答を測る。
    引数: data(dict)は原板、entry(dict)は保存親、seconds(float)は秒幅、tick(float)は呼値。
    返り値: dictは当時だけで算出できる観測特徴。売買方向代理は真の成行方向ではない。
    """
    at = int(np.searchsorted(data["row"], entry["decision_row"]))
    assert data["row"][at] == entry["decision_row"]
    t = data["time"][at]
    left = int(np.searchsorted(data["time"], t - seconds, side="left"))
    side = entry["side"]
    p, q, vol, last, ts = [data[k] for k in ("prices", "qty", "volume", "last", "time")]
    good = np.isfinite(p[:, 0]) & np.isfinite(p[:, 10]) & (p[:, 0] > 0.) & (p[:, 10] > p[:, 0])
    indices = np.arange(left, at + 1)
    anchor = max(0, left - 1)
    first = anchor if good[anchor] and data["row"][anchor] + 1 == data["row"][left] else next((j for j in indices if good[j]), None)
    if first is None:
        return dict(known=False)
    fixed = (p[first, 0] + p[first, 10]) / 2.
    flow, absflow = 0., 0.
    increments = upvotes = downvotes = ambiguous = 0.
    quote_changes = stale_quote_changes = zero_volume_quote_changes = 0
    fixed_qty = [[float(q[first, 0])], [float(q[first, 10])]]
    fixedprice = [p[first, 0], p[first, 10]]
    negative_volume = invalid = matched = positive_events = 0
    for j in indices:
        if not good[j]:
            invalid += 1
            continue
        for board in (0, 1):
            loc = np.where(p[j, board * 10:board * 10 + 10] == fixedprice[board])[0]
            fixed_qty[board].append(float(q[j, board * 10 + loc[0]]) if len(loc) else None)
        if j <= first or data["row"][j] != data["row"][j - 1] + 1 or not good[j - 1]:
            continue
        dv = vol[j] - vol[j - 1]
        changed = p[j, 0] != p[j - 1, 0] or p[j, 10] != p[j - 1, 10]
        if changed:
            quote_changes += 1
            stale_quote_changes += int(last[j] == last[j - 1])
            zero_volume_quote_changes += int(dv == 0.)
        if np.isfinite(dv) and dv < 0.:
            negative_volume += 1
        if np.isfinite(dv) and dv > 0.:
            positive_events += 1
            increments += dv
            # 約定方向そのものは公表されず、前行気配との位置関係を代理にする。
            if last[j] >= p[j - 1, 10]:
                upvotes += dv
            elif last[j] <= p[j - 1, 0]:
                downvotes += dv
            else:
                ambiguous += dv
        for board, sign in ((0, 1.), (1, -1.)):
            before = {p[j - 1, n]: q[j - 1, n] for n in range(board * 10, board * 10 + 10)
                      if np.isfinite(p[j - 1, n]) and np.isfinite(q[j - 1, n])}
            after = {p[j, n]: q[j, n] for n in range(board * 10, board * 10 + 10)
                     if np.isfinite(p[j, n]) and np.isfinite(q[j, n])}
            # 両行で表示された同一の絶対価格だけを比較。圏外はゼロにしない。
            for price in before.keys() & after.keys():
                change = after[price] - before[price]
                weight = 1. / (1. + abs(price - fixed) / tick)
                flow += sign * weight * change
                absflow += weight * abs(change)
                matched += 1
    fixed_summary = []
    for price, series in zip(fixedprice, fixed_qty):
        known = [v for v in series if v is not None]
        pairs = [(a, b) for a, b in zip(series[:-1], series[1:]) if a is not None and b is not None]
        fixed_summary.append(dict(price=float(price), visible=len(known), observations=len(series),
            first=known[0] if known else None, last=known[-1] if known else None,
            increases=sum(max(0., b - a) for a, b in pairs),
            decreases=sum(max(0., a - b) for a, b in pairs),
            connected_pairs=len(pairs)))
    vote = upvotes + downvotes
    return dict(known=True, rows=len(indices), normal_rows=int(good[indices].sum()), invalid=invalid,
        clock_seconds=float(t - ts[first]), volume_positive=increments, volume_negative_events=negative_volume,
        positive_volume_events=positive_events, buy_proxy=upvotes, sell_proxy=downvotes,
        ambiguous_volume=ambiguous, signed_volume_balance=side * (upvotes - downvotes) / vote if vote else None,
        signed_display_flow=side * flow, signed_display_balance=side * flow / absflow if absflow else None,
        display_change_absolute=absflow, matched_price_pairs=matched,
        quote_changes=quote_changes, unchanged_last_quote_changes=stale_quote_changes,
        unchanged_volume_quote_changes=zero_volume_quote_changes,
        signed_mid_change=float(side * ((p[at, 0] + p[at, 10]) - (p[first, 0] + p[first, 10])) / 2.),
        anchor_age=float(t - seconds - ts[first]),
        anchor_row=int(data["row"][first]),
        anchor_fresh=bool(ts[first] < t - seconds and 0. <= t - seconds - ts[first] <= 30.),
        fixed_initial_bid=fixed_summary[0], fixed_initial_ask=fixed_summary[1],
        final_last=float(last[at]), final_bid=float(p[at, 0]), final_ask=float(p[at, 10]),
        publication_volume_age=float(ts[at] - data["vtime"][at]) if np.isfinite(data["vtime"][at]) else None)


def group(records: list[dict], key: str, predicate) -> dict:
    """
    機能: 同じ観測条件で全親の勝ち負け内訳を記録する。
    引数: records(list[dict])、key(str)、predicate(callable)は母集団と条件。
    返り値: dictは除外仮定の既存結果分類であり、戦略再実行損益ではない。
    """
    selected = [r for r in records if predicate(r)]
    return dict(condition=key, count=len(selected), winning=sum(r["net"] > 0 for r in selected),
        losing=sum(r["net"] < 0 for r in selected), net=sum(r["net"] for r in selected),
        positive=sum(max(0., r["net"]) for r in selected), negative=sum(min(0., r["net"]) for r in selected),
        ids=[f'{r["session"]}/{r["number"]}' for r in selected])


def main() -> None:
    """
    機能: 全保存親の判断前原板を分類し、新研究の根拠を保存する。
    引数: なし。
    返り値: None。入力抽出・観測集計のみで金融再生はゼロ。
    """
    entries = rows()
    refs = {r["session"]: r for r in read(OLD / "入力準備.json")["packets"]}
    buckets = defaultdict(list)
    for entry in entries:
        buckets[(entry["session"], entry["symbol"])].append(entry)
    results = []
    for scene in sorted({key[0] for key in buckets}):
        packet = pickle.loads((ROOT / refs[scene]["path"]).read_bytes())
        for symbol in ("TOPIX", "NK225"):
            selected = buckets.get((scene, symbol), [])
            if not selected:
                continue
            rd = packet["inputs"][(scene, symbol)]
            data = extract(scene, symbol, selected, rd)
            for entry in selected:
                item = dict(entry)
                item["book30"] = window(data, entry, 30., rd["tick"])
                item["book120"] = window(data, entry, 120., rd["tick"])
                a, b = item["book30"], item["book120"]
                denom = b["volume_positive"] - a["volume_positive"]
                item["volume_rate_ratio"] = 3. * a["volume_positive"] / denom if denom > 0. else None
                results.append(item)
            print(scene, symbol, len(selected), "保存親の入口板を集計", flush=True)
    tables = []
    for method in ("N36", "NV25"):
        for symbol in ("TOPIX", "NK225"):
            population = [r for r in results if r["method"] == method and r["symbol"] == symbol]
            specs = [
                ("全親", lambda r: True),
                ("直前30秒の出来高方向代理が逆", lambda r: r["book30"]["signed_volume_balance"] is not None and r["book30"]["signed_volume_balance"] < 0.),
                ("直前120秒の出来高方向代理が逆", lambda r: r["book120"]["signed_volume_balance"] is not None and r["book120"]["signed_volume_balance"] < 0.),
                ("直前30秒の同一価格表示数量変化が逆", lambda r: r["book30"]["signed_display_balance"] is not None and r["book30"]["signed_display_balance"] < 0.),
                ("直前120秒の同一価格表示数量変化が逆", lambda r: r["book120"]["signed_display_balance"] is not None and r["book120"]["signed_display_balance"] < 0.),
                ("30秒出来高活動が直前90秒より低い", lambda r: r["volume_rate_ratio"] is not None and r["volume_rate_ratio"] < 1.),
                ("30秒出来高方向と同一価格表示数量が共に逆", lambda r: all(r["book30"][k] is not None and r["book30"][k] < 0. for k in ("signed_volume_balance", "signed_display_balance"))),
                ("120秒出来高方向と同一価格表示数量が共に逆", lambda r: all(r["book120"][k] is not None and r["book120"][k] < 0. for k in ("signed_volume_balance", "signed_display_balance"))),
                ("同じ30秒で気配順行かつ出来高方向代理は逆", lambda r: r["book30"]["anchor_fresh"] and r["book30"]["signed_mid_change"] > 0. and r["book30"]["signed_volume_balance"] is not None and r["book30"]["signed_volume_balance"] < 0.),
                ("同じ120秒で気配順行かつ出来高方向代理は逆", lambda r: r["book120"]["anchor_fresh"] and r["book120"]["signed_mid_change"] > 0. and r["book120"]["signed_volume_balance"] is not None and r["book120"]["signed_volume_balance"] < 0.),
            ]
            tables.append(dict(method=method, symbol=symbol, denominator=len(population),
                groups=[group(population, key, predicate) for key, predicate in specs]))
    save(HERE / "全入口の原板活動と固定価格表示数量.json", dict(
        passed=True, financial_replays=0, records=results, groups=tables,
        population_total=len(results), note="同じ親に対する観測分類。除外後の新しい売買経路は未評価。",
        clock_limit="CurrentPriceTimeを使用。原行順は保持するが、独立の受信時刻は無い。",
        missing="板十段から消えた価格は欠測扱い。数量減を約定又は取消しと断定しない。",
        source=reference(Path(__file__))))
    print(json.dumps(tables, ensure_ascii=False))


if __name__ == "__main__":
    main()
