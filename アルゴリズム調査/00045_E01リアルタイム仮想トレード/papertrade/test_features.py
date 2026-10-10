"""特徴量の公開順・過去参照・復元を外部通信なしで検証する。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import unittest

from .features import FeatureEngine, timestamp


START = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc).timestamp()


def candle(start: float, close: float, width: float = 4.0, closed: bool = True) -> dict:
    """機能: 価格関係が正しい検査用の足を作る。

    引数: start/close/width(float)、closed(bool)。返り値: controller互換の足(dict)。
    """
    return {"time": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "open": close, "high": close + width / 2, "low": close - width / 2,
            "close": close, "volume": 1, "volumeComplete": True, "closed": closed}


def book(at: float, mid: float, price: float | None = None) -> dict:
    """機能: 検査用の最良気配を生板JSON形へする。

    引数: at/mid(float)、price(float|None)。返り値: 板PUSH形(dict)。
    """
    return {"CurrentPriceTime": datetime.fromtimestamp(at, timezone.utc).isoformat(),
            "CurrentPrice": mid if price is None else price,
            "Buy1": {"Price": mid - 0.5, "Qty": 2},
            "Sell1": {"Price": mid + 0.5, "Qty": 3}}


def warmed() -> tuple[FeatureEngine, float]:
    """機能: 両銘柄の過去足を取得し上向きEMAを暖機する。

    引数: なし。返り値: 特徴量器と実受信時刻(tuple[FeatureEngine,float])。
    """
    engine = FeatureEngine("2026-10-02_Day", START)
    received = START + 95 * 60
    for symbol, scale in (("TOPIX", 1), ("NK225", 20)):
        engine.ingest_candles(symbol, 300,
            [candle(START + i * 300, 1000 * scale + i * 5 * scale, 4 * scale) for i in range(18)], received)
        engine.ingest_candles(symbol, 60,
            [candle(START + i * 60, 1000 * scale + i * scale, 4 * scale) for i in range(90)], received)
    return engine, received


class FeatureTests(unittest.TestCase):
    """観測順を入れ替えず、公開前の計算結果を利用しないことを検査する。"""

    def test_long_gap_does_not_reuse_old_thirty_second_support(self):
        """機能: 欠測前後の差を30秒上昇と見なして再入場しない。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        start = received + 60
        for second in range(71):
            result = engine.on_book('TOPIX', book(start + second, 1100 + second * .2), start + second)
        self.assertEqual(result['direction'], 1)
        resumed = start + 160
        for second in range(20):
            result = engine.on_book('TOPIX', book(resumed + second, 1200 + second), resumed + second)
            self.assertEqual(result['direction'], 0)

    def test_timestamp_requires_timezone_and_finite_number(self):
        """機能: 日時の曖昧性と非有限値を拒否する。

        引数: なし。返り値: なし(None)。
        """
        self.assertEqual(timestamp("2026-10-02T09:00:00+09:00"), START)
        for value in ("2026-10-02T09:00:00", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                timestamp(value)

    def test_atr_uses_three_bars_and_release_time(self):
        """機能: TRの別式と3本の暖機、5分終了から60秒の遅延を照合する。

        引数: なし。返り値: なし(None)。
        """
        engine = FeatureEngine("2026-10-02_Day", START)
        widths = (4, 6, 8)
        for i, width in enumerate(widths):
            engine.ingest_candles("TOPIX", 300, [candle(START + i * 300, 100, width)], START + (i + 1) * 300)
        self.assertIsNone(engine.snapshot("TOPIX", START + 959)["atr"])
        expected = ((4 * 11 + 6) / 12 * 11 + 8) / 12
        self.assertAlmostEqual(engine.snapshot("TOPIX", START + 960)["atr"], expected)

    def test_atr_floor_is_instrument_specific(self):
        """機能: ATRの最小幅を参照先物の2呼値に限定する。

        引数: なし。返り値: なし(None)。
        """
        engine = FeatureEngine("2026-10-02_Day", START)
        for symbol, expected in (("TOPIX", 1), ("NK225", 20)):
            engine.ingest_candles(symbol, 300,
                [candle(START + i * 300, 1000, 0.2) for i in range(3)], START + 960)
            self.assertEqual(engine.snapshot(symbol, START + 960)["atr"], expected)

    def test_actual_receipt_and_extra_peer_delay(self):
        """機能: 過去足の一括暖機が実受信前や相手遅延前へ漏れないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        self.assertIsNone(engine.snapshot("TOPIX", received - 0.01)["atr"])
        self.assertEqual(engine.snapshot("TOPIX", received)["main_direction"], 1)
        self.assertEqual(engine.snapshot("TOPIX", received + 59.99)["allowed_direction"], 0)
        self.assertEqual(engine.snapshot("TOPIX", received + 60)["allowed_direction"], 1)

    def test_ema_matches_closed_form_adjust_false(self):
        """機能: EMAを指数重みの総和による独立式と照合する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        snapshot = engine.snapshot("TOPIX", received + 60)
        for span, key in ((15, "ema_fast"), (60, "ema_slow")):
            alpha = 2 / (span + 1)
            expected = 1000 * (1 - alpha) ** 89
            expected += sum(alpha * (1000 + i) * (1 - alpha) ** (89 - i) for i in range(1, 90))
            self.assertAlmostEqual(snapshot[key], expected, places=9)

    def test_nominal_times_distinguish_old_candles_from_fresh_http(self):
        """機能: 古い足の新規受信を最新足と誤認しない監査時刻を確認する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        snapshot = engine.snapshot("TOPIX", received + 60)
        self.assertEqual(snapshot["atr_available"], received)
        self.assertEqual(snapshot["atr_nominal"], START + 17 * 300 + 360)
        self.assertEqual(snapshot["main_nominal"], START + 89 * 60 + 120)
        self.assertGreater(snapshot["atr_available"], snapshot["atr_nominal"])

    def test_unclosed_and_changed_candles(self):
        """機能: 未確定足を捨て、確定価格の書換えと未来確定値を拒否する。

        引数: なし。返り値: なし(None)。
        """
        engine = FeatureEngine("2026-10-02_Day", START)
        self.assertEqual(engine.ingest_candles("TOPIX", 60, [candle(START, 100, closed=False)], START + 60), 0)
        self.assertEqual(engine.ingest_candles("TOPIX", 60, [candle(START, 100)], START + 60), 1)
        self.assertEqual(engine.ingest_candles("TOPIX", 60, [candle(START, 100)], START + 70), 0)
        with self.assertRaises(ValueError):
            engine.ingest_candles("TOPIX", 60, [candle(START, 101)], START + 70)
        with self.assertRaises(ValueError):
            engine.ingest_candles("TOPIX", 60, [candle(START + 60, 101)], START + 70)

    def test_same_timestamp_block_is_not_used_until_next_timestamp(self):
        """機能: 同じ取引時刻の気配を次時刻まで公開しないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        now = received + 60
        engine.on_book("TOPIX", book(now, 1000), now)
        engine.on_book("TOPIX", book(now, 1002), now + 0.1)
        self.assertEqual(engine.markets["TOPIX"]["events"], [])
        result = engine.on_book("TOPIX", book(now + 1, 1050), now + 1)
        self.assertEqual(engine.markets["TOPIX"]["events"][-1]["mid"], 1002)
        self.assertEqual(result["price"], 1050)
        self.assertEqual(result["input_index"], 2)

    def test_failed_candle_batch_is_not_partially_applied(self):
        """機能: 一括応答に不正足があれば正常な前半も適用しないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        engine = FeatureEngine("2026-10-02_Day", START)
        before = engine.dump_state()
        with self.assertRaises(ValueError):
            engine.ingest_candles("TOPIX", 60,
                [candle(START, 100), candle(START + 60, -1)], START + 120)
        self.assertEqual(engine.dump_state(), before)

    def test_support_uses_mid_not_last_trade_and_expires(self):
        """機能: 最良気配中値による短期支持と120秒期限を確認する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        now = received + 60
        for second in range(40):
            output = engine.on_book("TOPIX", book(now + second, 1100 + second * 0.5, 5000), now + second)
        self.assertEqual(output["direction"], 1)
        self.assertEqual(output["price"], 5000)
        fixed_quote = book(now + 39, 1120, 5000)
        output = engine.on_book("TOPIX", fixed_quote, now + 160)
        self.assertEqual(output["direction"], 0)

    def test_b00_threshold_and_origin_are_past_publication(self):
        """機能: 価格悪化を120秒と30秒の双方で確認し観測連番を残す。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        now = received + 60
        for second in range(150):
            output = engine.on_book("TOPIX", book(now + second, 1200 - second * 0.25), now + second)
            if second < 121:
                self.assertEqual(output["adverse"], 0)
        self.assertEqual(output["adverse"], -1)
        self.assertEqual(output["adverse_source"], output["input_index"])
        repeated = engine.on_book("TOPIX", book(now + 149, 1160), now + 149.1)
        self.assertEqual(repeated["adverse_source"], output["input_index"])
        self.assertEqual(repeated["input_index"], output["input_index"] + 1)

    def test_json_resume_is_identical_to_uninterrupted_run(self):
        """機能: 未公開ブロック途中での保存再開を連続実行と照合する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        now = received + 60
        for second in range(100):
            engine.on_book("TOPIX", book(now + second, 1100 + math.sin(second / 10) * 10), now + second)
        restored = FeatureEngine.from_state(json.loads(json.dumps(engine.dump_state(), allow_nan=False)))
        for second in range(100, 180):
            payload = book(now + second, 1100 + math.sin(second / 10) * 10)
            self.assertEqual(engine.on_book("TOPIX", payload, now + second), restored.on_book("TOPIX", payload, now + second))
        self.assertEqual(engine.dump_state(), restored.dump_state())

    def test_disconnect_resets_support_but_preserves_counter_and_atr(self):
        """機能: 接続断で短期支持を破棄し、足と原観測の連番を維持する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        now = received + 60
        for second in range(40):
            previous = engine.on_book("TOPIX", book(now + second, 1100 + second), now + second)
        self.assertEqual(previous["direction"], 1)
        engine.reset_short_history()
        current = engine.on_book("TOPIX", book(now + 40, 1140), now + 40)
        self.assertEqual(current["input_index"], previous["input_index"] + 1)
        self.assertEqual(current["direction"], 0)
        self.assertEqual(current["atr"], previous["atr"])

    def test_invalid_order_does_not_advance_counter(self):
        """機能: 時刻逆行と不正価格を拒否して原観測連番を維持する。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        engine.on_book("TOPIX", book(received, 1000), received)
        with self.assertRaises(ValueError):
            engine.on_book("TOPIX", book(received - 1, 1000), received + 1)
        with self.assertRaises(ValueError):
            engine.on_book("TOPIX", book(received + 1, 1000, -1), received + 1)
        self.assertEqual(engine.markets["TOPIX"]["input_index"], 0)

    def test_future_candles_cannot_change_earlier_snapshot(self):
        """機能: 後日受信した足を追加しても、過去公開状態が書き換わらないことを調べる。

        引数: なし。返り値: なし(None)。
        """
        engine, received = warmed()
        before = engine.snapshot("TOPIX", received + 60)
        engine.ingest_candles("TOPIX", 60, [candle(received + 60, 9999)], received + 120)
        self.assertEqual(engine.snapshot("TOPIX", received + 60), before)


if __name__ == "__main__":
    unittest.main()
