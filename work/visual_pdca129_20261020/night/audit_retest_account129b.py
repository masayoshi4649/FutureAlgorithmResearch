"""夜間第六巡の保存全口座を、第四巡と同じ独立会計で照合する。"""

import hashlib
import json
import pickle
import time
import numpy as np
from audit_retest_account129 import HERE, TASK, ROOT, OLD, CHECKS, read, audit


def main() -> None:
    """
    機能: 第六巡全84保存口座の正常気配・数量・全行会計・親別集計を検算する。
    引数: なし。
    返り値: None。新しい会計証拠を保存し、売買判断は実行しない。
    """
    folder = TASK/"round6"
    account = read(folder/"全条件の会計.json")
    refs = {r["session"]:r for r in read(OLD/"入力準備.json")["packets"]}
    results, hashes = [], {}
    for scene in sorted({r["session"] for r in account["rows"]}):
        ref = refs[scene]
        path = ROOT/ref["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
        packet = pickle.loads(path.read_bytes())
        for symbol in ("TOPIX","NK225"):
            path = folder/"measurement"/f"{symbol}_{scene}.npz"
            hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            with np.load(path,allow_pickle=False) as saved:
                for row in [r for r in account["rows"] if r["session"]==scene and r["symbol"]==symbol]:
                    arrays = {k:saved[row["method"]+"__"+k] for k in ("orders","trades","curve")}
                    results.append(audit(packet["inputs"][scene,symbol],packet["quotes"][scene,symbol],arrays,row))
        print(scene,"第六巡保存会計照合",flush=True)
    target = HERE/f"夜間第六巡の保存全行会計と親別照合_{time.time_ns()}.json"
    target.write_text(json.dumps(dict(passed=True,rows=results,checks=CHECKS,
        source_hashes=hashes,financial_replays=0,API=0),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,accounts=len(results),checks=len(CHECKS),path=str(target)),ensure_ascii=False))


if __name__ == "__main__":
    main()
