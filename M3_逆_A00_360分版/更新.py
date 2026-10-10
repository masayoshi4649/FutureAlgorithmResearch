"""保存原本を検出し、固定した M3 逆・360 分版のセッション損益を更新する。"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import runpy
import sys
import tempfile
from zoneinfo import ZoneInfo


OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
WORK = ROOT / 'work/wave_v21'
JST = ZoneInfo('Asia/Tokyo')
SYMBOLS = ('TOPIX', 'NK225')
MULT = {'TOPIX': 1000., 'NK225': 10.}
KINDS = (('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv'))
SESSION_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}_(Day|Night)$')
OLD_SESSIONS = {f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ('Day', 'Night')}
CODE_PATHS = [
    'work/wave_v8/raw_features.py', 'work/wave_v9/turning_signals.py',
    'work/wave_v10/signals.py', 'work/wave_v11/signals.py',
    'work/wave_v13/data.py', 'work/wave_v13/exact_engine.py', 'work/wave_v13/new_signals.py',
    'work/wave_v13/catalog.py', 'work/wave_v13/research.py', 'work/wave_v16/reference.py',
    'work/wave_v17/signals.py', 'work/wave_v17/catalog.py', 'work/wave_v17/engine.py',
    'work/wave_v17/research.py', 'work/wave_v19/engine.py', 'work/wave_v19/signal_variants.py',
]


def read_json(path: Path) -> object:
    """機能: UTF-8 の JSON を読み取る。

    引数: path (Path)。返り値: JSON の内容 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """機能: 原本を書き換えず SHA256 を計算する。

    引数: path (Path)。返り値: ハッシュ文字列 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def clean(value: object) -> object:
    """機能: 非有限値と数値ライブラリの値を JSON に保存できる形にする。

    引数: value (object)。返り値: JSON 互換の値 (object)。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float):
        return None if not math.isfinite(value) else (0. if value == 0 else value)
    return value


def atomic_save(path: Path, value: object) -> None:
    """機能: 同じフォルダの一時ファイルから原子的に JSON を保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(clean(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def fixed_settings() -> tuple[dict, dict]:
    """機能: 条件のコピーと実行コードを固定し、以後の変更を検出する。

    引数: なし。返り値: 固定条件と固定記録 (tuple[dict, dict])。
    """
    source = ROOT / 'work/wave_v19/主候補の条件.json'
    target = OUT / '固定条件.json'
    guard = OUT / '固定条件の照合.json'
    if not target.exists():
        if guard.exists():
            raise RuntimeError('固定条件.json がありません。固定条件の変更として更新を中止します。')
        target.write_bytes(source.read_bytes())
    fixed = read_json(target)
    cfg = fixed['一枚でのエンジン設定']
    if fixed['候補ID'] != 'V0800' or fixed['信号条件']['id'] != 'S00' or cfg['timeout_min'] != 360 or cfg['initial_qty'] != 1 or cfg['audit_cap'] != 1:
        raise RuntimeError('V0800・S00・360 分・固定 1 枚の条件ではありません。')
    hashes = {name: digest(ROOT / name) for name in CODE_PATHS}
    state = dict(strategy_id='V0800', configuration_sha256=digest(target), code_hashes=hashes)
    if guard.exists():
        if read_json(guard) != state:
            raise RuntimeError('固定条件または実行コードが変わりました。旧結果との混在を防ぐため更新を中止します。別の手法として管理してください。')
    else:
        if digest(target) != digest(source):
            raise RuntimeError('初回の固定条件が既存の主候補と一致しません。')
        atomic_save(guard, state)
    return fixed, state


def paths_for(session: str) -> list[Path]:
    """機能: 両銘柄で必要な６原本のパスを返す。

    引数: session (str)。返り値: 原本パス一覧 (list[Path])。
    """
    return [ROOT / kind / symbol / f'{session}.{extension}' for kind, extension in KINDS for symbol in SYMBOLS]


def discover(previous: dict) -> list[str]:
    """機能: ローカル原本と前回台帳にあるセッションを重複なく検出する。

    引数: previous (dict)。返り値: 日時順の識別子 (list[str])。
    """
    sessions = {row['session'] for row in previous.get('records', []) + previous.get('pending', [])}
    for kind, extension in KINDS:
        for symbol in SYMBOLS:
            sessions.update(path.stem for path in (ROOT / kind / symbol).glob(f'*.{extension}') if SESSION_PATTERN.fullmatch(path.stem))
    return sorted(sessions)


def bounds(session: str) -> tuple[datetime, datetime]:
    """機能: 通常監視区間の開始と排他的終了を返す。

    引数: session (str)。返り値: 開始・終了日時 (tuple[datetime, datetime])。
    """
    day = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith('_Day'):
        return day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=40)
    return day + timedelta(hours=17), day + timedelta(days=1, hours=5, minutes=55)


def fingerprints(paths: list[Path]) -> dict:
    """機能: 更新中でない原本の内容ハッシュを取得する。

    引数: paths (list[Path])。返り値: 相対パスと SHA256 の対応 (dict)。
    """
    result = {}
    for path in paths:
        before = path.stat()
        result[path.relative_to(ROOT).as_posix()] = digest(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f'読取り中に原本が更新されました: {path.relative_to(ROOT)}')
    return result


def book_edges(path: Path, start: datetime, end: datetime) -> dict:
    """機能: 原本両端の価格時刻から開始・最終１分の存在を確認する。

    引数: path (Path)、start/end (datetime)。返り値: 最初と最後の日時 (dict)。
    """
    with path.open('rb') as stream:
        head = stream.read(2 * 1024 * 1024).splitlines()
        stream.seek(max(0, path.stat().st_size - 2 * 1024 * 1024))
        tail = stream.read().splitlines()
    stamps = []
    for line in head[1:-1] + tail[1:]:
        try:
            row = json.loads(line)
            value = row.get('CurrentPrice')
            stamp = datetime.fromisoformat(row['CurrentPriceTime'])
            if start <= stamp < end and isinstance(value, (int, float)) and value > 0:
                stamps.append(stamp)
        except (ValueError, TypeError, KeyError):
            continue
    if not stamps or min(stamps) >= start + timedelta(minutes=1) or max(stamps) < end - timedelta(minutes=1):
        raise ValueError(f'生板が開始１分または最終１分まで揃っていません: {path.relative_to(ROOT)}')
    return dict(first=min(stamps).isoformat(), last=max(stamps).isoformat())


def check_complete(session: str, now: datetime) -> dict:
    """機能: 両銘柄の原本、確定足、セッション終了を確認する。

    引数: session (str)、now (datetime)。返り値: 確認した入力範囲 (dict)。
    """
    start, end = bounds(session)
    if now < end:
        raise ValueError(f'セッション終了前です。終了予定 {end.isoformat()}')
    coverage = {}
    for symbol in SYMBOLS:
        coverage[symbol] = book_edges(ROOT / 'book' / symbol / f'{session}.jsonl', start, end)
        for interval in (1, 5):
            path = ROOT / f'candle_{interval}min' / symbol / f'{session}.csv'
            with path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            times = [datetime.fromisoformat(row['time']) for row in rows]
            if not times or times != sorted(set(times)):
                raise ValueError(f'足の日時が空・重複・逆順です: {path.relative_to(ROOT)}')
            closed = [stamp for stamp, row in zip(times, rows) if row['closed'].lower() == 'true']
            if start not in closed or end - timedelta(minutes=interval) not in closed:
                raise ValueError(f'開始足または最終確定足がありません: {path.relative_to(ROOT)}')
    return coverage


def initial_seeds(guard: dict) -> dict:
    """機能: 過去の固定記録と入力 SHA が一致した検証済み結果だけを候補にする。

    引数: guard (dict)。返り値: セッション別の結果と原本ハッシュ (dict)。
    """
    seeds = {}
    week = read_json(ROOT / 'work/wave_v19/探索前の固定記録.json')['ハッシュ']
    week_ok = all(Path(name).exists() and digest(Path(name)) == sha for name, sha in week.items())
    if week_ok:
        inventory = read_json(ROOT / 'work/wave_v16/データ棚卸し.json')['原本']
        expected = {}
        for item in inventory:
            bucket = expected.setdefault(item['セッション'], {})
            for kind in ('生板', '1分足', '5分足'):
                detail = item[kind]
                bucket[detail['原本'].replace('\\', '/')] = detail['SHA256']
        rows = read_json(ROOT / 'work/wave_v19/セッション比較.json')
        for session in OLD_SESSIONS:
            selected = [row for row in rows if row['method_id'] == 'V0800' and row['session'] == session]
            if len(selected) == 2 and len(expected.get(session, {})) == 6:
                seeds[session] = dict(records=selected, hashes=expected[session], source='既存週検証・原本 SHA 照合')
    day = read_json(ROOT / 'work/wave_v20/実行前の固定記録.json')
    if day['元候補資料SHA256'] == guard['configuration_sha256']:
        hashes = day['原本とコードSHA256']
        code_ok = all(digest(Path(path)) == sha for path, sha in hashes.items() if '\\work\\' in path)
        if code_ok:
            expected = {Path(path).relative_to(ROOT).as_posix(): sha for path, sha in hashes.items() if '\\work\\' not in path}
            selected = [row for row in read_json(ROOT / 'work/wave_v20/結果.json') if row['method_id'] == 'V0800' and row['quantity'] == 1]
            if len(selected) == 2 and len(expected) == 6:
                seeds[day['対象']] = dict(records=selected, hashes=expected, source='9 月 28 日検証・原本 SHA 照合')
    return seeds


def source_module(path: Path, name: str):
    """機能: 既存ソースを変更せず別名で読み込む。

    引数: path (Path)、name (str)。返り値: 読み込んだモジュール (module)。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def replay(session: str, fixed: dict, hashes: dict) -> tuple[list[dict], list[dict]]:
    """機能: 固定条件１通りを新規・変更された原本に適用する。

    引数: session (str)、fixed/hashes (dict)。返り値: 損益行と約定明細 (tuple[list, list])。
    """
    import numpy as np
    import numba

    cache = WORK / session
    cache.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True
    reference = source_module(ROOT / 'work/wave_v16/reference.py', 'ledger_reference')
    reference.previous.OUT = cache
    numba.config.CACHE_DIR = str(WORK / 'numba_cache')
    extractor = source_module(ROOT / 'work/wave_v8/raw_features.py', 'ledger_raw_features')
    features = {}
    for symbol in SYMBOLS:
        path = ROOT / 'book' / symbol / f'{session}.jsonl'
        quotes = []
        frame, audit = extractor.extract_features(path, symbol, session, quotes=quotes)
        extractor.write_features(frame, audit, cache / 'features', quotes=quotes)
        book, raw = reference.previous.data.scan_book(path, collect_prices=True)
        if audit['原本SHA256'] != hashes[path.relative_to(ROOT).as_posix()] or book['SHA256'] != audit['原本SHA256']:
            raise ValueError('抽出中に原本が更新されました。')
        tape_path = cache / 'features' / f'約定系列_{symbol}_{session}.npz'
        with np.load(tape_path, allow_pickle=False) as archive:
            tape = dict(archive)
        indices = tape['seq'].astype(int)
        tape['last'] = raw['last'][indices]
        tape['volume'] = raw['volume'][indices]
        tape['current_price'] = tape['last'].copy()
        np.savez_compressed(tape_path, **tape)
        features[symbol] = frame
    inputs = reference.previous.build_inputs([session], allow_holdout=True, roots={session: (ROOT, cache / 'features')})
    signals = source_module(ROOT / 'work/wave_v17/signals.py', 'ledger_signals')
    states = {key: signals.build_states(ready, inputs[(session, 'NK225' if key[1] == 'TOPIX' else 'TOPIX')], features=features[key[1]]) for key, ready in inputs.items()}
    variants = source_module(ROOT / 'work/wave_v19/signal_variants.py', 'ledger_variants')
    directions = variants.build_one(fixed['信号条件'], inputs, states)
    engine = source_module(ROOT / 'work/wave_v19/engine.py', 'ledger_engine')
    with reference.module_aliases(dict(catalog=source_module(ROOT / 'work/wave_v17/catalog.py', 'ledger_catalog'), engine=engine, signals=signals)):
        metrics = source_module(ROOT / 'work/wave_v17/research.py', 'ledger_metrics')
    metrics.MULT = MULT
    cfg = dict(fixed['一枚でのエンジン設定'], id='V0800')
    rows, trades = [], []
    for symbol in SYMBOLS:
        ready = inputs[(session, symbol)]
        end = bounds(session)[1].timestamp()
        if ready['time_s'][-1] < end - 60:
            raise ValueError(f'{symbol} の有効な評価入力が最終１分までありません。')
        result = engine.run(ready, directions[(session, symbol)], cfg, detail=True)
        if result['stats'][9] != 0 or result['stats'][2] > 1 or result['stats'][3] > 1:
            raise ValueError('場末の未返済玉または固定１枚上限違反があります。')
        rows.append(metrics.summarize(result, cfg, symbol, session))
        for tr in result['trades']:
            trades.append(dict(symbol=symbol, session=session, side='買い' if tr[2] > 0 else '売り', quantity=int(tr[3]),
                               entry_price=tr[4], exit_price=tr[5],
                               entry_time=datetime.fromtimestamp(ready['time_s'][int(tr[6])], JST).isoformat(),
                               exit_time=datetime.fromtimestamp(ready['time_s'][int(tr[7])], JST).isoformat(),
                               reason=engine.REASONS[int(tr[9])], net_yen=tr[10] * MULT[symbol]))
    atomic_save(cache / '再生記録.json', dict(strategy_id='V0800', source_hashes=hashes, records=rows, trades=trades))
    return rows, trades


def validate_rows(rows: list[dict], session: str) -> None:
    """機能: 両銘柄の一意性、固定１枚、損益・枚数の会計を確認する。

    引数: rows (list[dict])、session (str)。返り値: なし (None)。
    """
    if len(rows) != 2 or {row['symbol'] for row in rows} != set(SYMBOLS):
        raise ValueError('両銘柄の結果が２行で揃っていません。')
    for row in rows:
        if row['session'] != session or row['method_id'] != 'V0800' or row.get('quantity', 1) != 1:
            raise ValueError('セッション・手法・枚数が一致しません。')
        required = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units',
                    'zero_units', 'unit_balance', 'closed_units', 'cycles')
        for name in required:
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'{name} が有限の数値ではありません。')
        for name, value in row.items():
            if name.endswith('_yen') and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f'{name} が有限の金額ではありません。')
        for name in ('profit_units', 'loss_units', 'zero_units', 'unit_balance', 'closed_units', 'cycles'):
            if int(row[name]) != row[name] or (name != 'unit_balance' and row[name] < 0):
                raise ValueError(f'{name} が許容される整数枚数・回数ではありません。')
        if row['gross_profit_yen'] < 0 or row['gross_loss_yen'] < 0 or abs(row['gross_profit_yen'] - row['gross_loss_yen'] - row['net_yen']) > .01:
            raise ValueError('利益・損失・収支が一致しません。')
        if row['profit_units'] - row['loss_units'] != row['unit_balance'] or row['profit_units'] + row['loss_units'] + row['zero_units'] != row['closed_units']:
            raise ValueError('決済枚数の会計が一致しません。')
        if row['closed_units'] != row['cycles'] or row.get('max_long', 0) > 1 or row.get('max_short', 0) > 1:
            raise ValueError('固定１枚の取引回数または最大保有枚数が一致しません。')


def update() -> dict:
    """機能: 不足原本を保留し、変更のあるセッションだけ損益を更新する。

    引数: なし。返り値: 更新後の台帳 (dict)。
    """
    fixed, guard = fixed_settings()
    ledger_path = OUT / 'セッション損益.json'
    previous = read_json(ledger_path) if ledger_path.exists() else {}
    if previous and (previous.get('version') != 1 or previous.get('strategy_id') != 'V0800' or previous.get('configuration_sha256') != guard['configuration_sha256']):
        raise RuntimeError('既存台帳の版・手法・固定条件が一致しません。')
    grouped = {}
    for row in previous.get('records', []):
        grouped.setdefault(row['session'], []).append(row)
    seeds = None
    rows, pending, accepted = [], [], {}
    counts = dict(reused=0, seeded=0, replayed=0)
    now = datetime.now(JST)
    for session in discover(previous):
        paths = paths_for(session)
        missing = [path.relative_to(ROOT).as_posix() for path in paths if not path.is_file()]
        if missing:
            pending.append(dict(session=session, reason='両銘柄の６原本が揃っていません。', missing_files=missing))
            continue
        try:
            before = fingerprints(paths)
            coverage = check_complete(session, now)
            old = grouped.get(session, [])
            if len(old) == 2 and all(row.get('source_hashes') == before for row in old):
                selected = old
                counts['reused'] += 1
                origin = old[0]['source']
            else:
                if seeds is None:
                    try:
                        seeds = initial_seeds(guard)
                    except (ValueError, OSError, KeyError):
                        seeds = {}
                seed = seeds.get(session)
                if seed and seed['hashes'] == before:
                    selected, origin = seed['records'], seed['source']
                    counts['seeded'] += 1
                else:
                    print(f'{session}: 変更・新規原本を固定条件で再生します。', flush=True)
                    selected, _ = replay(session, fixed, before)
                    origin = '固定条件による原本再生'
                    counts['replayed'] += 1
            validate_rows(selected, session)
            if fingerprints(paths) != before:
                raise ValueError('処理中に原本が更新されました。次回更新で再評価します。')
            for row in selected:
                rows.append(dict(row, quantity=1, phase='調整に使用' if session in OLD_SESSIONS else '条件固定後',
                                 source_hashes=before, source=origin, coverage=coverage,
                                 computed_at=row.get('computed_at', now.isoformat())))
            accepted[session] = before
            print(f'{session}: 両銘柄の損益を確認しました。', flush=True)
        except (ValueError, OSError, KeyError, AssertionError) as error:
            pending.append(dict(session=session, reason=str(error)))
            print(f'{session}: 保留 — {error}', flush=True)
    # ----------------------------------------
    # 他セッションを処理している間の書換えも、公開直前に再確認する。
    for session, hashes in accepted.items():
        try:
            unchanged = fingerprints(paths_for(session)) == hashes
        except (OSError, ValueError):
            unchanged = False
        if not unchanged:
            rows = [row for row in rows if row['session'] != session]
            pending.append(dict(session=session, reason='更新実行中に原本が変わりました。次回更新で再評価します。'))
    fixed_settings()
    ledger = dict(version=1, strategy_id='V0800', updated_at=datetime.now(JST).isoformat(),
                  configuration_sha256=guard['configuration_sha256'], quantity_basis=1,
                  multipliers=MULT, assumptions='費用０・指定価格約定。既存の先物原本をミニ／マイクロ倍率で換算。',
                  records=sorted(rows, key=lambda row: (row['session'], SYMBOLS.index(row['symbol']))),
                  pending=sorted(pending, key=lambda row: row['session']), update_counts=counts)
    atomic_save(ledger_path, ledger)
    atomic_save(WORK / '最終更新記録.json', dict(updated_at=ledger['updated_at'], records=len(rows), pending=len(pending), **counts, api_requests=0, parameter_searches=0))
    return ledger


def main() -> None:
    """機能: 同時更新を防いで台帳を更新し、最後に表示 HTML を生成する。

    引数: なし。返り値: なし (None)。
    """
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    lock = OUT / '更新実行中.lock'
    try:
        stream = lock.open('x', encoding='utf-8')
    except FileExistsError as error:
        raise RuntimeError('更新が既に実行中です。前回が異常終了した場合は、実行中の Python がないことを確認して 更新実行中.lock を削除してください。') from error
    try:
        with stream:
            stream.write(f'{os.getpid()} {datetime.now(JST).isoformat()}\n')
        ledger = update()
        renderer = OUT / '表示生成.py'
        if renderer.exists():
            runpy.run_path(str(renderer), run_name='__main__')
        print(f'完了: {len(ledger["records"]) // 2} セッション、保留 {len(ledger["pending"])} セッション。', flush=True)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
