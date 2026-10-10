"""指定波の採点と帰無経路の価格整合を確認する。"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from null_checks import random_directions, rebuild_five, reflect_paths, summarize_runs
from targets import target_metrics
from bracket_checks import simulate_bracket
from engine import Config


ROOT = Path(__file__).resolve().parents[2]


class NullChecksTests(unittest.TestCase):
    """機能: 帰無経路と採点の境界条件を検査する。

    引数: unittest のテストメソッド名 (str)。返り値: テストケース (NullChecksTests)。
    """

    def test_original_targets_unchanged(self) -> None:
        """機能: 旧採用条件の４波採点が既存記録と一致することを確認する。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        records = json.loads((ROOT / "work/wave_v2/比較_採用指定波.json").read_text(encoding="utf-8"))
        trades = json.loads((ROOT / "work/wave_v2/比較_採用取引.json").read_text(encoding="utf-8"))
        for old in records:
            one = pd.read_csv(ROOT / "candle_1min" / old["symbol"] / f'{old["session"]}.csv')
            one.index = pd.to_datetime(one.pop("time"))
            new = target_metrics(one, trades, old["symbol"], old["session"])[0]
            for key in ("reference_points", "detection_delay_min", "correct_coverage", "opposite_coverage", "captured_points", "capture_ratio"):
                self.assertAlmostEqual(new[key], old[key], msg=key)
            self.assertEqual(new["passed"], old["passed"])
            self.assertEqual(new["coverage_pass"], old["passed"])

    def test_reflection_keeps_ranges_and_cross_asset_signs(self) -> None:
        """機能: 反転が高安・ギャップ幅・銘柄間の同時符号を保持するか調べる。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        index = pd.date_range("2026-09-22 17:00", periods=12, freq="min", tz="Asia/Tokyo")
        one = pd.DataFrame(dict(open=100 + np.arange(12), high=103 + np.arange(12), low=99 + np.arange(12), close=102 + np.arange(12), volume=1), index=index)
        copy = one.copy(deep=True)
        source = {("s", "NK225"): one, ("s", "TOPIX"): one * 2}
        transformed = reflect_paths(source, 260924000)
        first = transformed[("s", "NK225")]
        second = transformed[("s", "TOPIX")]
        pd.testing.assert_frame_equal(one, copy)
        np.testing.assert_allclose(first.high - first.low, one.high - one.low)
        np.testing.assert_allclose(np.abs(first.close - first.open), np.abs(one.close - one.open))
        np.testing.assert_allclose(np.abs(first.open.iloc[1:].to_numpy() - first.close.iloc[:-1].to_numpy()), np.abs(one.open.iloc[1:].to_numpy() - one.close.iloc[:-1].to_numpy()))
        np.testing.assert_allclose(second[["open", "high", "low", "close"]], first[["open", "high", "low", "close"]] * 2)
        self.assertTrue((first.high >= first[["open", "close"]].max(axis=1)).all())
        self.assertTrue((first.low <= first[["open", "close"]].min(axis=1)).all())
        pd.testing.assert_frame_equal(first, reflect_paths(source, 260924000)[("s", "NK225")])
        self.assertEqual(len(rebuild_five(first)), 2)

    def test_coin_direction_prefix_is_stable(self) -> None:
        """機能: 将来グリッド追加で既存乱数方向が変わらないことを確認する。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        index = pd.date_range("2026-09-22 17:00", periods=120, freq="min", tz="Asia/Tokyo")
        full = random_directions(index, 260923000)
        pd.testing.assert_series_equal(full.iloc[:51], random_directions(index[:51], 260923000))

    def test_incomplete_target_cannot_pass(self) -> None:
        """機能: 波の終端未観測や無取引を合格にしないことを確認する。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        index = pd.date_range("2026-09-23 09:00", periods=90, freq="min", tz="Asia/Tokyo")
        one = pd.DataFrame(dict(open=1000 - np.arange(90), close=999 - np.arange(90)), index=index)
        trade = dict(entry_time=index[5], exit_time=None, entry_price=995, exit_price=None, side=-1, closed=False)
        result = target_metrics(one, [trade], "NK225", "2026-09-23_Day")[0]
        self.assertFalse(result["target_complete"])
        self.assertFalse(result["passed"])
        empty = target_metrics(one, [], "NK225", "2026-09-23_Day")[0]
        self.assertEqual(empty["correct_coverage"], 0)
        self.assertFalse(empty["passed"])

    def test_distribution_does_not_add_symbols(self) -> None:
        """機能: 種の損益を銘柄内で集計し、異なる単位を混ぜないことを確認する。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        samples = [dict(symbol="NK225", seed=0, net_points=20, count=1), dict(symbol="NK225", seed=1, net_points=-10, count=1), dict(symbol="TOPIX", seed=0, net_points=1, count=1)]
        result = summarize_runs(samples, {"NK225": 20})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["mean"], 5)
        self.assertEqual(result[0]["profitable_seed_fraction"], 0.5)
        self.assertAlmostEqual(result[0]["reference_rank_fraction"], 2 / 3)

    def test_same_minute_loss_is_not_hidden(self) -> None:
        """機能: 新規足の同時返済損失を時間ゼロという理由で捕捉損益から消さない。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        index = pd.date_range("2026-09-23 09:00", periods=140, freq="min", tz="Asia/Tokyo")
        one = pd.DataFrame(dict(open=1000 - np.arange(140), close=999 - np.arange(140)), index=index)
        trade = dict(entry_time=index[10], exit_time=index[10], entry_price=990, exit_price=1000, side=-1, closed=True, net_points=-30)
        result = target_metrics(one, [trade], "NK225", "2026-09-23_Day")[0]
        self.assertEqual(result["captured_points"], -30)
        self.assertEqual(result["correct_coverage"], 0)
        self.assertEqual(result["correct_trade_net_points"], -30)

    def test_old_holding_is_not_new_wave_detection(self) -> None:
        """機能: 波のずっと前から保有しただけの取引を新しい波の検知と区別する。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        index = pd.date_range("2026-09-23 08:00", periods=210, freq="min", tz="Asia/Tokyo")
        one = pd.DataFrame(dict(open=2000 - np.arange(210), close=1999 - np.arange(210)), index=index)
        trade = dict(entry_time=index[0], exit_time=index[205], entry_price=2000, exit_price=1795, side=-1, closed=True, net_points=185)
        result = target_metrics(one, [trade], "NK225", "2026-09-23_Day")[0]
        self.assertTrue(result["coverage_pass"])
        self.assertFalse(result["passed"])
        self.assertIsNone(result["fresh_detection_delay_min"])
        self.assertEqual(result["carried_from_before_window_count"], 1)
        trade.update(entry_time=index[45], entry_price=1955, net_points=140)
        result = target_metrics(one, [trade], "NK225", "2026-09-23_Day")[0]
        self.assertTrue(result["passed"])
        self.assertEqual(result["fresh_detection_delay_min"], -20)
        self.assertEqual(result["early_entry_lead_min"], 20)

    def test_fixed_bracket_adverse_order_gap_and_deadline(self) -> None:
        """機能: 固定利確・損切りが同足接触、飛び越し、期限返済を不利側に処理する。

        引数: self (NullChecksTests)。返り値: なし (None)。
        """
        start = pd.Timestamp("2026-09-23 08:45", tz="Asia/Tokyo")
        times = pd.DatetimeIndex([start + pd.Timedelta(minutes=value) for value in (2, 3, 100)])
        data = dict(symbol="NK225", session="試験", tick=10.0, limit_min=100,
                    times=times, minutes=np.array([2, 3, 100]), positions=np.array([0, 1, 2]),
                    atr=np.array([20.0] * 3), ref=np.array([1000.0] * 3), limit=times[-1],
                    values=np.array([[1000, 1000, 1000, 1000], [1000, 1020, 950, 1000], [1010, 1010, 1010, 1010]], dtype=float))
        cfg = Config(101, entry="signal_limit", cooldown=20, warmup=0)
        schedule = (np.ones(3, dtype=int), np.ones(3, dtype=int))
        result = simulate_bracket(data, schedule, cfg, 0.5, 2.0)
        self.assertEqual(result[0]["exit_price"], 960)
        self.assertTrue(result[0]["ambiguous_exit"])
        data["values"][1] = [940, 950, 930, 940]
        result = simulate_bracket(data, schedule, cfg, 0.5, 2.0)
        self.assertEqual(result[0]["exit_price"], 940)
        data["values"][1] = [1000, 1005, 990, 1000]
        result = simulate_bracket(data, schedule, cfg, 2.0, 2.0)
        self.assertEqual(result[0]["exit_time"], times[-1])
        self.assertTrue(result[0]["closed"])
        self.assertEqual(result[0]["reason"], "セッション内の時刻返済")


if __name__ == "__main__":
    unittest.main()
