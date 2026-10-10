"""両建ての費用、順序、時間境界、再開条件を点検する。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hedge import HedgeConfig, simulate


def fixture(bars: list[list[float]], minutes: list[int] | None = None) -> dict:
    """機能: 先読み・同足接触の検査用に小さい再生入力を作る。

    引数: bars (list[list[float]]) はOHLC、minutes (list[int] | None) はセッションからの分。
    返り値: 再生入力 (dict)。
    """
    elapsed = minutes or list(range(15, 15 + len(bars) - 1)) + [100]
    start = pd.Timestamp("2026-09-23 08:45", tz="Asia/Tokyo")
    return dict(symbol="NK225", session="検査", tick=1.0, limit_min=100,
                values=np.array(bars, dtype=float), times=pd.DatetimeIndex([start + pd.Timedelta(minutes=x) for x in elapsed]),
                minutes=np.array(elapsed), positions=np.arange(len(bars)),
                atr=np.full(len(bars), 10.0), ref=np.full(len(bars), 100.0))


class HedgeTests(unittest.TestCase):
    """機能: 両建てモデルの実行規則を検査する。

    引数: unittestのメソッド名 (str)。返り値: テストケース (HedgeTests)。
    """

    def test_flat_hedge_costs_both_legs(self) -> None:
        """機能: 同価格で開始・終了した両建てが２脚分の費用損になることを調べる。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        trades, cell = simulate(fixture([[100, 100, 100, 100], [100, 100, 100, 100]]), HedgeConfig("固定利確", 1, 3, 30, 15))
        self.assertEqual(len(trades), 2)
        self.assertEqual(cell["cycle_count"], 1)
        self.assertEqual(cell["gross_points"], 0)
        self.assertEqual(cell["net_points"], -4)
        self.assertEqual(cell["stress_points"], -8)

    def test_both_touch_prefers_stop_and_gap_is_adverse(self) -> None:
        """機能: 利確と損切りの両接触を損切り側、飛び越しを不利な始値で処理する。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        bars = [[100, 100, 100, 100], [100, 130, 70, 100], [100, 100, 100, 100]]
        trades, cell = simulate(fixture(bars), HedgeConfig("固定利確", 0.5, 2, 30, 15))
        self.assertEqual(sorted(t["gross_points"] for t in trades), [-5, -5])
        self.assertEqual(cell["ambiguous"], 2)
        bars[1] = [80, 82, 78, 80]
        trades, cell = simulate(fixture(bars), HedgeConfig("固定利確", 0.5, 4, 30, 15))
        self.assertEqual(next(t["exit_price"] for t in trades if t["side"] == 1), 80)

    def test_trail_cannot_use_same_bar_peak_for_exit(self) -> None:
        """機能: 同じ足で新高値から追跡価格を更新し、過去の安値へ約定させない。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        bars = [[100, 100, 100, 100], [100, 140, 100, 138], [130, 131, 119, 125], [100, 100, 100, 100]]
        data = fixture(bars)
        trades, cell = simulate(data, HedgeConfig("勝ち脚追跡", 0.5, 2, 30, 15))
        long = next(t for t in trades if t["side"] == 1)
        self.assertEqual(long["exit_time"], data["times"][2])
        self.assertEqual(long["exit_price"], 120)

    def test_no_restart_until_both_legs_flat(self) -> None:
        """機能: 片脚が返済された後も残存脚の保有中は再新規しない。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        bars = [[100, 100, 100, 100], [100, 108, 100, 108], [108, 109, 105, 108], [110, 110, 110, 110]]
        data = fixture(bars, [15, 16, 60, 100])
        trades, cell = simulate(data, HedgeConfig("固定利確", 0.5, 4, 15, 15))
        self.assertEqual(cell["cycle_count"], 1)
        self.assertEqual(cell["count"], cell["closed"])
        self.assertEqual(next(t["exit_time"] for t in trades if t["side"] == 1), data["times"][-1])

    def test_coin_seed_reproducibility_and_two_contract_scale(self) -> None:
        """機能: 乱数種の再現性と総絶対枚数２への倍率を確認する。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        data = fixture([[100, 100, 100, 100], [100, 100, 100, 100]])
        cfg = HedgeConfig("勝ち脚追跡", 1, 3, 30, 15)
        first = simulate(data, cfg, 260925000)
        second = simulate(data, cfg, 260925000)
        self.assertEqual(first, second)
        self.assertEqual(first[1]["count"], 1)
        self.assertEqual(first[1]["net_points"], -2)
        self.assertEqual(first[1]["equivalent_two_contract_net_points"], -4)

    def test_unfilled_limit_and_no_intrabar_entry_selection(self) -> None:
        """機能: 両方の許容価格を満たさない始値では都合のよい足内部価格を使わない。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        data = fixture([[120, 121, 100, 100], [100, 100, 100, 100]])
        trades, cell = simulate(data, HedgeConfig("固定利確", 1, 3, 30, 15))
        self.assertEqual(cell["count"], 0)
        self.assertEqual(trades, [])

    def test_same_entry_bar_two_stops_and_accounting(self) -> None:
        """機能: 新規足の往復で両脚損切りとなる場合にも費用と損益を落とさない。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        data = fixture([[100, 110, 90, 100], [100, 100, 100, 100]])
        trades, cell = simulate(data, HedgeConfig("固定利確", .5, 3, 30, 15))
        self.assertEqual(cell["closed"], 2)
        self.assertEqual(cell["net_points"], -14)
        self.assertEqual(cell["profit_points"] - cell["loss_points"], cell["net_points"])
        self.assertTrue(all(t["entry_time"] == t["exit_time"] for t in trades))

    def test_flat_cooldown_boundary_and_seed_prefix(self) -> None:
        """機能: 両脚終了後の待機境界と、未来を足しても以前の乱数結果が不変か調べる。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        bars = [[100, 110, 90, 100]] * 4 + [[100, 100, 100, 100]]
        data = fixture(bars, [15, 20, 44, 45, 100])
        cfg = HedgeConfig("固定利確", .5, 3, 30, 15)
        trades, cell = simulate(data, cfg)
        self.assertEqual(cell["cycle_count"], 2)
        self.assertEqual(sorted({t["entry_time"] for t in trades}), [data["times"][0], data["times"][3]])
        full, unused = simulate(data, cfg, 260925000)
        prefix = dict(data)
        for key in ("values", "times", "minutes", "positions", "atr", "ref"):
            prefix[key] = data[key][:3]
        previous, unused = simulate(prefix, cfg, 260925000)
        self.assertEqual(previous, full[:len(previous)])

    def test_known_open_target_precedes_later_stop(self) -> None:
        """機能: 始値で利確が成立した既存脚を、その後の同足安値高値で損切りへ戻さない。

        引数: self (HedgeTests)。返り値: なし (None)。
        """
        cfg = HedgeConfig("固定利確", .5, 2, 30, 15)
        for side, bar, target in ((1, [125, 130, 94, 100], 120), (-1, [75, 106, 70, 100], 80)):
            data = fixture([[100, 100, 100, 100], bar, [100, 100, 100, 100]])
            trades, unused = simulate(data, cfg)
            leg = next(trade for trade in trades if trade["side"] == side)
            self.assertEqual(leg["exit_price"], target)
            self.assertEqual(leg["reason"], "始値で成立した固定利確")


if __name__ == "__main__":
    unittest.main()
