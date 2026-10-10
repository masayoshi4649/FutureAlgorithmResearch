"""固定損益比と小さい初期損切りについて、価格順序・因果性・既存互換を検査する。"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from exits import BASE, ConfigV5, simulate_exit


ROOT = Path(__file__).resolve().parents[2]


def sample(rows: list[tuple], positions: list[int] | None = None,
           start: str = "2026-09-21 09:00:00+09:00") -> dict:
    """機能: 一定ATR・既知基準価格を持つ手計算用の足を作る。

    引数: rows (list[tuple]) は始高安終、positions (list[int] | None) は実在する分位置、start (str) は開始。
    返り値: prepare と同じ再生入力 (dict)。
    """
    positions = list(range(len(rows))) if positions is None else positions
    grid = pd.date_range(start, periods=max(positions) + 1, freq="min")
    one = pd.DataFrame(rows, index=grid[positions], columns=["open", "high", "low", "close"], dtype=float)
    z = pd.DataFrame(dict(close=1000.0, atr=20.0, reg15=1.0, r2_15=0.5), index=grid)
    return BASE.prepare(one, z, "NK225", "合成セッション")


def run_sample(rows: list[tuple], side: int = 1, **kwargs) -> list[dict]:
    """機能: 初動待ちなしの合成足を追加返済方式で再生する。

    引数: rows (list[tuple])、side (int) は方向、kwargs (dict) は比較条件。
    返り値: 仮想取引 (list[dict])。
    """
    data = sample(rows)
    cfg = ConfigV5(1, warmup=0, **kwargs)
    return simulate_exit(data, BASE.sign_schedule(np.full(len(data["z"]), side)), cfg)


def execution_view(trades: list[dict]) -> list[dict]:
    """機能: 理由文や追加診断列を除き、約定と損益だけを比較可能にする。

    引数: trades (list[dict])。返り値: 比較用取引 (list[dict])。
    """
    fields = ("symbol", "session", "side", "signal_time", "entry_time", "entry_price", "atr", "exit_time",
              "exit_price", "closed", "duration_min", "gross_points", "net_points", "stress_points", "net_atr")
    return [{key: trade[key] for key in fields if key in trade} for trade in trades]


class ExitOrderTests(unittest.TestCase):
    """機能: 手計算できる価格経路で損切り・利確の成立順序を確認する。

    引数: unittest が設定する状態。返り値: TestCase インスタンス。
    """

    def test_loss_gap_both_directions(self) -> None:
        """機能: 初期損切りを飛び越えた始値は不利な始値で返済する。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        for side, gap in ((1, (940, 950, 930, 940)), (-1, (1060, 1070, 1050, 1060))):
            with self.subTest(side=side):
                trade = run_sample([(1000, 1000, 1000, 1000)] * 3 + [gap], side, exit_mode="fixed_bracket")[0]
                self.assertEqual(trade["gross_points"], -60)
                self.assertEqual(trade["net_points"], -80)

    def test_profit_gap_capped_at_limit(self) -> None:
        """機能: 利確を越えた有利な始値でも、指値価格より有利な利益を計上しない。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        for side, gap, expected in ((1, (1100, 1110, 1090, 1100), 1060), (-1, (900, 910, 890, 900), 940)):
            with self.subTest(side=side):
                trade = run_sample([(1000, 1000, 1000, 1000)] * 3 + [gap], side, exit_mode="fixed_bracket")[0]
                self.assertEqual(trade["exit_price"], expected)
                self.assertEqual(trade["gross_points"], 60)

    def test_both_hit_loss_first(self) -> None:
        """機能: 保有後の同じ足で損切りと利確の両方に触れたときは損失を優先する。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        for side in (1, -1):
            with self.subTest(side=side):
                trade = run_sample([(1000, 1000, 1000, 1000)] * 3 + [(1000, 1070, 930, 1000)], side, exit_mode="fixed_bracket")[0]
                self.assertEqual(trade["gross_points"], -20)
                self.assertTrue(trade["ambiguous_exit"])

    def test_open_profit_precedes_later_stop(self) -> None:
        """機能: 始値で既に利確成立していれば、その後の反落で損切りへ差し替えない。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        trade = run_sample([(1000, 1000, 1000, 1000)] * 3 + [(1080, 1100, 970, 990)], exit_mode="fixed_bracket")[0]
        self.assertEqual(trade["exit_price"], 1060)
        self.assertFalse(trade["ambiguous_exit"])

    def test_entry_bar_both_hit_loss_first(self) -> None:
        """機能: 新規足でも保護価格と利確の両接触は損失扱いにする。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        trade = run_sample([(1000, 1000, 1000, 1000)] * 2 + [(1000, 1080, 980, 1070)],
                           entry="stop", offset=0.5, exit_mode="fixed_bracket")[0]
        self.assertEqual(trade["entry_price"], 1010)
        self.assertEqual(trade["exit_price"], 990)
        self.assertTrue(trade["ambiguous_entry"])
        self.assertTrue(trade["ambiguous_exit"])

    def test_intrabar_limit_entry_does_not_claim_prior_high(self) -> None:
        """機能: 押し目新規より前に付けたかもしれない高値で、同足利確を断定しない。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        rows = [(1000, 1000, 1000, 1000)] * 2 + [(1000, 1060, 985, 1000)]
        trade = run_sample(rows, entry="pullback", offset=0.5, exit_mode="fixed_bracket")[0]
        self.assertEqual(trade["entry_price"], 990)
        self.assertFalse(trade["closed"])
        self.assertTrue(trade["ambiguous_exit"])

    def test_close_guarantees_same_bar_profit(self) -> None:
        """機能: 新規後の終値が利確を越えていれば、保護未接触の同足利確を認める。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        rows = [(1000, 1000, 1000, 1000)] * 2 + [(1000, 1060, 985, 1050)]
        trade = run_sample(rows, entry="pullback", offset=0.5, exit_mode="fixed_bracket")[0]
        self.assertEqual(trade["exit_price"], 1050)
        self.assertEqual(trade["entry_time"], trade["exit_time"])

    def test_fixed_bracket_does_not_trail(self) -> None:
        """機能: 固定損益比方式では高値を更新しても初期損切りを追跡させない。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        rows = [(1000, 1000, 1000, 1000)] * 3 + [(1000, 1050, 990, 1040), (1030, 1040, 990, 1000)]
        trade = run_sample(rows, exit_mode="fixed_bracket", trail=1)[0]
        self.assertFalse(trade["closed"])
        self.assertEqual(trade["initial_stop"], 980)

    def test_small_stop_and_following_bar_trail(self) -> None:
        """機能: 小さい初期保護を置き、高値更新による追跡返済は次足から有効にする。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        rows = [(1000, 1000, 1000, 1000)] * 3 + [(1000, 1100, 990, 1080), (1070, 1080, 1030, 1040)]
        trade = run_sample(rows, exit_mode="small_stop_trail", trail=3)[0]
        self.assertEqual(trade["initial_stop"], 980)
        self.assertEqual(trade["exit_time"].minute, 4)
        self.assertEqual(trade["exit_price"], 1040)

    def test_protection_survives_missing_atr(self) -> None:
        """機能: 保有後のATR欠測で初期保護を停止しない。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        data = sample([(1000, 1000, 1000, 1000)] * 3 + [(940, 950, 930, 940)])
        data["atr"] = data["atr"].copy()
        data["atr"][1] = np.nan
        cfg = ConfigV5(1, exit_mode="small_stop_trail", warmup=0)
        trade = simulate_exit(data, BASE.sign_schedule(np.ones(4)), cfg)[0]
        self.assertEqual(trade["exit_price"], 940)

    def test_session_deadline_and_missing_bar(self) -> None:
        """機能: 実在足でのみ新規・返済し、期限後最初の実在足で同セッション内返済する。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        data = sample([(1000, 1000, 1000, 1000)] * 4, positions=[0, 1, 4, 37], start="2026-09-21 15:00:00+09:00")
        cfg = ConfigV5(1, exit_mode="fixed_bracket", warmup=0)
        trade = simulate_exit(data, BASE.sign_schedule(np.ones(len(data["z"]))), cfg)[0]
        self.assertEqual(trade["entry_time"], data["z"].index[4])
        self.assertEqual(trade["exit_time"], data["z"].index[37])
        self.assertEqual(trade["reason"], "セッション内の時刻返済")

    def test_key_distinguishes_exit_parameters(self) -> None:
        """機能: 初期損切り・利確・方式が異なる設定を同じ識別子にしない。

        引数: self (ExitOrderTests)。返り値: なし (None)。
        """
        configs = [ConfigV5(1, exit_mode=mode, stop_loss=loss, take_profit=profit)
                   for mode in ("nativebaseline", "fixed_bracket", "small_stop_trail")
                   for loss in (0.5, 1.0) for profit in (2.0, 3.0)]
        self.assertEqual(len(configs), len({cfg.key for cfg in configs}))


class HistoricalExitTests(unittest.TestCase):
    """機能: 五つの保存セッションで既存互換と切断再生を確認する。

    引数: unittest が設定する状態。返り値: TestCase インスタンス。
    """

    @classmethod
    def setUpClass(cls) -> None:
        """機能: 通信せず保存済み五セッションを一度だけ読み込む。

        引数: cls (type[HistoricalExitTests])。返り値: なし (None)。
        """
        from data import load_data_v5
        cls.data = load_data_v5()

    def test_native_and_equivalent_small_stop_match(self) -> None:
        """機能: 既存委譲は完全一致し、同じ初期幅の追加追跡も既存約定を保つ。

        引数: self (HistoricalExitTests)。返り値: なし (None)。
        """
        from research import schedule_for
        methods = ("signal_limit", "pullback", "stop", "trail", "straddle_stop", "straddle_trail")
        for entry in methods:
            base_cfg = BASE.Config(1, entry=entry, trail=2.5, warmup=14)
            schedule = schedule_for(self.data, base_cfg)
            added_cfg = ConfigV5(**asdict(base_cfg), exit_mode="small_stop_trail", stop_loss=2.5)
            for key, item in self.data.items():
                with self.subTest(key=key, entry=entry):
                    old = BASE.simulate(item, schedule[key], base_cfg)
                    native = simulate_exit(item, schedule[key], base_cfg)
                    self.assertEqual(native, old)
                    added = simulate_exit(item, schedule[key], added_cfg)
                    self.assertEqual(execution_view(added), execution_view(old))

    def test_added_exits_prefix(self) -> None:
        """機能: 利確・初期保護・追跡が未来の価格追加で過去約定を変えないことを確認する。

        引数: self (HistoricalExitTests)。返り値: なし (None)。
        """
        from research import schedule_for
        checks = 0
        for mode in ("fixed_bracket", "small_stop_trail"):
            for entry in ("signal_limit", "pullback", "stop", "trail"):
                cfg = ConfigV5(9, entry=entry, exit_mode=mode, trail_basis="current", trail=3, stop_loss=1, take_profit=3)
                schedules = schedule_for(self.data, cfg)
                for key, full in self.data.items():
                    completed = simulate_exit(full, schedules[key], cfg)
                    self.assertTrue(all(trade["closed"] for trade in completed))
                    for fraction in (0.35, 0.70):
                        cutoff = full["z"].index[int((len(full["z"]) - 1) * fraction)]
                        one = full["one"].loc[:cutoff]
                        z = full["z"].loc[:cutoff]
                        clipped = BASE.prepare(one, z, key[1], key[0])
                        clipped_schedule = (schedules[key][0][:len(z)], schedules[key][1][:len(z)])
                        result = simulate_exit(clipped, clipped_schedule, cfg)
                        expected = []
                        for original in execution_view(completed):
                            if original["entry_time"] > one.index[-1]:
                                continue
                            trade = dict(original)
                            if trade["closed"] and trade["exit_time"] > one.index[-1]:
                                trade.update(exit_time=None, exit_price=None, closed=False, duration_min=None, gross_points=None)
                                for field in ("net_points", "stress_points", "net_atr"):
                                    trade.pop(field, None)
                            expected.append(trade)
                        with self.subTest(mode=mode, entry=entry, key=key, fraction=fraction):
                            self.assertEqual(execution_view(result), expected)
                        checks += 1
        print(f"追加返済の五セッション切断一致: {checks} 条件")


if __name__ == "__main__":
    unittest.main(verbosity=2)
