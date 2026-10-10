"""方向性枝の三出口について、次行・鏡像・未来切断・組会計を独立に確認する。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
BRANCH = HERE.parent / 'directional'
os.environ['NUMBA_CACHE_DIR'] = str(HERE / '.numba')
sys.path.insert(0, str(BRANCH))
spec = importlib.util.spec_from_file_location('監査対象方向性', BRANCH / 'engine.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def run_path(mids: np.ndarray, side: int, mode: int, symbol: str, finish: bool = True, pyramid: bool = True) -> tuple:
    """機能: 人工の生気配をそのまま三出口の売買器へ渡す。

    引数: mids(ndarray)、side/mode(int)、symbol(str)、finish/pyramid(bool)。
    返り値: 注文・返済等(tuple)。原本又は実損益を使わない。
    """
    n = len(mids)
    times = np.arange(n, dtype=float) * 5
    seq = np.arange(n, dtype=np.int64) * 3
    qty, value, top = (5, 1000., True) if symbol == 'TOPIX' else (10, 10., False)
    scale = 1. if top else 20.
    signals = np.array([[0, side, 4. * scale]], dtype=float)
    return engine.drive.py_func(times, seq, mids, mids - .25 * scale, mids + .25 * scale, signals,
        qty, 2 if top else 4, 10 if top else 20, pyramid, value, top, 4. * scale, .5 * scale,
        400., 45., 10., True, finish, mode)


def verify_account(orders: np.ndarray, trades: np.ndarray, symbol: str, mids: np.ndarray) -> None:
    """機能: 原本価格・費用・全flat組の現金損益を別会計で照合する。

    引数: orders/trades/mids(ndarray)、symbol(str)。返り値: なし(None)。
    """
    value = 1000. if symbol == 'TOPIX' else 10.
    assert np.all(orders[:, 3] - orders[:, 2] == 3)
    index = (orders[:, 3] / 3).astype(int)
    half_spread = .25 if symbol == 'TOPIX' else 5.
    np.testing.assert_array_equal(orders[:, 7], mids[index] + np.where(orders[:, 5] > 0, half_spread, -half_spread))
    fee = (orders[:, 6].astype(int) * 418) // 10 if symbol == 'TOPIX' else orders[:, 6] * 11
    np.testing.assert_array_equal(orders[:, 9], fee)
    position = np.cumsum(orders[:, 5] * orders[:, 6])
    assert position[-1] == 0 and np.max(np.abs(position)) <= (10 if symbol == 'TOPIX' else 20)
    cash = np.sum(-orders[:, 5] * orders[:, 6] * orders[:, 7] * value - fee)
    assert abs(cash - trades[:, 8].sum()) < 1e-7
    assert abs(fee.sum() - trades[:, 7].sum()) < 1e-7
    assert len(np.unique(trades[:, 21])) == 1


def main() -> None:
    """機能: 多経路・左右対称・各prefixと未来改変を検証し証跡を保存する。

    引数: なし。返り値: なし(None)。実装を変更せず、人工経路のみを再生する。
    """
    paths = [np.array(x, dtype=float) for x in (
        [100] * 18,
        [100, 100, 101, 102.5, 103, 104.5, 104.5, 102.5, 100, 99, 98, 98, 98, 98, 98, 98, 98, 98],
        [100, 100, 98, 96, 94, 93, 95, 100, 105, 106, 105, 103, 101, 100, 100, 100, 100, 100],
        [100, 100, 102.75, 100, 98, 99, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
        [100, 100, 105, 110, 113, 115, 111, 105, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
    )]
    tests = prefixes = mutations = 0
    protect_loss = []
    for symbol in ('TOPIX', 'NK225'):
        for mode in range(3):
            for path in paths:
                mirror_net = []
                for side in (1, -1):
                    prices = (path if side > 0 else 200 - path) * (1. if symbol == 'TOPIX' else 20.)
                    full = run_path(prices, side, mode, symbol)
                    verify_account(full[0], full[1], symbol, prices)
                    mirror_net.append(float(full[1][:, 8].sum()))
                    if mode in (1, 2):
                        assert not np.any(full[0][:, 4] == 3), '固定利確より先に追加した'
                    for cut in (2, 4, 7, 10, 14):
                        expected_orders = full[0][full[0][:, 3] < cut * 3]
                        expected_trades = full[1][full[1][:, 13] < cut * 3]
                        part = run_path(prices[:cut], side, mode, symbol, finish=False)
                        np.testing.assert_array_equal(part[0], expected_orders)
                        np.testing.assert_array_equal(part[1], expected_trades)
                        prefixes += 1
                        future = prices.copy()
                        future[cut:] = (300 if symbol == 'TOPIX' else 6000) - future[cut:]
                        changed = run_path(future, side, mode, symbol, finish=False)
                        np.testing.assert_array_equal(changed[0][changed[0][:, 3] < cut * 3], expected_orders)
                        np.testing.assert_array_equal(changed[1][changed[1][:, 13] < cut * 3], expected_trades)
                        mutations += 1
                    for t in full[1]:
                        if t[9] == 7 and t[8] < 0:
                            protect_loss.append(dict(銘柄=symbol, 方向=side, 費用後=float(t[8])))
                    tests += 1
                assert abs(mirror_net[0] - mirror_net[1]) < 1e-7
    assert protect_loss, '建値保護でも次行で赤字になり得る人工例を確認する'
    result = dict(合格=True, 人工再生=tests, 接頭辞比較=prefixes, 未来改変比較=mutations,
        次有効行約定=True, 売買鏡像=True, 全flat現金会計=True,
        固定利確出口は追加より優先=True, 保護判断後の価格飛び損失例=protect_loss,
        engine_SHA256=hashlib.sha256((BRANCH / 'engine.py').read_bytes()).hexdigest())
    (HERE / '方向性三出口の独立合成監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
