"""数量縮小と同約定の反対玉について、注文器に依存しない枠別会計を検算する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def reconstruct(prices: np.ndarray, events: list[dict], cap: int) -> np.ndarray:
    """機能: 枠と脚の新規・返済から現金、買売数量、全時価、実現、含みを再構成する。

    引数: prices (ndarray)、events (list[dict])、cap (int)。返り値: 六列の全行会計 (ndarray)。
    価格単位の独立会計であり、新規や返済の判断条件は生成しない。
    """
    assert prices.ndim == 1 and np.isfinite(prices).all() and cap > 0
    orders = {}
    for event in events:
        assert isinstance(event['row'], int) and event['row'] >= 0
        if event['row'] < len(prices):
            orders.setdefault(event['row'], []).append(event)
    cash = realized = 0.
    positions = {}
    output = np.zeros((len(prices), 6), dtype=float)
    for row, price in enumerate(prices):
        for event in orders.get(row, []):
            key = event['role'], event['slot']
            side, fill = event['side'], float(event['price'])
            assert side in (-1, 1) and np.isfinite(fill)
            if event['action'] == 'open':
                assert key not in positions, '同一枠脚の二重新規'
                positions[key] = side, fill
                cash -= side * fill
            elif event['action'] == 'close':
                assert key in positions, '存在しない枠脚の返済'
                old_side, initial = positions.pop(key)
                assert side == old_side
                cash += side * fill
                realized += side * (fill - initial)
            else:
                raise AssertionError('不明な注文種別')
        long = sum(side == 1 for side, initial in positions.values())
        short = sum(side == -1 for side, initial in positions.values())
        assert long <= cap and short <= cap
        unrealized = sum(side * (price - initial) for side, initial in positions.values())
        equity = cash + (long - short) * price
        np.testing.assert_allclose(equity, realized + unrealized, atol=1e-8, rtol=0)
        output[row] = cash, long, short, equity, realized, unrealized
    return output


def orders(row: int, action: str, role: str, slots: list[int], side: int, price: float) -> list[dict]:
    """機能: 同じ行・価格で処理する一枚ごとの枠注文を作る。

    引数: row/side (int)、action/role (str)、slots (list[int])、price (float)。
    返り値: 独立会計用の枠注文 (list[dict])。
    """
    return [dict(row=row, action=action, role=role, slot=slot, side=side, price=price) for slot in slots]


def equity_equivalence(prices: np.ndarray, net_events: list[dict], hedge_events: list[dict], cap: int) -> tuple:
    """機能: 純数量方式と反対玉方式の全行経済同値を確認する。

    引数: prices (ndarray)、各events (list[dict])、cap (int)。返り値: 二方式の曲線 (tuple[ndarray,ndarray])。
    実現と含みの内訳を同一と仮定せず、現金・純在庫・時価・最大下落を比較する。
    """
    net = reconstruct(prices, net_events, cap)
    hedge = reconstruct(prices, hedge_events, cap)
    np.testing.assert_allclose(net[:, 0], hedge[:, 0], atol=1e-8, rtol=0)
    np.testing.assert_allclose(net[:, 1] - net[:, 2], hedge[:, 1] - hedge[:, 2], atol=0, rtol=0)
    np.testing.assert_allclose(net[:, 3], hedge[:, 3], atol=1e-8, rtol=0)
    for curve in (net, hedge):
        assert np.all(curve[-1, 1:3] == 0)
        np.testing.assert_allclose(curve[-1, 3], curve[-1, 4], atol=1e-8, rtol=0)
    return net, hedge


def main() -> None:
    """機能: 復元有無・退役・反射・破損の人工会計を確認し、証跡を保存する。

    引数: なし。返り値: なし (None)。売買注文器や実データは使用しない。
    """
    checks = {}
    prices = np.array([100., 98., 101., 120., 140.])
    initial = orders(0, 'open', 'main', [1,2,3,4,5], 1, 100.)
    baseline = initial + orders(3,'close','main',[1,2],1,120.) + orders(4,'close','main',[3,4,5],1,140.)
    net = initial + orders(1,'close','main',[1,2],1,98.) + orders(2,'open','main',[1,2],1,101.) + baseline[5:]
    hedge = initial + orders(1,'open','cover',[1,2],-1,98.) + orders(2,'close','cover',[1,2],-1,101.) + baseline[5:]
    n, h = equity_equivalence(prices, net, hedge, 10)
    base = reconstruct(prices, baseline, 10)
    assert base[-1,3] == 160. and n[-1,3] == 154. and n[-1,3] - base[-1,3] == -6.
    checks['復元有りの154と基準差負6'] = True
    checks['復元有りの全行現金純在庫時価同値'] = True
    assert n[1,4] != h[1,4] and n[1,5] != h[1,5]
    checks['実現含み内訳の差を利益源にしない'] = True
    net2 = initial + orders(1,'close','main',[1,2],1,98.) + orders(4,'close','main',[3,4,5],1,140.)
    hedge2 = initial + orders(1,'open','cover',[1,2],-1,98.) + orders(3,'close','main',[1,2],1,120.) + orders(3,'close','cover',[1,2],-1,120.) + orders(4,'close','main',[3,4,5],1,140.)
    n2, h2 = equity_equivalence(prices, net2, hedge2, 10)
    assert n2[-1,3] == 116. and n2[-1,3] - base[-1,3] == -44.
    checks['復元なし116と退役時の架空利益禁止'] = True
    checks['被カバー枠退役の同価格二脚終了で全行同値'] = True
    reflected = deepcopy(net)
    for event in reflected:
        event['side'] *= -1; event['price'] = 300. - event['price']
    mirror = reconstruct(300. - prices, reflected, 10)
    np.testing.assert_allclose(mirror[:,3:], n[:,3:], atol=1e-8, rtol=0)
    checks['上下反射の全行時価実現含み一致'] = True
    for count in (2,3,4):
        prefix = reconstruct(prices[:count], net, 10)
        np.testing.assert_allclose(prefix, n[:count], atol=1e-8, rtol=0)
    checks['会計接頭部3点一致'] = True
    broken = deepcopy(hedge2)
    for event in broken:
        if event['role'] == 'cover' and event['action'] == 'close':
            event['row'] = 4; event['price'] = 140.
    rejected = 0
    try:
        equity_equivalence(prices, net2, broken, 10)
    except AssertionError:
        rejected += 1
    checks['片脚だけ後行へ送る非同値を拒否'] = rejected == 1
    for wrong in (initial + initial[:1], orders(0,'close','main',[1],1,100.),
                  orders(0,'open','main',list(range(11)),1,100.)):
        try:
            reconstruct(prices, wrong, 10)
        except AssertionError:
            rejected += 1
    assert rejected == 4
    checks['二重新規不存在返済上限超過を拒否'] = True
    value = dict(全人工会計合格=True, 検査数=len(checks), 検査=checks, 破損拒否数=rejected,
        位置付け='独立会計の期待値。新しい売買注文器の機能・因果監査合格を意味しない。',
        新実データ損益=False, 注文器使用=False, API取得数=0, 現在保存物使用=False,
        実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE/'partial_accounting_oracles.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('独立会計の人工期待値',len(checks),'群合格。新注文器/実損益は未使用。')


if __name__ == '__main__':
    main()
