"""独立金融監査器を金融前に人工の正常・破損会計で検査する。"""

import copy
import importlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/"audit_artificial"))
from check126 import artificial, run, mirror, legacy126
from audit126 import HERE, audit_account


def main():
    """
    機能: 全行時価・脚・親組の監査器が正常を通し破損を拒否することを確かめる。
    引数: なし。
    返り値: None。人工のみの自己監査を新所有域へ保存する。
    """
    checks = []
    with legacy126.isolated():
        legacy126.runtime()
        core = importlib.import_module("last_core126")
        for symbol, quantity in (("TOPIX", 5), ("NK225", 10)):
            case = artificial([100, 100, 103, 106, 110, 108, 113, 112, 111, 108, 106, 104, 102, 100, 98, 94], quantity=quantity)
            for reflected in (False, True):
                value = mirror(case) if reflected else case
                outputs = run(core, value, [0, .5, 0, 0])
                names = core.FIELDS + ("control_curve", "slot_curve", "slot_events", "adjustment_events",
                    "budget_events", "branch_events", "branch_curve", "risk_events", "guard_curve",
                    "guard_events", "block_events", "time_events", "policy_curve126", "policy_events126")
                arrays = {k:v for k,v in zip(names, outputs) if k in ("orders", "trades", "cycles", "curve", "stats", "policy_events126")}
                row = dict(symbol=symbol, session="人工", method="人工")
                summary = audit_account(row, arrays, value["args"][1])
                checks.append(dict(symbol=symbol, reflected=reflected, valid=True, net=summary["net"]))
                for name, column in (("trades", 10), ("curve", 5), ("orders", 4)):
                    damaged = copy.deepcopy(arrays)
                    damaged[name][-1, column] += 1
                    rejected = False
                    try:
                        audit_account(row, damaged, value["args"][1])
                    except (AssertionError, ValueError):
                        rejected = True
                    assert rejected, (name, column)
                    checks.append(dict(symbol=symbol, reflected=reflected, damaged=name, rejected=True))
    proof = dict(passed=True, checks=checks, financial_replays=0, market_reads=0)
    assert sys.argv[1:] in ([], ["--strict"])
    output = HERE/("注文根拠の厳密過去を含む監査器の純人工自己検査.json"
                   if sys.argv[1:] else "独立金融監査器の純人工自己検査.json")
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, checks=len(checks)), ensure_ascii=False))


if __name__ == "__main__":
    main()
