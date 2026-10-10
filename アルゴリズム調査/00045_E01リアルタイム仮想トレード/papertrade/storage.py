"""売買・建玉を同じSQLite取引で保存し、CSVを継続出力する。"""

from __future__ import annotations

import csv
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3


JST = timezone(timedelta(hours=9))
TRADE_FIELDS = ['記録ID', '記録時刻', 'セッション', '手法', '参照銘柄', '仮想商品', '参照限月',
                '参照銘柄番号', '区分', '建玉方向', '売買', '枚数', '約定価格', '新規価格',
                '確定損益円', '確定損益ポイント枚', '処理後保有枚数', '初期ATR', '理由', '組番号',
                '判断元行', '約定行', '市場価格時刻', '約定モデル', '費用円']
HEALTH_FIELDS = ['記録ID', '記録時刻', '種別', '内容']


def iso(timestamp: float) -> str:
    """機能: UNIX秒を日本時間へ変換する。

    引数: timestamp(float)。返り値: ISO時刻(str)。
    """
    return datetime.fromtimestamp(timestamp, JST).isoformat(timespec='milliseconds')


class RunLock:
    """同じ保存先を二つのプロセスが使うことを防ぐ。"""

    def __init__(self, directory: Path):
        """機能: 排他的ロックを取得する。

        引数: directory(Path)。返り値: なし(None)。
        """
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / '.実行中.lock').open('a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError('この保存先では既に仮想トレードが実行されています') from exc

    def close(self) -> None:
        """機能: プロセスの排他的ロックを解放する。

        引数: なし。返り値: なし(None)。
        """
        self.file.close()


class Store:
    """CSVを閲覧用、SQLiteをクラッシュ復旧用の正本として扱う。"""

    def __init__(self, directory: Path):
        """機能: 正本を開き、CSVを正本から安全に再構築する。

        引数: directory(Path)。返り値: なし(None)。
        """
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / '状態と売買.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, body TEXT NOT NULL)')
        self.db.commit()
        self.csv_dirty = True
        self.last_export_error = ''
        self.export()

    def load(self) -> dict | None:
        """機能: 最後に確定保存した状態を読む。

        引数: なし。返り値: 状態(dict|None)。
        """
        row = self.db.execute('SELECT body FROM state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def backup(self) -> Path:
        """機能: 互換更新前の正本をSQLiteの一貫した複製として残す。

        引数: なし。返り値: バックアップ先(Path)。既存台帳を上書きしない。
        """
        name = datetime.now(JST).strftime('更新前_%Y%m%d_%H%M%S_%f.sqlite3')
        target = self.directory / name
        destination = sqlite3.connect(target)
        try:
            self.db.backup(destination)
        finally:
            destination.close()
        return target

    def commit(self, state: dict, events: list[tuple[str, dict]]) -> None:
        """機能: 売買と対応する建玉を一括で確定保存する。

        引数: state(dict)、events(list[tuple[str,dict]])。返り値: なし(None)。
        """
        with self.db:
            self.db.execute('INSERT INTO state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                            (json.dumps(state, ensure_ascii=False, allow_nan=False),))
            for kind, event in events:
                self.db.execute('INSERT INTO events(kind,body) VALUES(?,?)',
                                (kind, json.dumps(event, ensure_ascii=False, allow_nan=False)))
        if events:
            self.csv_dirty = True
            self.export()

    def export(self) -> bool:
        """機能: 正本からCSVを再構築し、途中書込みや重複を修復する。

        引数: なし。返り値: 出力成功(bool)。ロック中は次回へ延期する。
        """
        if not self.csv_dirty:
            return True
        try:
            for kind, name, fields in [('trade', '売買記録.csv', TRADE_FIELDS), ('health', '稼働記録.csv', HEALTH_FIELDS)]:
                target = self.directory / name
                temporary = target.with_suffix('.csv.tmp')
                with temporary.open('w', newline='', encoding='utf-8-sig') as handle:
                    writer = csv.DictWriter(handle, fields, extrasaction='ignore')
                    writer.writeheader()
                    for event_id, body in self.db.execute('SELECT id,body FROM events WHERE kind=? ORDER BY id', (kind,)):
                        event = json.loads(body)
                        event['記録ID'] = event_id
                        writer.writerow(event)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            self.csv_dirty = False
            self.last_export_error = ''
            return True
        except OSError as exc:
            self.last_export_error = str(exc)
            return False

    def status(self, value: dict) -> None:
        """機能: 読みやすい現在状態を別ファイルへ出力する。

        引数: value(dict)。返り値: なし(None)。
        """
        target = self.directory / '現在状態.json'
        temporary = target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        os.replace(temporary, target)

    def close(self) -> None:
        """機能: CSV出力を再試行してDBを閉じる。

        引数: なし。返り値: なし(None)。
        """
        self.export()
        self.db.close()
