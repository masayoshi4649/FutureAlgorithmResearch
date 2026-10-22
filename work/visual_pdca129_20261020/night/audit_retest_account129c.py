"""夜間第七巡の保存全口座を、独立した全原行会計で照合する。"""

import hashlib
import json
import pickle
import time
import numpy as np
from audit_retest_account129 import HERE, TASK, ROOT, OLD, CHECKS, read, audit


def main() -> None:
    """
    機能: 完成済み第七巡保存口座の気配・数量・手数料・全原行時価を検算する。
    引数: なし。
    返り値: None。売買核を呼ばず、新しい監査証拠だけを保存する。
    """
    folder = TASK/"round7"
    account = read(folder/"全条件の会計.json")
    assert account["passed"]
    refs = {r["session"]:r for r in read(OLD/"入力準備.json")["packets"]}
    results,hashes = [],{}
    for scene in sorted({r["session"] for r in account["rows"]}):
        ref = refs[scene]
        path = ROOT/ref["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest()==ref["sha256"]
        packet = pickle.loads(path.read_bytes())
        for symbol in ("TOPIX","NK225"):
            path = folder/"measurement"/f"{symbol}_{scene}.npz"
            hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            with np.load(path,allow_pickle=False) as saved:
                for row in [r for r in account["rows"] if r["session"]==scene and r["symbol"]==symbol]:
                    arrays = {k:saved[row["method"]+"__"+k] for k in ("orders","trades","curve")}
                    results.append(audit(packet["inputs"][scene,symbol],packet["quotes"][scene,symbol],arrays,row))
        print(scene,"第七巡保存会計照合",flush=True)
    target = HERE/f"夜間第七巡の保存全行会計と親別照合_{time.time_ns()}.json"
    target.write_text(json.dumps(dict(passed=True,rows=results,checks=CHECKS,
        source_hashes=hashes,financial_replays=0,API=0),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=True,accounts=len(results),checks=len(CHECKS),path=str(target)),ensure_ascii=False))


if __name__=="__main__":
    main()
