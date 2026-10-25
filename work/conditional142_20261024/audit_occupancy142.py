"""保存注文の保有時間の和集合を検算し、公式セッション時間に対する保有率を求める。"""

from __future__ import annotations

import hashlib
import json
import pickle
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "work/aggressive140_20261024"


def read(path: Path) -> dict | list:
    """保存JSONを読み取る。

    引数: path(Path) は対象資料。
    返り値: dict|list は読み込んだ内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    """内容指紋を計算する。

    引数: path(Path) は読み取り対象。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def occupancy(orders: np.ndarray, times: np.ndarray, session: str) -> dict:
    """各玉の実数量から、何らかの建玉を保有した秒数を一度だけ数える。

    引数: orders(ndarray[N,10])、times(ndarray) は価格時計、session(str) は場ID。
    返り値: dict は和集合・買い・売り・両建て重複の時間と保有率。
    """
    day = session.endswith("_Day")
    duration = 420.0 if day else 780.0
    start = datetime.fromisoformat(session[:10] + ("T08:45:00+09:00" if day else "T17:00:00+09:00")).timestamp()
    end = start + duration * 60
    positions = {}
    intervals = defaultdict(list)
    long_count = short_count = 0
    previous = start
    union = long_time = short_time = hedged = parallel = quantity_seconds = 0.0
    for row in orders:
        stamp = float(times[int(row[0])])
        assert start <= stamp <= end and stamp >= previous, (session, stamp, previous)
        elapsed = stamp - previous
        quantity_seconds += (long_count + short_count) * elapsed
        if long_count + short_count:
            union += elapsed
        if long_count:
            long_time += elapsed
        if short_count:
            short_time += elapsed
        if long_count and short_count:
            hedged += elapsed
        owners = {int(key[0] >= 3_000_000) for key, value in positions.items() if value[1]}
        if len(owners) == 2:
            parallel += elapsed
        key, direction, quantity = (int(row[2]), int(row[8])), int(row[3]), int(row[4])
        if row[7] == 1:
            assert key not in positions, (session, "玉IDの重複", key)
            positions[key] = [direction, quantity, stamp]
            if direction == 1:
                long_count += quantity
            else:
                short_count += quantity
        else:
            assert key in positions, (session, "未保有返済", key)
            held = positions[key]
            assert held[0] == -direction and held[1] >= quantity, (session, "返済数量又は方向", key)
            held[1] -= quantity
            if held[0] == 1:
                long_count -= quantity
            else:
                short_count -= quantity
            if held[1] == 0:
                intervals[key[0]].append((held[2], stamp))
                del positions[key]
        assert long_count >= 0 and short_count >= 0
        previous = stamp
    assert not positions and long_count == 0 and short_count == 0, (session, "残玉")
    assert abs(union - (long_time + short_time - hedged)) < 1e-6
    assert 0 <= union <= duration * 60
    return dict(official_minutes=duration, held_minutes=union / 60, holding_ratio=union / (duration * 60),
                avg_held_quantity=quantity_seconds / (duration * 60),
                avg_quantity_while_held=quantity_seconds / union if union else 0.0,
                long_minutes=long_time / 60, short_minutes=short_time / 60, hedge_overlap_minutes=hedged / 60,
                core_addon_overlap_minutes=parallel / 60)


def main() -> None:
    """第一巡の全方法を集計し、過去会計の保有時間と照合する。

    引数: なし。
    返り値: None。保存済み注文の読取りと時刻集計だけを行う。
    """
    saved = read(HERE / "結果142.json")
    compared = read(HERE / "比較集計142.json")
    expected = {(row["symbol"], row["session"], row["method"]): row for row in saved["rows"]}
    packets = {item["session"]: item for manifest in (OLD / "known_manifest140.json", OLD / "inputs/input_manifest.json") for item in read(manifest)["packets"]}
    cache = {(item["symbol"], item["session"]): item for item in saved["cache"]}
    assert len(packets) == 50 and len(cache) == 100
    rows, provenance = [], []
    for session, reference in sorted(packets.items()):
        packet_path = ROOT / reference["path"]
        assert sha(packet_path) == reference["sha256"], packet_path
        packet = pickle.loads(packet_path.read_bytes())
        for symbol in ("NK225", "TOPIX"):
            time = packet["inputs"][session, symbol]["time_s"]
            entry = cache[symbol, session]
            source = ROOT / entry["path"]
            assert sha(source) == entry["sha256"], source
            provenance.append(dict(symbol=symbol, session=session, packet=reference, measurement=entry))
            with np.load(source) as data:
                for method in data.files:
                    measured = occupancy(data[method], time, session)
                    old = expected[symbol, session, method]
                    assert abs(old["held_minutes"] - measured["held_minutes"]) < 1e-8, (symbol, session, method, old["held_minutes"], measured)
                    rows.append(dict(symbol=symbol, session=session, method=method, kind="Day" if session.endswith("_Day") else "Night", net=old["net"], entries=old["entries"], **measured))
        del packet
    # ----------------------------------------
    # 逐次選択は保存された当該場の選択先の時間を採用する。新しい方式選択はしない。
    mapping = {(row["symbol"], row["session"], row["method"]): row for row in rows}
    selection = {(row["symbol"], row["session"]): row for row in read(HERE / "逐次選択142.json")}
    for old in compared["rows"]:
        if old["method"] != "W01":
            continue
        chosen = old["component_method"]
        assert chosen == selection[old["symbol"], old["session"]]["chosen"]
        source = mapping[old["symbol"], old["session"], chosen]
        assert abs(source["held_minutes"] - old["held_minutes"]) < 1e-8
        rows.append(dict(source, method="W01", component_method=chosen))
    groups = defaultdict(list)
    for row in rows:
        groups[row["symbol"], row["method"]].append(row)
    summary = []
    for (symbol, method), values in sorted(groups.items()):
        assert len(values) == 50, (symbol, method, len(values))
        for kind in ("all", "Day", "Night"):
            members = [row for row in values if kind == "all" or row["kind"] == kind]
            denominator = sum(row["official_minutes"] for row in members)
            summary.append(dict(symbol=symbol, method=method, kind=kind, sessions=len(members),
                mean_holding_ratio=float(np.mean([row["holding_ratio"] for row in members])),
                time_weighted_holding_ratio=sum(row["held_minutes"] for row in members) / denominator,
                held_minutes=sum(row["held_minutes"] for row in members), official_minutes=denominator,
                min_holding_ratio=min(row["holding_ratio"] for row in members), max_holding_ratio=max(row["holding_ratio"] for row in members),
                sessions_at_least_50pct=sum(row["holding_ratio"] >= .5 for row in members),
                hedge_overlap_minutes=sum(row["hedge_overlap_minutes"] for row in members),
                core_addon_overlap_minutes=sum(row["core_addon_overlap_minutes"] for row in members),
                mean_held_quantity=float(np.mean([row["avg_held_quantity"] for row in members])),
                time_weighted_held_quantity=sum(row["avg_held_quantity"] * row["official_minutes"] for row in members) / denominator,
                no_trade_sessions=sum(row["entries"] == 0 for row in members), net=sum(row["net"] for row in members)))
    report = dict(新金融再生=0, API取得=0, 定義={"公式時間": "デイ08:45～15:45の420分、ナイト17:00～翌06:00の780分", "各場保有率": "実約定後に一玉以上を保有する時間の和集合÷公式時間。売り買い同時保有も一度だけ数える。", "全場平均": "各場保有率の算術平均。無取引は0。", "時間加重": "全場の保有時間合計÷全場の公式時間合計。夜間は分母時間が長い。", "時計制約": "保存価格時計基準。実受信時計による保有秒数ではない。", "深夜の扱い": "無動意区間は除外しない。活動区間基準の保有率は別の未測定指標。"},
                  会計数=len(rows), 元会計保有時間の一致=True, 両建て控除の和集合検算=True, summary=summary, rows=rows, provenance=provenance,
                  結果SHA256=sha(HERE / "結果142.json"), 比較集計SHA256=sha(HERE / "比較集計142.json"))
    (HERE / "全手法の保有率独立集計142.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 第一巡の保有率", "", "保存全注文から玉ごとに保有を復元し、売り買い・主担当と追加担当の重複時間を一度だけ数えた。元のheld_minutesはこの和集合と全件一致した。新しい売買再生は0回。", "", "デイ420分・ナイト780分を公式時間として使用。全場平均は各場の率を等しく平均し、時間加重率は保有分合計を公式分合計で割る。深夜無動意を除いた活動区間率は未測定。時刻は保存価格時計基準。", "", "|商品|手法|全50場平均|デイ平均|ナイト平均|時間加重|50%以上の場数|", "|---|---|---:|---:|---:|---:|---:|"]
    summary_map = {(row["symbol"], row["method"], row["kind"]): row for row in summary}
    for (symbol, method), values in sorted(groups.items()):
        if method.startswith("A_"):
            continue
        all_row, day, night = [summary_map[symbol, method, kind] for kind in ("all", "Day", "Night")]
        lines.append(f'|{symbol}|{method}|{all_row["mean_holding_ratio"]:.1%}|{day["mean_holding_ratio"]:.1%}|{night["mean_holding_ratio"]:.1%}|{all_row["time_weighted_holding_ratio"]:.1%}|{all_row["sessions_at_least_50pct"]}/50|')
    lines.extend(["", "追加担当単独A_を含む全会計、場別保有率、同方向・逆方向の重複分は[独立集計JSON](全手法の保有率独立集計142.json)に保存した。個々の場で50%以上を必須とする判定はしていない。保有率が高いことだけを収益の優位性とはしない。"])
    (HERE / "第一巡の保有率142.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    visible = [row for row in summary if row["kind"] == "all" and not row["method"].startswith("A_")]
    print(json.dumps(dict(会計数=len(rows), 元保有時間一致=True, 比較=visible), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
