"""保存済み原本と再利用する特徴の一致を確認する。新規取得は行わない。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night']


def main() -> None:
    """機能: 原本のSHA256・抽出履歴・保存期間を確認して日本語JSONを保存する。

    引数: なし。返り値: なし (None)。
    """
    records = []
    for session in SESSIONS:
        partial = session == SESSIONS[-1]
        feature_root = ROOT/'work'/'wave_v9'/'live'/'features' if partial else ROOT/'work'/'wave_v8'/'features'
        raw_root = ROOT/'work'/'wave_v9'/'live' if partial else ROOT
        candles = raw_root/'work'/'wave_v7'/'live' if partial else ROOT
        for symbol in ['NK225', 'TOPIX']:
            path = raw_root/'book'/symbol/f'{session}.jsonl'
            digest = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
            audit = json.loads((feature_root/f'{symbol}_{session}_audit.json').read_text(encoding='utf-8'))
            tape = dict(np.load(feature_root/f'約定系列_{symbol}_{session}.npz'))
            feature_checks = []
            for filename, field in [(f'{symbol}_{session}.csv', '特徴CSV_SHA256'),
                                    (f'約定系列_{symbol}_{session}.npz', '約定系列NPZ_SHA256')]:
                feature_path = feature_root/filename
                feature_hash = hashlib.sha256(feature_path.read_bytes()).hexdigest()
                feature_match = feature_hash == audit[field]
                if not feature_match:
                    raise ValueError(f'抽出成果のハッシュが変化しています: {feature_path}')
                feature_checks.append(dict(ファイル=str(feature_path.relative_to(ROOT)), SHA256=feature_hash,
                                           既存抽出時と一致=feature_match))
            rows = []
            for interval in [1, 5]:
                candle_path = candles/f'candle_{interval}min'/symbol/f'{session}.csv'
                frame = pd.read_csv(candle_path)
                rows.append(dict(分足=interval, 原本=str(candle_path.relative_to(ROOT)), 行数=len(frame),
                                 最初=str(frame.time.iloc[0]), 最後=str(frame.time.iloc[-1]),
                                 SHA256=hashlib.sha256(candle_path.read_bytes()).hexdigest()))
            match = digest == audit['原本SHA256']
            if not match:
                raise ValueError(f'特徴と原本が一致しません: {path}')
            records.append(dict(セッション=session, 銘柄=symbol, 完了セッション=not partial,
                                原本=str(path.relative_to(ROOT)), バイト数=path.stat().st_size,
                                SHA256=digest, 既存抽出時と一致=match, 原本行数=audit['読取行数'],
                                有効板行数=len(tape['seq']), 特徴行数=audit['特徴行数'],
                                最初の有効気配=str(pd.Timestamp(tape['time_s'][0], unit='s', tz='Asia/Tokyo')),
                                最後の有効気配=str(pd.Timestamp(tape['time_s'][-1], unit='s', tz='Asia/Tokyo')),
                                抽出成果=feature_checks, 足=rows))
    # ----------------------------------------
    # 前回取得済み夜間の追加分は、今回は既知の部分セッションとして扱う。
    payload = dict(確認時刻=str(pd.Timestamp.now(tz='Asia/Tokyo')), 今回API取得回数=0,
                   完了セッション数=5, 部分セッション数=1,
                   部分セッション上限='2026-09-23T23:22:00+09:00',
                   説明='原本５セッションの追加はない。v9で取得済みの9/23夜間23:22未満を既知資料に追加する。',
                   銘柄セッション=records)
    (OUT/'入力原本確認.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(銘柄セッション数=len(records), 原本行数=sum(r['原本行数'] for r in records),
                          有効板行数=sum(r['有効板行数'] for r in records), 原本一致=all(r['既存抽出時と一致'] for r in records)), ensure_ascii=False))


if __name__ == '__main__':
    main()
