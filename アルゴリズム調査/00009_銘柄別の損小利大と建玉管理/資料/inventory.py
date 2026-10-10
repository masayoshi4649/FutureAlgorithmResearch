"""保存原本の一覧とハッシュを前回監査と照合し、通信せず追加の有無を確認する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = ROOT/'work/wave_v13'


def sha256(path: Path) -> str:
    """機能: 原本を変更せず内容のハッシュを求める。

    引数: path (Path)。返り値: str: SHA256。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    """機能: 原本42件と既知夜間６件を棚卸しし、変更と新規追加を記録する。

    引数: なし。返り値: None: 今回データ棚卸し.jsonを作業先へ保存する。
    """
    previous = json.loads((OLD/'原本メタ監査.json').read_text(encoding='utf-8'))
    expected, metadata = {}, {}
    for row in previous:
        for kind in ['生板', '1分足', '5分足']:
            entry = row[kind]
            path = ROOT/entry['原本']
            expected[path] = entry['SHA256']
            metadata[path] = dict(セッション=row['セッション'], 銘柄=row['銘柄'], 種別=kind, 前回記録=entry)
    receipt = json.loads((OLD/'現在照合_取得記録.json').read_text(encoding='utf-8'))
    for book in receipt['books']:
        path = OLD/'live/book'/book['銘柄']/f"{receipt['session']}.jsonl"
        expected[path] = book['SHA256']
        metadata[path] = dict(セッション=receipt['session'], 銘柄=book['銘柄'], 種別='生板', 前回記録=book)
    for candle in receipt['candles']:
        path = ROOT/candle['path']
        expected[path] = candle['sha256']
        metadata[path] = dict(セッション=receipt['session'], 銘柄=candle['symbol'], 種別=f"{candle['minutes']}分足", 前回記録=candle)
    found = {p for folder in ['book', 'candle_1min', 'candle_5min'] for p in (ROOT/folder).glob('*/*') if p.is_file()}
    found.update(path for path in expected if path.is_relative_to(OLD/'live'))
    rows = []
    for path in sorted(found):
        actual = sha256(path)
        rows.append(dict(原本=path.relative_to(ROOT).as_posix(), SHA256=actual, バイト数=path.stat().st_size,
                         前回SHA256=expected.get(path), 前回一致=actual == expected.get(path),
                         **metadata.get(path, dict(種別='今回追加'))))
    result = dict(棚卸し時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), API取得数=0,
                  対象ファイル数=len(rows), 前回一致数=sum(r['前回一致'] for r in rows),
                  追加ファイル=[p.relative_to(ROOT).as_posix() for p in sorted(found-set(expected))],
                  消失ファイル=[p.relative_to(ROOT).as_posix() for p in sorted(set(expected)-found)],
                  内容変更ファイル=[r['原本'] for r in rows if r['前回SHA256'] and not r['前回一致']],
                  既知完全セッション数=7, 既知途中セッション=receipt['session'], 既知途中排他的締切=receipt['cutoff'],
                  注意='前回の保留日中と現在夜間前半も今回は既知資料であり、未知検証と表記しない。', 原本=rows)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'今回データ棚卸し.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != '原本'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
