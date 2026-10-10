"""旧在庫の主5条件を、注文順の全flat区切りから独立検算する。"""

import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent.parent / 'wave_v61/inventory'


def main() -> None:
    """機能: 主5条件250場の組数・勝率・純益・同注文中値を別会計で照合する。

    引数: なし。返り値: なし(None)。約定や条件を再探索しない。
    """
    result = json.loads((HERE.parent / 'inventory/R0_旧在庫の原因分解.json').read_text(encoding='utf-8'))
    quotes = pickle.loads((HERE.parent.parent / 'wave_v60/quotes.pkl').read_bytes())
    checks = groups = 0
    primary = []
    for method in result['methods']:
        if not method['primary'] or method['price_mode'] != 'quote':
            continue
        ledgers = pickle.loads((PRIOR / 'ledger' / (method['id'] + '.pkl')).read_bytes())
        amounts = []
        for account in method['accounts']:
            key = (account['session'], account['symbol'])
            orders = ledgers[key]['orders']
            q = quotes[key]
            value = 1000. if key[1] == 'TOPIX' else 10.
            long = short = cash = base = mid_cash = 0.
            finished = []
            for order in orders:
                entry, side, quantity = order[9] == 1, order[10], order[11]
                cash -= side * quantity * order[12] * value + order[13]
                mid_cash -= side * quantity * q['mid'][int(order[2])] * value + order[13]
                if entry:
                    if side > 0:
                        long += quantity
                    else:
                        short += quantity
                elif side > 0:
                    short -= quantity
                else:
                    long -= quantity
                assert long >= 0 and short >= 0
                if long == 0 and short == 0:
                    finished.append(cash - base)
                    base = cash
            assert long == short == 0
            net = np.array(finished)
            assert len(net) == account['groups']
            assert int(np.sum(net > 0)) == account['wins']
            assert int(np.sum(net < 0)) == account['losses']
            assert int(np.sum(net == 0)) == account['flats']
            assert abs(net.sum() - account['net']) < 1e-6
            assert abs(mid_cash - account['fixed_mid_net']) < 1e-6
            checks += 1
            groups += len(net)
            amounts.append(dict(場=key[0], 銘柄=key[1], 組数=len(net), 純益=float(net.sum())))
        primary.append(dict(条件=method['id'], 検算場数=len(amounts)))
    assert checks == 250
    proof = dict(合格=True, 全flat組の原本順会計=True, 両側残玉ゼロを要求=True,
        主条件数=len(primary), 検算場数=checks, 検算組数=groups, 条件=primary)
    (HERE / '旧在庫主5条件の組会計再確認.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
