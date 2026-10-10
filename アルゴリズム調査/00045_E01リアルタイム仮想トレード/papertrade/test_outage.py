"""一時的な通信断と約定価格の経過時間を分けて運転回復を検証する。"""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from . import test_runtime as fixtures
from .test_runtime import RECEIVED, REGISTRATION, book, candles


class OutageTests(unittest.TestCase):
    """実際の売買器を使い、短期断で建玉を失わないことを確認する。"""

    setUp = fixtures.RuntimeTests.setUp
    tearDown = fixtures.RuntimeTests.tearDown
    push = fixtures.RuntimeTests.push
    opened = fixtures.RuntimeTests.opened
    records = fixtures.RuntimeTests.records

    def resume_both(self, at: float) -> None:
        """機能: 切断前と同価格で両銘柄の受信を再開する。

        引数: at(float) は再受信時刻。返り値: なし(None)。
        """
        self.now = at
        self.runner.accept_candles(candles(asof=at), at)
        for symbol, price in (("TOPIX", 1118), ("NK225", 22360)):
            self.push(symbol, at, price)

    def test_same_trade_time_does_not_turn_live_book_into_outage(self) -> None:
        """機能: 約定が90秒なくても板PUSHが続けば通信中断と判定しない。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        quoted = self.now
        ready_before = deepcopy(self.runner.ready_after)
        count_before = len(self.records())
        for second in range(1, 91):
            self.now = quoted + second
            for symbol, price in (("TOPIX", 1118), ("NK225", 22360)):
                self.runner.accept_book(book(symbol, quoted, price), self.now, self.now)
            self.runner.watch(self.now)
        self.assertEqual(self.runner.gaps, {s: False for s in REGISTRATION})
        self.assertEqual(self.runner.ready_after, ready_before)
        self.assertEqual(self.runner.last_push, {s: self.now for s in REGISTRATION})
        self.assertEqual(len(self.records()), count_before)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        self.assertEqual(self.runner.engines["NK225"].status()["quantity"], 10)

    def test_ten_second_disconnect_preserves_positions_and_readiness(self) -> None:
        """機能: 10秒の通信断から戻っても一律返済や120秒待機を行わない。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        ready_before = deepcopy(self.runner.ready_after)
        interrupted = self.now + 1
        self.runner.gap("短時間切断の検査", interrupted)
        self.resume_both(interrupted + 10)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        self.assertEqual(self.runner.engines["NK225"].status()["quantity"], 10)
        self.assertEqual(self.runner.ready_after, ready_before)
        self.assertEqual([r["区分"] for r in self.records()], ["新規", "新規"])

    def test_ninety_second_disconnect_preserves_positions(self) -> None:
        """機能: 90秒の切断は猶予内として保有と返済条件を継続する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        ready_before = deepcopy(self.runner.ready_after)
        interrupted = self.now + 1
        self.runner.gap("90秒切断の検査", interrupted)
        self.now = interrupted + 90
        self.runner.watch(self.now)
        self.resume_both(self.now)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        self.assertEqual(self.runner.engines["NK225"].status()["quantity"], 10)
        self.assertEqual(self.runner.ready_after, ready_before)
        self.assertEqual(len(self.records()), 2)

    def test_silent_wire_pause_recovers_without_blanket_liquidation(self) -> None:
        """機能: 切断通知がなくても無受信を検知し、猶予内復旧なら保有する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        before = self.now
        self.now = before + 90
        self.runner.watch(self.now)
        self.assertTrue(all(self.runner.gaps.values()))
        self.resume_both(self.now + 1)
        self.assertFalse(any(self.runner.gaps.values()))
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)

    def test_recovery_crossing_existing_stop_uses_observed_price(self) -> None:
        """機能: 断線中に既設損切りを跨いだ場合は復旧観測価格で返済する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        interrupted = self.now + 1
        before = self.runner.engines["TOPIX"].status()
        stop = next(level for reason, level, passed in before["exit_shadow"]["plan"]["levels"] if reason == 1)
        observed = stop - 10
        self.runner.gap("既設ストップ跨ぎの検査", interrupted)
        self.push("TOPIX", interrupted + 10, observed)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 0)
        last = self.records()[-1]
        self.assertEqual(last["区分"], "返済")
        self.assertEqual(last["理由"], "組の損切り")
        self.assertEqual(float(last["約定価格"]), observed)
        self.assertNotEqual(float(last["約定価格"]), stop)

    def test_stale_price_is_not_used_even_when_push_proves_connection_alive(self) -> None:
        """機能: 通信生存を示す古い約定価格をストップ執行に使用しない。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        quoted = self.now
        before = self.runner.engines["TOPIX"].snapshot()
        self.now = quoted + self.options.max_price_age + 1
        self.runner.accept_book(book("TOPIX", quoted, 1000), self.now, self.now)
        self.assertEqual(self.runner.last_push["TOPIX"], self.now)
        self.assertEqual(self.runner.last_fresh["TOPIX"], quoted)
        self.assertEqual(self.runner.engines["TOPIX"].snapshot(), before)
        self.assertEqual(len(self.records()), 2)

    def test_stale_reconnection_push_cannot_consume_observed_stop_recovery(self) -> None:
        """機能: 復旧後の古い約定PUSHを除外し、最初の有効価格で既設損切りを評価する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        quoted = self.now
        self.runner.gap("古い価格を含む再接続の検査", quoted + 1)
        stale_received = quoted + self.options.max_price_age + 1
        self.now = stale_received
        self.runner.accept_book(book("TOPIX", quoted, 1000), stale_received, stale_received)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        self.assertEqual(len(self.records()), 2)
        self.push("TOPIX", stale_received + 1, 1000)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 0)
        self.assertEqual(float(self.records()[-1]["約定価格"]), 1000)
        self.assertEqual(self.records()[-1]["理由"], "組の損切り")

    def test_long_silence_closes_only_on_new_observation(self) -> None:
        """機能: 長期無受信では復旧返済へ移り、未観測の約定を作らない。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        quoted = self.now
        self.now = quoted + self.options.reconnect_grace_seconds + 1
        self.runner.watch(self.now)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        self.assertEqual(len(self.records()), 2)
        resumed = self.now + 1
        self.resume_both(resumed)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 0)
        self.assertEqual(self.runner.engines["NK225"].status()["quantity"], 0)
        self.assertEqual(self.runner.ready_after, {s: resumed + 120 for s in REGISTRATION})
        closes = [r for r in self.records() if r["区分"] == "返済"]
        self.assertEqual(len(closes), 2)
        self.assertTrue(all(r["理由"] == "データ中断後の観測価格で返済" for r in closes))

    def test_repeated_soft_gap_preserves_short_history_and_existing_stop(self) -> None:
        """機能: 再接続失敗を繰り返しても猶予内では短期根拠を消さない。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        before = self.runner.features.dump_state()
        plan_before = deepcopy(self.runner.engines["TOPIX"].status()["exit_shadow"]["plan"])
        ready_before = deepcopy(self.runner.ready_after)
        for elapsed in (1, 5, 10, 30):
            self.runner.gap("再接続待ちの検査", self.now + elapsed)
        self.assertEqual(self.runner.features.dump_state(), before)
        self.assertEqual(self.runner.engines["TOPIX"].status()["exit_shadow"]["plan"], plan_before)
        self.assertEqual(self.runner.ready_after, ready_before)

    def test_missing_peer_push_blocks_prepared_entry(self) -> None:
        """機能: 実際に相手銘柄の通信が途絶えた場合は既設新規を取消す。

        引数: なし。返り値: なし(None)。
        """
        self.runner.gaps = {s: False for s in REGISTRATION}
        self.runner.ready_after = {s: RECEIVED for s in REGISTRATION}
        self.runner.last_fresh = {s: RECEIVED for s in REGISTRATION}
        self.runner.last_push = {s: RECEIVED for s in REGISTRATION}
        original = self.runner.features.on_book

        def supported(symbol: str, payload: dict, received: float) -> dict:
            """機能: 通信生存制御の検査用に入口根拠を確定値へ置換する。

            引数: symbol(str)、payload(dict)、received(float)。返り値: 特徴量(dict)。
            """
            feature = original(symbol, payload, received)
            feature.update(atr=10.0, direction=1, main_nominal=received,
                           peer_nominal=received, atr_nominal=received)
            return feature

        with patch.object(self.runner.features, "on_book", side_effect=supported):
            self.push("TOPIX", RECEIVED, 100)
            self.assertIsNotNone(self.runner.engines["TOPIX"].status()["pending_entry"])
            self.now = RECEIVED + self.options.stale_seconds + 1
            self.runner.watch(self.now)
            self.push("TOPIX", self.now, 103)
        self.assertIsNone(self.runner.engines["TOPIX"].status()["pending_entry"])
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 0)
        self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
