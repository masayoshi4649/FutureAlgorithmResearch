"""出口だけが異なる合成経路で、次行約定と壁・追跡開始条件を確認する。"""

import json
from pathlib import Path

import numpy as np

from engine import drive


HERE = Path(__file__).resolve().parent


def run_case(prices: list[float], wall: float, side: int, mode: int) -> tuple:
    """機能: 末尾に場末判断行・約定行を設けた単一候補を再生する。

    引数: prices(list[float])、wall(float)、side/mode(int)。返り値: 売買台帳(tuple)。
    """
    times = np.r_[np.arange(len(prices) - 2, dtype=float), 1000., 1001.]
    signals = np.array([[0., float(side), 5., wall, wall + side]])
    return drive(times, np.arange(len(prices), dtype=np.int64), np.asarray(prices, float),
                 signals, 1, 1., 1000., mode, True)


def main() -> None:
    """機能: ロングとショートの対称経路で出口と約定順序を検査する。

    引数: なし。返り値: なし(None)。合格した確認点をJSONへ保存する。
    """
    checks = []
    cases = [
        ('壁が先', [100., 100., 99., 98., 98., 98.], 99., {0: (3, 3), 1: (3, 3), 2: (5, 2), 3: (3, 3)}),
        ('1幅未達の追跡線', [100., 100., 104., 99., 98., 98., 98.], 90.,
         {0: (4, 1), 1: (6, 2), 2: (4, 1), 3: (6, 2)}),
        ('1幅到達後の追跡線', [100., 100., 105., 100., 99., 99., 99.], 90.,
         {0: (4, 1), 1: (6, 2), 2: (4, 1), 3: (4, 1)}),
        ('約定直後の壁割れ', [100., 98., 97., 97., 97.], 99.,
         {0: (2, 3), 1: (2, 3), 2: (4, 2), 3: (2, 3)}),
    ]
    for name, source, wall, expected in cases:
        for side in (1, -1):
            mids = source if side == 1 else [200. - p for p in source]
            structure = wall if side == 1 else 200. - wall
            for mode in range(4):
                orders, legs, groups, counts = run_case(mids, structure, side, mode)
                exit_row, reason = expected[mode]
                assert orders.shape == (2, 13) and legs.shape == (1, 16)
                assert orders[0, 3] == 1 and orders[1, 3] == exit_row and orders[1, 9] == reason
                assert np.all(orders[:, 3] == orders[:, 2] + 1)
                assert orders[1, 8] == side * (mids[exit_row] - mids[1])
                np.testing.assert_array_equal(counts, [1, 1, 0, 0, 0, 0])
                checks.append(dict(経路=name, 方向=side, 出口='ABCD'[mode], 合格=True))
    # ----------------------------------------
    # 観測を後で追加しても、既に約定した注文と過去の判断行は変わらない。
    times = np.r_[np.arange(7, dtype=float), 1000., 1001.]
    mids = np.array([100., 100., 105., 100., 99., 102., 90., 90., 90.])
    signals = np.array([[0., 1., 5., 95., 96.]])
    for mode in range(4):
        full = drive(times, np.arange(9), mids, signals, 1, 1., 1000., mode, True)[0]
        for cut in (3, 5, 7):
            part = drive(times[:cut], np.arange(cut), mids[:cut], signals, 1, 1., 1000., mode, False)[0]
            np.testing.assert_array_equal(part, full[full[:, 3] < cut])
            changed = mids.copy()
            changed[cut:] += 40.
            altered = drive(times, np.arange(9), changed, signals, 1, 1., 1000., mode, True)[0]
            np.testing.assert_array_equal(full[full[:, 3] < cut], altered[altered[:, 3] < cut])
            checks.append(dict(経路='未来の切断と改変', 出口='ABCD'[mode], 切断行=cut, 合格=True))
    result = dict(合格=True, 件数=len(checks), 詳細=checks,
                  限界='合成検査。実原本のA再現と全注文会計は別に実施する。')
    (HERE / '出口合成検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(合格=True, 件数=len(checks)), ensure_ascii=False))


if __name__ == '__main__':
    main()
