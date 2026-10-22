"""追加された原本を監査し、未見の日中を封印したまま学習入力を準備する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FEATURES = OUT / 'features'
TRAIN = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
         '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night']
HOLDOUT = '2026-09-24_Day'
SYMBOLS = ['NK225', 'TOPIX']


def import_module(path: Path, name: str):
    """機能: 既存の凍結コードを変更せず別名で読み込む。

    引数: path (Path): ソース。name (str): 固有名。
    返り値: module: 読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def signals_module(allow_holdout: bool = False):
    """機能: 旧ライブへの暗黙参照を除いた既存24信号器を準備する。

    引数: allow_holdout (bool): 固定後に最終保留の価格利用を許可する場合だけTrue。
    返り値: module: 許可したセッションの原本参照を明示した信号器。
    """
    module = import_module(ROOT/'work/wave_v11/signals.py', 'v13_reference_signals')
    for session in TRAIN+([HOLDOUT] if allow_holdout else []):
        module.CANDLE_OVERRIDES[session] = ROOT
        module.FEATURE_OVERRIDES[session] = FEATURES
    return module


def scan_book(path: Path, collect_prices: bool) -> tuple[dict, dict]:
    """機能: 原本の日時・件数・ハッシュを調べ、学習側だけ価格配列を抽出する。

    引数: path (Path): 読取専用原本。collect_prices (bool): 価格保持の許可。
    返り値: tuple[dict, dict]: 価格を含まない監査記録と、許可された価格列。
    """
    hasher = hashlib.sha256()
    count, missing, backwards = 0, 0, 0
    first, final, previous = None, None, None
    prices, volumes, stamps = [], [], []
    with path.open('rb') as handle:
        for line in handle:
            hasher.update(line)
            raw = json.loads(line)
            stamp = raw.get('CurrentPriceTime')
            count += 1
            if stamp:
                backwards += int(previous is not None and stamp < previous)
                first = first or stamp
                final = stamp
                previous = stamp
            else:
                missing += 1
            if collect_prices:
                value = raw.get('CurrentPrice')
                prices.append(float(value) if isinstance(value, (float, int)) and value > 0 else np.nan)
                volumes.append(raw.get('TradingVolume') or 0.)
                stamps.append(stamp)
    audit = dict(原本=str(path.relative_to(ROOT)), SHA256=hasher.hexdigest(), バイト数=path.stat().st_size,
                 行数=count, 最初の約定時刻=first, 最後の約定時刻=final,
                 時刻欠損行数=missing, 時刻逆行数=backwards,
                 価格保持=collect_prices)
    return audit, dict(last=np.asarray(prices, dtype=float), volume=np.asarray(volumes, dtype=float), stamps=stamps)


def candle_metadata(path: Path) -> dict:
    """機能: 足の価格を出力せず日時・確定状態・完全出来高を点検する。

    引数: path (Path): 読取専用CSV。
    返り値: dict: 件数と時刻の監査。
    """
    frame = pd.read_csv(path, usecols=['time', 'closed', 'volume_complete'])
    times = pd.to_datetime(frame.time)
    return dict(原本=str(path.relative_to(ROOT)), SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                行数=len(frame), 最初の足時刻=str(times.iloc[0]), 最後の足時刻=str(times.iloc[-1]),
                確定足数=int(frame.closed.astype(str).str.lower().eq('true').sum()),
                出来高完全足数=int(frame.volume_complete.astype(str).str.lower().eq('true').sum()),
                足時刻重複数=int(times.duplicated().sum()), 足時刻昇順=bool(times.is_monotonic_increasing))


def candle_consistency(session: str, symbol: str, raw: dict) -> dict:
    """機能: 学習側だけ生約定価格から足を再集計して保存足を比較する。

    引数: session/symbol (str): 対象。raw (dict): 原本順の約定価格と時刻。
    返り値: dict: OHLC一致件数と差異の概要。出来高は時刻遅延のため別扱い。
    """
    series = pd.Series(raw['last'], index=pd.to_datetime(raw['stamps']))
    series = series.loc[series.index.notna() & series.notna()]
    outcomes = {}
    for interval in [1, 5]:
        frame = pd.read_csv(ROOT/f'candle_{interval}min'/symbol/f'{session}.csv')
        frame.index = pd.to_datetime(frame.time)
        ohlc = series.resample(f'{interval}min').ohlc()
        common = frame.index.intersection(ohlc.dropna().index)
        left = frame.loc[common, ['open', 'high', 'low', 'close']].to_numpy(float)
        right = ohlc.loc[common, ['open', 'high', 'low', 'close']].to_numpy(float)
        equal = np.isclose(left, right, rtol=0, atol=1e-8)
        outcomes[f'{interval}分足'] = dict(共通足数=len(common), OHLC全一致足数=int(equal.all(axis=1).sum()),
                                             OHLC別不一致数=dict(zip(['open', 'high', 'low', 'close'], (~equal).sum(axis=0).astype(int).tolist())),
                                             保存足だけの時刻数=len(frame.index.difference(ohlc.dropna().index)))
    return outcomes


def prepare(sessions: list[str] | None = None, allow_holdout: bool = False) -> None:
    """機能: 全原本のメタ監査と６セッションの因果的特徴・現在価格を保存する。

    引数: sessions (list[str] | None): 対象、Noneは全件メタ情報と学習側価格。
    allow_holdout (bool): 固定後に最終保留の価格利用を許可する場合だけTrue。
    返り値: None: 作業フォルダだけに成果を保存する。APIへは接続しない。
    """
    FEATURES.mkdir(parents=True, exist_ok=True)
    extractor = import_module(ROOT/'work/wave_v8/raw_features.py', 'v13_original_raw_features')
    audits = []
    for session in TRAIN+[HOLDOUT] if sessions is None else sessions:
        if session not in TRAIN+[HOLDOUT]:
            raise ValueError('登録していないセッションは読み込みません')
        for symbol in SYMBOLS:
            path = ROOT/'book'/symbol/f'{session}.jsonl'
            permitted = session != HOLDOUT or allow_holdout
            book, raw = scan_book(path, collect_prices=permitted)
            row = dict(セッション=session, 銘柄=symbol, 用途='最終保留' if session == HOLDOUT else '学習候補', 生板=book)
            for interval in [1, 5]:
                row[f'{interval}分足'] = candle_metadata(ROOT/f'candle_{interval}min'/symbol/f'{session}.csv')
            if permitted:
                stem = f'{symbol}_{session}'
                old_audit_path = ROOT/f'work/wave_v8/features/{stem}_audit.json'
                old_audit = json.loads(old_audit_path.read_text(encoding='utf-8')) if old_audit_path.exists() else {}
                reusable = old_audit.get('原本SHA256') == book['SHA256']
                row['旧特徴原本SHA256一致'] = reusable
                if reusable:
                    for name in [f'{stem}.csv', f'{stem}.npz', f'{stem}_audit.json', f'約定系列_{stem}.npz']:
                        shutil.copy2(ROOT/'work/wave_v8/features'/name, FEATURES/name)
                else:
                    quotes = []
                    features, audit = extractor.extract_features(path, symbol, session, quotes=quotes)
                    extractor.write_features(features, audit, FEATURES, quotes=quotes)
                target = FEATURES/f'約定系列_{stem}.npz'
                tape = dict(np.load(target, allow_pickle=False))
                indices = tape['seq'].astype(int)
                tape['last'] = raw['last'][indices]
                tape['volume'] = raw['volume'][indices]
                tape['current_price'] = tape['last'].copy()
                np.savez_compressed(target, **tape)
                audit_path = FEATURES/f'{stem}_audit.json'
                tape_audit = json.loads(audit_path.read_text(encoding='utf-8'))
                tape_audit['追加前の約定系列NPZ_SHA256'] = tape_audit.get('約定系列NPZ_SHA256')
                tape_audit['約定系列NPZ_SHA256'] = hashlib.sha256(target.read_bytes()).hexdigest()
                tape_audit['今回追加列'] = 'last/current_priceはseq行のCurrentPrice、volumeはTradingVolume。欠損は補完しない。'
                audit_path.write_text(json.dumps(tape_audit, ensure_ascii=False, indent=2), encoding='utf-8')
                row['真の約定価格追加'] = dict(行数=len(indices), 有効現在価格数=int(np.isfinite(tape['last']).sum()),
                    約定系列SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
                    説明='元の有効板行番号seqでCurrentPriceとTradingVolumeを対応。中値への置換なし。')
                row['足と生約定価格の整合'] = candle_consistency(session, symbol, raw)
            audits.append(row)
            name = '最終保留開封監査.json' if allow_holdout else '原本メタ監査.json'
            (OUT/name).write_text(json.dumps(audits, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(dict(セッション=session, 銘柄=symbol, 行数=book['行数'], 最後=book['最後の約定時刻'], 用途=row['用途']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='保存原本を監査して学習側だけ準備')
    parser.add_argument('--allow-holdout', action='store_true')
    parser.add_argument('--session', action='append')
    args = parser.parse_args()
    prepare(sessions=args.session, allow_holdout=args.allow_holdout)
