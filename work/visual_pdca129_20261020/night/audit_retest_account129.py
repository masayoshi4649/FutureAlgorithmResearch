"""夜間第四巡の保存注文から全原行会計を独立に再構築する。売買核は呼ばない。"""

import hashlib
import json
from pathlib import Path
import pickle
import time
import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
OLD = ROOT/"work/daynight128_20261020"
CHECKS = []


def read(path: Path) -> dict:
    """
    機能: 日本語の保存資料を読む。
    引数: path(Path)は資料位置。
    返り値: dictは資料内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def equal(name: str, actual: object, expected: object) -> None:
    """
    機能: 独立数値との一致を確認する。
    引数: name(str)、actual/expected(object)は名称・二つの数値群。
    返り値: None。不一致なら停止する。
    """
    np.testing.assert_allclose(actual, expected, rtol=0., atol=1.e-8, err_msg=name)
    CHECKS.append(name)


def audit(ready: dict, q: dict, arrays: dict, row: dict) -> dict:
    """
    機能: 次正常行気配、各親、全原行の現金・保有・時価を独立に検算する。
    引数: ready/q/arrays/row(dict)は原入力・気配・保存出力・保存要約。
    返り値: dictは親別内訳付き独立会計。売買判断は再実行しない。
    """
    orders, trades, curve = (arrays[k] for k in ("orders", "trades", "curve"))
    n = len(ready["time_s"])
    symbol = row["symbol"]
    mult, rate, amount = (1000., 418, 5) if symbol == "TOPIX" else (10., 110, 10)
    prefix = f"{row['method']}_{row['session']}_{symbol}"
    fills = orders[:, 0].astype(np.int64)
    decisions = orders[:, 1].astype(np.int64)
    qty = orders[:, 4].astype(np.int64)
    signs = orders[:, 3]
    good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
    good &= (q["bid"] > 0.) & (q["ask"] > q["bid"])
    goodrows = np.flatnonzero(good)
    equal(prefix+"_整数数量", qty, orders[:, 4])
    equal(prefix+"_一定数量", qty, np.full(len(qty), amount))
    equal(prefix+"_判断後最初の正常行", fills,
          goodrows[np.searchsorted(goodrows, decisions, side="right")])
    equal(prefix+"_実売買側気配", orders[:, 5],
          np.where(signs > 0., q["ask"][fills], q["bid"][fills]))
    # ----------------------------------------
    # 夜間核の現金は建代金ではなく、返済粗収支から全注文手数料を引く定義。
    fees = qty*rate//10
    cashchange = np.zeros(n)
    feechanges = np.zeros(n)
    poschange = np.zeros(n)
    entrychange = np.zeros(n)
    np.add.at(cashchange, fills, -fees)
    np.add.at(feechanges, fills, fees)
    np.add.at(poschange, fills, signs*qty)
    parents = []
    for parent in np.unique(orders[:, 2]):
        own = orders[orders[:, 2] == parent]
        enter = own[own[:, 7] == 1.]
        exits = own[own[:, 7] == 0.]
        equal(prefix+f"_親{parent}一新規一返済", [len(enter), len(exits)], [1, 1])
        a, b = enter[0], exits[0]
        e, x, sign = int(a[0]), int(b[0]), int(a[3])
        equal(prefix+f"_親{parent}上下対称数量", [b[3], b[4]], [-sign, a[4]])
        gross = sign*(b[5]-a[5])*a[4]*mult
        fee = int(fees[orders[:, 2] == parent].sum())
        net = gross-fee
        ownmark = q["bid"] if sign > 0 else q["ask"]
        movements = sign*(ownmark[e:x+1][good[e:x+1]]-a[5])
        saved = trades[int(parent)]
        equal(prefix+f"_親{parent}保存取引",
              saved[:11], [e, x, sign, a[4], a[5], b[5], gross, fee, net,
                           max(0., float(movements.max())), min(0., float(movements.min()))])
        cashchange[x] += gross
        entrychange[e] += a[5]
        entrychange[x] -= a[5]
        parents.append(dict(parent=int(parent), entry_row=e, exit_row=x,
            decision_row=int(a[1]), exit_decision_row=int(b[1]), side=sign,
            quantity=int(a[4]), entry=float(a[5]), exit=float(b[5]),
            gross=float(gross), fee=fee, net=float(net), mfe=float(saved[9]),
            mae=float(saved[10]), width=float(saved[11]), reason=int(saved[12])))
    cash = np.cumsum(cashchange)
    cumulativefees = np.cumsum(feechanges)
    position = np.cumsum(poschange)
    entryprice = np.cumsum(entrychange)
    prior = np.maximum.accumulate(np.where(good, np.arange(n), 0))
    mark = np.where(position > 0., q["bid"][prior], q["ask"][prior])
    equity = cash+np.where(position != 0., position*(mark-entryprice)*mult, 0.)
    equal(prefix+"_全原行会計", curve,
          np.column_stack([equity, position, cumulativefees, cash]))
    equal(prefix+"_全返済", position[-1], 0.)
    equal(prefix+"_上限", np.max(np.abs(position)) <= (10 if symbol == "TOPIX" else 20), True)
    nets = np.array([p["net"] for p in parents])
    equal(prefix+"_要約", [row[k] for k in ("profit", "loss", "net", "gross", "fees",
          "entries", "quantity", "parent_wins", "parent_losses")],
          [nets[nets > 0.].sum(), -nets[nets < 0.].sum(), nets.sum(),
           sum(p["gross"] for p in parents), sum(p["fee"] for p in parents),
           len(parents), len(parents)*amount, sum(nets > 0.), sum(nets < 0.)])
    return dict(method=row["method"], session=row["session"], symbol=symbol,
                net=float(nets.sum()), parents=parents)


def main() -> None:
    """
    機能: 第四巡全保存口座を検算し、指紋付き証拠を保存する。
    引数: なし。
    返り値: None。金融再生・API取得は行わない。
    """
    folder = TASK/"round4"
    account = read(folder/"全条件の会計.json")
    refs = {r["session"]: r for r in read(OLD/"入力準備.json")["packets"]}
    results, hashes = [], {}
    for scene in sorted({r["session"] for r in account["rows"]}):
        ref = refs[scene]
        path = ROOT/ref["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
        packet = pickle.loads(path.read_bytes())
        for symbol in ("TOPIX", "NK225"):
            path = folder/"measurement"/f"{symbol}_{scene}.npz"
            hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            with np.load(path, allow_pickle=False) as saved:
                for row in [r for r in account["rows"] if r["session"] == scene and r["symbol"] == symbol]:
                    arrays = {k: saved[row["method"]+"__"+k] for k in ("orders", "trades", "curve")}
                    results.append(audit(packet["inputs"][scene, symbol],
                                         packet["quotes"][scene, symbol], arrays, row))
        print(scene, "保存会計照合", flush=True)
    target = HERE/f"夜間第四巡の保存全行会計と親別照合_{time.time_ns()}.json"
    target.write_text(json.dumps(dict(passed=True, rows=results, checks=CHECKS,
        source_hashes=hashes, financial_replays=0, API=0), ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    print(json.dumps(dict(passed=True, accounts=len(results), checks=len(CHECKS),
                         path=str(target)), ensure_ascii=False))


if __name__ == "__main__":
    main()
