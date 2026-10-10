"""指値を含む二枝について、原本順と費用会計を人工経路で独立検査する。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / '.numba')
sys.path.insert(0, str(ROOT / 'directional'))


def load(name: str, path: Path) -> object:
    """機能: 対象売買器をファイル名で読み込む。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


directional = load('指値方向性', ROOT / 'directional/engine_round2.py')
inventory = load('指値在庫', ROOT / 'inventory/engine.py')


def check_directional() -> dict:
    """機能: 三出口の指値入口を売買鏡像・接頭辞・期限で検査する。

    引数: なし。返り値: 検査件数(dict)。
    """
    total = dict(paths=0, trades=0, prefixes=0, mutations=0, boundaries=0)
    n = 95
    paths = [np.r_[100.5, 100.5, 99.5, 98.5, np.repeat(102., n-4)],
             np.r_[100.5, 100.5, 99.5, 98.5, np.linspace(99, 110, n-4)],
             np.r_[100.5, 100.5, 99.5, 98.5, np.linspace(99, 90, n-4)],
             np.r_[100.5, 100.5, 99.5, 98.5, 103, 108, 100, np.repeat(100., n-7)]]
    for top in (True, False):
        scale, value, qty = (1., 1000., 5) if top else (20., 10., 10)
        for exit_mode in range(3):
            for path in paths:
                mirror = []
                for side in (1, -1):
                    p = (path if side == 1 else 201.-path) * scale
                    times = np.arange(n)*5.
                    seq = np.arange(n)*3
                    sig = np.array([[0., side, 8.*scale]])

                    def run(prices: np.ndarray, stamps: np.ndarray, rows: np.ndarray, finish: bool) -> tuple:
                        """機能: 同じ固定条件で対象を実行する。

                        引数: prices/stamps/rows(ndarray)、finish(bool)。返り値: 再生結果(tuple)。
                        """
                        return directional.drive.py_func(stamps, rows, prices, prices-.5*scale, prices+.5*scale,
                            sig, qty, 0, qty*2, False, value, top, 8.*scale, scale, 400., 45., 10., True,
                            finish, exit_mode, True)

                    out = run(p, times, seq, True)
                    orders, trades = out[:2]
                    assert len(orders) == 2 and len(trades) == 1
                    assert orders[0, 3] == 9, '同値への接触だけでは指値約定しない'
                    assert orders[0, 7] == (100. if side == 1 else 101.)*scale
                    assert orders[1, 3] == orders[1, 2]+3
                    fee = qty*418//10 if top else qty*11
                    np.testing.assert_array_equal(orders[:, 9], np.repeat(fee, 2))
                    cash = np.sum(-orders[:, 5]*orders[:, 6]*orders[:, 7]*value-orders[:, 9])
                    assert np.isclose(cash, trades[:, 8].sum())
                    mirror.append(cash)
                    for cut in (1, 2, 3, 4, 8, 13, 30):
                        part = run(p[:cut], times[:cut], seq[:cut], False)
                        expected = orders[orders[:, 3] < cut*3]
                        expected_t = trades[trades[:, 13] < cut*3]
                        np.testing.assert_array_equal(part[0], expected)
                        np.testing.assert_array_equal(part[1], expected_t)
                        changed = p.copy()
                        changed[cut:] = 201*scale-changed[cut:]
                        future = run(changed, times, seq, False)
                        np.testing.assert_array_equal(future[0][future[0][:, 3] < cut*3], expected)
                        np.testing.assert_array_equal(future[1][future[1][:, 13] < cut*3], expected_t)
                        total['prefixes'] += 1
                        total['mutations'] += 1
                    total['paths'] += 1
                    total['trades'] += len(trades)
                assert np.isclose(mirror[0], mirror[1])
    # ----------------------------------------
    # 執行時計・更新行数の両期限と新規締切をそれぞれ別に検査する。
    for stamp, row, expected in ((60., 2000, True), (61., 10, False), (10., 2001, False), (100., 10, False)):
        p = np.array([100.5, 98.5])
        out = directional.drive.py_func(np.array([0., stamp]), np.array([0, row]), p, p-.5, p+.5,
            np.array([[0., 1., 8.]]), 5, 0, 10, False, 1000., True, 8., 1., 400., 45., 10., True,
            False, 0, True)
        assert bool(len(out[0])) == expected
        total['boundaries'] += 1
    return total


def check_inventory() -> dict:
    """機能: 四約定方式と利益保護について、全行現金・接頭辞・境界を検査する。

    引数: なし。返り値: 検査件数(dict)。
    """
    total = dict(paths=0, trades=0, prefixes=0, mutations=0, boundaries=0)
    n = 180
    for top in (True, False):
        scale, value, qty, fee_tenths = (1., 1000., 5, 418) if top else (20., 10., 10, 110)
        for mode in range(4):
            for protect, lock in ((0, 0), (1, 0), (1, 1)):
                for style in range(3):
                    base = np.r_[100.5, 100.5, 99.5, 98.5,
                                 101 + (np.sin(np.arange(n-4)/8.)*16 if style == 0 else
                                        np.linspace(0, 20 if style == 1 else -20, n-4))]
                    for side in (1, -1):
                        p = (base if side == 1 else 201-base)*scale
                        times = np.arange(n)*10.
                        sig = np.zeros(n, dtype=np.int8)
                        sig[::31] = side

                        def run(prices: np.ndarray, stamps: np.ndarray, signs: np.ndarray, finish: bool) -> tuple:
                            """機能: 在庫売買器に固定人工経路を渡す。

                            引数: prices/stamps/signs(ndarray)、finish(bool)。返り値: 再生結果(tuple)。
                            """
                            return inventory.drive.py_func(stamps, prices-.5*scale, prices+.5*scale, signs,
                                8.*scale, scale, qty, value, fee_tenths, 1600., mode, protect, lock, finish)

                        out = run(p, times, sig, True)
                        orders, groups, curve, position = out[:4]
                        assert len(orders) == 2*len(groups) and len(groups)>0
                        cash = np.zeros(n)
                        q = np.zeros(n)
                        np.add.at(cash, orders[:, 2].astype(int), -orders[:, 6]*orders[:, 7]*orders[:, 8]*value-orders[:, 9])
                        np.add.at(q, orders[:, 2].astype(int), orders[:, 6]*orders[:, 7])
                        q = np.cumsum(q)
                        liquid = p if mode == 3 else np.where(q >= 0, p-.5*scale, p+.5*scale)
                        np.testing.assert_allclose(curve, np.cumsum(cash)+q*liquid*value, atol=1e-6, rtol=0)
                        np.testing.assert_array_equal(position, np.sign(q))
                        np.testing.assert_allclose(groups[:, 11], groups[:, 1]*(groups[:, 8]-groups[:, 7])*qty*value-2*(qty*fee_tenths//10), atol=1e-6)
                        for cut in (1, 2, 3, 4, 9, 32, 74, 141):
                            part = run(p[:cut], times[:cut], sig[:cut], False)
                            expected = orders[orders[:, 2] < cut]
                            expected_g = groups[groups[:, 4] < cut]
                            np.testing.assert_array_equal(part[0], expected)
                            np.testing.assert_array_equal(part[1], expected_g)
                            np.testing.assert_array_equal(part[2], curve[:cut])
                            future = p.copy()
                            future[cut:] = 201*scale-future[cut:]
                            changed = run(future, times, sig, False)
                            np.testing.assert_array_equal(changed[0][changed[0][:, 2] < cut], expected)
                            np.testing.assert_array_equal(changed[1][changed[1][:, 4] < cut], expected_g)
                            np.testing.assert_array_equal(changed[2][:cut], curve[:cut])
                            total['prefixes'] += 1
                            total['mutations'] += 1
                        total['paths'] += 1
                        total['trades'] += len(groups)
    # ----------------------------------------
    # 在庫枝は60秒未満だけ指値有効。触値ではなく1呼値通過を要求する。
    for stamp, price, expected in ((59., 98.5, True), (60., 98.5, False), (10., 99.5, False)):
        p = np.array([100.5, price])
        out = inventory.drive.py_func(np.array([0., stamp]), p-.5, p+.5, np.array([1, 0]), 8., 1.,
            5, 1000., 418, 1600., 1, 0, 0, False)
        assert bool(len(out[0])) == expected
        total['boundaries'] += 1
    return total


def main() -> None:
    """機能: 二枝を検査し固定コードSHA付きの証跡を保存する。

    引数: なし。返り値: なし(None)。市場データとAPIは使わない。
    """
    result = dict(合格=True, 方向性R2=check_directional(), 在庫R1R2R3=check_inventory(),
        監査範囲='待機済み指値・通過・期限・次行成行・全flat費用・未来切断。実商品の指値約定保証ではない。',
        SHA256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                (ROOT/'directional/engine_round2.py', ROOT/'inventory/engine.py')})
    (HERE/'指値二枝の独立合成監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
