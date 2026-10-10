"""第２回の検知器を先読み、約定時刻、セッション境界、評価基準から検証する。"""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

import research_v2 as research


def flat_market(start: str, finish: str, price: float = 1000.0) -> tuple:
    """機能: 約定時刻と保護条件を検査する単純な価格と特徴量を作る。

    引数: start/finish (str) は日本時間付き端点、price (float) は価格。
    返り値: 実在足、特徴量、一定の正方向強度の組 (tuple)。
    """
    index = pd.date_range(start, finish, freq="min")
    one = pd.DataFrame({"open": price, "high": price + 1, "low": price - 1,
                        "close": price, "volume": 1, "closed": True}, index=index)
    features = pd.DataFrame({"atr": 10.0, "stale_minutes": 0.0}, index=index)
    strength = pd.Series(1.0, index=index)
    return one, features, strength


def entry_history(trades: list[dict], cutoff: pd.Timestamp) -> list[tuple]:
    """機能: ある時点以前に実際に開始した取引の履歴を抽出する。

    引数: trades (list[dict]) は取引列、cutoff (Timestamp) は評価時点。
    返り値: 開始時刻・信号時刻・方向・約定価格の列 (list[tuple])。
    """
    return [(t["entry_time"], t["signal_time"], t["side"], t["entry_price"])
            for t in trades if t["entry_time"] <= cutoff]


class CausalityTests(unittest.TestCase):
    """保存データの未来改変と途中切断に対して過去の結果が不変であることを調べる。"""

    @classmethod
    def setUpClass(cls) -> None:
        """機能: 保存済み２銘柄の日中価格と板特徴を一度読み込む。

        引数: cls (type)。返り値: なし (None)。
        """
        cls.session = "2026-09-22_Day"
        cls.cutoff = pd.Timestamp("2026-09-22T11:20:00+09:00")
        cls.frames = {}
        for symbol in research.SYMBOLS:
            one = research.read_candle(research.ROOT / "candle_1min" / symbol / f"{cls.session}.csv")
            five = research.read_candle(research.ROOT / "candle_5min" / symbol / f"{cls.session}.csv")
            z = research.price_features(one, five, research.TICKS[symbol])
            path = research.OUT / f"板特徴_{symbol}_{cls.session}.csv"
            z = research.attach_book(z, path)
            if "book_present" not in z:
                raise AssertionError("板特徴がないため全系統の因果性検証を完了できない")
            cls.frames[symbol] = one, five, z, path

    def test_price_features_are_prefix_invariant(self) -> None:
        """機能: 保存価格を途中で切っても過去の特徴量が一致することを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        for symbol, (one, five, _, _) in self.frames.items():
            with self.subTest(銘柄=symbol):
                truncated_one = one.loc[:self.cutoff]
                available = truncated_one.index[-1]
                truncated_five = five.loc[five.index + pd.Timedelta(minutes=4) <= available]
                complete = research.price_features(one, five, research.TICKS[symbol]).loc[:available]
                partial = research.price_features(truncated_one, truncated_five, research.TICKS[symbol])
                assert_frame_equal(complete, partial)

    def test_future_price_changes_cannot_change_past_features(self) -> None:
        """機能: 未来の価格を極端に変更しても過去の特徴量が変化しないことを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        for symbol, (one, five, _, _) in self.frames.items():
            with self.subTest(銘柄=symbol):
                changed_one, changed_five = one.copy(), five.copy()
                for frame, mask in ((changed_one, one.index > self.cutoff),
                                    (changed_five, five.index + pd.Timedelta(minutes=4) > self.cutoff)):
                    frame.loc[mask, ["open", "high", "low", "close"]] += 100000
                    frame.loc[mask, "volume"] *= 1000
                expected = research.price_features(one, five, research.TICKS[symbol]).loc[:self.cutoff]
                actual = research.price_features(changed_one, changed_five, research.TICKS[symbol]).loc[:self.cutoff]
                assert_frame_equal(expected, actual)

    def test_future_book_changes_cannot_change_past_features(self) -> None:
        """機能: 未来の板特徴を大きく変えても過去の板特徴が一致することを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        for symbol, (one, five, z, path) in self.frames.items():
            with self.subTest(銘柄=symbol), tempfile.TemporaryDirectory() as folder:
                changed = pd.read_csv(path)
                future = pd.to_datetime(changed.time) > self.cutoff
                for col in changed.select_dtypes(include="number"):
                    changed.loc[future, col] = 100000
                replacement = Path(folder) / "未来を改変した板.csv"
                changed.to_csv(replacement, index=False, encoding="utf-8")
                base = research.price_features(one, five, research.TICKS[symbol])
                actual = research.attach_book(base, replacement)
                assert_frame_equal(z.loc[:self.cutoff], actual.loc[:self.cutoff], check_exact=False, atol=1e-12)

    def test_all_scores_are_prefix_invariant(self) -> None:
        """機能: 登録された全系統の方向強度が途中切断で変化しないことを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        for symbol in research.SYMBOLS:
            z = self.frames[symbol][2]
            other = self.frames["TOPIX" if symbol == "NK225" else "NK225"][2]
            for family in research.FAMILIES:
                with self.subTest(銘柄=symbol, 系統=family):
                    complete = research.score(z, other, family, 0.5).loc[:self.cutoff]
                    partial = research.score(z.loc[:self.cutoff], other.loc[:self.cutoff], family, 0.5)
                    assert_series_equal(complete, partial)

    def test_all_trade_histories_are_prefix_invariant(self) -> None:
        """機能: 登録された全系統で途中切断以前の新規と返済履歴が一致することを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        for symbol in research.SYMBOLS:
            one, _, z, _ = self.frames[symbol]
            other = self.frames["TOPIX" if symbol == "NK225" else "NK225"][2]
            for family in research.FAMILIES:
                with self.subTest(銘柄=symbol, 系統=family):
                    cfg = research.Config(family, 0.5, 3, 4.0)
                    strength = research.score(z, other, family, cfg.threshold)
                    complete = research.simulate(one, z, strength, cfg, symbol, self.session)
                    partial = research.simulate(one.loc[:self.cutoff], z.loc[:self.cutoff],
                                                strength.loc[:self.cutoff], cfg, symbol, self.session)
                    self.assertEqual(entry_history(complete, self.cutoff), entry_history(partial, self.cutoff))
                    completed_before = [t for t in complete if t["closed"] and t["exit_time"] <= self.cutoff]
                    self.assertEqual(completed_before, [t for t in partial if t["closed"]])

    def test_five_minute_atr_waits_for_bar_close(self) -> None:
        """機能: ５分足のＡＴＲが足確定前の１分判定に混入しないことを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        one, five, _, _ = self.frames["NK225"]
        z = research.price_features(one, five, 10.0)
        first_available_row = five.index[2] + pd.Timedelta(minutes=4)
        self.assertTrue(z.loc[z.index < first_available_row, "atr"].isna().all())
        self.assertTrue(np.isfinite(z.loc[first_available_row, "atr"]))

    def test_saved_sessions_never_carry_positions_across_boundary(self) -> None:
        """機能: 全保存セッションと全検知系統で終了時に未返済がないことを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        data = research.load_data()
        for family in research.FAMILIES:
            cfg = research.Config(family, 0.5, 3, 4.0)
            for (session, symbol), (one, z) in data.items():
                other = data[(session, "TOPIX" if symbol == "NK225" else "NK225")][1]
                with self.subTest(系統=family, 銘柄=symbol, セッション=session):
                    trades = research.simulate(one, z, research.score(z, other, family, cfg.threshold), cfg, symbol, session)
                    limit = research.deadline(one.index)
                    for trade in trades:
                        self.assertTrue(trade["closed"])
                        self.assertIn(trade["entry_time"], one.index)
                        self.assertIn(trade["exit_time"], one.index)
                        self.assertLess(trade["entry_time"], limit - pd.Timedelta(minutes=30))
                        self.assertLessEqual(trade["exit_time"], one.index[-1])

    def test_selected_peer_configuration_is_prefix_invariant_in_all_sessions(self) -> None:
        """機能: 最終候補の閾値と確認回数でも全保存セッションの途中切断が不変であることを確認する。

        引数: self (CausalityTests)。返り値: なし (None)。
        """
        data = research.load_data()
        cfg = research.Config(24, 0.25, 1, 4.0, 1)
        for (session, symbol), (one, z) in data.items():
            with self.subTest(銘柄=symbol, セッション=session):
                other = data[(session, "TOPIX" if symbol == "NK225" else "NK225")][1]
                strength = research.score(z, other, cfg.family, cfg.threshold)
                complete = research.simulate(one, z, strength, cfg, symbol, session)
                self.assertTrue(all(trade["closed"] for trade in complete))
                for fraction in (0.25, 0.5, 0.75):
                    cutoff = one.index[int((len(one) - 1) * fraction)]
                    partial_strength = research.score(z.loc[:cutoff], other.loc[:cutoff], cfg.family, cfg.threshold)
                    assert_series_equal(strength.loc[:cutoff], partial_strength)
                    partial = research.simulate(one.loc[:cutoff], z.loc[:cutoff], partial_strength, cfg, symbol, session)
                    self.assertEqual(entry_history(complete, cutoff), entry_history(partial, cutoff))
                    expected = [trade for trade in complete if trade["closed"] and trade["exit_time"] <= cutoff]
                    self.assertEqual(expected, [trade for trade in partial if trade["closed"]])


class ExecutionTests(unittest.TestCase):
    """人工的な価格で約定遅延、欠測、費用、セッション境界を独立に検査する。"""

    def setUp(self) -> None:
        """機能: 明確な約定確認用の設定を用意する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        self.cfg = research.Config(1, 0.5, 1, 6.0)

    def run_simulation(self, one: pd.DataFrame, z: pd.DataFrame, strength: pd.Series, session: str) -> list:
        """機能: 日経先物の価格単位で約定条件を試す。

        引数: one/z (DataFrame)、strength (Series)、session (str)。返り値: 取引一覧 (list)。
        """
        return research.simulate(one, z, strength, self.cfg, "NK225", session)

    def test_entry_waits_one_minute_after_signal_availability(self) -> None:
        """機能: 終値確定後の信号からさらに１分待って約定することを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:10+09:00")
        trade = self.run_simulation(one, z, strength, "2026-09-24_Day")[0]
        self.assertEqual(trade["signal_time"], one.index[0] + pd.Timedelta(minutes=1))
        self.assertEqual(trade["entry_time"], one.index[0] + pd.Timedelta(minutes=2))

    def test_missing_minutes_cannot_create_fills(self) -> None:
        """機能: 欠けた分の前方補完価格で約定を捏造しないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:10+09:00")
        one = one.drop(one.index[2:7])
        trades = self.run_simulation(one, z, strength, "2026-09-24_Day")
        self.assertEqual(trades[0]["entry_time"], pd.Timestamp("2026-09-24T09:07+09:00"))
        self.assertTrue(all(t["entry_time"] in one.index for t in trades))

    def test_stale_features_block_new_positions(self) -> None:
        """機能: １０分を超えて古い価格特徴から新規を作らないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:10+09:00")
        z["stale_minutes"] = 11
        self.assertEqual(self.run_simulation(one, z, strength, "2026-09-24_Day"), [])

    def test_day_session_closes_before_session_end(self) -> None:
        """機能: 日中の建玉が定刻に返済され、その後新規が発生しないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T15:39+09:00")
        trades = self.run_simulation(one, z, strength, "2026-09-24_Day")
        self.assertEqual(len(trades), 1)
        self.assertTrue(trades[0]["closed"])
        self.assertEqual(trades[0]["exit_time"], pd.Timestamp("2026-09-24T15:35+09:00"))

    def test_night_session_closes_next_morning(self) -> None:
        """機能: 夜間の返済期限が日付を跨いだ翌朝となることを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T17:00+09:00", "2026-09-25T05:54+09:00")
        trade = self.run_simulation(one, z, strength, "2026-09-24_Night")[0]
        self.assertTrue(trade["closed"])
        self.assertEqual(trade["exit_time"], pd.Timestamp("2026-09-25T05:50+09:00"))

    def test_day_session_cannot_repay_using_next_session_price(self) -> None:
        """機能: 日中の返済前に価格が途切れても日中終了以後の価格へ返済を持ち越さないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for extra in ("2026-09-24T15:40+09:00", "2026-09-24T17:00+09:00"):
            with self.subTest(混入時刻=extra):
                one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T15:34+09:00")
                one.loc[pd.Timestamp(extra)] = one.iloc[-1]
                with self.assertRaises(ValueError):
                    self.run_simulation(one, z, strength, "2026-09-24_Day")

    def test_night_session_cannot_repay_using_next_session_price(self) -> None:
        """機能: 夜間の返済前に価格が途切れても夜間終了以後の価格へ返済を持ち越さないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for extra in ("2026-09-25T05:55+09:00", "2026-09-25T08:45+09:00"):
            with self.subTest(混入時刻=extra):
                one, z, strength = flat_market("2026-09-24T17:00+09:00", "2026-09-25T05:49+09:00")
                one.loc[pd.Timestamp(extra)] = one.iloc[-1]
                with self.assertRaises(ValueError):
                    self.run_simulation(one, z, strength, "2026-09-24_Night")

    def test_missing_deadline_uses_next_observed_minute(self) -> None:
        """機能: 返済予定分に足がない場合の実在価格による返済時刻を確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T15:39+09:00")
        one = one.drop(pd.date_range("2026-09-24T15:35+09:00", "2026-09-24T15:36+09:00", freq="min"))
        trade = self.run_simulation(one, z, strength, "2026-09-24_Day")[0]
        self.assertEqual(trade["exit_time"], pd.Timestamp("2026-09-24T15:37+09:00"))
        self.assertLess(trade["exit_time"], pd.Timestamp("2026-09-24T15:40+09:00"))

    def test_truncated_day_is_marked_open(self) -> None:
        """機能: セッション途中のデータ末尾で架空の決済を行わないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T11:00+09:00")
        trade = self.run_simulation(one, z, strength, "2026-09-24_Day")[0]
        self.assertFalse(trade["closed"])
        self.assertIsNone(trade["exit_price"])
        self.assertIsNone(trade["gross_points"])
        self.assertNotIn("net_points", trade)

    def test_truncated_night_is_marked_open(self) -> None:
        """機能: 午前０時を超えた夜間途中でも末尾決済しないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T17:00+09:00", "2026-09-25T01:00+09:00")
        trade = self.run_simulation(one, z, strength, "2026-09-24_Night")[0]
        self.assertFalse(trade["closed"])
        self.assertIsNone(trade["exit_time"])

    def test_new_session_has_no_carried_position(self) -> None:
        """機能: 前の呼出しに未決済があっても新セッションへ保有状態を渡さないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T11:00+09:00")
        self.assertFalse(self.run_simulation(one, z, strength, "2026-09-24_Day")[0]["closed"])
        one, z, strength = flat_market("2026-09-24T17:00+09:00", "2026-09-24T20:00+09:00")
        self.assertEqual(self.run_simulation(one, z, strength * 0, "2026-09-24_Night"), [])

    def test_no_new_position_in_final_thirty_minutes(self) -> None:
        """機能: 返済予定時刻前の新規停止を確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T14:00+09:00", "2026-09-24T15:39+09:00")
        strength.loc[strength.index < pd.Timestamp("2026-09-24T15:03+09:00")] = 0
        self.assertEqual(self.run_simulation(one, z, strength, "2026-09-24_Day"), [])

    def test_long_adverse_gap_cannot_fill_at_better_stop(self) -> None:
        """機能: ロングの逆行窓開けを過去の有利な逆指値価格で決済しないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:06+09:00")
        one.loc[one.index[3], ["open", "high", "low", "close"]] = [940, 950, 930, 940]
        trade = self.run_simulation(one, z, strength, "2026-09-24_Day")[0]
        self.assertEqual(trade["exit_price"], 940)
        self.assertEqual(trade["gross_points"], -60)
        self.assertEqual(trade["net_points"], -80)
        self.assertEqual(trade["stress_points"], -100)

    def test_short_adverse_gap_cannot_fill_at_better_stop(self) -> None:
        """機能: ショートの逆行窓開けでも逆指値より不利な始値を使うことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:06+09:00")
        one.loc[one.index[3], ["open", "high", "low", "close"]] = [1060, 1070, 1050, 1060]
        trade = self.run_simulation(one, z, -strength, "2026-09-24_Day")[0]
        self.assertEqual(trade["exit_price"], 1060)
        self.assertEqual(trade["gross_points"], -60)

    def test_entry_minute_protection_is_not_skipped(self) -> None:
        """機能: 新規約定分の途中で保護条件に達した損失を見落とさないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:06+09:00")
        one.loc[one.index[2], "low"] = 900
        trade = self.run_simulation(one, z, strength, "2026-09-24_Day")[0]
        self.assertTrue(trade["closed"])
        self.assertEqual(trade["duration_min"], 0)
        self.assertEqual(trade["gross_points"], -30)

    def test_known_opposite_signal_exits_before_intraminute_stop(self) -> None:
        """機能: 始値で可能な反対信号返済が同じ分の後続安値より優先することを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:06+09:00")
        strength.iloc[1:] = -1
        one.loc[one.index[3], "low"] = 900
        cfg = research.Config(1, 0.5, 1, 6.0, 1)
        trade = research.simulate(one, z, strength, cfg, "NK225", "2026-09-24_Day")[0]
        self.assertEqual(trade["exit_time"], one.index[3])
        self.assertEqual(trade["exit_price"], 1000)
        self.assertEqual(trade["reason"], "反対方向が継続")

    def test_confirmed_reversal_can_open_opposite_at_same_price(self) -> None:
        """機能: 既知の反対信号で返済した同じ始値から逆方向へ切り替えられることを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:10+09:00")
        strength.iloc[1:] = -1
        cfg = research.Config(1, 0.5, 1, 6.0, 1)
        trades = research.simulate(one, z, strength, cfg, "NK225", "2026-09-24_Day")
        self.assertEqual(len(trades), 2)
        self.assertEqual([trade["side"] for trade in trades], [1, -1])
        self.assertEqual(trades[0]["exit_time"], trades[1]["entry_time"])
        self.assertEqual(trades[0]["exit_price"], trades[1]["entry_price"])

    def test_stop_blocks_same_direction_even_after_cooldown(self) -> None:
        """機能: 損切り後に同じ信号が続いても５分後の同方向再入場を防ぐことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:30+09:00")
        one.loc[one.index[3], "low"] = 900
        trades = self.run_simulation(one, z, strength, "2026-09-24_Day")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["reason"], "保護・追跡返済")

    def test_neutral_signal_does_not_unlock_stopped_direction(self) -> None:
        """機能: 中立信号だけでは損切り後の同方向禁止を解除しないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:30+09:00")
        one.loc[one.index[3], "low"] = 900
        strength.iloc[5:10] = 0
        self.assertEqual(len(self.run_simulation(one, z, strength, "2026-09-24_Day")), 1)

    def test_opposite_signal_unlocks_stopped_direction_after_cooldown(self) -> None:
        """機能: 反対信号を一度観測すると同方向禁止は解除されるが５分待ちは保つことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:30+09:00")
        one.loc[one.index[3], "low"] = 900
        strength.iloc[4] = -1
        trades = self.run_simulation(one, z, strength, "2026-09-24_Day")
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]["exit_time"], one.index[3])
        self.assertEqual(trades[1]["entry_time"], one.index[8])
        self.assertEqual(trades[1]["side"], 1)

    def test_entry_minute_stop_also_blocks_same_direction(self) -> None:
        """機能: 約定分の保護返済でも同方向の無条件再入場を禁止することを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:30+09:00")
        one.loc[one.index[2], "low"] = 900
        trades = self.run_simulation(one, z, strength, "2026-09-24_Day")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["reason"], "約定足の保護返済")

    def test_peer_strategy_neutral_state_closes_without_reversal(self) -> None:
        """機能: 自指数が反転して他指数が未確認なら中立化し、反対新規を出さないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z, strength = flat_market("2026-09-24T09:00+09:00", "2026-09-24T09:10+09:00")
        strength.iloc[1:] = 0
        cfg = research.Config(24, 0.25, 1, 4.0, 1)
        trades = research.simulate(one, z, strength, cfg, "NK225", "2026-09-24_Day")
        self.assertEqual(len(trades), 1)
        self.assertTrue(trades[0]["closed"])
        self.assertEqual(trades[0]["exit_time"], one.index[3])
        self.assertEqual(trades[0]["exit_price"], 1000)
        self.assertEqual(trades[0]["reason"], "自指数が反転・相手未確認")


class PeerDirectionTests(unittest.TestCase):
    """最終候補の他指数確認と継続状態を合成した特徴量で検査する。"""

    def setUp(self) -> None:
        """機能: 全ての新規方向条件を満たす２銘柄の特徴量を用意する。

        引数: self (PeerDirectionTests)。返り値: なし (None)。
        """
        index = pd.date_range("2026-09-24T09:00+09:00", periods=90, freq="min")
        self.z = pd.DataFrame({"atr": 10.0, "di40": 0.5, "move20": 0.5,
                               "reg60": 1.0, "r2_60": 0.8, "stale_minutes": 0.0,
                               "age": np.arange(90)}, index=index)
        self.peer = self.z.copy()

    def test_stale_peer_cannot_confirm_new_direction(self) -> None:
        """機能: 他指数が１０分を超えて古い場合に新規方向の確認へ使わないことを確認する。

        引数: self (PeerDirectionTests)。返り値: なし (None)。
        """
        self.peer["stale_minutes"] = 11
        actual = research.score(self.z, self.peer, 24, 0.25)
        self.assertTrue(actual.eq(0).all())

    def test_stale_own_data_cannot_create_hidden_persistent_state(self) -> None:
        """機能: 自指数が古い期間だけで内部状態を作り、新鮮化後に持ち出さないことを確認する。

        引数: self (PeerDirectionTests)。返り値: なし (None)。
        """
        self.z.loc[self.z.index[:80], "stale_minutes"] = 11
        self.z.loc[self.z.index[80:], "reg60"] = -1
        actual = research.score(self.z, self.peer, 24, 0.25)
        self.assertTrue(actual.eq(0).all())

    def test_own_reversal_exits_and_waits_for_peer_before_short_entry(self) -> None:
        """機能: 自指数反転で中立となり、他指数が揃うまで反対方向の新規を待つことを確認する。

        引数: self (PeerDirectionTests)。返り値: なし (None)。
        """
        self.z.loc[self.z.index[40:], ["di40", "move20", "reg60"]] *= -1
        self.peer.loc[self.peer.index[60:], "reg60"] = -1
        actual = research.score(self.z, self.peer, 24, 0.25)
        self.assertTrue(actual.iloc[:34].eq(0).all())
        self.assertTrue(actual.iloc[34:44].eq(1).all())
        self.assertTrue(actual.iloc[44:64].eq(0).all())
        self.assertTrue(actual.iloc[64:].eq(-1).all())

    def test_long_regression_threshold_is_required_before_entry(self) -> None:
        """機能: 短期方向だけでは新規を出さず、長期回帰の最低変位も必要であることを確認する。

        引数: self (PeerDirectionTests)。返り値: なし (None)。
        """
        self.z["reg60"] = 0.4
        actual = research.score(self.z, self.peer, 24, 0.25)
        self.assertTrue(actual.eq(0).all())


class TargetMetricTests(unittest.TestCase):
    """指定波の捕捉判定が無信号や遅すぎる検知を合格させないことを確認する。"""

    def setUp(self) -> None:
        """機能: 長時間上昇する参照波を用意する。

        引数: self (TargetMetricTests)。返り値: なし (None)。
        """
        self.one, _, _ = flat_market("2026-09-21T10:45+09:00", "2026-09-21T15:39+09:00")
        for col in ("open", "high", "low", "close"):
            self.one[col] += np.arange(len(self.one))

    def trade(self, begin: str, end: str, side: int = 1) -> dict:
        """機能: 採点対象として明確な開始・終了を持つ取引を作る。

        引数: begin/end (str) は時分、side (int) は方向。返り値: 取引 (dict)。
        """
        t0, t1 = [pd.Timestamp(f"2026-09-21T{clock}+09:00") for clock in (begin, end)]
        return {"entry_time": t0, "exit_time": t1, "side": side,
                "entry_price": float(self.one.loc[t0, "open"]),
                "exit_price": float(self.one.loc[t1, "open"])}

    def metric(self, trades: list[dict]) -> dict:
        """機能: 一つの参照波の評価結果を得る。

        引数: trades (list[dict])。返り値: 評価 (dict)。
        """
        return research.target_metrics(self.one, trades, "NK225", "2026-09-21_Day")[0]

    def test_no_signal_cannot_pass(self) -> None:
        """機能: 何もしない候補を指定波合格扱いしないことを確認する。

        引数: self (TargetMetricTests)。返り値: なし (None)。
        """
        result = self.metric([])
        self.assertFalse(result["passed"])
        self.assertIsNone(result["detection_delay_min"])
        self.assertEqual(result["correct_coverage"], 0)

    def test_timely_persistent_profitable_wave_passes(self) -> None:
        """機能: 十分早く長く保有し値幅を得た候補が合格することを確認する。

        引数: self (TargetMetricTests)。返り値: なし (None)。
        """
        result = self.metric([self.trade("11:00", "15:35")])
        self.assertTrue(result["passed"])
        self.assertEqual(result["detection_delay_min"], 15)
        self.assertAlmostEqual(result["correct_coverage"], 275 / 295)

    def test_sixty_one_minute_delay_cannot_pass(self) -> None:
        """機能: ６０分上限を超えた検知が後半の利益だけで合格しないことを確認する。

        引数: self (TargetMetricTests)。返り値: なし (None)。
        """
        result = self.metric([self.trade("11:46", "15:35")])
        self.assertEqual(result["detection_delay_min"], 61)
        self.assertFalse(result["passed"])

    def test_short_overlap_cannot_pass(self) -> None:
        """機能: 一瞬だけ同方向になった候補を継続波検知扱いしないことを確認する。

        引数: self (TargetMetricTests)。返り値: なし (None)。
        """
        result = self.metric([self.trade("10:45", "11:04")])
        self.assertIsNone(result["detection_delay_min"])
        self.assertFalse(result["passed"])

    def test_opposite_position_is_reported_separately(self) -> None:
        """機能: 逆方向の保有を捕捉時間に加えず別に報告することを確認する。

        引数: self (TargetMetricTests)。返り値: なし (None)。
        """
        result = self.metric([self.trade("10:45", "15:35", -1)])
        self.assertEqual(result["correct_coverage"], 0)
        self.assertAlmostEqual(result["opposite_coverage"], 290 / 295)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
