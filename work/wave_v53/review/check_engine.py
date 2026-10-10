"""売買管理の独立した合成事例を検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from engine import execute, protected_stop


def ready(prices: list, times: list | None = None, symbol: str = 'TOPIX', limit: float = 2000.) -> dict:
    """機能: 原本行に対応する最小限の試験入力を作る。

    引数: prices(list)、times(list|None)、symbol(str)、limit(float)。
    返り値: 入力辞書(dict)。
    """
    return dict(last=np.array(prices, float), time_s=np.array(times if times is not None else range(len(prices)), float),
                seq=np.arange(len(prices), dtype=np.int64) + 100, symbol=symbol, session='合成試験', start=0., limit=limit)


def row(index: int, signal: int = 0, raw: int = 0, invalid: float = 98., target: float = np.nan,
        atr: float = 2., regime: int = 2, trend: int = 0, book: int = 0,
        long: float = np.nan, short: float = np.nan) -> list:
    """機能: 明示した条件だけを持つ判断行を作る。

    引数: index/signal/raw/regime/trend/book(int)、価格と幅(float)。返り値: 判断行(list)。
    """
    return [index, signal, raw, invalid, target, atr, regime, trend, book, long, short]


def main() -> None:
    """機能: 事前に手計算した次行約定と分割会計を検証し証跡を保存する。

    引数: なし。返り値: なし(None)。
    """
    checks = []
    x = ready([100, 100, 97, 96])
    z = execute(x, [row(0, 1)], False)
    assert z['net'] == -20000 and z['orders'][0][3] == 101 and z['orders'][1][2:4] == [102., 103.]
    checks.append('新規と初期損切りは判断直後の次有効行で約定')

    for symbol, first, half, net in [('TOPIX', 5, 2, 5500.), ('NK225', 10, 5, 125.)]:
        x = ready([100, 100, 101, 102, 101, 100.5], symbol=symbol)
        ds = [row(0, 1, target=101), row(2)]
        z = execute(x, ds, True)
        assert [o[6] for o in z['orders']] == [first, half, first-half]
        assert [o[11] for o in z['orders']] == [first, first-half, 0]
        assert z['cycles'] == 1 and z['repayment_legs'] == 2 and z['net'] == net
        mirrored = x.copy()
        mirrored['last'] = 200. - x['last']
        ms = [row(0, -1, invalid=102, target=99), row(2, invalid=102)]
        mz = execute(mirrored, ms, True)
        assert mz['net'] == z['net'] and mz['group_nets'] == z['group_nets']
        np.testing.assert_allclose(mz['curve'], z['curve'], atol=1e-8)
    checks.append('両銘柄の一度だけ半減・残数・上下反射・分割会計')

    x = ready([100, 100, 104, 103.2, 103.1])
    z = execute(x, [row(0, 1, regime=1, trend=1), row(3, regime=1, trend=1, book=-1)], True)
    assert z['orders'][-1][2:4] == [103., 104.] and z['orders'][-1][9] == 2
    checks.append('最新板の悪化で幅を縮めた同じ判断行から次行全返済')

    x = ready([100, 100, 100.2, 100.1], [0, 1, 301, 302])
    z = execute(x, [row(0, 1, regime=1, trend=1)], True)
    assert z['orders'][-1][9] == 5 and z['orders'][-1][0:2] == [301., 302.]
    checks.append('五分経過の未進展撤退')

    x = ready([100, 100, 100.7, 100.7, 100.7, 100.7], [0, 1, 100, 700, 901, 902])
    z = execute(x, [row(0, 1), row(3, regime=1, trend=1)], True)
    assert z['orders'][-1][9] == 4 and z['orders'][-1][0] == 901.
    checks.append('状況が変わっても保有期限は延長しない')

    x = ready([100, 100, 100.8, 100.8, 100.8], [0, 1, 500, 600, 601], limit=600.)
    z = execute(x, [row(0, 1, regime=1, trend=1)], True)
    assert z['orders'][-1][9] == 8 and z['orders'][-1][0:2] == [600., 601.]
    checks.append('場末は残数を全返済し次の場へ持ち越さない')

    times = [0, 1, 2, 3, 4, 5, 65, 66, 67, 68, 128, 129, 968, 969]
    ds = [row(0, 1, target=101), row(2), row(6, 1), row(10, 1), row(12, 1)]
    for first_fill, final_fill, expected in [(90, 101, [0., 65., 968.]), (130, 99, [0., 65., 128.])]:
        prices = [100, 100, 101, first_fill, final_fill, final_fill, 100, 100, 97, 97, 100, 100, 100, 100]
        z = execute(ready(prices, times), ds, True, finish=False)
        opens = [o[0] for o in z['orders'] if o[4] == 1]
        assert opens == expected, (first_fill, opens)
    checks.append('最後の返済脚でなく全返済脚の合計で連敗休止を決める')

    rng = np.random.default_rng(5353)
    for side in (-1, 1):
        stop, best = 100-side*2, 100.
        for i in range(1000):
            best += side*float(rng.uniform(0, .02))
            following = protected_stop(stop, side, best, 100., 2., float(rng.uniform(.5, 5)),
                                       float(i*3), int(rng.integers(0, 3)), int(rng.integers(-1, 2)), int(rng.integers(-1, 2)))
            assert side*(following-stop) >= 0
            stop = following
    checks.append('二千回の状況変化でも保護線を不利方向へ戻さない')

    x = ready([100, 100, 101, 102, 101, 100.5])
    ds = np.asarray([row(0, 1, target=101), row(2)], float)
    full = execute(x, ds, True)
    for cut in range(2, len(x['seq'])):
        part = {k: v[:cut] if isinstance(v, np.ndarray) else v for k, v in x.items()}
        actual = execute(part, ds[ds[:, 0] < cut], True, finish=False)
        expected = [o for o in full['orders'] if o[3] < x['seq'][cut]]
        assert actual['orders'] == expected
        altered = {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in x.items()}
        altered['last'][cut:] = [600 + 17*i for i in range(len(x['last'])-cut)]
        az = execute(altered, ds, True, finish=False)
        assert [o for o in az['orders'] if o[3] < x['seq'][cut]] == expected
    checks.append('四切断点の途中打切りと未来価格改変は過去の注文を変えない')

    try:
        execute(ready([100, 100]), [row(0, 1)], True)
    except ValueError:
        checks.append('未返済のまま終了した入力を正常な完了扱いにしない')
    else:
        raise AssertionError('未返済検査なし')

    result = dict(合格=True, 検査数=len(checks), 検査=checks,
                  実装SHA256=hashlib.sha256((HERE.parent/'engine.py').read_bytes()).hexdigest())
    (HERE/'管理の合成検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
