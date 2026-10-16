"""独立会計器そのものを、手計算できる分割返済と利益保護で試す。"""

import hashlib
import json
import numpy as np

import synthetic
import accounts
from original import module, HERE, WORK, ROOT


def main():
    """
    機能: 親会計の出力を独立FIFOと現金曲線で照合し、人工の手計算にも一致させる。
    引数: なし。
    返り値: None。監査結果のみを保存する。
    """
    parent = module("wave85_research", WORK / "research.py")
    old = module("wave85_old_independent", ROOT / "work/wave_v67/audit/independent_accounting.py")
    checks = []
    for reflected in (False, True):
        for mask in (0, 2):
            result = synthetic.fixture([100, 100, 108, 103, 110, 111, 111],
                {1: (1, 0)}, {4: (1, 0, 7), 6: (1, 0, 9)}, mask=mask, reflected=reflected)
            n = len(result["price"])
            ready = dict(session="人工", symbol="TOPIX", seq=np.arange(n), time_s=np.arange(n) * 301.,
                         last=result["price"], limit=float(n * 301.))
            config = dict(initial_qty=5, audit_cap=10)
            actual, ledger, _ = parent.account(synthetic.strategy.previous, ready, result, config)
            formatted = dict(ledger, config=config, trades=ledger["net_trades"], fees=ledger["fees"].tolist())
            row, _, _ = old.measure(ready, formatted, "observed")
            trace = accounts.trace(ready, ledger, row)
            accounts.ratios(row)
            accounts.equal(row, actual)
            accounts.guards(ready, ledger, trace, bool(mask & 2))
            assert actual["gross"] == 53000 and actual["fees"] == 417 and actual["net"] == 52583
            checks.append(dict(ショート=reflected, 利益保護=bool(mask & 2), 料金前=53000, 料金=417, 収支=52583,
                               全行時価SHA一致=True, 独立会計一致=True))
    output = dict(全合格=True, 検査=checks, コードSHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (HERE / "accounts.py", Path(__file__))})
    (HERE / "独立会計器の人工自己検査.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(全合格=True, 検査数=len(checks)), ensure_ascii=False))


if __name__ == "__main__":
    from pathlib import Path
    main()
