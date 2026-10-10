"""合成価格だけで時刻因果性と仮想約定の境界条件を検証する。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

import research


def make_config(family: int = 1, confirm: int = 1, timeframe: int = 5) -> research.Config:
    """機能: 検証用の共通設定を生成する。

    引数: family (int) は系統、confirm (int) は連続確認数、timeframe (int) は足の分数。
    返り値: 設定 (Config)。
    """
    return research.Config(family=family, strength=0.8, confirm=confirm, trail=1.5, timeframe=timeframe)


def minute_bars(start: str = "2026-09-21 09:00", periods: int = 60) -> pd.DataFrame:
    """機能: 一定価格の合成１分足を生成する。

    引数: start (str) は開始時刻、periods (int) は足数。
    返り値: 四本値を持つ足 (DataFrame)。
    """
    index = pd.date_range(start, periods=periods, freq="min", tz="Asia/Tokyo")
    return pd.DataFrame(dict(open=100.0, high=100.5, low=99.5, close=100.0, volume=1.0), index=index)


def synthetic_features(start: pd.Timestamp, directions: list[int]) -> tuple[pd.DataFrame, pd.Series]:
    """機能: 約定処理を指標計算から独立して検証する入力を作る。

    引数: start (Timestamp) は５分足開始時刻、directions (list[int]) は方向。
    返り値: 固定ＡＴＲ特徴量と方向系列 (tuple[DataFrame, Series])。
    """
    index = pd.date_range(start, periods=len(directions), freq="5min")
    return pd.DataFrame(dict(atr=2.0), index=index), pd.Series(directions, index=index)


def simulate(df: pd.DataFrame, directions: list[int] | None = None) -> list[dict]:
    """機能: 合成５分足により合成１分足上で仮想売買する。

    引数: df (DataFrame) は１分足、directions (list[int] | None) は方向。
    返り値: 将来ラベルを計算しないイベント一覧 (list[dict])。
    """
    z, s = synthetic_features(df.index[0], directions or [1])
    return research.backtest(df, z, s, make_config(), "TOPIX", "合成検証", labels=False)


class CausalTests(unittest.TestCase):
    """過去の特徴量と判断が将来価格に依存しないことを検証する。"""

    def test_future_append_preserves_all_past_features_and_signals(self) -> None:
        """機能: 将来の急反転追加でも過去の特徴量と１２系統判断が不変か確認する。

        引数: self (CausalTests)。返り値: なし (None)。
        """
        index = pd.date_range("2026-09-21 09:00", periods=100, freq="5min", tz="Asia/Tokyo")
        t = np.arange(100)
        close = 1000 + 2*t + 2*np.sin(t/3)
        close[65:] = 1000 - 40*np.arange(35)
        data = pd.DataFrame(dict(open=close-0.2, high=close+0.6, low=close-0.6, close=close), index=index)
        peer = data * 0.3
        prefix = research.features(data.iloc[:65])
        whole = research.features(data)
        peer_prefix = research.features(peer.iloc[:65])
        peer_whole = research.features(peer)
        pd.testing.assert_frame_equal(prefix, whole.iloc[:65])
        for family in range(1, 13):
            for confirm in (1, 2):
                with self.subTest(系統=family, 連続確認数=confirm):
                    cfg = make_config(family, confirm)
                    before = research.signal(prefix, peer_prefix, cfg)
                    after = research.signal(whole, peer_whole, cfg).iloc[:65]
                    self.assertGreater(int(before.abs().sum()), 0, "全件中立による空の検証を防ぐ")
                    pd.testing.assert_series_equal(before, after)

    def test_execution_waits_for_completed_bar_and_one_minute_delay(self) -> None:
        """機能: 各時間軸の足の確定から１分後まで新規約定しないと確認する。

        引数: self (CausalTests)。返り値: なし (None)。
        """
        for timeframe in (1, 5, 10):
            with self.subTest(足の分数=timeframe):
                data = minute_bars(periods=15)
                z, s = synthetic_features(data.index[0], [1])
                records = research.backtest(data, z, s, make_config(timeframe=timeframe), "TOPIX", "合成検証", labels=False)
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["entry_time"], data.index[timeframe+1])
                self.assertEqual(records[0]["signal_time"], data.index[timeframe])

    def test_resampling_excludes_incomplete_bar_and_preserves_completed_past(self) -> None:
        """機能: 未完成１０分足を除外し、将来追加で確定済み足が変わらないと確認する。

        引数: self (CausalTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=35)
        data.loc[data.index[25]:, ["open", "high", "low", "close"]] = [80, 81, 79, 80]
        before = research.make_bars(data.iloc[:25], pd.DataFrame(), 10)
        after = research.make_bars(data, pd.DataFrame(), 10)
        self.assertEqual(len(before), 2)
        self.assertEqual(len(after), 3)
        pd.testing.assert_frame_equal(before, after.iloc[:2])

    def test_future_append_preserves_earlier_entries_and_closed_trade(self) -> None:
        """機能: 将来足の追加で既存の新規判断と決済済み取引が変わらないと確認する。

        引数: self (CausalTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=80)
        data.loc[data.index[7], ["open", "high", "low", "close"]] = [95, 96, 94, 95]
        data.loc[data.index[40]:, ["open", "high", "low", "close"]] = [120, 121, 119, 120]
        prefix = simulate(data.iloc[:35], [1, 1, 1, 1, 1, 1])
        whole = simulate(data, [1]*16)
        self.assertEqual(prefix, whole[:len(prefix)])


class ExecutionTests(unittest.TestCase):
    """足内順序を仮定しない損切り、追跡、期限、再検知を確認する。"""

    def test_entry_bar_stop_for_both_sides(self) -> None:
        """機能: 新規約定した同じ足で初期損切りに触れた場合の決済を確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, expected in ((1, 97.0), (-1, 103.0)):
            with self.subTest(方向=side):
                data = minute_bars(periods=8)
                data.loc[data.index[6], ["high", "low"]] = [104.0, 96.0]
                rec = simulate(data, [side])[0]
                self.assertTrue(rec["closed"])
                self.assertEqual(rec["exit_time"], rec["entry_time"])
                self.assertEqual(rec["exit_price"], expected)
                self.assertEqual(rec["gross_points"], -3.0)

    def test_common_risk_atr_controls_stop_and_remains_fixed(self) -> None:
        """機能: 時間軸指標のＡＴＲでなく共通５分ＡＴＲを建玉時点で固定するか確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=14)
        data.loc[data.index[12], ["open", "high", "low", "close"]] = [100, 100.5, 96, 98]
        z, s = synthetic_features(data.index[0], [1, 1])
        z["atr"] = 0.1
        z["risk_atr"] = [2.0, 20.0]
        rec = research.backtest(data, z, s, make_config(), "TOPIX", "合成検証", labels=False)[0]
        self.assertEqual(rec["atr"], 2.0)
        self.assertEqual(rec["exit_price"], 97.0)
        self.assertEqual(rec["exit_time"], data.index[12])

    def test_missing_common_risk_atr_suppresses_entry(self) -> None:
        """機能: 共通５分ＡＴＲが未確定の場合に代替ＡＴＲで取引しないと確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=15)
        z, s = synthetic_features(data.index[0], [1])
        z["risk_atr"] = np.nan
        self.assertEqual(research.backtest(data, z, s, make_config(), "TOPIX", "合成検証", labels=False), [])

    def test_gap_through_stop_uses_unfavorable_open_for_both_sides(self) -> None:
        """機能: 損切り価格を飛び越す次足では不利な始値が約定価格となるか確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, opening in ((1, 95.0), (-1, 105.0)):
            with self.subTest(方向=side):
                data = minute_bars(periods=8)
                data.loc[data.index[7], ["open", "high", "low", "close"]] = [opening, opening+1, opening-1, opening]
                rec = simulate(data, [side])[0]
                self.assertEqual(rec["exit_price"], opening)
                self.assertEqual(rec["gross_points"], -5.0)

    def test_entry_close_updates_trailing_stop_for_next_bar(self) -> None:
        """機能: 約定足の確定終値による追跡損切りが次足から有効になるか確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, first, second, expected in (
            (1, [100, 104.5, 99.5, 104], [104, 104.5, 100, 100], 101.0),
            (-1, [100, 100.5, 95.5, 96], [96, 100, 95.5, 100], 99.0),
        ):
            with self.subTest(方向=side):
                data = minute_bars(periods=8)
                data.loc[data.index[6], ["open", "high", "low", "close"]] = first
                data.loc[data.index[7], ["open", "high", "low", "close"]] = second
                rec = simulate(data, [side])[0]
                self.assertTrue(rec["closed"], "前足終値の追跡水準で決済する必要がある")
                self.assertEqual(rec["exit_price"], expected)

    def test_same_bar_high_does_not_tighten_stop_before_low(self) -> None:
        """機能: 足内高値の先行を仮定せず前足終値からだけ追跡するか確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=9)
        data.loc[data.index[6], ["open", "high", "low", "close"]] = [100, 108, 99, 100]
        data.loc[data.index[7], ["open", "high", "low", "close"]] = [100, 110, 98, 109]
        data.loc[data.index[8], ["open", "high", "low", "close"]] = [109, 110, 105, 106]
        rec = simulate(data)[0]
        self.assertEqual(rec["exit_time"], data.index[8])
        self.assertEqual(rec["exit_price"], 106.0)

    def test_maximum_holding_exits_at_120_minute_open(self) -> None:
        """機能: 約定から１２０分経過した足の始値で決済するか確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=127)
        data.loc[data.index[126], ["open", "high", "low", "close"]] = [102, 102.5, 101.5, 102]
        rec = simulate(data)[0]
        self.assertEqual(rec["duration_min"], 120)
        self.assertEqual(rec["exit_price"], 102.0)
        self.assertEqual(rec["reason"], "120分経過")

    def test_fixed_session_deadline(self) -> None:
        """機能: 日中の固定決済期限に達した足の始値で決済するか確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        data = minute_bars("2026-09-21 14:50", 46)
        rec = simulate(data)[0]
        self.assertEqual(rec["exit_time"], pd.Timestamp("2026-09-21 15:35", tz="Asia/Tokyo"))
        self.assertEqual(rec["reason"], "時刻決済")

    def test_continuous_signal_is_not_repeated_after_stop(self) -> None:
        """機能: 継続点灯中は損切りと待機時間経過だけで同方向へ入り直さないと確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=70)
        data.loc[data.index[6], "low"] = 96
        self.assertEqual(len(simulate(data, [1]*14)), 1)

    def test_neutral_reset_respects_twenty_minute_cooldown(self) -> None:
        """機能: 中立２回で再検知可能になっても２０分待機が守られるか確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=35)
        data.loc[data.index[6], "low"] = 96
        rec = simulate(data, [1, 0, 0, 1, 1, 1, 1])
        self.assertEqual([r["entry_time"] for r in rec], [data.index[6], data.index[26]])


class LabelTests(unittest.TestCase):
    """未成熟・欠損がある将来を成功率の分母へ混ぜないことを確認する。"""

    def test_insufficient_future_is_unknown(self) -> None:
        """機能: ３０分の将来が揃わないイベントを不正解扱いしないと確認する。

        引数: self (LabelTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=15)
        label = research.label_wave(data, data.index[0], 100, 1, 2)
        self.assertIsNone(label["wave30"])
        self.assertIsNone(label["forward30_atr"])

    def test_short_jump_and_long_continuation_have_different_labels(self) -> None:
        """機能: 初期の急騰だけでは３０分持続ラベルの成功にならないと確認する。

        引数: self (LabelTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=40)
        data.loc[data.index[:5], ["high", "low", "close"]] = [102.5, 100, 102]
        label = research.label_wave(data, data.index[0], 100, 1, 2)
        self.assertTrue(label["wave5"])
        self.assertFalse(label["wave30"])
        data.loc[:, ["open", "high", "low", "close"]] = [101, 101.5, 100.5, 101]
        label = research.label_wave(data, data.index[0], 100, 1, 2)
        self.assertTrue(label["wave30"])

    def test_gap_over_two_minutes_invalidates_label(self) -> None:
        """機能: 将来価格に３分の欠測がある場合は持続性を採点しないと確認する。

        引数: self (LabelTests)。返り値: なし (None)。
        """
        data = minute_bars(periods=40)
        data = data.drop(data.index[10:13])
        label = research.label_wave(data, data.index[0], 100, 1, 2)
        self.assertIsNone(label["wave30"])
        self.assertIsNone(label["forward30_atr"])


class SummaryTests(unittest.TestCase):
    """異なる価格単位を誤って加算しないことを確認する。"""

    def test_mixed_symbol_points_are_not_reported(self) -> None:
        """機能: 両銘柄のポイント損益・比率・ドローダウンを混合集計しないと確認する。

        引数: self (SummaryTests)。返り値: なし (None)。
        """
        records = [dict(symbol=symbol, closed=True, wave30=True, net_points=points,
                        stress_points=points-1, net_atr=0.5, stress_atr=0.25, duration_min=30)
                   for symbol, points in (("NK225", 100), ("TOPIX", -2))]
        result = research.summary(records)
        for key in ("net_points", "stress_points", "profit_factor", "max_drawdown_points"):
            with self.subTest(集計項目=key):
                self.assertIsNone(result[key])

if __name__ == "__main__":
    unittest.main(verbosity=2)
