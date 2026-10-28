"""既存25夜の必要気配と保存D07注文を切り出す。新しい金融再生は実施しない。"""

import hashlib
import json
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JST = timezone(timedelta(hours=9))


def reference(path):
    """ファイルの内容指紋・バイト数・相対パスを返す。

    引数: path(Path)は既存入力又は専用出力。
    返り値: dictはpath、sha256、bytes。元資料は変更しない。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def split_orders(orders, times, quiet_start, resume):
    """新規親の所属で保存D07を前段・後段へ分離する。

    引数: orders(ndarray)は十列保存注文、times(ndarray)は元行時刻、quiet_start/resume(float)は既知の切替時刻。
    返り値: tuple[ndarray,ndarray]は前段・後段。全親完結、境界持越しなしを要求する。
    """
    pre_ids, post_ids = set(), set()
    for parent in dict.fromkeys(orders[:, 2]):
        rows = orders[orders[:, 2] == parent]
        opening = rows[rows[:, 7] == 1]
        assert len(opening)
        first = float(times[int(opening[0, 0])])
        if first < quiet_start:
            assert np.all(times[rows[:, 0].astype(np.int64)] < resume)
            pre_ids.add(parent)
        else:
            assert first >= resume
            assert np.all(times[rows[:, 1].astype(np.int64)] >= resume)
            post_ids.add(parent)
        assert int(sum(rows[rows[:, 7] == 1, 4])) == int(sum(rows[rows[:, 7] == 0, 4]))
    pre_mask = np.isin(orders[:, 2], list(pre_ids))
    post_mask = np.isin(orders[:, 2], list(post_ids))
    assert np.all(pre_mask ^ post_mask)
    return orders[pre_mask].copy(), orders[post_mask].copy()


def main():
    """既存入力の指紋を確認し、研究148向けの最小入力と全入力目録を生成する。

    引数: なし。
    返り値: None。既存夜間入力25場だけを保存し、現セッション・売買経路は作らない。
    """
    target = HERE / "inputs"
    target.mkdir(parents=True, exist_ok=True)
    original_manifest = ROOT / "work/research145_roles/保存入力145.json"
    source_manifest = json.loads(original_manifest.read_text(encoding="utf-8"))
    original = {row["session"]: row for row in source_manifest["sessions"]}
    records = []
    for cache in sorted((ROOT / "work/research145_engine/cache").glob("*_Night.pkl")):
        scene = cache.stem
        cache_ref = reference(cache)
        expected = original[scene]["cache"]
        assert cache_ref == expected, f"既存145入力指紋の不一致: {scene}"
        with cache.open("rb") as stream:
            _, original_data, _, _, original_label = pickle.load(stream)
        source_ready, source_quotes = original_data["ready"], original_data["quotes"]
        ready = {key: source_ready[key] for key in ("time_s", "start", "limit", "tick", "us_open", "session", "symbol", "seq")}
        quotes = {key: source_quotes[key] for key in ("bid", "ask", "quote_valid")}
        times = ready["time_s"]
        assert all(len(value) == len(times) for value in quotes.values())
        np.testing.assert_array_equal(source_quotes["time_s"], times)
        np.testing.assert_array_equal(source_quotes["seq"], ready["seq"])
        assert np.all(np.isfinite(times)) and np.all(np.diff(times) >= 0)
        quiet_start, resume = float(ready["us_open"]) - 900, float(ready["us_open"]) + 900
        order_path = ROOT / "work/research145_roles/orders" / f"{scene}.npz"
        result_path = ROOT / "work/research145_roles/results" / f"{scene}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        order_ref = reference(order_path)
        assert order_ref == result["orders"]
        with np.load(order_path) as source:
            baseline = source["D07"].copy()
        pre, post = split_orders(baseline, times, quiet_start, resume)
        # ----------------------------------------
        # 事後ラベルは会計専用。エンジンへ渡すdataには一切混ぜない。
        label = dict(original_label)
        label["source_direction"] = original_label.get("direction")
        change = float(label["change"])
        label["direction"] = "上昇" if change > 0 else "下落" if change < 0 else "横ばい"
        label["label_use"] = "事後の上昇下落別会計のみ。売買エンジンへ渡さない。"
        prepared = dict(data=dict(ready=ready, quotes=quotes), label=label, baseline=baseline, pre=pre, post=post)
        destination = target / f"{scene}.pkl"
        with destination.open("wb") as stream:
            pickle.dump(prepared, stream, protocol=pickle.HIGHEST_PROTOCOL)
        with destination.open("rb") as stream:
            verified = pickle.load(stream)
        for key in quotes:
            np.testing.assert_array_equal(verified["data"]["quotes"][key], source_quotes[key])
        np.testing.assert_array_equal(verified["data"]["ready"]["time_s"], times)
        for key in ("baseline", "pre", "post"):
            np.testing.assert_array_equal(verified[key], prepared[key])
        record = {"session": scene, "prepared": reference(destination), "source_cache": cache_ref, "source_orders": order_ref, "source_account": reference(result_path), "original_145_dependencies": original[scene], "rows": len(times), "orders": len(baseline), "pre_orders": len(pre), "post_orders": len(post), "time_nondecreasing": True, "original_seq_nondecreasing": bool(np.all(np.diff(ready["seq"]) >= 0)), "same_time_original_order_preserved": True, "original_index_preserved": True, "future_label_engine_excluded": True, "quiet_start": quiet_start, "resume": resume, "raw_nk_book_sha256": label.get("book_sha256"), "raw_nk_candle_sha256": label.get("candle_sha256"), "label_direction_display": label["direction"]}
        records.append(record)
    assert len(records) == 25
    # ----------------------------------------
    # 原資料全件照合は既存145の証跡を参照し、今回の読み取り範囲と区別する。
    provenance_paths = (
        original_manifest,
        ROOT / "work/research145_data/全保存資料の再照合145.json",
        ROOT / "work/research145_data/データ網羅性と再利用範囲145.md",
        ROOT / "work/research145_roles/役割別構成145.json",
        ROOT / "work/research145_roles/new_addon_manifest145.json",
        HERE / "audit/D07保存会計と切替境界.json",
    )
    manifest = {
        "created_at": datetime.now(JST).isoformat(), "purpose": "入力切出しと保存注文分離のみ。新規金融再生は0件。",
        "market_replays": 0, "new_decisions": 0, "API_calls": 0, "real_orders": 0,
        "schema": {"data": {"ready": ["time_s", "start", "limit", "tick", "us_open", "session", "symbol", "seq"], "quotes": ["bid", "ask", "quote_valid"]}, "label": "事後会計用。旧directionの文字化けはchangeの符号から表示だけ補完しsource_directionへ原文を保存。", "baseline": "元D07全約定[N,10]", "pre": "US-15分前に始まりUS+15分前に全返済した親", "post": "全仮想D07を継続した際のUS+15分以降の親"},
        "quote_valid": "Buy1/Sell1価格と数量が有限、bid>0、ask>bid、双方Qty>0。気配差上限なし。TradingVolumeTimeは資格に使わない。元キャッシュを変更せず継承。",
        "clock": "元CurrentPriceTime。元添字と同一時計内の原行順を保持。独立受信時計を持たず、実際の受信時刻又は5秒遅延の厳密再現とは呼ばない。",
        "compose": "開場から完全仮想D07を運転し、US+15分後だけ実通知に採用する新仕様。新前段の実損益を仮想D07へ注入しない。新前段全玉と未約定の解消が後段開始条件。",
        "implementation": reference(Path(__file__).resolve()), "provenance": [reference(path) for path in provenance_paths], "sessions": records,
    }
    (HERE / "入力目録148.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": len(records), "rows": sum(row["rows"] for row in records), "prepared_bytes": sum(row["prepared"]["bytes"] for row in records), "all_original_seq_nondecreasing": all(row["original_seq_nondecreasing"] for row in records), "market_replays": 0, "manifest": "work/preus148/入力目録148.json"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
