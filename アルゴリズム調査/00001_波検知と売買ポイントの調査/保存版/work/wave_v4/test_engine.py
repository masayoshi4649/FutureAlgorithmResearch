"""新規条件と追跡返済の因果性・順序・セッション境界を独立に検査する。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

import engine
import signals


ROOT = Path(__file__).resolve().parents[2]
SESSIONS = ("2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night")
METHODS = ("signal_limit", "pullback", "stop", "trail", "straddle_stop", "straddle_trail")


def synthetic(
    rows: list[tuple[float, float, float, float]],
    start: str = "2026-09-21 09:00:00+09:00",
    positions: list[int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """機能: 実在足と均一な既知特徴を持つ合成セッションを作る。

    引数: rows (list[tuple[float, float, float, float]]) は始高安終、start (str) は開始、
    positions (list[int] | None) は実在する分位置。
    返り値: 実在足と特徴 (tuple[DataFrame, DataFrame])。
    """
    if positions is None:
        positions = list(range(len(rows)))
    grid = pd.date_range(start, periods=max(positions) + 1, freq="min")
    one = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=grid[positions], dtype=float)
    z = pd.DataFrame({"close": 1000.0, "atr": 20.0}, index=grid)
    return one, z


def play(one: pd.DataFrame, z: pd.DataFrame, directions: np.ndarray, cfg: engine.Config) -> list[dict]:
    """機能: 初動待ちを無効にして、合成足の約定機能だけを分離して再生する。

    引数: one/z (DataFrame)、directions (ndarray)、cfg (Config)。
    返り値: 仮想取引 (list[dict])。
    """
    return engine.simulate(engine.prepare(one, z, "NK225", "合成デイ"), engine.sign_schedule(directions), replace(cfg, warmup=0))


def prefix_trades(trades: list[dict], cutoff: pd.Timestamp) -> list[dict]:
    """機能: 全期間の取引記録を、切断時刻に見えていた状態へ投影する。

    引数: trades (list[dict])、cutoff (Timestamp) は最後の実在足開始時刻。
    返り値: 切断時点の取引 (list[dict])。
    """
    result = []
    for original in trades:
        if original["entry_time"] > cutoff:
            continue
        trade = dict(original)
        if trade["closed"] and trade["exit_time"] > cutoff:
            trade.update(exit_time=None, exit_price=None, closed=False, duration_min=None,
                         gross_points=None, reason="観測途中")
            for key in ("net_points", "stress_points", "net_atr"):
                trade.pop(key, None)
        result.append(trade)
    return result


class ExecutionTests(unittest.TestCase):
    """機能: 高安の順序と取引時刻を手計算できる足で確認する。

    引数: unittest が設定する試験実行状態。返り値: TestCase インスタンス。
    """

    def test_confirmation_and_delay(self) -> None:
        """機能: 符号確認回数と、確定後１分遅延を検査する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        raw = np.array([1, 1, 0, -1, -1, -1, np.nan])
        side, streak = engine.sign_schedule(raw)
        np.testing.assert_array_equal(side, [1, 1, 0, -1, -1, -1, 0])
        np.testing.assert_array_equal(streak, [1, 2, 0, 1, 2, 3, 0])
        one, z = synthetic([(1000, 1010, 990, 1000)] * 6)
        trades = play(one, z, np.ones(len(z)), engine.Config(1, confirm=2))
        self.assertEqual(trades[0]["entry_time"], z.index[3])
        self.assertEqual(trades[0]["signal_time"], z.index[2])

    def test_unobserved_prices_never_fill(self) -> None:
        """機能: 価格特徴を前方補完しても、欠落した足で約定しないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z = synthetic([(1000, 1010, 990, 1000)] * 3, positions=[0, 1, 5])
        trades = play(one, z, np.ones(len(z)), engine.Config(1))
        self.assertEqual(trades[0]["entry_time"], z.index[5])
        self.assertTrue(all(t["entry_time"] in one.index for t in trades))

    def test_gap_stop_both_directions(self) -> None:
        """機能: 保有後の不利な始値ギャップを保護価格で美化しないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, gap, expected in ((1, (940, 950, 930, 940), 940), (-1, (1060, 1070, 1050, 1060), 1060)):
            with self.subTest(side=side):
                one, z = synthetic([(1000, 1010, 990, 1000)] * 3 + [gap])
                trades = play(one, z, np.full(len(z), side), engine.Config(1, trail=2))
                self.assertEqual(len(trades), 1)
                self.assertEqual(trades[0]["exit_price"], expected)
                self.assertEqual(trades[0]["gross_points"], -60)

    def test_pullback_limit_price(self) -> None:
        """機能: 押し戻りの指値は接触前に約定せず、成立価格も不利に変えないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side in (1, -1):
            with self.subTest(side=side):
                neutral = (1000, 1000, 1000, 1000)
                touch = (1000, 1010, 990, 1000)
                one, z = synthetic([neutral] * 3 + [touch])
                trades = play(one, z, np.full(len(z), side), engine.Config(1, entry="pullback", offset=0.5, trail=3))
                self.assertEqual(trades[0]["entry_time"], z.index[3])
                self.assertEqual(trades[0]["entry_price"], 1000 - side * 10)

    def test_stop_entry_adverse_open(self) -> None:
        """機能: 逆指値新規の閾値を飛び越した始値を実約定価格に反映する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, gap, expected in ((1, (1040, 1050, 1030, 1040), 1040), (-1, (960, 970, 950, 960), 960)):
            with self.subTest(side=side):
                one, z = synthetic([(1000, 1000, 1000, 1000)] * 2 + [gap])
                trades = play(one, z, np.full(len(z), side), engine.Config(1, entry="stop", offset=0.5))
                self.assertEqual(trades[0]["entry_price"], expected)

    def test_entry_trailing_uses_prior_bar_anchor(self) -> None:
        """機能: 新規追跡の当分安値・高値を、同分の反発成立に遡って使用しない。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, excursion, trigger, expected in (
            (1, (1000, 1000, 960, 980), (980, 990, 970, 980), 980),
            (-1, (1000, 1040, 1000, 1020), (1020, 1030, 1010, 1020), 1020),
        ):
            with self.subTest(side=side):
                one, z = synthetic([(1000, 1000, 1000, 1000)] * 2 + [excursion, trigger])
                cfg = engine.Config(1, entry="trail", offset=0.5, trail=3)
                trades = play(one, z, np.full(len(z), side), cfg)
                self.assertEqual(trades[0]["entry_time"], z.index[3])
                self.assertEqual(trades[0]["entry_price"], expected)

    def test_same_bar_entry_stop_is_loss_and_marked(self) -> None:
        """機能: 新規後の保護価格接触を否定できない足は損失と曖昧印を付ける。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, wide in ((1, (1000, 1020, 960, 1000)), (-1, (1000, 1040, 980, 1000))):
            with self.subTest(side=side):
                one, z = synthetic([(1000, 1000, 1000, 1000)] * 2 + [wide])
                cfg = engine.Config(1, entry="stop", offset=0.5, trail=2)
                trade = play(one, z, np.full(len(z), side), cfg)[0]
                self.assertTrue(trade["closed"])
                self.assertTrue(trade["ambiguous_entry"])
                self.assertEqual(trade["entry_time"], trade["exit_time"])
                self.assertEqual(trade["gross_points"], -40)

    def test_entry_bar_high_cannot_tighten_stop_retroactively(self) -> None:
        """機能: 新規足の順序不明な高値で、同足の返済価格を引き上げない。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z = synthetic([(1000, 1000, 1000, 1000)] * 2 + [(1000, 1100, 990, 1000), (1000, 1010, 990, 1000)])
        trade = play(one, z, np.ones(len(z)), engine.Config(1, trail=2))[0]
        self.assertFalse(trade["closed"])

    def test_existing_trail_updates_after_close(self) -> None:
        """機能: 既存保有の高値追跡は確定後の次足から有効になる。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        rows = [(1000, 1000, 1000, 1000)] * 3 + [(1000, 1100, 980, 1050), (1070, 1080, 1050, 1060)]
        one, z = synthetic(rows)
        trade = play(one, z, np.ones(len(z)), engine.Config(1, trail=2))[0]
        self.assertEqual(trade["exit_time"], z.index[4])
        self.assertEqual(trade["exit_price"], 1060)

    def test_current_atr_shrinks_then_never_loosens_stop(self) -> None:
        """機能: 現在ATRの縮小で保護価格を締め、再拡大しても緩めないことを確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, touch, expected in ((1, (1000, 1010, 970, 990), 980), (-1, (1000, 1030, 990, 1010), 1020)):
            with self.subTest(side=side):
                one, z = synthetic([(1000, 1000, 1000, 1000)] * 5 + [touch])
                z["atr"] = [20.0, 10.0, 40.0, 40.0, 40.0, 40.0]
                cfg_current = engine.Config(1, trail=2, trail_basis="current")
                cfg_entry = engine.Config(1, trail=2, trail_basis="entry")
                current = play(one, z, np.full(len(z), side), cfg_current)[0]
                entry = play(one, z, np.full(len(z), side), cfg_entry)[0]
                self.assertEqual(current["exit_time"], z.index[5])
                self.assertEqual(current["exit_price"], expected)
                self.assertEqual(current["atr"], 20)
                self.assertFalse(entry["closed"])

    def test_straddle_obeys_confirmation(self) -> None:
        """機能: 上下同時待機の注文も、指定された連続確認回数より前には発注しない。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for method in ("straddle_stop", "straddle_trail"):
            with self.subTest(method=method):
                one, z = synthetic([(1000, 1020, 980, 1000)] * 5)
                trade = play(one, z, np.ones(len(z)), engine.Config(1, entry=method, confirm=2))[0]
                self.assertEqual(trade["entry_time"], z.index[3])

    def test_warmup_earliest_entry_resets_each_session(self) -> None:
        """機能: 初動待ちは日中・夜間ごとにリセットされ、欠測後の初観測からは数えない。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for warmup in (30, 45, 60):
            for start, side in (("2026-09-21 08:45:00+09:00", 1), ("2026-09-21 17:00:00+09:00", -1)):
                with self.subTest(warmup=warmup, start=start):
                    positions = list(range(20, 81))
                    one, z = synthetic([(1000, 1000, 1000, 1000)] * len(positions), start=start, positions=positions)
                    cfg = engine.Config(1, warmup=warmup)
                    result = engine.simulate(engine.prepare(one, z, "NK225", start), engine.sign_schedule(np.full(len(z), side)), cfg)
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0]["entry_time"], z.index[warmup])
                    self.assertEqual(result[0]["side"], side)

    def test_warmup_prevents_prearmed_trailing_anchor(self) -> None:
        """機能: 初動待ち中の極値を使って新規追跡注文を先に準備しない。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        rows = [(1000, 1000, 1000, 1000)] * 47
        rows[44] = (1000, 1000, 960, 980)
        rows[45] = (980, 1000, 970, 980)
        rows[46] = (990, 1000, 980, 990)
        one, z = synthetic(rows, start="2026-09-21 08:45:00+09:00")
        cfg = engine.Config(1, entry="trail", offset=0.5, warmup=45)
        result = engine.simulate(engine.prepare(one, z, "NK225", "初動待ち"), engine.sign_schedule(np.ones(len(z))), cfg)
        self.assertEqual(result[0]["entry_time"], z.index[46])
        self.assertEqual(result[0]["entry_price"], 990)

    def test_regime_break_tightens_without_market_exit(self) -> None:
        """機能: 直線性崩れは追跡幅だけを縮め、成行返済せず、状態回復でも保護価格を緩めない。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for side, touch, expected in ((1, (1000, 1010, 970, 990), 980), (-1, (1000, 1030, 990, 1010), 1020)):
            with self.subTest(side=side):
                one, z = synthetic([(1000, 1000, 1000, 1000)] * 5 + [touch])
                z["reg15"] = float(side)
                z["r2_15"] = [0.5, 0.1, 0.5, 0.5, 0.5, 0.5]
                regime = play(one, z, np.full(len(z), side), engine.Config(1, trail=3, trail_basis="regime"))[0]
                current = play(one, z, np.full(len(z), side), engine.Config(1, trail=3, trail_basis="current"))[0]
                self.assertEqual(regime["exit_time"], z.index[5])
                self.assertEqual(regime["exit_price"], expected)
                self.assertFalse(current["closed"])

    def test_signal_neutral_and_reverse_do_not_exit(self) -> None:
        """機能: 中立または逆方向の新規信号だけでは保有を返済しない。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z = synthetic([(1000, 1010, 990, 1000)] * 7)
        trade = play(one, z, np.array([1, 0, -1, -1, 0, 0, 0]), engine.Config(1))[0]
        self.assertEqual(trade["side"], 1)
        self.assertFalse(trade["closed"])

    def test_straddle_double_touch_is_marked(self) -> None:
        """機能: 上下両条件に触れた足は先着を断定せず曖昧印を残す。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        for method in ("straddle_stop", "straddle_trail"):
            with self.subTest(method=method):
                one, z = synthetic([(1000, 1000, 1000, 1000)] * 2 + [(1000, 1020, 980, 1000)])
                trade = play(one, z, np.ones(len(z)), engine.Config(1, entry=method, trail=3))[0]
                self.assertTrue(trade["ambiguous_entry"])

    def test_session_deadline_and_foreign_price_rejection(self) -> None:
        """機能: セッション時刻返済と、後続セッション価格を混ぜた入力の拒否を確認する。

        引数: self (ExecutionTests)。返り値: なし (None)。
        """
        one, z = synthetic([(1000, 1010, 990, 1000)] * 40, start="2026-09-21 15:00:00+09:00")
        trades = play(one, z, np.ones(len(z)), engine.Config(1))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_time"], pd.Timestamp("2026-09-21 15:35:00+09:00"))
        self.assertEqual(trades[0]["reason"], "セッション内の時刻返済")
        for final in ("2026-09-21 15:40:00+09:00", "2026-09-21 17:00:00+09:00"):
            with self.subTest(final=final):
                foreign = one.copy()
                foreign.loc[pd.Timestamp(final)] = [1000, 1010, 990, 1000]
                with self.assertRaises(ValueError):
                    engine.prepare(foreign, z, "NK225", "合成デイ")
        night_index = pd.DatetimeIndex([pd.Timestamp("2026-09-21 17:00:00+09:00"), pd.Timestamp("2026-09-22 05:55:00+09:00")])
        night_one = pd.DataFrame([(1000, 1010, 990, 1000)] * 2, columns=one.columns, index=night_index)
        with self.assertRaises(ValueError):
            engine.prepare(night_one, z, "NK225", "合成ナイト")


class WarmupPrefixTests(unittest.TestCase):
    """機能: 初動待ちが追加された２条件だけを、実データの境界で切断再生する。

    引数: unittest が設定する試験実行状態。返り値: TestCase インスタンス。
    """

    def test_warmup_current_and_regime_prefix(self) -> None:
        """機能: 45分の前後と後半で、現在ATR型・状態依存型の過去約定不変を確認する。

        引数: self (WarmupPrefixTests)。返り値: なし (None)。
        """
        from research import load_data, read_candle, schedule_for

        full_data = load_data()
        configs = (engine.Config(3, trail_basis="current", warmup=45),
                   engine.Config(1, trail_basis="regime", warmup=45))
        full_schedules = {cfg.key: schedule_for(full_data, cfg) for cfg in configs}
        full_trades = {cfg.key: {key: engine.simulate(item, full_schedules[cfg.key][key], cfg)
                                for key, item in full_data.items()} for cfg in configs}
        checks = 0
        for session in SESSIONS:
            base = full_data[(session, "NK225")]["z"].index
            for position in (44, 45, 90, len(base) // 2):
                cutoff = base[position]
                clipped_data = {}
                for symbol, tick in engine.TICKS.items():
                    one = full_data[(session, symbol)]["one"].loc[:cutoff]
                    five = read_candle(ROOT / "candle_5min" / symbol / f"{session}.csv")
                    book_dir = "wave_v3_check" if session == "2026-09-22_Night" else "wave_v2"
                    book = ROOT / "work" / book_dir / f"板特徴_{symbol}_{session}.csv"
                    z = signals.build_features(one, five, book, tick, cutoff)
                    clipped_data[(session, symbol)] = engine.prepare(one, z, symbol, session)
                for cfg in configs:
                    clipped_schedules = schedule_for(clipped_data, cfg)
                    for key, item in clipped_data.items():
                        with self.subTest(session=session, position=position, symbol=key[1], basis=cfg.trail_basis):
                            result = engine.simulate(item, clipped_schedules[key], cfg)
                            expected = prefix_trades(full_trades[cfg.key][key], item["times"][-1])
                            self.assertEqual(result, expected)
                            self.assertTrue(all((trade["entry_time"] - base[0]).total_seconds() >= 45 * 60 for trade in result))
                            checks += 1
        print(f"初動45分の現在ATR・状態依存型の切断一致: {checks} 条件")


class HistoricalPrefixTests(unittest.TestCase):
    """機能: 保存４セッションで過去信号・過去約定が将来追加で変化しないことを確認する。

    引数: unittest が設定する試験実行状態。返り値: TestCase インスタンス。
    """

    def test_saved_sessions_prefix(self) -> None:
        """機能: 全24系統と６新規方法を実データ上で切断再生する。

        引数: self (HistoricalPrefixTests)。返り値: なし (None)。
        """
        checks = 0
        for session in SESSIONS:
            inputs = {}
            for symbol, tick in engine.TICKS.items():
                frames = []
                for unit in ("1min", "5min"):
                    frame = pd.read_csv(ROOT / f"candle_{unit}" / symbol / f"{session}.csv")
                    frame["time"] = pd.to_datetime(frame.time)
                    frames.append(frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index())
                board_dir = "wave_v3_check" if session == "2026-09-22_Night" else "wave_v2"
                inputs[symbol] = (*frames, ROOT / "work" / board_dir / f"板特徴_{symbol}_{session}.csv", tick)
            end = max(args[0].index[-1] for args in inputs.values())
            full = {symbol: signals.build_features(*args, end) for symbol, args in inputs.items()}
            for fraction in (0.35, 0.7):
                cutoff = full["NK225"].index[int((len(full["NK225"]) - 1) * fraction)]
                prefix = {symbol: signals.build_features(*args, cutoff) for symbol, args in inputs.items()}
                for symbol, z in prefix.items():
                    peer_symbol = "TOPIX" if symbol == "NK225" else "NK225"
                    pd.testing.assert_frame_equal(z, full[symbol].loc[:cutoff], check_exact=False, rtol=1e-12, atol=1e-12)
                    one = inputs[symbol][0]
                    clipped = one.loc[:cutoff]
                    clipped_data = engine.prepare(clipped, z, symbol, session)
                    full_data = engine.prepare(one, full[symbol], symbol, session)
                    for family in signals.FAMILIES:
                        for param in signals.PARAMETERS:
                            with self.subTest(session=session, symbol=symbol, fraction=fraction, family=family, param=param):
                                before = signals.get_signals(z, prefix[peer_symbol], family, param)
                                after = signals.get_signals(full[symbol], full[peer_symbol], family, param)
                                pd.testing.assert_series_equal(before, after.loc[:cutoff], check_exact=True)
                                for basis in ("entry", "current", "regime"):
                                    cfg = engine.Config(family, param=param, entry=METHODS[(family - 1) % len(METHODS)], trail_basis=basis)
                                    full_trades = engine.simulate(full_data, engine.sign_schedule(after.to_numpy()), cfg)
                                    small_trades = engine.simulate(clipped_data, engine.sign_schedule(before.to_numpy()), cfg)
                                    self.assertEqual(small_trades, prefix_trades(full_trades, clipped.index[-1]))
                                    self.assertTrue(all(t["entry_time"] in one.index for t in full_trades))
                                    self.assertTrue(all(t["closed"] for t in full_trades))
                                    checks += 1
        print(f"保存４セッションの信号・約定切断一致: {checks} 条件")


if __name__ == "__main__":
    unittest.main(verbosity=2)
