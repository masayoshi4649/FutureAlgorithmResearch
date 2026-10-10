"""通信を禁止し、保存済み応答だけで一回取得コードの変換条件を確認する。"""

from __future__ import annotations

import copy
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import fetch_once as target


class OfflineChecks(unittest.TestCase):
    """現在データ取得を一切実行しないヘルパーの検査。"""

    @classmethod
    def setUpClass(cls) -> None:
        """過去の保存応答と新規の自領域を準備する。

        引数: cls（type）テストクラス。
        返り値: None。
        """
        cls.cutoff = target.parse_stamp("2026-09-23T15:39:00+09:00")
        cls.source = target.ROOT / "work/wave_v4/一度取得_2026-09-23_Day"
        cls.output = target.OUT / "data_audit_fetch_test" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        cls.output.mkdir(parents=True)
        cls.status = json.loads((cls.source / "status.json").read_text(encoding="utf-8"))
        cls.session, cls.start, cls.end = target.identify_session(cls.status, cls.cutoff)

    def test_status_session(self) -> None:
        """保存状態の両銘柄と日付の一致を確認する。

        引数: self（OfflineChecks）テスト。
        返り値: None。
        """
        self.assertEqual(self.session, "2026-09-23_Day")
        wrong = copy.deepcopy(self.status)
        wrong["current"][0]["sessionId"] = "2026-09-22_Day"
        with self.assertRaises(ValueError):
            target.identify_session(wrong, self.cutoff)
        with self.assertRaises(ValueError):
            target.identify_session(self.status, target.parse_stamp("2026-09-24T10:00:00+09:00"))

    def test_candle_conversion(self) -> None:
        """４保存応答から確定締切内の足だけを書き出す。

        引数: self（OfflineChecks）テスト。
        返り値: None。
        """
        records = []
        with patch.object(target, "LIVE", self.output), patch.object(target.urllib.request, "build_opener", side_effect=AssertionError("通信禁止")):
            for symbol in target.SYMBOLS:
                for minutes in (1, 5):
                    result = target.convert_candles(self.source / f"{symbol}_{minutes}min.json", symbol, minutes, self.session, self.start, self.end, self.cutoff)
                    self.assertGreater(result["rows"], 0)
                    self.assertLess(target.parse_stamp(result["last"]), self.cutoff)
                    if minutes == 5:
                        self.assertEqual(result["last"], "2026-09-23T15:30:00+09:00")
                    records.append(result)
        target.write_json(self.output / "確定足変換検査.json", records)

    def test_wrong_snapshot(self) -> None:
        """別セッション応答をそのまま採用しないことを確認する。

        引数: self（OfflineChecks）テスト。
        返り値: None。
        """
        payload = json.loads((self.source / "NK225_1min.json").read_text(encoding="utf-8"))
        payload["snapshot"]["sessionId"] = "2026-09-22_Day"
        path = self.output / "別セッション応答.json"
        target.write_json(path, payload)
        with self.assertRaises(ValueError):
            target.convert_candles(path, "NK225", 1, self.session, self.start, self.end, self.cutoff)

    def test_duplicate_bar(self) -> None:
        """重複した時刻を除去して見逃すのでなく拒否する。

        引数: self（OfflineChecks）テスト。
        返り値: None。
        """
        payload = json.loads((self.source / "NK225_1min.json").read_text(encoding="utf-8"))
        payload["data"].insert(1, copy.deepcopy(payload["data"][0]))
        path = self.output / "重複応答.json"
        target.write_json(path, payload)
        with self.assertRaises(ValueError):
            target.convert_candles(path, "NK225", 1, self.session, self.start, self.end, self.cutoff)

    def test_redirect_denied(self) -> None:
        """転送先への追加リクエストを生成しないことを確認する。

        引数: self（OfflineChecks）テスト。
        返り値: None。
        """
        self.assertIsNone(target.NoRedirect().redirect_request(None, None, 302, "転送", {}, "http://invalid.example"))

    def test_unclosed_excluded(self) -> None:
        """時刻上は終了していても未確定フラグの足を除く。

        引数: self（OfflineChecks）テスト。
        返り値: None。
        """
        payload = json.loads((self.source / "NK225_1min.json").read_text(encoding="utf-8"))
        payload["data"][0]["closed"] = False
        path = self.output / "未確定応答.json"
        target.write_json(path, payload)
        with patch.object(target, "LIVE", self.output / "未確定検査"):
            result = target.convert_candles(path, "NK225", 1, self.session, self.start, self.end, self.cutoff)
        self.assertEqual(result["excluded_unclosed_or_after_cutoff"], 1)
        self.assertEqual(result["first"], "2026-09-23T08:46:00+09:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
