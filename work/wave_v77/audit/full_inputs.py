"""60口座の価格有限性と三遅延の全価格窓・直前レンジ・OFIを独立照合する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import pickle

import numpy as np

from independent_account import HERE, save
from board_oracle import FIELDS, snapshot, digest
from price_oracle import market, compare


ROOT = HERE.parents[2]
INPUTS = HERE.parent/"inputs"


def load(path: Path) -> object:
    """機能: 準備済み資料だけを読み取る。

    引数: path(Path)。返り値: 内容(object)。原本・APIを取得しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf-8"))


def material(meta: dict) -> tuple:
    """機能: 旧58と新2口座を、指紋検証した準備資料から接続する。

    引数: meta(dict)。返り値: ready/book/snapshot(tuple)。
    """
    values = []
    for kind, extra in (("ready", "extra_inputs.pkl"), ("features", "extra_features.pkl"), ("snapshots", "extra_snapshots.pkl")):
        merged = {}
        for name in meta["input_paths"][kind]:
            item = load(ROOT/name)
            assert not set(merged)&set(item)
            merged.update(item)
        item = load(INPUTS/extra)
        assert not set(merged)&set(item)
        merged.update(item)
        values.append(merged)
    assert len(values[0]) == 60 and set(values[0]) == set(values[1]) == set(values[2])
    return tuple(values)


def account_basics(key: tuple, ready: dict, book: dict, snap: dict) -> int:
    """機能: 全行有限mid契約・原本対応・即時板の恒等式を確認する。

    引数: key(tuple)、ready/book/snap(dict)。返り値: 全行数(int)。
    """
    assert len(ready["seq"]) and np.all(np.diff(ready["seq"]) > 0) and np.all(np.diff(ready["time_s"]) >= 0)
    for field in ("seq", "time_s"):
        np.testing.assert_array_equal(book[field], ready[field]); np.testing.assert_array_equal(snap[field], ready[field])
    for field in ("bid", "ask", "mid", "last"):
        assert np.isfinite(book[field]).all(), (key, field, "非有限価格")
    q = snap["valid"]
    best = (book["bid_qty"]-book["ask_qty"])/(book["bid_qty"]+book["ask_qty"])
    np.testing.assert_allclose(snap["best_imbalance"][q], best[q], atol=1.e-12, rtol=0)
    np.testing.assert_allclose(snap["microprice"][q], book["mid"][q]+best[q]*(book["ask"][q]-book["bid"][q])/2, atol=1.e-9, rtol=0)
    np.testing.assert_allclose(snap["depth_imbalance"][q],
        (snap["weighted_bid_qty"][q]-snap["weighted_ask_qty"][q])/(snap["weighted_bid_qty"][q]+snap["weighted_ask_qty"][q]), atol=1.e-12, rtol=0)
    assert np.isfinite(np.column_stack([snap[f][q] for f in FIELDS])).all()
    return len(ready["seq"])


def one_market(job: tuple, ready: dict, book: dict, snap: dict) -> tuple:
    """機能: 一市場一遅延の全格子・5窓・2レンジ・2フローを独立照合する並列単位。

    引数: job(tuple)、ready/book/snap(dict)。返り値: 口座・遅延・独立特徴・比較数(tuple)。
    """
    delay, key, grid, saved = job
    expected = market(grid, delay, ready[key], book[key], snap[key])
    checks = compare(saved, expected)
    return delay, key, expected, checks


def coverage(session: str, delay: int, grid: np.ndarray, markets: dict) -> dict:
    """機能: 独立特徴から両市場の可用性と実観測秒数を再集計する。

    引数: session(str)、delay(int)、grid(ndarray)、markets(dict)。返り値: 十分性の1行(dict)。
    """
    a, b = (markets[s] for s in ("TOPIX", "NK225"))
    row = dict(session=session, delay=delay, grid_count=len(grid), both_current=int((a["current"]["valid"]&b["current"]["valid"]).sum()), windows={}, ranges={}, flow={})
    for window in (30, 60, 180, 300, 600):
        x, y = a["windows"][window], b["windows"][window]
        valid = x["source_valid"]&y["source_valid"]
        row["windows"][str(window)] = dict(both_source_valid=int(valid.sum()),
            both_efficiency=int((valid&np.isfinite(x["efficiency"])&np.isfinite(y["efficiency"])).sum()),
            actual_seconds_TOP=[float(z) for z in np.quantile(x["actual_seconds"][valid], [0, .5, 1])] if valid.any() else None,
            actual_seconds_NK=[float(z) for z in np.quantile(y["actual_seconds"][valid], [0, .5, 1])] if valid.any() else None)
    for window in (60, 180):
        x, y = a["ranges"][window], b["ranges"][window]
        row["ranges"][str(window)] = dict(both_source_valid=int((x["source_valid"]&y["source_valid"]).sum()), both_position=int((x["position_valid"]&y["position_valid"]).sum()))
    for window in (15, 30):
        x, y = a["flow"][window], b["flow"][window]
        row["flow"][str(window)] = dict(both_source_valid=int((x["source_valid"]&y["source_valid"]).sum()),
            both_valid_min3=int((x["valid"]&y["valid"]&(x["nonzero_ofi_count"] >= 3)&(y["nonzero_ofi_count"] >= 3)).sum()))
    return row


def main() -> None:
    """機能: 全60口座、三遅延の特徴全点・生板サンプル・十分性を検算する。

    引数: なし。返り値: なし(None)。損益結果を参照しない。
    """
    meta = load(INPUTS/"metadata.json")
    assert all(digest(ROOT/p) == expected for p, expected in meta["reused_input_hashes"].items())
    assert all(digest(INPUTS/p) == expected for p, expected in meta["hashes"].items())
    ready, book, snap = material(meta)
    total = sum(account_basics(k, r, book[k], snap[k]) for k, r in ready.items())
    sample_count = 0
    for account in meta["extra_raw_audit"]:
        key = account["session"], account["symbol"]
        for sample in account["raw_samples"]:
            i, raw = sample["i"], sample["raw"]
            assert ready[key]["seq"][i] == sample["seq"]
            assert ready[key]["time_s"][i] == datetime.fromisoformat(raw["CurrentPriceTime"]).timestamp()
            expected = snapshot(raw, ready[key]["tick"])
            assert snap[key]["valid"][i] == expected["valid"]
            for f in FIELDS:
                np.testing.assert_allclose(snap[key][f][i], expected[f], atol=1.e-9, rtol=1.e-10, equal_nan=True)
            sample_count += 1
    saved_coverage = {(r["delay"], r["session"]): r for r in load(INPUTS/"入力十分性.json")["rows"]}
    checks = grid_points = coverage_rows = 0
    for delay in (1, 5, 15):
        grids = load(INPUTS/f"grids_delay{delay}.pkl")
        jobs = []
        for session, s in grids.items():
            reference = ready[(session, "TOPIX")]
            expected_grid = np.arange(reference["start"]+300., reference["limit"]-60.+1.e-6, 5.)
            np.testing.assert_array_equal(s["grid"], expected_grid)
            for symbol in ("TOPIX", "NK225"):
                jobs.append((delay, (session, symbol), s["grid"], s["markets"][symbol]))
        independent = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            tasks = [pool.submit(one_market, job, ready, book, snap) for job in jobs]
            for done, task in enumerate(as_completed(tasks), 1):
                _, key, expected, count = task.result()
                independent[key] = expected; checks += count; grid_points += len(expected["current"]["index"])
                if done % 20 == 0:
                    print(f"価格窓・レンジ独立監査 遅延{delay} {done}/60", flush=True)
        for session, s in grids.items():
            row = coverage(session, delay, s["grid"], {symbol: independent[(session, symbol)] for symbol in ("TOPIX", "NK225")})
            assert row == saved_coverage[(delay, session)], (delay, session, "十分性")
            coverage_rows += 1
        del grids, independent
    save(HERE/"全価格窓と直前レンジと新Night入力の独立監査.json", dict(合格=True,
        口座数=60, 既往口座数=58, 新Night口座数=2, 全対応行数=total, 全行mid有限契約確認=True,
        新Night添付原本sample数=sample_count, 遅延数=3, 市場格子数=180, 現在参照点数=grid_points,
        価格窓点数=grid_points*5, 直前レンジ点数=grid_points*2, OFI窓点数=grid_points*2,
        配列照合数=checks, 十分性照合行数=coverage_rows, 全準備指紋一致=True,
        方式="Python bisectの同時計先頭strictpast、TV/高安/品質/OFIは直接区間走査。元cumsum/dequeと別計算。",
        限界="prepared価格全行有限を検証。原本全再走査はせず、追加入力の添付原本・指紋を使用。共通受信時計はない。",
        原本取得=0, API取得=0, 実注文=0, 損益閲覧=0))
    print(json.dumps(dict(合格=True, 全対応行数=total, 市場格子数=180, 配列照合数=checks), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
