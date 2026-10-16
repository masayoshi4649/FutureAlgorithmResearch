"""局所料金修正を、複数返済人工例と保存済み数量縮小六結果で照合する。"""

import hashlib
import pickle
import sys
import numpy as np
from diagnose import ROOT, HERE, save
from boundaries import module


def raw_curve(ready, ledger):
    """
    機能: 保存注文・返済脚から旧会計へ渡す全行時価曲線を独立再構成する。
    引数: ready/ledger(dict)。
    返り値: ndarray。旧戦略の再生は実行しない。
    """
    n = len(ready['last'])
    cash, qty, longs, shorts, gross = (np.zeros(n) for _ in range(5))
    campaign = np.full(n, -1.)
    for order in ledger['orders']:
        i, side, q = int(order[0]), int(order[3]), int(order[4])
        cash[i] -= side * q * order[5]
        qty[i] += side * q
        direction = side if order[7] else -side
        inventory = longs if direction == 1 else shorts
        inventory[i] += q if order[7] else -q
        if order[7]:
            campaign[i:] = order[2]
    for t in ledger['trades']:
        gross[int(t[7])] += t[10]
    cash, qty, longs, shorts, gross = map(np.cumsum, (cash, qty, longs, shorts, gross))
    raw = cash + qty * ready['last']
    drawdown = np.maximum.accumulate(np.maximum.accumulate(np.maximum(raw, 0)) - raw)
    curve = np.c_[raw, gross, longs, shorts, drawdown, cash, qty, campaign]
    assert hashlib.sha256(curve.tobytes()).hexdigest() == ledger['raw_curve_SHA256']
    return curve


def main():
    """
    機能: 新返済料金キューが衝突を解消し旧一建値の会計を変えないことを確認する。
    引数: なし。
    返り値: None。全検査は人工注文か保存済み注文の読み替えのみ。
    """
    local = module('監査87移植新料金', ROOT / 'work/wave_v87/round6/fee_account.py')
    sample = module('監査87移植料金人工', HERE / 'fee_collision.py')
    fifo = module('監査87移植料金FIFO', HERE / 'allocation_fifo.py')
    old_folder = ROOT / 'work/wave_v85/audit'
    sys.path.insert(0, str(old_folder))
    module('original', old_folder / 'original.py')
    account = module('監査87移植料金会計比較', old_folder / 'accounts.py')
    prepare = module('監査87移植料金入力', ROOT / 'work/wave_v85/prepare.py')
    before = hashlib.sha256((ROOT / 'work/wave_v87/round6/fee_account.py').read_bytes()).hexdigest()
    artificial = []
    for symbol in ('TOPIX', 'NK225'):
        ready, result, config = sample.fixture(symbol)
        row, ledger, equity = local.account(ready, result, config)
        expected, _, raw = fifo.measure(ready, ledger, 'observed')
        account.equal(row, expected)
        np.testing.assert_array_equal(np.asarray(raw), result['trades'])
        assert row['net'] == equity[-1]
        artificial.append(dict(商品=symbol, 注文料=ledger['fees'], 合計料=row['fees'], 収支=row['net']))
    # ----------------------------------------
    # 一注文を複数脚へ配賦する場合も、次の返済注文へ量を正しく繰り越す。
    orders = np.array([[9, 8, 0, -1, 3, 100, 9, 0], [9, 8, 0, -1, 7, 100, 9, 0]], dtype=float)
    trades = np.zeros((4, 11))
    trades[:, 2] = 1
    trades[:, 3] = [1, 2, 1, 6]
    trades[:, 5] = 100
    trades[:, 7] = 9
    trades[:, 9] = 9
    charges = np.array([125., 292.])
    np.testing.assert_allclose(local.allocate_exit_fees(orders, charges, trades),
                               [125 / 3, 250 / 3, 292 / 7, 1752 / 7], atol=1e-9)
    inputs, _, _ = prepare.load_inputs(verify=False)
    cases = []
    for model in ('observed', 'specified'):
        for ident in ('GU', 'S1', 'S2'):
            path = ROOT / f'work/wave_v87/round4/{model}/ledgers/{ident}.pkl'
            ledgers = pickle.loads(path.read_bytes())
            for key, ledger in ledgers.items():
                ready = inputs[key]
                result = dict(ledger, curve=raw_curve(ready, ledger))
                row, changed, equity = local.account(ready, result, ledger['settings'])
                account.equal(changed['trades'], ledger['net_trades'])
                np.testing.assert_array_equal(changed['fees'], ledger['fees'])
                assert hashlib.sha256(equity.tobytes()).hexdigest() == ledger['curve_SHA256']
                expected, _, raw = fifo.measure(ready, changed, model)
                account.equal(row, expected)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1, 11), ledger['trades'])
            cases.append(dict(モデル=model, 条件=ident, 口座数=len(ledgers), 台帳SHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
    assert before == hashlib.sha256((ROOT / 'work/wave_v87/round6/fee_account.py').read_bytes()).hexdigest()
    save('局所料金修正の人工と既存360口座照合.json', dict(全合格=True, 人工口座=artificial,
        一注文複数脚と複数注文の数量消費一致=True, 保存口座数=sum(c['口座数'] for c in cases), 条件別=cases,
        修正料金コードSHA256=before, 注記='注文の価格・時刻・数量・売買エンジンは変更せず、保存済み六結果の料金・決済脚・全行時価が不変。'))


if __name__ == '__main__':
    main()
