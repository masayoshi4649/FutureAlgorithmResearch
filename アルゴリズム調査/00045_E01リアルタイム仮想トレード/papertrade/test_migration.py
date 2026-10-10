"""旧台帳を残す互換更新と、再起動時の実際の観測価格を検証する。"""

from pathlib import Path
from contextlib import closing
import json
import sqlite3
import unittest

from . import test_runtime as fixtures
from .runtime import PaperRunner


class MigrationTests(unittest.TestCase):
    """台帳を捨てずに修正版へ移行する経路を確認する。"""

    setUp = fixtures.RuntimeTests.setUp
    tearDown = fixtures.RuntimeTests.tearDown
    push = fixtures.RuntimeTests.push
    opened = fixtures.RuntimeTests.opened
    records = fixtures.RuntimeTests.records

    def test_known_legacy_backup_preserves_orders_and_positions(self):
        """機能: 既知旧版だけをバックアップし、建玉と取引IDを維持する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        saved = self.store.load()
        signatures = json.loads((Path(__file__).parent / 'legacy_compatibility.json').read_text(encoding='utf-8'))['signatures']
        saved['signature'] = next(k for k, v in signatures.items() if v['fill_mode'] == 'specified')
        saved.pop('connectivity', None)
        self.store.commit(saved, [])
        records = self.records()
        self.now += 1
        self.runner = PaperRunner(self.options, self.store)
        self.runner.checkpoint(self.now, True)
        backups = list(self.path.glob('更新前_*.sqlite3'))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as old:
            self.assertEqual(json.loads(old.execute('SELECT body FROM state').fetchone()[0])['signature'], saved['signature'])
            self.assertEqual(old.execute("SELECT COUNT(*) FROM events WHERE kind='trade'").fetchone()[0], 2)
        self.assertEqual(self.records(), records)
        self.assertEqual(self.runner.engines['TOPIX'].status()['quantity'], 5)
        self.assertNotEqual(self.store.load()['signature'], saved['signature'])

    def test_unknown_legacy_state_is_not_adopted(self):
        """機能: 未確認の戦略署名を旧版として無条件に受け入れない。

        引数: なし。返り値: なし(None)。
        """
        self.runner.checkpoint(self.now, True)
        saved = self.store.load()
        saved['signature'] = '未確認の別戦略'
        self.store.commit(saved, [])
        with self.assertRaises(ValueError):
            PaperRunner(self.options, self.store)
        self.assertEqual(self.store.load()['signature'], saved['signature'])
        self.assertFalse(list(self.path.glob('更新前_*.sqlite3')))

    def test_short_restart_stop_crossing_uses_observed_price(self):
        """機能: 短時間再起動後にストップを跨いでいれば復帰時価格で返済する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        self.now += 2
        self.runner = PaperRunner(self.options, self.store)
        self.push('TOPIX', self.now, 1000)
        self.assertEqual(float(self.records()[-1]['約定価格']), 1000)
        self.assertEqual(self.records()[-1]['約定モデル'], 'observed_recovery')

    def test_restart_rejects_older_quote_without_aborting(self):
        """機能: 保存前より古いPUSHが復旧時に届いても除外して継続する。

        引数: なし。返り値: なし(None)。
        """
        self.opened()
        self.now += 2
        self.runner = PaperRunner(self.options, self.store)
        payload = fixtures.book('TOPIX', self.now - 5, 1118)
        self.runner.accept_book(payload, self.now, self.now)
        self.assertEqual(self.runner.rejected_count, 1)
        self.assertEqual(self.runner.engines['TOPIX'].status()['quantity'], 5)


if __name__ == '__main__':
    unittest.main()
