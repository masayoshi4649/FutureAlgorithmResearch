"""学習６セッションだけを対象に生価格対応と足の微差を独立点検する。"""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

import data


def run() -> None:
    """機能: 全約定系列の価格対応・旧夜間との包含・足の差分を点検する。

    引数: なし。
    返り値: None: 学習側の監査JSONと日本語報告書を作業先へ保存する。
    """
    records = []
    for session in data.TRAIN:
        for symbol in data.SYMBOLS:
            path = data.ROOT/'book'/symbol/f'{session}.jsonl'
            _, raw = data.scan_book(path, collect_prices=True)
            target = data.FEATURES/f'約定系列_{symbol}_{session}.npz'
            tape = dict(np.load(target, allow_pickle=False))
            expected = raw['last'][tape['seq'].astype(int)]
            assert np.array_equal(tape['last'], expected, equal_nan=True)
            assert np.array_equal(tape['last'], tape['current_price'], equal_nan=True)
            row = dict(セッション=session, 銘柄=symbol, 全行CurrentPrice一致=True, 対応行数=len(expected), 足差分=[])
            series = pd.Series(raw['last'], index=pd.to_datetime(raw['stamps']))
            series = series.loc[series.index.notna() & series.notna()]
            for interval in [1, 5]:
                bars = pd.read_csv(data.ROOT/f'candle_{interval}min'/symbol/f'{session}.csv')
                bars.index = pd.to_datetime(bars.time)
                ohlc = series.resample(f'{interval}min').ohlc()
                common = bars.index.intersection(ohlc.dropna().index)
                columns = ['open', 'high', 'low', 'close']
                difference = bars.loc[common, columns] - ohlc.loc[common, columns]
                for timestamp in difference.index[(difference.abs() > 1e-8).any(axis=1)]:
                    row['足差分'].append(dict(間隔分=interval, 時刻=timestamp.isoformat(),
                        保存足=bars.loc[timestamp, columns].astype(float).to_dict(),
                        生板再集計=ohlc.loc[timestamp, columns].astype(float).to_dict(),
                        差=difference.loc[timestamp].astype(float).to_dict()))
            if session == data.TRAIN[-1]:
                older = data.ROOT/'work/wave_v11/live/book'/symbol/f'{session}.jsonl'
                before = older.read_bytes()
                with path.open('rb') as handle:
                    prefix = handle.read(len(before))
                row['前回API保存分が今回原本の先頭と完全一致'] = prefix == before
                row['前回API保存バイト数'] = len(before)
                row['今回増加バイト数'] = path.stat().st_size-len(before)
                first_line = before.splitlines(keepends=True)[0]
                original = path.read_bytes()
                position = original.find(first_line)
                row['前回API先頭行が今回原本で見つかるバイト位置'] = position
                row['前回API保存分が今回原本の連続部分と完全一致'] = position >= 0 and original[position:position+len(before)] == before
                row['前回API先頭より前に今回追加された原本行数'] = original[:position].count(b'\n') if position >= 0 else None
            # ----------------------------------------
            # 真の約定価格追加後の監査ハッシュへ更新し、旧ハッシュも残す。
            audit_path = data.FEATURES/f'{symbol}_{session}_audit.json'
            tape_audit = json.loads(audit_path.read_text(encoding='utf-8'))
            tape_audit.setdefault('追加前の約定系列NPZ_SHA256', tape_audit.get('約定系列NPZ_SHA256'))
            tape_audit['約定系列NPZ_SHA256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            tape_audit['今回追加列'] = 'last/current_priceはseq行のCurrentPrice、volumeはTradingVolume。欠損は補完しない。'
            audit_path.write_text(json.dumps(tape_audit, ensure_ascii=False, indent=2), encoding='utf-8')
            records.append(row)
    output = dict(最終保留の価格参照=False, 検査=records)
    (data.OUT/'入力対応と足差分の監査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(対象数=len(records), 全行価格一致=all(r['全行CurrentPrice一致'] for r in records),
                         比較約定行数=sum(r['対応行数'] for r in records),
                         足差分数=sum(len(r['足差分']) for r in records)), ensure_ascii=False))


if __name__ == '__main__':
    run()
