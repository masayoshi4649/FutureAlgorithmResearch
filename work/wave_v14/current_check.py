"""全思想の採用条件を凍結し、現在六応答を一回だけ保存して再生入力へ変換する。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

import reference

ROOT, OUT, OLD = reference.ROOT, reference.OUT, reference.OLD
LIVE = OUT / 'live'
FROZEN = OUT / '現在照合_凍結記録.json'
JST = ZoneInfo('Asia/Tokyo')
SYMBOLS = reference.SYMBOLS
LOCAL_FILES = ['reference.py', 'risk_guard.py', 'metrics.py', 'research.py', 'grid_engine.py',
    'pair_engine.py', 'details.py', 'current_check.py', '検証計画.md', '現在照合計画.md',
    '最終選択.json', '全条件一覧.json', '既存追加条件_損益前固定.json',
    '格子条件_損益前固定.json', 'NT_固定条件.json', 'NT_事前設計.json',
    '既知入力.pkl', '既知入力の用途.json']
DEPENDENCIES = ['work/wave_v13/exact_engine.py', 'work/wave_v13/new_signals.py',
    'work/wave_v13/data.py', 'work/wave_v13/research.py', 'work/wave_v13/catalog.py',
    'work/wave_v13/current_check.py', 'work/wave_v13/live/取得記録.json',
    'work/wave_v11/signals.py', 'work/wave_v10/signals.py', 'work/wave_v9/turning_signals.py',
    'work/wave_v9/execution.py', 'work/wave_v8/raw_features.py', 'work/wave_v7/fetch_once.py']
LEGACY = reference.previous.data.import_module(OLD / 'current_check.py', 'v14_audited_current_transport')


def now_jst() -> datetime:
    """機能: 日本時間の現在時刻を返す。

    引数: なし。返り値: タイムゾーン付き時刻 (datetime)。
    """
    return datetime.now(JST)


def sha256(path: Path) -> str:
    """機能: 対象を変更せず内容のSHA256を計算する。

    引数: path (Path)。返り値: ハッシュ文字列 (str)。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_files() -> list[Path]:
    """機能: 実行・選択・既知入力・取得に使う固定対象を列挙する。

    引数: なし。返り値: 固定対象 (list[Path])。
    """
    return [OUT / name for name in LOCAL_FILES] + [ROOT / name for name in DEPENDENCIES]


def configure_legacy() -> None:
    """機能: 旧取得器の実装を変更せず、今回の凍結検査と保存先へ接続する。

    引数: なし。返り値: なし (None)。通信は実行しない。
    """
    LEGACY.ROOT, LEGACY.OUT, LEGACY.LIVE, LEGACY.FROZEN = ROOT, OUT, LIVE, FROZEN
    LEGACY.now_jst, LEGACY.freeze_check = now_jst, freeze_check
    LEGACY.research = reference.previous


def read_selection() -> tuple[dict, list[dict], list[str]]:
    """機能: 保存された全条件と採用IDを参照し、再選択せず整合だけ検査する。

    引数: なし。返り値: 選択記録・全条件・採用ID (tuple[dict, list[dict], list[str]])。
    """
    selection = json.loads((OUT / '最終選択.json').read_text(encoding='utf-8'))
    configs = json.loads((OUT / '全条件一覧.json').read_text(encoding='utf-8'))
    mapping = {config['id']: config for config in configs}
    ids = sorted(set(selection['照合ID']))
    if len(mapping) != len(configs) or not ids or not set(ids) <= set(mapping):
        raise ValueError('全条件と照合IDが一致しません')
    if not set(SYMBOLS) <= set(selection['主候補']):
        raise ValueError('両銘柄の主候補記録がありません')
    for row in selection['主候補'].values():
        if row.get('採用') and row['採用']['method'] not in ids:
            raise ValueError('主候補が照合IDに含まれていません')
    return selection, configs, ids


def freeze() -> dict:
    """機能: 全思想の条件、コード、既知境界、既知原本のハッシュを一回だけ固定する。

    引数: なし。返り値: 凍結記録 (dict)。現在APIは取得しない。
    """
    if FROZEN.exists() or (LIVE / '一回取得開始.json').exists():
        raise FileExistsError('凍結または取得を開始済みのため、再凍結しません')
    stamp = now_jst()
    session, start, end = LEGACY.current_session(stamp)
    selection, configs, ids = read_selection()
    mapping = {config['id']: config for config in configs}
    old_record = json.loads((OLD / 'live/取得記録.json').read_text(encoding='utf-8'))
    same_session = session == old_record['session']
    known_cutoff = old_record['cutoff'] if same_session else start.isoformat()
    if not start <= datetime.fromisoformat(known_cutoff) < end:
        raise ValueError('既知境界が今回のセッション範囲にありません')
    old_books = {}
    if same_session:
        for symbol in SYMBOLS:
            path = OLD / 'live/book' / symbol / f'{session}.jsonl'
            old_books[symbol] = dict(path=path.relative_to(ROOT).as_posix(), sha256=sha256(path), bytes=path.stat().st_size)
    record = dict(fixed_at=stamp.isoformat(), session=session, starts_at=start.isoformat(), ends_at=end.isoformat(),
        known_cutoff=known_cutoff, known_session=same_session, known_books=old_books,
        selected_ids=ids, selected_configs=[mapping[identifier] for identifier in ids],
        selected_by_symbol={symbol: row['採用']['method'] for symbol, row in selection['主候補'].items() if row.get('採用')},
        files_sha256={path.relative_to(ROOT).as_posix(): sha256(path) for path in tracked_files()},
        要求数=6, 各要求回数=1, 再試行=False, リダイレクト=False, 取得後再選択=False,
        手数料=0, 気配差控除=0,
        主評価='同じナイトの場合は既知23:19直前の全建玉評価を引き継ぎ、締切までの差分を未知部分とする。',
        実時間前向き運用=False, 説明='全セッションを再生して状態を継続し、未知部分と全体参考を区別する。')
    with FROZEN.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f'通信なしで{len(ids)}条件・{len(record["files_sha256"])}ファイルを凍結しました。既知境界{known_cutoff}', flush=True)
    return record


def freeze_check() -> dict:
    """機能: 凍結ファイルと条件・既知境界の不変性を確認する。

    引数: なし。返り値: 検証済み凍結記録 (dict)。
    """
    record = json.loads(FROZEN.read_text(encoding='utf-8'))
    fixed_at = datetime.fromisoformat(record['fixed_at'])
    if fixed_at.tzinfo is None or fixed_at > now_jst():
        raise ValueError('凍結日時が不正です')
    expected = {path.relative_to(ROOT).as_posix() for path in tracked_files()}
    if set(record['files_sha256']) != expected:
        raise ValueError('凍結対象一覧が一致しません')
    for relative, digest in record['files_sha256'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha256(path) != digest:
            raise RuntimeError(f'凍結後の変更があります: {relative}')
    selected, configs, ids = read_selection()
    mapping = {config['id']: config for config in configs}
    if record['selected_ids'] != ids or record['selected_configs'] != [mapping[identifier] for identifier in ids]:
        raise RuntimeError('凍結後の条件・照合ID変更を検出しました')
    primary = {symbol: row['採用']['method'] for symbol, row in selected['主候補'].items() if row.get('採用')}
    if primary != record['selected_by_symbol']:
        raise RuntimeError('凍結後に主候補が変わっています')
    old = json.loads((OLD / 'live/取得記録.json').read_text(encoding='utf-8'))
    same_session = record['session'] == old['session']
    expected_cutoff = old['cutoff'] if same_session else record['starts_at']
    if same_session != record['known_session'] or record['known_cutoff'] != expected_cutoff:
        raise RuntimeError('既知境界が事前の取得記録と一致しません')
    for old_book in record['known_books'].values():
        path = (ROOT / old_book['path']).resolve()
        if not path.is_relative_to(OLD.resolve()) or path.stat().st_size != old_book['bytes'] or sha256(path) != old_book['sha256']:
            raise RuntimeError('既知セッションの原本が凍結後に変わっています')
    return record


def fetch() -> dict:
    """機能: 監査済み取得器を使い、六URLを一回ずつ保存する。

    引数: なし。返り値: 取得記録 (dict)。失敗後の再試行はしない。
    """
    configure_legacy()
    frozen = freeze_check()
    cutoff = now_jst().replace(second=0, microsecond=0)
    if cutoff <= datetime.fromisoformat(frozen['known_cutoff']):
        raise ValueError('既知境界より後のデータがまだありません')
    record = LEGACY.fetch()
    record.update(known_cutoff=frozen['known_cutoff'], known_session=frozen['known_session'],
                  主評価='既知境界直前から取得締切直前への全玉評価差。全体参考とは別に計算する。')
    reference.save(LIVE / '取得記録.json', record)
    reference.save(OUT / '現在照合_取得記録.json', record)
    return record


def receipt_check(frozen: dict) -> dict:
    """機能: 保存応答と変換足のハッシュ・所属・要求数を確認する。

    引数: frozen (dict)。返り値: 検証済み取得記録 (dict)。
    """
    configure_legacy()
    record = LEGACY.receipt_check(frozen)
    if record.get('known_cutoff') != frozen['known_cutoff'] or record.get('known_session') != frozen['known_session']:
        raise ValueError('取得記録の既知境界が凍結と一致しません')
    return record


def known_prefix_check(frozen: dict) -> list[dict]:
    """機能: 同セッションの旧原本が新しい応答の完全な先頭部分として残るか調べる。

    引数: frozen (dict)。返り値: 銘柄ごとの先頭一致監査 (list[dict])。
    """
    records = []
    for symbol, old in frozen['known_books'].items():
        old_path = (ROOT / old['path']).resolve()
        if not old_path.is_relative_to(OLD.resolve()) or sha256(old_path) != old['sha256'] or old_path.stat().st_size != old['bytes']:
            raise RuntimeError('前回の既知原本が変わっています')
        path = LIVE / 'book' / symbol / f'{frozen["session"]}.jsonl'
        digest = hashlib.sha256()
        remaining = old['bytes']
        with path.open('rb') as stream:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError('現在原本が既知原本より短くなっています')
                digest.update(chunk)
                remaining -= len(chunk)
        if digest.hexdigest() != old['sha256']:
            raise RuntimeError('現在原本の先頭が既知原本と一致しません')
        records.append(dict(銘柄=symbol, 既知バイト数=old['bytes'], 新バイト数=path.stat().st_size,
                            既知原本SHA256=old['sha256'], 先頭バイト完全一致=True))
    return records


def prepare() -> dict:
    """機能: 保存現在原本から特徴・CurrentPrice・再生入力だけを作る。

    引数: なし。返り値: 入力準備記録 (dict)。通信・再選択・損益評価は行わない。
    """
    frozen = freeze_check()
    receipt = receipt_check(frozen)
    prefixes = known_prefix_check(frozen)
    data = reference.previous.data
    extractor = data.import_module(ROOT / 'work/wave_v8/raw_features.py', 'v14_saved_current_raw_features')
    feature_dir = LIVE / 'features'
    feature_dir.mkdir(parents=True, exist_ok=True)
    session, rows = receipt['session'], []
    for symbol in SYMBOLS:
        source = LIVE / 'book' / symbol / f'{session}.jsonl'
        quotes = []
        frame, audit = extractor.extract_features(source, symbol, session, quotes=quotes)
        extractor.write_features(frame, audit, feature_dir, quotes=quotes)
        book, original = data.scan_book(source, collect_prices=True)
        target = feature_dir / f'約定系列_{symbol}_{session}.npz'
        tape = dict(np.load(target, allow_pickle=False))
        indices = tape['seq'].astype(int)
        tape['last'], tape['volume'] = original['last'][indices], original['volume'][indices]
        tape['current_price'] = tape['last'].copy()
        np.savez_compressed(target, **tape)
        audit_path = feature_dir / f'{symbol}_{session}_audit.json'
        feature_audit = json.loads(audit_path.read_text(encoding='utf-8'))
        feature_audit['追加前の約定系列NPZ_SHA256'] = feature_audit.get('約定系列NPZ_SHA256')
        feature_audit['約定系列NPZ_SHA256'] = sha256(target)
        feature_audit['今回追加列'] = 'last/current_priceは同じseq行のCurrentPrice。volumeはTradingVolume。価格補完なし。'
        reference.save(audit_path, feature_audit)
        rows.append(dict(銘柄=symbol, 原本=book, 約定系列行数=len(indices),
                         有効現在価格数=int(np.isfinite(tape['last']).sum()), 約定系列SHA256=sha256(target)))
    prepared = reference.previous.build_inputs([session], roots={session: (LIVE, feature_dir)})
    target = OUT / '現在入力.pkl'
    with target.open('wb') as stream:
        pickle.dump(prepared, stream, protocol=pickle.HIGHEST_PROTOCOL)
    freeze_check()
    receipt_check(frozen)
    record = dict(prepared_at=now_jst().isoformat(), session=session, cutoff=receipt['cutoff'],
        known_cutoff=frozen['known_cutoff'], manifest_sha256=sha256(FROZEN),
        prepared_sha256=sha256(target), selected_ids=frozen['selected_ids'], 入力=rows, 既知原本先頭照合=prefixes,
        選択変更=False, 今回準備中の要求数=0, 損益評価=False,
        説明='全セッションの状態再生用入力。未知部分の評価は別の固定済みdetails.pyが既知境界との差分で行う。')
    reference.save(OUT / '現在照合_入力準備記録.json', record)
    print(f'保存{session}から２銘柄の現在入力を準備しました。追加通信０回。', flush=True)
    return record


def main() -> None:
    """機能: 明示された凍結・一回取得・保存入力準備だけを実行する。

    引数: コマンドライン。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='条件凍結と現在セッションの一回取得')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true')
    group.add_argument('--fetch', action='store_true')
    group.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.fetch:
        fetch()
    else:
        prepare()


if __name__ == '__main__':
    main()
