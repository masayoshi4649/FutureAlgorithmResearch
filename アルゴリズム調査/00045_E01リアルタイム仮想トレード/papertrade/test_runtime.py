"""市場受信、注文器、保存復旧及び日本語CSVを一続きで検証する。"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .runtime import PaperRunner, parser
from .storage import Store, iso


START = datetime.fromisoformat("2026-10-02T08:45:00+09:00").timestamp()
END = datetime.fromisoformat("2026-10-02T15:45:00+09:00").timestamp()
RECEIVED = START + 95 * 60
REGISTRATION = {
    "TOPIX": {"symbol": "検査TOPIX", "derivMonth": "202612"},
    "NK225": {"symbol": "検査NK225", "derivMonth": "202612"},
}


def candles(generation: str = "検査世代1", session: str = "2026-10-02_Day",
            start: float = START, end: float = END, asof: float = RECEIVED) -> dict:
    """機能: controller互換の4系統の上向き確定足を作る。

    引数: generation/session(str)、start/end/asof(float)。返り値: 受信バッチ(dict)。
    """
    batch = {}
    for symbol, scale in (("TOPIX", 1), ("NK225", 20)):
        for period, seconds in (("1min", 60), ("5min", 300)):
            rows = []
            for i in range(max(0, int((asof - start) // seconds))):
                price = (1000 + i * seconds / 60) * scale
                rows.append(dict(time=iso(start + i * seconds), open=price, high=price + 2 * scale,
                                 low=price - 2 * scale, close=price, closed=True))
            batch[symbol, period] = {
                "snapshot": {"sessionId": session, "generation": generation, "code": symbol,
                             "session": {"startsAt": iso(start), "endsAt": iso(end)}},
                "data": rows,
            }
    return {"batch": batch, "registration": REGISTRATION}


def book(symbol: str, at: float, price: float) -> dict:
    """機能: 新鮮な約定価格と有効な最良気配を含むPUSHを作る。

    引数: symbol(str)、at/price(float)。返り値: 板PUSH(dict)。
    """
    tick = 0.5 if symbol == "TOPIX" else 10
    return {"Symbol": REGISTRATION[symbol]["symbol"], "CurrentPriceTime": iso(at),
            "CurrentPrice": price, "Buy1": {"Price": price - tick / 2, "Qty": 20},
            "Sell1": {"Price": price + tick / 2, "Qty": 20}}


class RuntimeTests(unittest.TestCase):
    """運転全体の未約定・復旧・データ停止条件をテストする。"""

    def setUp(self) -> None:
        """機能: 一時保存先と固定時計を用意する。

        引数: なし。返り値: なし(None)。
        """
        self.temporary = tempfile.TemporaryDirectory(prefix="仮想運転検査_")
        self.path = Path(self.temporary.name)
        self.now = RECEIVED
        self.clock = patch("papertrade.runtime.time.time", side_effect=lambda: self.now)
        self.clock.start()
        self.prints = patch("builtins.print")
        self.prints.start()
        self.options = parser().parse_args(["--output", str(self.path)])
        self.store = Store(self.path)
        self.runner = PaperRunner(self.options, self.store)
        self.runner.accept_candles(candles(), self.now)

    def tearDown(self) -> None:
        """機能: 保存先を閉じ、時計の置換と一時ファイルを戻す。

        引数: なし。返り値: なし(None)。
        """
        self.store.close()
        self.prints.stop()
        self.clock.stop()
        self.temporary.cleanup()

    def push(self, symbol: str, at: float, price: float) -> None:
        """機能: 一件の受信と即時保存を運転器に渡す。

        引数: symbol(str)、at/price(float)。返り値: なし(None)。
        """
        self.now = at
        self.runner.accept_book(book(symbol, at, price), at, at)
        self.runner.checkpoint(at, True)

    def opened(self) -> None:
        """機能: 人工確定足と板を通して両銘柄の新規建てまで実行する。

        引数: なし。返り値: なし(None)。
        """
        for second in range(181):
            at = RECEIVED + second
            if second % 10 == 0:
                self.runner.accept_candles(candles(asof=at), at)
            for symbol, scale in (("TOPIX", 1), ("NK225", 20)):
                self.push(symbol, at, (1100 + second * 0.1) * scale)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        self.assertEqual(self.runner.engines["NK225"].status()["quantity"], 10)

    def records(self) -> list[dict]:
        """機能: 閲覧用CSVを日本語見出しで読む。

        引数: なし。返り値: 売買行一覧(list[dict])。
        """
        self.store.export()
        with (self.path / "売買記録.csv").open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_real_features_to_entry_exit_and_japanese_csv(self) -> None:
        """機能: 実特徴量器から新規、損切り、日本語CSVの金額まで検査する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        self.push("TOPIX", self.now + 1, 1000)
        self.push("NK225", self.now + 1, 20000)
        rows = self.records()
        self.assertEqual([r["区分"] for r in rows].count("新規"), 2)
        self.assertEqual([r["区分"] for r in rows].count("返済"), 2)
        for symbol, qty, factor in (("TOPIX", 5, 1000), ("NK225", 10, 10)):
            entered, closed = [r for r in rows if r["参照銘柄"] == symbol]
            self.assertEqual(entered["建玉方向"], "ロング")
            self.assertEqual((entered["売買"], closed["売買"]), ("買い", "売り"))
            self.assertEqual((int(entered["枚数"]), int(closed["枚数"])), (qty, qty))
            expected = qty * (float(closed["約定価格"]) - float(entered["約定価格"])) * factor
            self.assertAlmostEqual(float(closed["確定損益円"]), expected)
            self.assertEqual(closed["処理後保有枚数"], "0")
            self.assertLess(int(entered["判断元行"]), int(entered["約定行"]))
        self.assertTrue((self.path / "売買記録.csv").read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_restart_preserves_live_positions_without_index_reversal(self) -> None:
        """機能: 短時間の再開で建玉・継続連番・CSVの重複防止を確認する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        previous = {s: e.status()["row"] for s, e in self.runner.engines.items()}
        before = len(self.records())
        self.now += 1
        self.runner = PaperRunner(self.options, self.store)
        self.runner.accept_candles(candles(), self.now)
        for symbol, price in (("TOPIX", 1118), ("NK225", 22360)):
            self.push(symbol, self.now, price)
            self.assertEqual(self.runner.engines[symbol].status()["row"], previous[symbol] + 1)
            self.assertEqual(self.runner.engines[symbol].status()["quantity"], 5 if symbol == 'TOPIX' else 10)
        rows = self.records()
        self.assertEqual(len(rows), before)
        self.assertEqual(len({r["記録ID"] for r in rows}), len(rows))

    def test_generation_change_keeps_positions_and_rebases_indices(self) -> None:
        """機能: controller世代変更後に旧建玉を残して観測価格で返済する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        previous = {s: e.status()["row"] for s, e in self.runner.engines.items()}
        self.now += 1
        self.runner.accept_candles(candles("検査世代2"), self.now)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        for symbol, price in (("TOPIX", 1118), ("NK225", 22360)):
            self.push(symbol, self.now, price)
            self.assertEqual(self.runner.engines[symbol].status()["row"], previous[symbol] + 1)
            self.assertEqual(self.runner.latest_features[symbol]["input_index"], 0)
            self.assertEqual(self.runner.engines[symbol].status()["quantity"], 0)

    def test_cutoff_returns_at_next_fresh_observation(self) -> None:
        """機能: 場内返済時刻で次観測の全返済を予約することを確認する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        at = END - 600
        for symbol, price in (("TOPIX", 1118), ("NK225", 22360)):
            # このケースは終場条件の検査。市場受信は直前まで続いたものとする。
            self.runner.last_push[symbol] = at - 1
            self.push(symbol, at, price)
            self.assertGreater(self.runner.engines[symbol].status()["quantity"], 0)
        for symbol, price in (("TOPIX", 1118), ("NK225", 22360)):
            self.push(symbol, at + 1, price)
            self.assertEqual(self.runner.engines[symbol].status()["quantity"], 0)
        self.assertEqual([r["理由"] for r in self.records() if r["区分"] == "返済"], ["セッション内返済"] * 2)

    def test_missing_session_exit_stops_without_fabricated_close(self) -> None:
        """機能: 観測が途絶えたまま終場なら返済を捏造せず停止する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        self.now = END
        self.runner.watch(self.now)
        self.assertTrue(self.runner.halted)
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)

    def test_new_session_does_not_settle_old_position(self) -> None:
        """機能: 次セッションを受けても旧建玉の返済価格を作らない。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        new_start = datetime.fromisoformat("2026-10-02T17:00:00+09:00").timestamp()
        new_end = datetime.fromisoformat("2026-10-03T06:00:00+09:00").timestamp()
        self.now = new_start + 95 * 60
        self.runner.accept_candles(candles("次世代", "2026-10-02_Night", new_start, new_end), self.now)
        self.assertTrue(self.runner.halted)
        self.assertEqual(self.runner.session["id"], "2026-10-02_Day")
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 5)
        self.assertEqual(len(self.records()), 2)

    def test_pre_gap_queued_price_cannot_be_recovery_fill(self) -> None:
        """機能: 中断前に受信したキュー内価格を復旧時の約定に流用しない。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        interrupted = self.now + 3
        self.now = interrupted
        self.runner.gap('キュー欠落の検査', interrupted, hard=True)
        old_time = interrupted - 1
        self.runner.accept_book(book('TOPIX', old_time, 1118), old_time, interrupted)
        self.assertEqual(self.runner.engines['TOPIX'].status()['quantity'], 5)
        self.assertEqual(len(self.records()), 2)
        self.push('TOPIX', interrupted + 1, 1117)
        self.assertEqual(self.runner.engines['TOPIX'].status()['quantity'], 0)
        self.assertEqual(self.records()[-1]['約定価格'], '1117.0')

    def test_stale_peer_cancels_already_prepared_entry(self) -> None:
        """機能: 相手の鮮度悪化で、既設新規が発火する前に取消す。

        引数: なし。返り値: なし(None)。
        """
        self.runner.gaps = {s: False for s in REGISTRATION}
        self.runner.ready_after = {s: RECEIVED for s in REGISTRATION}
        self.runner.last_fresh = {s: RECEIVED for s in REGISTRATION}
        original = self.runner.features.on_book

        def supported(symbol: str, payload: dict, received: float) -> dict:
            """機能: 鮮度制御の検査用に入口根拠だけを確定値へ置換する。

            引数: symbol(str)、payload(dict)、received(float)。返り値: 特徴量(dict)。
            """
            value = original(symbol, payload, received)
            value.update(atr=10.0, direction=1, main_nominal=received, peer_nominal=received, atr_nominal=received)
            return value

        with patch.object(self.runner.features, "on_book", side_effect=supported):
            self.push("TOPIX", RECEIVED, 100)
            self.assertIsNotNone(self.runner.engines["TOPIX"].status()["pending_entry"])
            self.runner.last_fresh["NK225"] = RECEIVED - self.options.stale_seconds
            self.push("TOPIX", RECEIVED + 1, 103)
        self.assertIsNone(self.runner.engines["TOPIX"].status()["pending_entry"])
        self.assertEqual(self.runner.engines["TOPIX"].status()["quantity"], 0)
        self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
