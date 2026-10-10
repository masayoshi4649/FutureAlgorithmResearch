"""場の切替で届く未設定価格を除外し、正常な観測から再開することを検査する。"""

from copy import deepcopy
from datetime import datetime
import unittest

from . import test_runtime as fixtures
from .runtime import stamp


class SessionTransitionTests(unittest.TestCase):
    """切替前後の欠損・混在応答に対する状態保存と復帰を確認する。"""

    setUp = fixtures.RuntimeTests.setUp
    tearDown = fixtures.RuntimeTests.tearDown
    push = fixtures.RuntimeTests.push
    opened = fixtures.RuntimeTests.opened
    records = fixtures.RuntimeTests.records

    def unset_book(self, symbol: str, at: float) -> dict:
        """機能: 保存板で確認した価格と価格時刻がnullの通知を再現する。

        引数: symbol(str)、at(float)。返り値: 未設定価格の板(dict)。
        """
        value = fixtures.book(symbol, at, 1000)
        value.update(CurrentPrice=None, CurrentPriceTime=None)
        return value

    def test_missing_timestamp_is_an_expected_input_error(self) -> None:
        """機能: null等が未捕捉のAttributeErrorにならないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        for value in (None, '', ' ', 0, [], {}, '不正日時', '2026-10-02T17:00:00'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stamp(value)
        self.assertEqual(stamp('2026-10-02T08:00:00Z'), stamp('2026-10-02T17:00:00+09:00'))

    def test_null_price_preserves_position_and_recovers_at_observed_stop(self) -> None:
        """機能: 保有中のnullで状態を壊さず、復帰価格がストップを越えたら返済する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        before = self.runner.engines['TOPIX'].snapshot()
        features = self.runner.features.dump_state()
        last_fresh = self.runner.last_fresh['TOPIX']
        count = len(self.records())
        self.now += 1
        self.runner.accept_book(self.unset_book('TOPIX', self.now), self.now, self.now)
        after = self.runner.engines['TOPIX'].snapshot()
        self.assertEqual(before, after)
        self.assertEqual(self.runner.features.dump_state(), features)
        self.assertEqual(self.runner.last_fresh['TOPIX'], last_fresh)
        self.assertEqual(self.runner.last_push['TOPIX'], self.now)
        self.assertEqual(self.runner.rejected_count, 1)
        self.assertEqual(len(self.records()), count)
        self.push('TOPIX', self.now + 1, 1000)
        self.assertEqual(self.runner.engines['TOPIX'].status()['quantity'], 0)
        self.assertEqual(self.records()[-1]['約定価格'], '1000.0')
        self.assertEqual(self.records()[-1]['約定モデル'], 'observed_recovery')

    def test_null_cancels_pending_entry_without_advancing_price_clock(self) -> None:
        """機能: 未設定の通知を新規条件成立や価格観測として扱わない。

        引数: なし。返り値: なし(None)。
        """
        engine = self.runner.engines['TOPIX']
        engine.on_tick(self.now, 1000, 10, 1)
        self.assertIsNotNone(engine.status()['pending_entry'])
        self.now += 1
        self.runner.accept_book(self.unset_book('TOPIX', self.now), self.now, self.now)
        self.assertIsNone(engine.status()['pending_entry'])
        self.assertEqual(engine.status()['quantity'], 0)
        self.assertEqual(engine.status()['row'], 0)
        self.assertEqual(self.runner.received_count['TOPIX'], 0)
        self.assertEqual(self.records(), [])

    def test_day_night_and_next_day_resume_only_with_current_session_price(self) -> None:
        """機能: 切替前後のnullと旧終値を除外し、新セッションの価格から観測を再開する。

        引数: なし。返り値: なし(None)。
        """
        cases = [
            ('2026-10-02_Night', '2026-10-02T17:00:00+09:00', '2026-10-03T06:00:00+09:00'),
            ('2026-10-03_Day', '2026-10-03T08:45:00+09:00', '2026-10-03T15:45:00+09:00'),
        ]
        for session, begins, ends in cases:
            with self.subTest(session=session):
                start, end = stamp(begins), stamp(ends)
                old_end = self.runner.session['end']
                self.now = old_end - 0.1
                self.runner.accept_book(self.unset_book('TOPIX', self.now), self.now, self.now)
                self.now = old_end + 1
                self.runner.accept_candles(fixtures.candles('切替_' + session, session, start, end, self.now), self.now)
                self.assertEqual(self.runner.session['id'], session)
                self.assertEqual(self.runner.latest_features, {})
                self.runner.accept_book(self.unset_book('TOPIX', self.now), self.now, self.now)
                old_price = fixtures.book('TOPIX', old_end - 1, 1000)
                self.runner.accept_book(old_price, start + 1, start + 1)
                self.assertEqual(self.runner.engines['TOPIX'].status()['row'], -1)
                self.push('TOPIX', start + 2, 1000)
                self.assertEqual(self.runner.engines['TOPIX'].status()['row'], 0)
                self.assertEqual(self.runner.ready_after['TOPIX'], start + 122)
                self.assertFalse(self.runner.gaps['TOPIX'])
                self.assertFalse(self.runner.halted)
                self.assertEqual(self.records(), [])

    def test_invalid_snapshot_preserves_session_until_consistent_retry(self) -> None:
        """機能: null・不一致の足メタ情報を待機し、整合した次の応答で切り替える。

        引数: なし。返り値: なし(None)。
        """
        start = stamp('2026-10-02T17:00:00+09:00')
        end = stamp('2026-10-03T06:00:00+09:00')
        self.now = fixtures.END + 1
        valid = fixtures.candles('夜世代', '2026-10-02_Night', start, end, self.now)
        old_session = deepcopy(self.runner.session)
        old_features = self.runner.features.dump_state()
        last_poll = self.runner.last_poll
        for field, value in [('startsAt', None), ('endsAt', ''), ('endsAt', fixtures.iso(start)),
                             ('startsAt', fixtures.iso(start + 60))]:
            with self.subTest(field=field, value=value):
                invalid = deepcopy(valid)
                invalid['batch']['TOPIX', '5min']['snapshot']['session'][field] = value
                self.runner.accept_candles(invalid, self.now)
                self.assertEqual(self.runner.session, old_session)
                self.assertEqual(self.runner.features.dump_state(), old_features)
                self.assertEqual(self.runner.last_poll, last_poll)
                self.assertFalse(self.runner.halted)
        for field in ('session', 'sessionId', 'generation'):
            with self.subTest(field=field):
                invalid = deepcopy(valid)
                invalid['batch']['NK225', '1min']['snapshot'][field] = None
                self.runner.accept_candles(invalid, self.now)
                self.assertEqual(self.runner.session, old_session)
        self.runner.accept_candles(valid, self.now + 10)
        self.assertEqual(self.runner.session['id'], '2026-10-02_Night')
        self.assertEqual(self.records(), [])

    def test_null_then_new_session_still_rejects_overnight_position(self) -> None:
        """機能: null対応で場跨ぎ禁止の検査を弱めず、未返済玉を残して停止する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        self.now += 1
        self.runner.accept_book(self.unset_book('TOPIX', self.now), self.now, self.now)
        start = stamp('2026-10-02T17:00:00+09:00')
        end = stamp('2026-10-03T06:00:00+09:00')
        self.now = fixtures.END + 1
        self.runner.accept_candles(fixtures.candles('夜世代', '2026-10-02_Night', start, end, self.now), self.now)
        self.assertTrue(self.runner.halted)
        self.assertEqual(self.runner.session['id'], '2026-10-02_Day')
        self.assertEqual(self.runner.engines['TOPIX'].status()['quantity'], 5)
        self.assertEqual(len(self.records()), 2)


if __name__ == '__main__':
    unittest.main()
