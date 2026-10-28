"""00149で再利用する原資料と既存気配資料の同一性を確認する。"""

from __future__ import annotations

import hashlib
import json
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def fingerprint(path: Path) -> dict:
    """資料を全読して指紋を作る。

    引数: path (Path): 読取対象。
    返り値: dict: 絶対パス、長さ、SHA256、読取中変更検査。
    """
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f'読取中に資料が変更された: {path}')
    return dict(path=str(path.resolve()), bytes=after.st_size,
                sha256=digest.hexdigest(), mtime_ns=after.st_mtime_ns,
                unchanged_during_read=True)


def main() -> None:
    """過去25夜と取得済み途中場の入力一覧を固定する。

    引数: なし。
    返り値: None。JSONを保存し、件数のみ出力する。
    """
    old_path = ROOT / 'work/research145_data/全保存資料の再照合145.json'
    old = json.loads(old_path.read_text('utf-8'))
    prior = {str(Path(x['path']).resolve()).casefold(): x for x in old['files']}
    source_path = ROOT / 'work/preus148/入力目録148.json'
    source = json.loads(source_path.read_text('utf-8'))
    rows = []
    for item in source['sessions']:
        session = item['session']
        ready_path = ROOT / item['prepared']['path']
        ready_fp = fingerprint(ready_path)
        if ready_fp['sha256'] != item['prepared']['sha256']:
            raise RuntimeError(f'既存気配資料不一致: {session}')
        cache_fp = fingerprint(ROOT / item['source_cache']['path'])
        if cache_fp['sha256'] != item['source_cache']['sha256']:
            raise RuntimeError(f'145気配キャッシュ不一致: {session}')
        ready = pickle.loads(ready_path.read_bytes())['data']['ready']
        row = dict(session=session, start=ready['start'], us_open=ready['us_open'],
                   force_close=ready['limit'], end=ready['start'] + 13 * 3600,
                   cutoff=ready['start'] + 13 * 3600 + 60, partial=False,
                   books={}, candles={}, fingerprints=[], prepared=ready_fp, source_cache145=cache_fp)
        for symbol in ('NK225', 'TOPIX'):
            base = ROOT.parent / 'JP_OSE_Data/future' / symbol / session
            row['books'][symbol] = str((base / 'book.jsonl').resolve())
            row['candles'][symbol] = {str(sec): str((base / f'candle_{sec // 60}min.csv').resolve()) for sec in (60, 300)}
            for name in ('book.jsonl', 'candle_1min.csv', 'candle_5min.csv'):
                fp = fingerprint(base / name)
                prior_fp = prior.get(fp['path'].casefold())
                fp['previous145_sha256'] = prior_fp['sha256'] if prior_fp else None
                fp['matches_previous145'] = prior_fp is None or fp['sha256'] == prior_fp['sha256']
                if not fp['matches_previous145']:
                    raise RuntimeError(f'原資料145との不一致: {fp["path"]}')
                row['fingerprints'].append(fp)
        rows.append(row)
        print(session, '原資料6件・既存気配1件を確認', flush=True)

    # ----------------------------------------
    # 途中場は既知の切断資料だけを追加し、前後比較に混ぜない。
    session = '2026-10-26_Night'
    current = ROOT / 'work/current_idle_20261026/三波確認/data'
    start = datetime(2026, 10, 26, 17, tzinfo=JST).timestamp()
    cutoff = datetime(2026, 10, 26, 21, 13, 52, tzinfo=JST).timestamp()
    row = dict(session=session, start=start, us_open=start + 5.5 * 3600,
               force_close=start + 12 * 3600 + 50 * 60,
               end=start + 13 * 3600, cutoff=cutoff, partial=True,
               books={}, candles={}, fingerprints=[],
               prepared=fingerprint(ROOT / f'work/preus148/inputs/{session}.pkl'))
    for symbol in ('NK225', 'TOPIX'):
        row['books'][symbol] = str((current / f'{symbol}_book.jsonl').resolve())
        row['candles'][symbol] = {str(sec): str((current / f'{symbol}_candles_{sec // 60}min.json').resolve()) for sec in (60, 300)}
        row['fingerprints'] += [fingerprint(Path(p)) for p in [row['books'][symbol], *row['candles'][symbol].values()]]
    rows.append(row)
    result = dict(created_at=datetime.now(JST).isoformat(),
                  purpose='金融再生を行わない原資料同一性と参照先の準備',
                  definition=fingerprint(OUT / '観測定義.json'),
                  provenance=[fingerprint(old_path), fingerprint(source_path)],
                  complete_sessions=25, partial_sessions=1, API_calls=0,
                  new_market_decisions=0, sessions=rows)
    (OUT / '原資料一覧149.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print('完了: 完了25夜・途中1夜・原資料156ファイル')


if __name__ == '__main__':
    main()
