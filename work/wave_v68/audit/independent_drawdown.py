"""保存注文と全観測値の現金・保有枚数から、手数料後の含み損益と最大下落を再構築する。"""

from __future__ import annotations

from hashlib import sha256
import gzip
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
POINT = {"TOPIX": 1000, "NK225": 10}


def reconstruct(ready: dict, ledger: dict) -> np.ndarray:
    """機能: エンジンの時価列を使わず全行の独立時価を再計算する。

    引数: ready/ledger(dict)。返り値: 料金後の円時価(ndarray[float64])。
    """
    price = ready["last"]
    assert np.isfinite(price).all() and (price > 0).all()
    n = len(price)
    cash = np.zeros(n)
    quantity = np.zeros(n)
    charges = np.zeros(n)
    symbol = ledger["symbol"]
    value = POINT[symbol]
    for order in ledger["orders"]:
        row = int(order[0])
        side, count, fill = int(order[3]), int(order[4]), order[5]
        assert 0 <= int(order[1]) < row < n
        cash[row] -= side * count * fill * value
        quantity[row] += side * count
        charges[row] += 418 * count // 10 if symbol == "TOPIX" else 11 * count
    cash = np.cumsum(cash)
    quantity = np.cumsum(quantity)
    assert quantity[-1] == 0
    assert np.abs(quantity).max(initial=0) <= (5 if symbol == "TOPIX" else 10)
    return cash + quantity * price * value - np.cumsum(charges)


def main() -> None:
    """機能: 全条件全口座の最大下落と時価終端を独立復元して保存する。

    引数: なし。返り値: なし(None)。
    """
    packets = {}
    fingerprints = {}
    for p in sorted((WORK / "observed").glob("*.json.gz")):
        packet = json.loads(gzip.decompress(p.read_bytes()))
        key = packet["variant"]["id"]
        packets[key] = {(l["session"], l["symbol"]): (l, r) for l, r in zip(packet["ledgers"], packet["rows"])}
        fingerprints[p.name] = sha256(p.read_bytes()).hexdigest()
    assert packets
    results = []
    seen = set()
    for folder in sorted((ROOT / "work/wave_v67/prepared").iterdir()):
        path = folder / "new_inputs.pkl"
        if not path.exists():
            continue
        inputs = pickle.loads(path.read_bytes())
        for key, ready in sorted(inputs.items()):
            assert key not in seen
            seen.add(key)
            for name, ledger_rows in packets.items():
                if key not in ledger_rows:
                    continue
                ledger, row = ledger_rows[key]
                assert ledger["session"] == row["session"] and ledger["symbol"] == row["symbol"]
                eq = reconstruct(ready, ledger)
                high = np.maximum.accumulate(np.maximum(eq, 0))
                dd = float((high - eq).max(initial=0))
                assert abs(dd - row["max_drawdown"]) < 1e-5, (name, key, dd, row["max_drawdown"])
                assert abs(eq[-1] - row["net"]) < 1e-5
                assert abs(eq[0] - ledger["equity_checkpoints"][0][0]) < 1e-5
                assert abs(eq[-1] - ledger["equity_checkpoints"][1][0]) < 1e-5
                results.append(dict(条件=name, セッション=key[0], 銘柄=key[1], 全観測行=len(eq),
                                    最大下落=dd, 終端収支=float(eq[-1]), 独立復元一致=True))
        print(folder.name, "独立時価復元完了", len(results), flush=True)
    assert len(results) == sum(len(v) for v in packets.values())
    packet = dict(全合格=True, 条件数=len(packets), 口座数=len(results), 記録=results,
                  入力結果SHA256=fingerprints, 実装SHA256=sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE / "全観測時価と最大下落の独立復元.json").write_text(
        json.dumps(packet, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(全合格=True, 条件数=len(packets), 口座数=len(results)), ensure_ascii=False))


if __name__ == "__main__":
    main()
