"""原本を読み取り専用で走査し、前回の入力記録との差分を保存する。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
BASELINE = ROOT / 'work' / 'wave_v23' / '入力確認.json'
JST = timezone(timedelta(hours=9))


def digest(path: Path) -> str:
    """機能: ファイルを分割して読み、SHA256を計算する。

    引数: path (Path) 読み取るファイル。
    返り値: SHA256の16進表現 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as source:
        while part := source.read(8 * 1024 * 1024):
            value.update(part)
    return value.hexdigest()


def inspect(path: Path) -> dict:
    """機能: 読取前後の大きさと更新時刻を照合し、原本のハッシュを取得する。

    引数: path (Path) 原本ファイル。
    返り値: 相対パス、SHA256、属性、読取中変更の有無 (dict)。
    """
    before = path.stat()
    value = digest(path)
    after = path.stat()
    return {
        '相対パス': path.relative_to(ROOT).as_posix(),
        'SHA256': value,
        'バイト数': after.st_size,
        '更新時刻': datetime.fromtimestamp(after.st_mtime, JST).isoformat(),
        '読取中属性不変': (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
    }


def main() -> None:
    """機能: 全原本と前回78ファイルの差を監査し、今回領域だけへ保存する。

    引数: なし。
    返り値: なし (None)。APIアクセスや原本更新は行わない。
    """
    begin = datetime.now(JST).isoformat()
    baseline = json.loads(BASELINE.read_text(encoding='utf-8'))
    previous = baseline['原本SHA256']
    paths = sorted(path for folder in ['book', 'candle_1min', 'candle_5min']
                   for path in (ROOT / folder).rglob('*') if path.is_file())
    with ThreadPoolExecutor(max_workers=2) as executor:
        files = list(executor.map(inspect, paths))
    current = {item['相対パス']: item['SHA256'] for item in files}
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    changed = sorted(name for name in set(current) & set(previous)
                     if current[name] != previous[name])
    unchanged = sorted(name for name in set(current) & set(previous)
                       if current[name] == previous[name])

    # ----------------------------------------
    # セッションと銘柄ごとに、板・１分足・５分足の組が揃うか確認する。
    sessions = sorted({path.stem for path in paths
                       if path.parent.name in ['NK225', 'TOPIX']
                       and path.suffix in ['.jsonl', '.csv']})
    completeness = []
    for session in sessions:
        expected = [f'{folder}/{symbol}/{session}.{extension}'
                    for symbol in ['TOPIX', 'NK225']
                    for folder, extension in [('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv')]]
        completeness.append({
            'セッション': session,
            '開始日': session[:10],
            '不足ファイル': [name for name in expected if name not in current],
            '前回から追加されたファイル': [name for name in expected if name in added],
            '前回から内容変更されたファイル': [name for name in expected if name in changed],
        })
    result = {
        '監査開始時刻': begin,
        '監査終了時刻': datetime.now(JST).isoformat(),
        '比較元': BASELINE.relative_to(ROOT).as_posix(),
        '比較元SHA256': digest(BASELINE),
        '前回ファイル数': len(previous),
        '現在ファイル数': len(current),
        '総バイト数': sum(item['バイト数'] for item in files),
        '一致数': len(unchanged),
        '追加': added,
        '削除': removed,
        '内容変更': changed,
        '読取中属性変更': [item['相対パス'] for item in files if not item['読取中属性不変']],
        '前回と全原本が一致': not (added or removed or changed),
        'セッション数': len(sessions),
        '開始日数': len({session[:10] for session in sessions}),
        'セッション一覧': sessions,
        '組合せ確認': completeness,
        'ファイル': files,
        '全期間既読': not (added or changed),
        '未見期間が増えたと判断できるか': False,
        '注記': 'ファイル追加だけでは研究者に未見だった証明にならない。既存13セッションを再利用する検証は事後の時間順再現と呼ぶ。',
        'API取得数': 0,
        '原本変更数': 0,
    }
    (WORK / 'data_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['前回ファイル数', '現在ファイル数', '一致数', '追加', '削除', '内容変更', 'セッション数', '開始日数']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
