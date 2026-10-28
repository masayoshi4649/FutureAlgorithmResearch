"""未来の市場損益を見ずに検証する、人工価格による機械的な条件検査。"""

from copy import deepcopy
import unittest

import numpy as np

from configs import BASE, CONFIGS
from engine import prepare, simulate


def artificial(prices, cutoff=1800.0, times=None, spread=10.0):
    """
    機能: 人工中値を同じ時系列書式の最良気配へ変換する。
    引数: prices(ndarray)、cutoff(float)、times(ndarray|None)、spread(float)。
    返り値: dict。readyとquotesのみを持つ人工資料。
    """
    prices = np.asarray(prices, dtype=float)
    times = np.arange(len(prices), dtype=float) if times is None else np.asarray(times, dtype=float)
    return dict(ready=dict(time_s=times, start=0.0, limit=cutoff + 3600.0,
                           us_open=cutoff + 900.0, tick=10.0, session="人工_Night", symbol="NK225"),
                quotes=dict(bid=prices - spread * 0.5, ask=prices + spread * 0.5,
                            quote_valid=np.ones(len(prices), dtype=bool)))


def crop(data, size):
    """
    機能: 人工資料の未来部分を切り捨てる。
    引数: data(dict)、size(int)。
    返り値: dict。元資料を変更しない時系列接頭部分。
    """
    result = deepcopy(data)
    result["ready"]["time_s"] = result["ready"]["time_s"][:size]
    result["quotes"] = {key: values[:size] for key, values in result["quotes"].items()}
    return result


class EngineChecks(unittest.TestCase):
    """価格・時刻・数量・保護条件の人工検査をまとめる。"""

    def test_確定足は接頭部分で不変(self):
        """
        機能: 全期間から準備しても、過去に見える特徴値が変わらないことを確認する。
        引数: self(EngineChecks)。
        返り値: None。異常時は検査失敗。
        """
        t = np.arange(2200)
        data = artificial(60000.0 + 0.17 * t + 15.0 * np.sin(t / 97.0))
        full = prepare(data)
        for size in (619, 901, 1451):
            short = prepare(crop(data, size))
            latest = short["bar_index"][-1]
            np.testing.assert_allclose(full["bars"][:latest + 1], short["bars"][:latest + 1], equal_nan=True)
            one = simulate(data, BASE, full)["orders"]
            two = simulate(crop(data, size), BASE, short)["orders"]
            np.testing.assert_array_equal(one[one[:, 0] < size], two)

    def test_未確定の急変を入口へ使わない(self):
        """
        機能: 急騰した分足が未確定の間は傾きへ流入しないことを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        prices = np.full(660, 60000.0)
        prices[600:] = 61000.0
        result = simulate(artificial(prices), BASE)
        self.assertEqual(len(result["orders"]), 0)

    def test_売買は上下対称(self):
        """
        機能: 全価格を上下反転すると、同時刻・同枚数で反対売買になることを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        t = np.arange(2300)
        prices = 60000.0 + np.where(t < 1050, t * 0.4, 420.0 - (t - 1050) * 0.55)
        a = simulate(artificial(prices), BASE)["orders"]
        b = simulate(artificial(120000.0 - prices), BASE)["orders"]
        self.assertGreater(len(a), 0)
        np.testing.assert_array_equal(a[:, [0, 1, 2, 4, 6, 7, 8, 9]], b[:, [0, 1, 2, 4, 6, 7, 8, 9]])
        np.testing.assert_array_equal(a[:, 3], -b[:, 3])
        np.testing.assert_allclose(a[:, 5] + b[:, 5], 120000.0)

    def test_判断の次の正常気配で約定(self):
        """
        機能: 判断足約定と異常気配約定を禁止し、正常気配まで待つことを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        data = artificial(60000.0 + np.arange(1600) * 0.2)
        first = simulate(data, BASE)["orders"][0]
        decision = int(first[1])
        data["quotes"]["quote_valid"][decision + 1:decision + 4] = False
        result = simulate(data, BASE)["orders"]
        self.assertEqual(int(result[0, 0]), decision + 4)
        for order in result:
            index, judged = map(int, order[:2])
            self.assertGreater(index, judged)
            self.assertTrue(data["quotes"]["quote_valid"][index])
            self.assertFalse(data["quotes"]["quote_valid"][judged + 1:index].any())
            actual = data["quotes"]["ask" if order[3] > 0 else "bid"][index]
            self.assertEqual(order[5], actual)

    def test_境界を越えた新規は取り消す(self):
        """
        機能: 境界の直前に成立した新規が境界後の気配で約定しないことを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        data = artificial(60000.0 + np.arange(900) * 0.2)
        decision = int(simulate(data, BASE)["orders"][0, 1])
        data["ready"]["us_open"] = decision + 1.0 + 900.0
        result = simulate(data, BASE)
        self.assertEqual(len(result["orders"]), 0)
        self.assertEqual(result["diagnostics"][-1]["reason_code"], 7.0)

    def test_境界で次正常気配へ全返済(self):
        """
        機能: 区間終了で指標を待たずに返済し、異常気配を飛ばすことを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        data = artificial(60000.0 + np.arange(1300) * 0.2, cutoff=1100.0)
        data["quotes"]["quote_valid"][1100:1104] = False
        result = simulate(data, BASE)
        closed = result["orders"][result["orders"][:, 7] == 0]
        self.assertGreater(len(closed), 0)
        self.assertTrue(np.all(closed[:, 0] == 1104))
        self.assertTrue(np.all(closed[:, 1] == 1100))
        self.assertFalse(result["positions"])

    def test_途中の末尾を架空決済しない(self):
        """
        機能: 現在セッションの末尾では残玉をそのまま返すことを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        result = simulate(artificial(60000.0 + np.arange(900) * 0.2), BASE)
        self.assertGreater(len(result["positions"]), 0)
        self.assertFalse(np.any(result["orders"][:, 7] == 0))

    def test_欠測分足を補間しない(self):
        """
        機能: 観測のない分足を作らず、その窓を未知にすることを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        t = np.r_[np.arange(600), np.arange(780, 1000)]
        prepared = prepare(artificial(60000.0 + t * 0.2, times=t))
        self.assertTrue(np.isnan(prepared["bar_close"][10:13]).all())
        self.assertTrue(np.isnan(prepared["bars"][13:16, 1]).all())

    def test_欠測を入口確認時間に算入しない(self):
        """
        機能: 確認中に通信欠測があると確認時計が再開時にリセットされることを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        data = artificial(60000.0 + np.arange(900) * 0.2)
        data["quotes"]["quote_valid"][608:620] = False
        result = simulate(data, BASE)
        self.assertGreaterEqual(result["orders"][0, 1], 635)

    def test_黒字の方向反証だけでは返済しない(self):
        """
        機能: 勢いが逆転しても黒字の未保護玉を減速利確しないことを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        t = np.arange(1550)
        prices = 60000.0 + np.where(t < 1100, t * 0.25, 275.0 - (t - 1100) * 0.1)
        config = deepcopy(BASE)
        config.update(quantities=[10], add_gain_points=[], activation_points=1000.0, trail_points=80.0)
        result = simulate(artificial(prices), config)
        self.assertTrue(result["positions"])
        self.assertGreater(result["positions"][0]["unrealized_points"], 0)
        self.assertFalse(np.any(result["orders"][:, 7] == 0))

    def test_損切りは指標欠測でも動く(self):
        """
        機能: 価格の急変と指標欠測が重なっても、固定損切りが発注されることを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        prices = 60000.0 + np.arange(1000) * 0.2
        prices[850:] -= 500.0
        data = artificial(prices)
        data["quotes"]["quote_valid"][720:850] = False
        result = simulate(data, BASE)
        close = result["orders"][(result["orders"][:, 7] == 0) & (result["orders"][:, 6] == 3)]
        self.assertGreater(len(close), 0)
        self.assertTrue(np.all(close[:, 1] == 850))
        self.assertTrue(np.all(close[:, 0] == 851))

    def test_トレール発動と玉別価格(self):
        """
        機能: 利益到達後のトレール返済と、追撃による既存停止価格不変を確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        t = np.arange(1500)
        prices = 60000.0 + np.where(t < 1100, t * 0.6, 660.0 - (t - 1100) * 0.6)
        result = simulate(artificial(prices), BASE)
        entries = result["orders"][result["orders"][:, 7] == 1]
        self.assertGreaterEqual(len(entries), 2)
        trailing = [event for event in result["diagnostics"] if event["reason_code"] == 5]
        self.assertTrue(trailing)
        for event in trailing:
            opening = entries[(entries[:, 2] == event["parent"]) & (entries[:, 8] == event["ticket"])][0]
            self.assertGreaterEqual(event["side"] * (event["best_price"] - opening[5]), BASE["activation_points"])
            self.assertGreaterEqual(event["side"] * (event["best_price"] - event["decision_price"]), BASE["trail_points"])
            self.assertTrue(event["protected"])

    def test_全条件の玉上限と親別清算(self):
        """
        機能: 16条件を人工往復価格で検査し、最大10枚と完了時ゼロ玉を確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        t = np.arange(3000)
        prices = 60000.0 + 250.0 * np.sin(t / 260.0) + 0.03 * t
        for config in CONFIGS:
            result = simulate(artificial(prices, cutoff=2600.0), config)
            held = 0
            for order in result["orders"]:
                held += int(order[4]) * (1 if order[7] else -1)
                self.assertGreaterEqual(held, 0)
                self.assertLessEqual(held, 10)
            self.assertEqual(held, 0)
            self.assertFalse(result["positions"])

    def test_減速と上向き加速を買い方向と混同しない(self):
        """
        機能: 下落速度が鈍るだけの価格で、正の加速度を買い条件に誤用しないことを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        t = np.arange(1000)
        prices = 61000.0 - 0.8 * t + 0.0002 * t * t
        config = deepcopy(CONFIGS[1])
        result = simulate(artificial(prices), config)
        self.assertEqual(len(result["orders"]), 0)

    def test_トレールも指標欠測時に動く(self):
        """
        機能: 利益保護を開始した玉は、傾きが未知になっても価格で返済することを確認する。
        引数: self(EngineChecks)。
        返り値: None。
        """
        prices = 60000.0 + np.arange(1250) * 0.6
        prices[1150:] = 60479.0
        data = artificial(prices)
        data["quotes"]["quote_valid"][1000:1150] = False
        result = simulate(data, BASE)
        events = [e for e in result["diagnostics"] if e["reason_code"] == 5]
        self.assertTrue(events)
        self.assertTrue(all(e["index"] == 1150 for e in events))
        self.assertTrue(all(np.isnan(e["fast_speed"]) for e in events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
