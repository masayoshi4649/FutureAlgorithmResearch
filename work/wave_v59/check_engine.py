"""小幅回収の保護・利確・状態選択・次行会計を、損益を見る前に合成検査する。"""

import json
from pathlib import Path

import numpy as np

from engine import drive, execute


HERE = Path(__file__).resolve().parent


def case(prices: list[float], mode: int, width: float = 2., side: int = 1,
         lower: float = np.nan, upper: float = np.nan, regime: int = 0,
         automatic: bool = False, times: np.ndarray | None = None, tick: float = 1.) -> tuple:
    """機能: 末尾に場末返済行を持つ一候補の経路を再生する。

    引数: prices(list[float])、mode/side/regime(int)、width/lower/upper/tick(float)、automatic(bool)、times(ndarray|None)。
    返り値: 売買台帳(tuple)。反対方向は価格と境界を対称変換する。
    """
    mids = np.asarray(prices, float)
    if times is None:
        times = np.r_[np.arange(len(mids) - 2, dtype=float), 1000., 1001.]
    if side < 0:
        mids = 200. - mids
        lower, upper = 200. - upper, 200. - lower
    signals = np.array([[0., side, width, lower, upper, regime]], float)
    return drive(times, np.arange(len(mids)), mids, signals, 1, 1., tick, 1000., mode, automatic, True)


def main() -> None:
    """機能: 価格閾値・優先順・自動切替と中値/気配の独立会計を照合する。

    引数: なし。返り値: なし(None)。合格件数を日本語JSONへ保存する。
    """
    checks = []
    paths = [
        ('初期逆行', [100., 100., 98., 97., 97., 97.], {1: (3, 1), 2: (3, 1), 3: (3, 3)}),
        ('固定利確と次行ずれ', [100., 100., 102., 103., 103., 103.], {1: (3, 2), 2: (4, 2), 3: (5, 6)}),
        ('半幅順行から保護', [100., 100., 101., 100., 99., 99., 99.], {1: (6, 6), 2: (4, 3), 3: (5, 3)}),
    ]
    for name, prices, expected in paths:
        for side in (1, -1):
            for mode in (1, 2, 3):
                orders, legs, _, counts, modes = case(prices, mode, side=side)
                assert orders[1, 3] == expected[mode][0] and orders[1, 9] == expected[mode][1]
                assert np.all(orders[:, 3] == orders[:, 2] + 1)
                np.testing.assert_array_equal(counts, [1, 1, 0, 0, 0, 0])
                np.testing.assert_array_equal(modes, [[mode, 0]])
                assert legs[0, 6] == side * (orders[1, 7] - orders[0, 7])
                checks.append(dict(検査=name, 方向=side, 出口=mode))
    # ----------------------------------------
    # 境界の一致は許容し、外側への観測で返済する。初期stopとの同時成立はstopを優先する。
    for side in (1, -1):
        for mode in (1, 2, 3):
            orders = case([100., 100., 102., 103., 104., 104.], mode, 10., side, 90., 102.)[0]
            assert orders[1, 2] == 3 and orders[1, 3] == 4 and orders[1, 9] == 5
            orders = case([100., 100., 98., 97., 97., 97.], mode, 2., side, 99., 110.)[0]
            assert orders[1, 9] == (3 if mode == 3 else 1)
            checks.append(dict(検査='範囲の厳密逸脱とstop優先', 方向=side, 出口=mode))
    for automatic in (False, True):
        for regime in (0, 1):
            orders, _, _, _, modes = case([100., 100., 102., 103., 103., 103.], 1,
                                           regime=regime, automatic=automatic)
            selected = 3 if automatic and regime == 1 else 1
            assert modes[0, 0] == selected and orders[1, 9] == (6 if selected == 3 else 2)
            checks.append(dict(検査='自動切替の適用範囲', 自動=automatic, 状態=regime))
    # ----------------------------------------
    # 10分は約定時計の約定時から数え、X3には適用しない。切上げは半幅と1.5幅を別計算する。
    times = np.array([0., 1., 600., 601., 602., 1000., 1001.])
    for mode in (1, 2, 3):
        orders = case([100.] * 7, mode, times=times)[0]
        assert orders[1, 2] == (5 if mode == 3 else 3)
        assert orders[1, 9] == (6 if mode == 3 else 4)
        checks.append(dict(検査='10分の起点と適用範囲', 出口=mode))
    rounded = case([100., 100., 101., 100., 102., 100., 99., 99., 99.], 2, width=3.)[0]
    assert rounded[1, 2] == 5 and rounded[1, 9] == 3
    checks.append(dict(検査='半幅切上げは2呼値'))
    # ----------------------------------------
    # 中値利益と往復気配差を個別計算する。未決済接頭辞も計算できなければならない。
    mids = np.array([100., 100., 102., 103., 103., 103.])
    seqs = np.arange(len(mids))
    ready = dict(time_s=np.array([0., 1., 2., 3., 1000., 1001.]), seq=seqs,
                 tick=1., limit=1000., session='合成', symbol='検査')
    quotes = dict(mid=mids, bid=mids - .5, ask=mids + .5, seq=seqs)
    signals = np.array([[0., 1., 2., np.nan, np.nan, 0.]])
    result = execute(ready, quotes, signals, 5, 1000., 1)
    assert result['net'] == 15000. and result['sensitivity']['売買気配']['net'] == 10000.
    assert result['sensitivity']['売買気配']['drawdown'] >= 2500.
    checks.append(dict(検査='中値と売買気配の会計'))
    for cut in (2, 3, 4):
        part_ready = {k: (v[:cut] if isinstance(v, np.ndarray) else v) for k, v in ready.items()}
        part_quotes = {k: v[:cut] for k, v in quotes.items()}
        part = execute(part_ready, part_quotes, signals, 5, 1000., 1, finish=False)
        expected = [o for o in result['orders'] if o[3] < cut]
        np.testing.assert_array_equal(part['orders'], expected)
        checks.append(dict(検査='未決済接頭辞', 切断行=cut))
    path = HERE / 'review/売買器の合成検査.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(合格=True, 件数=len(checks), 詳細=checks), ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(合格=True, 件数=len(checks)), ensure_ascii=False))


if __name__ == '__main__':
    main()
