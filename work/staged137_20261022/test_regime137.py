"""原板を読まない人工経路だけで、因果性と玉別管理を検査する。"""

import unittest

import numpy as np

from regime_engine137 import simulate


def fixture(length=180):
    """
    機能: 時刻と正常気配、二市場支持を人工生成する。
    引数: length(int)は人工原行数。
    返り値: dictは再生引数。ファイルや市場データを読み取らない。
    """
    times = 1000. + np.arange(length, dtype=float)
    mid = np.full(length, 1000.)
    market = np.zeros((length, 12))
    market[:, 0:2], market[:, 2:4] = mid[:, None], 20.
    market[:, 4:8] = (.1, .3, .1, .3)
    market[:, 8], market[:, 9], market[:, 10], market[:, 11] = times - 1., times - 31., times - 32., 1.
    return dict(times=times, bid=mid-1., ask=mid+1., qok=np.ones(length, dtype=bool), atr=np.full(length, 20.),
                market=market, phase=np.ones(length, dtype=int), start=1000., end=times[-3], us_open=900.,
                config=dict(initial_qty=2, target_qty=5, max_per_side=10, entry_cutoff=0., add_mode=0))


def price(case, values):
    """
    機能: 人工経路の価格だけを更新する。
    引数: case(dict)は人工入力、values(ndarray)は人工中値。
    返り値: None。caseの気配と二市場中値列を更新する。
    """
    case["bid"], case["ask"] = values-1., values+1.
    case["market"][:, :2] = values[:, None]


def copy_case(case):
    """
    機能: 人工入力を独立コピーする。
    引数: case(dict)は人工入力。
    返り値: dictは配列と設定を複製した入力。
    """
    return {key: value.copy() if isinstance(value, (dict, np.ndarray)) else value for key, value in case.items()}


class RegimeTests(unittest.TestCase):
    """人工経路における因果性、注文時計、独立停止を検証する。"""

    def test_next_raw_row_and_integer_fee(self):
        """
        機能: 同秒の次原行は使用でき、料金が注文ごと切捨てられることを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。失敗時はAssertionError。
        """
        case = fixture()
        case["config"]["initial_qty"] = 5
        case["times"][16] = case["times"][15]
        case["market"][:, 8] = case["times"] - 1.
        orders, events = simulate(**case)
        self.assertEqual(tuple(orders[0, [0, 1, 4, 7, 9]]), (16., 15., 5., 1., 192.))
        self.assertTrue(np.all(orders[:, 0] > orders[:, 1]))
        self.assertFalse(np.any(events[:, 1] == 4))
        self.assertEqual(orders[-1, 6], 7)

    def test_future_change_preserves_order_prefix(self):
        """
        機能: 未来の価格・特徴を改変しても、それ以前の注文を変えないことを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        first = fixture()
        second = copy_case(first)
        second["bid"][90:] = 500.
        second["ask"][90:] = 502.
        second["market"][90:, 4:8] *= -1.
        a, _ = simulate(**first)
        b, _ = simulate(**second)
        np.testing.assert_array_equal(a[a[:, 0] < 90], b[b[:, 0] < 90])

    def test_long_short_reflection(self):
        """
        機能: 同一経路の上下反転で、時刻・枚数・理由・損益が対称になることを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        up = fixture()
        values = np.full(180, 1000.)
        values[25:65] = np.linspace(1000., 1040., 40)
        values[65:85] = np.linspace(1040., 1010., 20)
        values[85:] = 1010.
        price(up, values)
        down = copy_case(up)
        down["bid"], down["ask"] = 2000.-up["ask"], 2000.-up["bid"]
        down["market"][:, :2] = 2000.-up["market"][:, :2]
        down["market"][:, 4:8] *= -1.
        a, _ = simulate(**up)
        b, _ = simulate(**down)
        cols = [0, 1, 2, 4, 6, 7, 8, 9]
        np.testing.assert_array_equal(a[:, cols], b[:, cols])
        np.testing.assert_array_equal(a[:, 3], -b[:, 3])
        np.testing.assert_allclose(a[:, 5], 2000.-b[:, 5])

    def test_addition_stop_does_not_move_original_stop(self):
        """
        機能: 追撃だけを半幅で切り、元玉は元建値の一幅停止を保つことを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["config"].update(add_mode=2)
        case["market"][18:26, 4:8] = (.01, .17, .01, .17)
        values = np.full(180, 1000.)
        values[35:60] = 1010.
        values[60:] = 999.
        price(case, values)
        orders, events = simulate(**case)
        adds = orders[(orders[:, 7] == 1) & (orders[:, 8] == 1)]
        self.assertEqual(len(adds), 1)
        self.assertEqual(adds[0, 4], 3)
        add_exit = orders[(orders[:, 7] == 0) & (orders[:, 8] == 1)]
        self.assertEqual(add_exit[0, 6], 4)
        core_exit = orders[(orders[:, 7] == 0) & (orders[:, 8] == 0)]
        self.assertEqual(core_exit[0, 6], 7)
        self.assertGreater(core_exit[0, 0], add_exit[0, 0])
        inventory = np.cumsum(orders[:, 4] * (2 * orders[:, 7]-1))
        self.assertEqual(inventory.max(), 5)
        self.assertEqual(inventory[-1], 0)
        self.assertFalse(np.any(events[:, 1] == 4))

    def test_old_support_is_not_new_support(self):
        """
        機能: 入口以前から続く強支持だけでは追撃を発注しないことを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["config"]["add_mode"] = 2
        values = np.full(180, 1000.)
        values[40:] = 1010.
        price(case, values)
        orders, _ = simulate(**case)
        self.assertFalse(np.any((orders[:, 7] == 1) & (orders[:, 8] == 1)))

    def test_gap_resets_continuity(self):
        """
        機能: 十五秒超の通信空白が支持継続の待ち時間へ算入されないことを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["times"][10:] += 30.
        case["market"][:, 8] = case["times"]-1.
        case["end"] += 30.
        orders, _ = simulate(**case)
        self.assertEqual(orders[0, 1], 25.)
        self.assertEqual(orders[0, 0], 26.)

    def test_clock_limits_size_without_forcing_exit(self):
        """
        機能: 活発帯の初回を一枚にし、区分変化だけでは保有を返さないことを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["config"]["mode"] = "time"
        case["phase"][:60] = 9
        case["phase"][60:] = 10
        orders, _ = simulate(**case)
        self.assertEqual(orders[0, 4], 1)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[-1, 6], 7)
        case["config"]["avoid_shock"] = True
        orders, _ = simulate(**case)
        self.assertEqual(orders[0, 1], 75)
        self.assertEqual(orders[0, 4], 2)

    def test_no_late_normal_quote_is_reported(self):
        """
        機能: 終場以降に正常気配がなければ、未返済を架空約定で隠さないことを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["qok"][-3:] = False
        orders, events = simulate(**case)
        self.assertEqual(len(orders), 1)
        self.assertTrue(np.any(events[:, 1] == 4))
        self.assertTrue(np.any(events[:, 1] == 5))

    def test_ten_contract_cap_and_single_addition(self):
        """
        機能: 一枚から九枚を追加しても片方向十枚を超えず、一度だけ追加することを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["config"].update(initial_qty=1, target_qty=10, add_mode=1)
        values = np.full(180, 1000.)
        values[35:] = 1010.
        price(case, values)
        orders, _ = simulate(**case)
        opens = orders[orders[:, 7] == 1]
        np.testing.assert_array_equal(opens[:, 4], (1, 9))
        inventory = np.cumsum(orders[:, 4] * (2 * orders[:, 7]-1))
        self.assertEqual(inventory.max(), 10)
        self.assertEqual(inventory[-1], 0)

    def test_unknown_does_not_establish_support_reversal(self):
        """
        機能: 一時欠測を強支持が崩れた証拠に代用せず、復帰だけで追加しないことを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["config"]["add_mode"] = 2
        case["market"][18:26, 11] = 0.
        values = np.full(180, 1000.)
        values[35:] = 1010.
        price(case, values)
        orders, _ = simulate(**case)
        self.assertFalse(np.any((orders[:, 7] == 1) & (orders[:, 8] == 1)))

    def test_two_market_reversal_requires_continuity(self):
        """
        機能: 二市場が三十秒継続して逆行してから返済することを検査する。
        引数: self(RegimeTests)はテスト対象。
        返り値: None。
        """
        case = fixture()
        case["market"][20:, 4:8] *= -1.
        orders, _ = simulate(**case)
        self.assertEqual(orders[1, 6], 6)
        self.assertEqual(orders[1, 1], 50)
        self.assertEqual(orders[1, 0], 51)


if __name__ == "__main__":
    unittest.main(verbosity=2)
