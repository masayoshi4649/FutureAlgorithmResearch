"""元GUを変更せず気配約定を写す実行層の少数独立人工例。"""

from decimal import Decimal, ROUND_FLOOR
import numpy as np

import engine
from accounting import account
from bridge import HERE, owned_cache, runtime, save, source_hashes
from specification import CASES


def fixture(symbol: str, side: int = 1) -> tuple[dict, dict, np.ndarray]:
    """
    機能: 当行の指値到達と次行資格を区別できる小さな保存観測を作る。
    引数: symbol(str)、side(int)は商品と方向。
    返り値: tuple[dict,dict,ndarray]。紙上feedを人工に固定する。
    """
    quantity = 5 if symbol == 'TOPIX' else 10
    p = np.array([100., 100., 97., 98., 100., 104., 101., 101.])
    bid = np.array([99., 95., 97., 97., 99., 103., 100., 100.])
    ask = np.array([101., 97., 99., 98., 101., 105., 102., 102.])
    f = np.array([[1, 0, 0, 1, quantity, 100., 0, 1, 0, 10.],
                  [5, 0, 0, -1, quantity, 104., 0, 0, 0, 0.]])
    if side < 0:
        p = 200. - p; bid, ask = 200. - ask, 200. - bid
        f[:, 3] *= -1; f[:, 5] = 200. - f[:, 5]
    ready = dict(time_s=np.arange(8, dtype=float), last=p, seq=np.arange(8), tick=1., limit=7., start=0.)
    q = dict(bid=bid, ask=ask, quote_valid=np.ones(8, bool))
    return ready, q, f


def play(ready: dict, q: dict, f: np.ndarray, market: bool = False, quiet: np.ndarray | None = None,
         python: bool = False) -> tuple:
    """
    機能: 人工だけの実行層を同一引数で呼び出す。
    引数: ready/q(dict)、f/quiet(ndarray)、market/python(bool)。
    返り値: tuple。実素材の金融を呼ばない。
    """
    silent = np.zeros(len(ready['last']), bool) if quiet is None else quiet
    function = engine.simulate.py_func if python else engine.simulate
    return function(ready['time_s'], ready['last'], q['bid'], q['ask'], q['quote_valid'],
                    f, silent, np.zeros(len(silent), bool), ready['limit'], 20, ready['tick'], .2, market)


def run() -> None:
    """
    機能: 因果順序・鏡像・旧参考一致・料金後現金を独立期待値で確認する。
    引数: なし。
    返り値: None。所有域へ人工証跡を一つ保存する。
    """
    target = HERE / '人工検査.json'; assert not target.exists()
    checks = []; agreements = 0
    with owned_cache():
        rt = runtime()
        old = rt['strategy'].engine.simulate
        for symbol in ('TOPIX', 'NK225'):
            for side in (1, -1):
                r, q, f = fixture(symbol, side)
                results = {}
                for case in CASES:
                    if case['execution'] == '旧現在値参考':
                        args = (r['time_s'], r['last'], f, np.zeros(8, bool), np.zeros(8, bool), 7., 20, 1., .2, False)
                        actual = old(*args); alternate = old.py_func(*args)
                    else:
                        actual = play(r, q, f, case['execution'] == '気配成行')
                        alternate = play(r, q, f, case['execution'] == '気配成行', python=True)
                    for a, b in zip(actual, alternate):
                        np.testing.assert_array_equal(a, b); agreements += 1
                    summary, ledger = account(('人工', symbol), r, q, actual, case)
                    quantity = 5 if symbol == 'TOPIX' else 10
                    entry = {'L_D20_BBO': 98., 'E01_G_U_BBO': 99., 'L_D20_PRICE': 97.}[case['id']]
                    exitprice = 101. if case['execution'] == '旧現在値参考' else 100.
                    fee = 41.8 if symbol == 'TOPIX' else 11.
                    mult = 1000. if symbol == 'TOPIX' else 10.
                    expected = (exitprice - entry) * quantity * mult - 2 * int((Decimal(str(fee)) * quantity).to_integral_value(rounding=ROUND_FLOOR))
                    assert summary['収支'] == expected
                    entryrow = 3 if case['id'] == 'L_D20_BBO' else 2
                    np.testing.assert_array_equal(actual[0][:, 0], [entryrow, 6])
                    assert actual[0][0, 1] == 1 and actual[0][1, 1] == 5
                    results[case['id']] = dict(新規行=entryrow, 返済行=6, 収支=expected)
                checks.append(dict(商品=symbol, 方向=side, 条件=results,
                    公開当行到達でも約定なし=True, Lastだけ指値到達で気配未到達なら未約定=True))
        # ----------------------------------------
        # 同行の気配到達は紙上返済より先、反対に到達前の紙上返済は永久取消する。
        r, q, f = fixture('TOPIX')
        same = f.copy(); same[1, 0] = 3
        a = play(r, q, same)
        np.testing.assert_array_equal(a[0][:, 0], [3, 4])
        cancel = f.copy(); cancel[1, 0] = 2
        a = play(r, q, cancel); assert len(a[0]) == 0 and a[7][-1, 6] == 1
        checks.append(dict(同到達返済は新規3返済4=True, 到達前返済は新規取消=True))
        # ----------------------------------------
        # 予約返済は正常気配を待ち、紙上親が先へ進んでも古い実返済を失わない。
        r, q, f = fixture('TOPIX')
        q['quote_valid'][3:5] = False
        f = np.array([[1, 0, 0, 1, 5, 100., 0, 1, 0, 10.], [3, 0, 0, -1, 5, 100., 0, 0, 0, 0.],
                      [4, 0, 1, 1, 5, 100., 0, 1, 0, 10.], [6, 0, 1, -1, 5, 100., 0, 0, 0, 0.]])
        a = play(r, q, f, True)
        np.testing.assert_array_equal(a[0][:, 0], [2, 5])
        assert a[0][1, 1] == 3 and int(a[8][a[8][:, 2] == 1][0, 17]) == 94
        account(('人工欠測', 'TOPIX'), r, q, a, CASES[1])
        checks.append(dict(欠測でも元判断行3保持=True, 返済中の次親新規は拒否=True, 実返済5=True))
        # ----------------------------------------
        # 休止と返済期限は待機新規より先。料金は注文をまとめず部分返済ごとに切捨てる。
        r, q, f = fixture('TOPIX')
        quiet = np.zeros(8, bool); quiet[3] = True
        a = play(r, q, f, False, quiet); assert len(a[0]) == 0
        f = np.array([[1, 0, 0, 1, 5, 100., 0, 1, 0, 10.], [4, 0, 0, -1, 2, 103., 0, 0, 0, 0.],
                      [5, 0, 0, -1, 3, 104., 0, 0, 0, 0.]])
        a = play(r, q, f, True)
        s, l = account(('人工部分', 'TOPIX'), r, q, a, CASES[1])
        np.testing.assert_array_equal(l['order_fees'], [209, 83, 125]); assert s['費用'] == 417
        checks.append(dict(休止で指値取消=True, 部分返済料金=[209, 83, 125]))
        # ----------------------------------------
        # 未来側を変更しても切断前の注文・証跡・全行状態は変わらない。
        r, q, f = fixture('TOPIX')
        full = play(r, q, f)
        cut = 5
        short = {k: v[:cut] if isinstance(v, np.ndarray) else v for k, v in r.items()}
        partial = play(short, {k: v[:cut] for k, v in q.items()}, f[f[:, 0] < cut])
        np.testing.assert_array_equal(full[0][full[0][:, 0] < cut], partial[0])
        np.testing.assert_array_equal(full[2][:cut], partial[2]); np.testing.assert_array_equal(full[7][:cut], partial[7])
        q['bid'][cut:] += 100; q['ask'][cut:] += 100
        future = play(r, q, f)
        np.testing.assert_array_equal(full[0][full[0][:, 0] < cut], future[0][future[0][:, 0] < cut])
        np.testing.assert_array_equal(full[2][:cut], future[2][:cut]); np.testing.assert_array_equal(full[7][:cut], future[7][:cut])
        checks.append(dict(切断時未返済親を保持=True, 未来改変は過去注文時価へ不影響=True))
        save(target, dict(全合格=True, scope='私有人工のみ。実33素材の新金融0。',
            検査=checks, PythonJIT配列一致数=agreements, 実装SHA256=source_hashes(),
            旧execute数値変更=False, 料金の独立算式='Decimal料金×枚数の注文別ROUND_FLOOR'))
        print('気配指値・成行・旧参考の人工検査合格', flush=True)


if __name__ == '__main__':
    run()
