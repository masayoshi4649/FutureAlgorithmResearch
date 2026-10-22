"""日中第二巡の実親・元影・再参加と残りの時価列を保存資料だけで照合する。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は位置。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    """
    機能: 保存実親と元影の対応、参加回数、親別会計と最大損失列を別に確認する。
    引数: argv[1](str)は保存巡。省略時day_round2。
    返り値: None。金融核は読み込まず保存結果のみ照合する。
    """
    name = sys.argv[1] if len(sys.argv) > 1 else "day_round2"
    source = WORK/name/"全条件の会計.json"
    result = read(source)
    manifest = {x["session"]: x for x in read(ROOT/"work/daynight128_20261020/入力準備.json")["packets"]}
    rows = []
    for ref in result["cache"]:
        session, symbol = ref["session"], ref["symbol"]
        path = ROOT/ref["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
        feedref = manifest[session]["features"]
        assert hashlib.sha256((ROOT/feedref["path"]).read_bytes()).hexdigest() == feedref["sha256"]
        with np.load(ROOT/feedref["path"]) as prepared:
            original_feed = prepared[symbol+"__feed"]
        with np.load(path) as archive:
            for row in result["rows"]:
                if row["session"] != session or row["symbol"] != symbol:
                    continue
                prefix = row["method"]+"__"
                orders, curve, cycles, events, links = [archive[prefix+k] for k in
                                                       ("orders", "curve", "cycles", "execution_events", "parent_mapping")]
                entered = orders[orders[:, 7] == 1]
                assert len(links) == len(entered) == len(cycles)
                assert len(set(links[:, 0])) == len(links)
                equity = curve[:, 0]
                dd = np.maximum.accumulate(np.maximum.accumulate(np.maximum(0., equity))-equity)
                np.testing.assert_allclose(curve[:, 4], dd, rtol=0, atol=1.e-7)
                np.testing.assert_array_equal(curve[:, 6], curve[:, 2]-curve[:, 3])
                parents = []
                mult, rate = (1000, 418) if symbol == "TOPIX" else (10, 110)
                for cid, shadow, attempt, source_row in links.astype(int):
                    own = orders[orders[:, 2] == cid]
                    begin, leaves = own[own[:, 7] == 1], own[own[:, 7] == 0]
                    assert len(begin) == 1 and begin[0, 1] == source_row
                    assert attempt in (0, 1)
                    if attempt == 0:
                        corresponding = original_feed[(original_feed[:, 2] == shadow) & (original_feed[:, 7] == 1)]
                        assert len(corresponding) == 1 and corresponding[0, 0] == source_row
                        assert corresponding[0, 3] == begin[0, 3] and corresponding[0, 4] == begin[0, 4]
                    else:
                        retry = events[(events[:, 1] == 17) & (events[:, 2] == cid)]
                        assert len(retry) == 1 and retry[0, 0] == source_row and retry[0, 8] == shadow
                        assert retry[0, 10] == 1
                    gross = float(np.sum(begin[0, 3]*leaves[:, 4]*(leaves[:, 5]-begin[0, 5]))*mult)
                    fees = int(sum(own[:, 4].astype(int)*rate//10))
                    saved_cycle = cycles[cycles[:, 0] == cid]
                    assert len(saved_cycle) == 1 and np.isclose(saved_cycle[0, 3]*mult, gross)
                    parents.append(dict(parent=int(cid), shadow=int(shadow), attempt=int(attempt),
                                        gross=gross, fees=fees, net=gross-fees))
                for shadow in np.unique(links[:, 1]):
                    attempts = links[links[:, 1] == shadow, 2].astype(int)
                    assert attempts.tolist() in ([0], [0, 1])
                assert sum(x["net"] > 0 for x in parents) == row["parent_wins"]
                assert sum(x["net"] < 0 for x in parents) == row["parent_losses"]
                rows.append(dict(method=row["method"], session=session, symbol=symbol,
                                 parents=parents, curve_rows=len(curve), passed=True))
    out = dict(passed=True, rows=rows, accounts=len(rows), parent_count=sum(len(x["parents"]) for x in rows),
               curve_rows=sum(x["curve_rows"] for x in rows),
               source=dict(path=source.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
               auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), financial_replays=0,
               scope="全注文会計に加えて、元影・初回・再参加最大一回・完結親・最大損失列・純保有枚数列を検査")
    target = HERE/(name+"_元影と再参加及び時価列の独立追補.json")
    assert not target.exists()
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
