"""複数建値の同一行返済で旧料金配賦のキーが衝突することを最小注文列で確認する。"""

import hashlib
import math
import numpy as np
from diagnose import ROOT, HERE, save
from boundaries import module


def fixture(symbol):
    """
    機能: 初回2枚・追加8枚・部分1枚・残り1枚と8枚同時返済の人工注文を作る。
    引数: symbol(str)。
    返り値: tuple[dict,dict,dict]の入力・生結果・設定。優位性の評価には使用しない。
    """
    price = np.array([100., 100., 101., 102., 103.])
    orders = np.array([[1, 0, 0, 1, 2, 100, 1, 1], [2, 1, 0, 1, 8, 101, 75, 1],
        [3, 2, 0, -1, 1, 102, 30, 0], [4, 3, 0, -1, 1, 103, 9, 0],
        [4, 3, 0, -1, 8, 103, 9, 0]], dtype=float)
    trades = np.array([[0, 0, 1, 1, 100, 102, 1, 3, 0, 30, 2],
        [0, 0, 1, 1, 100, 103, 1, 4, 0, 9, 3],
        [0, 1, 1, 8, 101, 103, 2, 4, 0, 9, 16]], dtype=float)
    cycles = np.array([[0, 1, 4, 21, 8, 4, 10, 10, 1, 9]], dtype=float)
    cash, qty = np.zeros(5), np.zeros(5)
    for o in orders:
        cash[int(o[0])] -= o[3] * o[4] * o[5]
        qty[int(o[0])] += o[3] * o[4]
    curve = np.zeros((5, 8))
    curve[:, 0] = np.cumsum(cash) + np.cumsum(qty) * price
    stats = np.zeros(11)
    stats[0], stats[2] = 21, 10
    ready = dict(symbol=symbol, session='人工料金衝突', last=price, time_s=np.arange(5, dtype=float),
                 seq=np.arange(5), limit=10000.)
    return ready, dict(orders=orders, trades=trades, cycles=cycles, curve=curve, stats=stats), dict(initial_qty=2, audit_cap=10 if symbol == 'TOPIX' else 20)


def main():
    """
    機能: 旧配賦の衝突と、注文ごとの料金総額を最小例で照合する。
    引数: なし。
    返り値: None。旧会計・売買エンジン・過去結果は変更しない。
    """
    strategy = module('監査87料金衝突戦略', ROOT / 'work/wave_v87/round4/strategy.py')
    fifo = module('監査87料金衝突FIFO', HERE / 'allocation_fifo.py')
    records = []
    for symbol in ('TOPIX', 'NK225'):
        ready, result, config = fixture(symbol)
        fee, scale = (41.8, 1000) if symbol == 'TOPIX' else (11., 10)
        charges = [math.floor(o[4] * fee + 1e-8) for o in result['orders']]
        details = []
        allocations = [charges[0] / 2 + charges[2], charges[0] / 2 + charges[3], charges[1] + charges[4]]
        for t, allocated in zip(result['trades'], allocations):
            cid, _, side, q, ep, xp, e, x, _, reason, gross = t
            details.append(dict(組=int(cid), 方向=int(side), 枚数=int(q), 新規行=int(e), 返済行=int(x),
                新規原本行=int(e), 返済原本行=int(x), 新規時刻=e, 返済時刻=x,
                建値=ep, 返済値=xp, 理由=int(reason), 利益損失前=gross * scale,
                手数料=allocated, 収支=gross * scale - allocated))
        ledger = dict(result, session=ready['session'], config=config, trades=details, fees=charges)
        row, _, raw = fifo.measure(ready, ledger, 'observed')
        np.testing.assert_array_equal(np.asarray(raw), result['trades'])
        rejected = False
        try:
            strategy.previous.account(ready, result, config)
        except AssertionError:
            rejected = True
        assert rejected == (symbol == 'TOPIX')
        records.append(dict(商品=symbol, 旧会計が不整合を拒否=rejected,
            注文料金=charges, 正しい全料金=sum(charges), 正しい脚への配賦=allocations,
            正しい収支=row['net'], 同一行返済2注文の正しい料=charges[3] + charges[4],
            旧辞書が最後の単価で9枚へ配賦する料=9 * charges[4] / 8))
    source = ROOT / 'work/wave_v67/study.py'
    save('同一行複数返済の旧料金配賦衝突.json', dict(全合格=True, 検査=records,
        原因='旧exit_chargeのキーが親組と返済行のみ。同じ原本行に別々の返済注文があると上書きし、数量ごとの切捨て料率の違いを失う。',
        修正要件='返済注文を順序付きで維持し、各注文の数量を建値脚へ消費する。料金は注文ごとに切捨てた額を、その注文が返済した枚数へ配賦する。',
        波及範囲='元GUには原則一建値しかなく、保存済み六結果の独立会計は合格。複数建値を新たに導入した追加条件で会計が止まり、誤った新成績は保存されなかった。',
        元会計SHA256=hashlib.sha256(source.read_bytes()).hexdigest()))


if __name__ == '__main__':
    main()
