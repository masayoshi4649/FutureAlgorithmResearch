"""CSVの復旧、正本との整合、二重起動禁止を検証する。"""

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .storage import RunLock, Store
from .transport import MarketClient


class StorageTest(unittest.TestCase):
    """運転ログの紛失と重複に関係する失敗経路を確認する。"""

    def test_crash_repair_and_idempotent_export(self):
        """機能: CSVの欠落・破損を正本から重複なしで復旧する。

        引数: なし。返り値: なし(None)。
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store = Store(path)
            store.commit({'quantity': 5}, [('trade', {'区分': '新規', '枚数': 5})])
            store.commit({'quantity': 0}, [('trade', {'区分': '返済', '枚数': 5, '確定損益円': 1000})])
            store.close()
            (path / '売買記録.csv').write_bytes(b'partial')
            reopened = Store(path)
            self.assertEqual(reopened.load(), {'quantity': 0})
            reopened.export()
            with (path / '売買記録.csv').open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([r['記録ID'] for r in rows], ['1', '2'])
            self.assertEqual([r['区分'] for r in rows], ['新規', '返済'])
            reopened.close()

    def test_csv_locked_does_not_lose_committed_trade(self):
        """機能: CSVの置換失敗中も売買と建玉が正本へ保存される。

        引数: なし。返り値: なし(None)。
        """
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            with patch('papertrade.storage.os.replace', side_effect=PermissionError('編集中')):
                store.commit({'quantity': 5}, [('trade', {'区分': '新規', '枚数': 5})])
            self.assertEqual(store.load()['quantity'], 5)
            self.assertTrue(store.csv_dirty)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
            self.assertTrue(store.export())
            self.assertFalse(store.csv_dirty)
            store.close()

    def test_invalid_event_rolls_back_state(self):
        """機能: 同じ取引内のイベント保存失敗が建玉更新も取り消す。

        引数: なし。返り値: なし(None)。
        """
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            store.commit({'quantity': 0}, [])
            with self.assertRaises(ValueError):
                store.commit({'quantity': 5}, [('trade', {'price': float('nan')})])
            self.assertEqual(store.load(), {'quantity': 0})
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)
            store.close()

    def test_exclusive_lock(self):
        """機能: 同じ出力先への二重起動を拒否し、終了後は取得できる。

        引数: なし。返り値: なし(None)。
        """
        with tempfile.TemporaryDirectory() as folder:
            first = RunLock(Path(folder))
            try:
                with self.assertRaises(RuntimeError):
                    RunLock(Path(folder))
            finally:
                first.close()
            second = RunLock(Path(folder))
            second.close()

    def test_order_paths_and_credential_urls_rejected(self):
        """機能: 注文・取消・登録変更に繋がるパスを通信前に拒否する。

        引数: なし。返り値: なし(None)。
        """
        client = MarketClient('http://127.0.0.1:9')
        for path in ('/kabusapi/sendorder', '/api/v1/future/orders', '/kabus/login',
                     '/api/v1/history/status?redirect=/sendorder'):
            with self.assertRaises(ValueError):
                client.get(path)
        with self.assertRaises(ValueError):
            MarketClient('http://key:secret@example.invalid')


if __name__ == '__main__':
    unittest.main()
