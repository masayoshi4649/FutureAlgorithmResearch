"""前観測注文、元枠会計、通常影時計及び保存台帳との一致を確認する。"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import unittest

try:
    from .strategy import E01Engine
except ImportError:
    from strategy import E01Engine


class StrategyTest(unittest.TestCase):
    """将来値を使用できない逐次入力だけで注文器を検証する。"""

    def engine(self, symbol: str = "TOPIX", mode: str = "specified") -> E01Engine:
        """機能: テスト用セッションの注文器を作る。

        引数: symbol/mode(str)。返り値: 注文器(E01Engine)。
        """
        return E01Engine(symbol, "検査_Day", 0.0, 30000.0, 30600.0, fill_mode=mode)

    def opened(self) -> E01Engine:
        """機能: 100から102.5への反発で5枚を新規建てする。

        引数: なし。返り値: 建玉を持つ注文器(E01Engine)。
        """
        e = self.engine()
        self.assertEqual(e.on_tick(1200, 100, 10, 1), [])
        entry = e.on_tick(1201, 103, 10, 1)[0]
        self.assertEqual((entry["price"], entry["row"], entry["source_row"]), (102.5, 1, 0))
        return e

    def test_entry_waits_for_next_observation(self) -> None:
        """機能: 新設条件は同じ観測では約定しないことを検査する。

        引数: なし。返り値: なし(None)。
        """
        e = self.opened()
        self.assertEqual(e.status()["quantity"], 5)
        self.assertEqual(e.on_tick(1202, 95, 10, 1)[0]["realized_yen"], -37500)

    def test_quantity_reduction_retires_original_split_slots(self) -> None:
        """機能: 悪化半減で返済済みの元枠を2ATR到達時に二重返済しない。

        引数: なし。返り値: なし(None)。
        """
        e = self.opened()
        e.on_tick(1202, 118, 10, 1)
        e.on_tick(1203, 117, 10, 1, adverse=-1, adverse_source=3)
        reduction = e.on_tick(1204, 116, 10, 1)
        self.assertEqual([(v["quantity"], v["reason_code"]) for v in reduction], [(2, 30)])
        self.assertEqual(e.on_tick(1205, 123, 10, 1), [])
        self.assertEqual(e.status()["quantity"], 3)

    def test_old_adverse_cannot_pass_new_gate(self) -> None:
        """機能: 順行到達以前に公開された悪化信号を再利用しない。

        引数: なし。返り値: なし(None)。
        """
        e = self.opened()
        e.on_tick(1202, 118, 10, 1, adverse=-1, adverse_source=2)
        e.on_tick(1203, 117, 10, 1, adverse=-1, adverse_source=2)
        self.assertIsNone(e.snapshot()["actual"]["pending"])

    def test_tight_exit_keeps_normal_shadow_alive(self) -> None:
        """機能: E01完済直後の再参入を通常影が抑えることを検査する。

        引数: なし。返り値: なし(None)。
        """
        e = self.opened()
        e.on_tick(1202, 123, 10, 1)
        e.on_tick(1203, 133, 10, 1)
        closes = e.on_tick(1204, 125, 10, 1)
        self.assertEqual(closes[0]["reason_code"], 2)
        self.assertEqual(e.status()["quantity"], 0)
        self.assertEqual(e.status()["normal_shadow"]["direction"], 1)
        e.on_tick(1600, 130, 10, 1)
        self.assertIsNone(e.status()["pending_entry"])

    def test_snapshot_restore_identical(self) -> None:
        """機能: JSON保存・復元後も次の注文が同一であることを検査する。

        引数: なし。返り値: なし(None)。
        """
        e = self.opened()
        saved = json.loads(json.dumps(e.snapshot(), allow_nan=False))
        other = E01Engine("TOPIX", "検査_Day", 0, 30000, 30600, state=saved)
        for t, price in [(1202, 123), (1203, 133), (1204, 125)]:
            self.assertEqual(e.on_tick(t, price, 10, 1), other.on_tick(t, price, 10, 1))
        self.assertEqual(e.snapshot(), other.snapshot())

    def test_observed_fills_at_current_price(self) -> None:
        """機能: 観測価格方式では飛び越した水準へ遡及約定しない。

        引数: なし。返り値: なし(None)。
        """
        e = self.engine(mode="observed")
        e.on_tick(1200, 100, 10, 1)
        self.assertEqual(e.on_tick(1201, 110, 10, 1)[0]["price"], 110)
        self.assertEqual(e.on_tick(1202, 90, 10, 1)[0]["price"], 90)

    def test_disabled_entry_cancels_existing_setup(self) -> None:
        """機能: 品質遮断が未約定新規を取り消すことを検査する。

        引数: なし。返り値: なし(None)。
        """
        e = self.engine()
        e.on_tick(1200, 100, 10, 1)
        self.assertEqual(e.on_tick(1201, 110, 10, 1, allow_entry=False), [])
        self.assertEqual(e.positions(), [])
        e.on_tick(1202, 100, 10, 1)
        e.cancel_entry()
        self.assertIsNone(e.status()["pending_entry"])

    def test_session_close_is_not_backfilled(self) -> None:
        """機能: 終場越えの未返済を過去値で埋めず異常とする。

        引数: なし。返り値: なし(None)。
        """
        e = self.opened()
        with self.assertRaises(ValueError):
            e.force_flatten(30600, 100)
        with self.assertRaises(ValueError):
            e.on_tick(30600, 100, 10, 1)
        e.on_tick(30000, 100, 10, 0)
        close = e.on_tick(30001, 100, 10, 0)
        self.assertEqual(close[0]["reason_code"], 9)
        self.assertEqual(e.positions(), [])

    def test_future_source_and_bad_restart_rejected(self) -> None:
        """機能: 未来の根拠と枚数超過状態の再開を拒否する。

        引数: なし。返り値: なし(None)。
        """
        e = self.engine()
        with self.assertRaises(ValueError):
            e.on_tick(1200, 100, 10, 1, adverse=-1, adverse_source=2)
        saved = self.opened().snapshot()
        saved["actual"]["slots"] = [True] * 11
        with self.assertRaises(ValueError):
            E01Engine("TOPIX", "検査_Day", 0, 30000, 30600, state=saved)


def historical_parity() -> list[dict]:
    """機能: 保存実データから元特徴量を作り、新注文器を既存E01台帳と照合する。

    引数: なし。返り値: セッション別の注文完全一致記録(list[dict])。
    通常運転に不要なNumPy等はこの明示的検証だけで使用する。
    """
    import numpy as np

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("仮想運転の旧信号照合", root / "work/wave_v48/update_20261001/replay_added_session.py")
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    stored = json.loads(gzip.decompress((root / "work/wave_v49/early/ledgers/E01.json.gz").read_bytes()))
    stored += json.loads(gzip.decompress((root / "work/wave_v50/update_20261001_day/ledgers/E01.json.gz").read_bytes()))
    expected = {(r["session"], r["symbol"]): r for r in stored}
    sources = [("work/wave_v47", "inputs.pkl", "features_depth.pkl"),
               ("work/wave_v48/update_20260930", "new_inputs.pkl", "new_features_depth.pkl"),
               ("work/wave_v48/update_20261001", "new_inputs.pkl", "new_features_depth.pkl"),
               ("work/wave_v50/update_20261001_day", "new_inputs.pkl", "new_features_depth.pkl")]
    reports = []
    for folder, inputs_name, features_name in sources:
        inputs = pickle.loads((root / folder / inputs_name).read_bytes())
        features = pickle.loads((root / folder / features_name).read_bytes())
        signals = old.signals(inputs, features, root)
        for key, ready in sorted(inputs.items()):
            engine = E01Engine(key[1], key[0], ready["start"], ready["limit"], ready.get("session_close", ready["limit"] + 600))
            direction, bad = signals["entry"][key], signals["B00"][key]
            actual = []
            for i, (t, price, atr) in enumerate(zip(ready["time_s"], ready["last"], ready["atr"])):
                events = engine.on_tick(float(t), float(price), float(atr), int(direction[i]),
                                        int(bad["direction"][i]), int(bad["source_row"][i]), input_index=i)
                actual.extend([[e["row"], e["source_row"], e["campaign"], e["direction"] if e["event"] == "新規" else -e["direction"],
                                e["quantity"], e["price"], e["reason_code"], int(e["event"] == "新規")] for e in events])
            np.testing.assert_array_equal(np.asarray(actual, dtype=float).reshape(-1, 8), np.asarray(expected[key]["orders"], dtype=float))
            assert engine.positions() == []
            record = dict(session=key[0], symbol=key[1], observations=len(ready["last"]), orders=len(actual),
                          realized_yen=engine.status()["realized_yen"], 注文8項目全一致=True)
            reports.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E01注文器の逐次性と保存台帳を検査する")
    parser.add_argument("--historical", action="store_true", help="保存実データの全17セッションも照合する")
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StrategyTest))
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.historical:
        reports = historical_parity()
        target = Path(__file__).resolve().parents[1] / "戦略注文一致検証.json"
        target.write_text(json.dumps(dict(全合格=True, results=reports), ensure_ascii=False, indent=2), encoding="utf-8")
