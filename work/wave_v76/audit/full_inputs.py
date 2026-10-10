"""全保存即時板の恒等式・生サンプル・四短期窓を独立照合する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

from independent_account import save
from input_oracle import FIELDS, snapshot, market, compare, digest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("wave76_audit_input_core", HERE.parent / "inputs/core.py")
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)


def load(path: Path) -> object:
    """機能: 今回入力又は以前の固定準備資料だけを読み込む。

    引数: path(Path)。返り値: 保存内容(object)。原本とAPIを取得しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == ".pkl" else json.loads(path.read_text(encoding="utf-8"))


def raw_fixture() -> dict:
    """機能: 最良の買数量が厚い、全十段が揃った人工板一行を作る。

    引数: なし。返り値: 生板形式(dict)。
    """
    return {f"{side}{i}": dict(Price=100. - (i - 1) if side == "Buy" else 101. + (i - 1),
        Qty=6. if side == "Buy" else 2.) for side in ("Buy", "Sell") for i in range(1, 11)}


def snapshot_checks(raw: dict, tick: float, stored: dict | None = None) -> None:
    """機能: 被検査器と保存サンプルを、独立の板統計式へ照合する。

    引数: raw(dict)、tick(float)、stored(dict|None)。返り値: なし(None)。
    """
    expected = snapshot(raw, tick)
    for actual in [core.snapshot_values(raw, tick)] + ([stored] if stored is not None else []):
        assert actual["valid"] == expected["valid"]
        for field in FIELDS:
            value = actual[field]
            if value is None:
                value = np.nan
            np.testing.assert_allclose(value, expected[field], rtol=1.e-10, atol=1.e-9, equal_nan=True,
                err_msg=field)


def coverage_row(session: str, delay: int, grid: np.ndarray, markets: dict) -> dict:
    """機能: 独立計算した状態から、双方観測・無活動・実窓長を再集計する。

    引数: session(str)、delay(int)、grid(ndarray)、markets(dict)。返り値: 十分性行(dict)。
    """
    row = dict(session=session, delay=delay, grid_count=len(grid),
        both_snapshot=int((markets["TOPIX"]["current"]["valid"] & markets["NK225"]["current"]["valid"]).sum()))
    for window in (5, 15, 30, 60):
        a, b = [markets[s]["windows"][window] for s in ("TOPIX", "NK225")]
        source, flow = a["source_valid"] & b["source_valid"], a["valid"] & b["valid"]
        row[str(window)] = dict(both_source_valid=int(source.sum()), both_ofi_valid=int(flow.sum()),
            both_min3_ofi_events=int((flow & (a["nonzero_ofi_count"] >= 3) & (b["nonzero_ofi_count"] >= 3)).sum()),
            same_row_TOP=int(a["same_row"].sum()), same_row_NK=int(b["same_row"].sum()),
            zero_denominator_TOP=int(a["zero_ofi_denominator"].sum()), zero_denominator_NK=int(b["zero_ofi_denominator"].sum()),
            observed_seconds_TOP=np.quantile(a["actual_seconds"][source], [0, .5, 1]).tolist() if source.any() else None,
            observed_seconds_NK=np.quantile(b["actual_seconds"][source], [0, .5, 1]).tolist() if source.any() else None)
    return row


def main() -> None:
    """機能: 58即時板と174市場格子の全特徴・生174サンプルを独立照合する。

    引数: なし。返り値: なし(None)。損益結果と新戦略の選定を参照しない。
    """
    meta = load(HERE.parent / "inputs/入力と即時板特徴の仕様.json")
    ready, books = {}, {}
    for label, merged in (("ready", ready), ("book", books)):
        for name in meta["input_paths"][label]:
            assert digest(ROOT / name) == meta["input_SHA256"][name]
            data = load(ROOT / name)
            assert not set(merged) & set(data)
            merged.update(data)
    for name, expected in meta["hashes"].items():
        assert digest(HERE.parent / "inputs" / name) == expected
    snaps = load(HERE.parent / "inputs/snapshots.pkl")
    grids = load(HERE.parent / "inputs/grids.pkl")
    assert len(ready) == len(books) == len(snaps) == 58 and set(ready) == set(books) == set(snaps)
    snapshot_rows = raw_samples = artificial = 0
    for key, r in ready.items():
        f, snap = books[key], snaps[key]
        for field in ("seq", "time_s"):
            np.testing.assert_array_equal(snap[field], r[field])
        np.testing.assert_array_equal(snap["valid"], f["valid"])
        good = snap["valid"]
        assert np.isfinite(np.column_stack([snap[field][good] for field in FIELDS])).all()
        best = (f["bid_qty"] - f["ask_qty"]) / (f["bid_qty"] + f["ask_qty"])
        np.testing.assert_allclose(snap["best_imbalance"][good], best[good], atol=1.e-12, rtol=0)
        micro = f["mid"] + best * (f["ask"] - f["bid"]) / 2.
        np.testing.assert_allclose(snap["microprice"][good], micro[good], atol=1.e-9, rtol=0)
        np.testing.assert_allclose(snap["micro_offset_ticks"][good],
            best[good] * (f["ask"][good] - f["bid"][good]) / (2 * r["tick"]), atol=1.e-9, rtol=0)
        depth = (snap["weighted_bid_qty"] - snap["weighted_ask_qty"]) / (snap["weighted_bid_qty"] + snap["weighted_ask_qty"])
        np.testing.assert_allclose(snap["depth_imbalance"][good], depth[good], atol=1.e-12, rtol=0)
        snapshot_rows += len(r["time_s"])
    for account in meta["原本照合"]:
        key = account["session"], account["symbol"]
        for sample in account["原本サンプル"]:
            row = sample["i"]
            assert ready[key]["seq"][row] == sample["seq"]
            assert ready[key]["time_s"][row] == datetime.fromisoformat(sample["raw"]["CurrentPriceTime"]).timestamp()
            assert books[key]["bid"][row] == sample["raw"]["Buy1"]["Price"]
            assert books[key]["ask"][row] == sample["raw"]["Sell1"]["Price"]
            snapshot_checks(sample["raw"], ready[key]["tick"], sample["features"])
            for field in FIELDS:
                np.testing.assert_allclose(snaps[key][field][row], snapshot(sample["raw"], ready[key]["tick"])[field],
                    atol=1.e-9, rtol=1.e-10, equal_nan=True)
            raw_samples += 1
    original = raw_fixture()
    snapshot_checks(original, 1.)
    assert snapshot(original, 1.)["microprice"] > 100.5
    artificial += 1
    variants = []
    for path, value in (("Buy1", {"Price": 100., "Qty": 0.}), ("Sell2", {"Price": 101., "Qty": 2.}),
            ("Buy3", {"Price": 98., "Qty": -1.}), ("Sell10", {"Price": float("nan"), "Qty": 2.}),
            ("Buy2", {"Price": 99., "Qty": float("inf")})):
        changed = deepcopy(original)
        changed[path] = value
        variants.append(changed)
    changed = deepcopy(original)
    del changed["Buy10"]
    variants.append(changed)
    for changed in variants:
        snapshot_checks(changed, 1.)
        assert not snapshot(changed, 1.)["valid"]
        artificial += 1
    for tick in (0., -1., float("nan")):
        snapshot_checks(original, tick)
        artificial += 1
    array_checks = points = window_points = 0
    independent_coverage = []
    for delay, sessions in sorted(grids.items()):
        assert len(sessions) == 29
        for session, stored in sorted(sessions.items()):
            grid = stored["grid"]
            r = ready[(session, "TOPIX")]
            np.testing.assert_array_equal(grid, np.arange(r["start"] + 300., r["limit"] - 60. + 1.e-6, 5.))
            independent = {}
            for symbol, actual in stored["markets"].items():
                key = session, symbol
                expected = market(grid, delay, ready[key], books[key], snaps[key])
                array_checks += compare(actual, expected)
                points += len(grid)
                window_points += 4 * len(grid)
                independent[symbol] = expected
            independent_coverage.append(coverage_row(session, delay, grid, independent))
        print(f"遅延{delay}秒の全入力を独立照合しました", flush=True)
    actual_coverage = load(HERE.parent / "inputs/入力十分性.json")["rows"]
    assert sorted(actual_coverage, key=lambda x: (x["delay"], x["session"])) == independent_coverage
    save(HERE / "全即時板と短期窓と十分性の独立監査.json", dict(合格=True, 保存口座数=58,
        即時板原本対応行数=snapshot_rows, 原本添付サンプル式照合数=raw_samples,
        人工一行板式検査数=artificial, 遅延数=len(grids), 市場格子数=58 * len(grids),
        current全点数=points, 短期窓全点数=window_points, 照合配列数=array_checks,
        十分性場遅延集計数=len(independent_coverage),
        検査=["全seq時計1対1", "全最良数量偏り・microprice恒等式", "生174サンプルの距離加重十段式",
            "strictpast同時計先頭", "始点除外終点含む原本逐次OFI和", "ゼロ分母・少数証拠・欠測・同一行の区別",
            "実窓秒と両気配移動", "全174市場格子と全87場遅延十分性"],
        入力指紋=meta["hashes"],
        限界="最終約定代理時計上の同期。生十段の全原本再走査はせず、入力担当の原本指紋・全seq検査と添付サンプルを利用。実受信時計の証明ではない。",
        原本取得=0, API取得=0, 実注文=0, 損益閲覧=0))
    print(f"即時板{snapshot_rows:,}行・窓{window_points:,}点が独立一致しました", flush=True)


if __name__ == "__main__":
    main()
