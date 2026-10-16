"""参照側の変更だけを、鏡像・取消・到達・旧仕様nullで確認する。"""

import numpy as np

import common
import catalog
import engine


def fixture(symbol: str, side: int) -> tuple[dict, dict, np.ndarray]:
    """
    機能: 三参照の価格差で約定行が2/3/4へ分かれる私有例を作る。
    引数: symbol(str)、side(int)は商品と方向。
    返り値: tuple[dict,dict,ndarray]。人工呼値1、実素材のnative呼値とは別。
    """
    p = np.array([100., 100., 98., 97., 96., 100., 103., 103., 103., 103.])
    bid = np.array([99., 99., 97., 96., 95., 99., 101., 102., 102., 102.])
    ask = bid + 2
    qty = common.QUANTITY[symbol]
    f = np.array([[1, 0, 0, 1, qty, 100., 0, 1, 0, 10.], [6, 5, 0, -1, qty, 103., 0, 0, 0, 0.]])
    if side < 0:
        p = 200. - p; bid, ask = 200. - ask, 200. - bid
        f[:, 3] *= -1; f[:, 5] = 200. - f[:, 5]
    r = dict(time_s=np.arange(10, dtype=float), last=p, seq=np.arange(10), tick=1., limit=9., start=0.)
    q = dict(bid=bid, ask=ask, quote_valid=np.ones(10, bool))
    return r, q, f


def play(r: dict, q: dict, f: np.ndarray, anchors: np.ndarray, python: bool = False) -> tuple:
    """
    機能: 人工入力だけを今回の参照値実行層へ渡す。
    引数: r/q(dict)、f/anchors(ndarray)、python(bool)は数値入力と実装指定。
    返り値: tuple。実素材金融は行わない。
    """
    function = engine.simulate.py_func if python else engine.simulate
    return function(r['time_s'], r['last'], q['bid'], q['ask'], q['quote_valid'], anchors, f,
        np.zeros(len(r['last']), bool), np.zeros(len(r['last']), bool), r['limit'], 20, r['tick'], .2, False)


def run() -> None:
    """
    機能: 三参照の因果性と両方向対称、公開不正の永久取消を独立期待値で確認する。
    引数: なし。
    返り値: None。sourceと人工の証跡を保存する。
    """
    counts = 0; checks = []
    with common.cache():
        for symbol in ('TOPIX', 'NK225'):
            for side in (1, -1):
                r, q, f = fixture(symbol, side)
                for case, expected in zip(catalog.catalog(), (2, 3, 4)):
                    a = catalog.anchors(r, q, f, case['mode'])
                    actual = play(r, q, f, a); alternate = play(r, q, f, a, True)
                    for x, y in zip(actual, alternate):
                        np.testing.assert_array_equal(x, y); counts += 1
                    np.testing.assert_array_equal(actual[0][:, 0], [expected, 7])
                    row, ledger = common.ACCOUNT.account(('人工', symbol), r, q, actual, case)
                    qty = common.QUANTITY[symbol]; multiplier = 1000 if symbol == 'TOPIX' else 10
                    fee = 209 if symbol == 'TOPIX' else 110
                    assert row['収支'] == (expected + 1) * qty * multiplier - fee * 2
                    assert actual[0][0, 1] == 1 and actual[0][1, 1] == 6
                    checks.append(dict(symbol=symbol, side=side, mode=case['mode'], 新規行=expected, 返済行=7))
        # ----------------------------------------
        # 旧Lastの参照値なら正常公開時の経済を全配列で再現する。
        old = common.module('106参照値の不変旧BBOengine', common.REFERENCE / 'engine.py')
        r, q, f = fixture('TOPIX', 1); a = np.full(10, np.nan); a[1] = f[0, 5]
        current = play(r, q, f, a)
        prior = old.simulate(r['time_s'], r['last'], q['bid'], q['ask'], q['quote_valid'], f,
            np.zeros(10, bool), np.zeros(10, bool), 9., 20, 1., .2, False)
        for x, y in zip(current, prior):
            np.testing.assert_array_equal(x, y); counts += 1
        # ----------------------------------------
        # 公開行が不正なら参照値は未準備、後に正常へ戻ってもその親の新規はしない。
        q['quote_valid'][1] = False
        a = catalog.anchors(r, q, f, '即時側'); assert np.isnan(a[1])
        actual = play(r, q, f, a)
        assert len(actual[0]) == 0 and actual[7][1, 6] == 1 and actual[8][0, 17] == 95
        # ----------------------------------------
        # 到達前の初紙上返済は永久取消、同到達行の紙上返済は次正常quoteへ返済。
        r, q, f = fixture('TOPIX', 1)
        cancel = f.copy(); cancel[1, 0] = 3
        a = catalog.anchors(r, q, cancel, '受動側'); actual = play(r, q, cancel, a)
        assert len(actual[0]) == 0
        same = f.copy(); same[1, 0] = 2
        a = catalog.anchors(r, q, same, '即時側'); actual = play(r, q, same, a)
        np.testing.assert_array_equal(actual[0][:, 0], [2, 3])
        # ----------------------------------------
        # 接頭の当時入力だけを渡しても注文/清算時価/状態が一致し、未来清算しない。
        a = catalog.anchors(r, q, f, '即時側'); full = play(r, q, f, a); cut = 5
        rr = {k: v[:cut] if isinstance(v, np.ndarray) else v for k, v in r.items()}
        qq = {k: v[:cut] for k, v in q.items()}
        partial = play(rr, qq, f[f[:, 0] < cut], a[:cut])
        np.testing.assert_array_equal(full[0][full[0][:, 0] < cut], partial[0])
        np.testing.assert_array_equal(full[2][:cut], partial[2]); np.testing.assert_array_equal(full[7][:cut], partial[7])
        common.save(common.HERE / '参照値三対照と不正公開の人工検査.json', dict(全合格=True,
            PythonJIT及び旧正常null配列一致=counts, 条件=checks, 公開当行fill禁止=True,
            不正公開は永久取消=True, 先返済取消=True, 同到達返済は次quote=True,
            接頭未来清算なし=True, sourceSHA256=common.sources(), 金融再生=0, 紙上再生=0))
        print('三参照・不正公開・元BBO null・接頭人工合格', flush=True)


if __name__ == '__main__':
    run()
