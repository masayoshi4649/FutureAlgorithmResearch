"""保存された一週間の原本だけを監査し、前回入力の再利用可否を記録する。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
JST = ZoneInfo('Asia/Tokyo')
SYMBOLS = ['NK225', 'TOPIX']
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
KNOWN = SESSIONS[:7]
HOLDOUT = SESSIONS[-1]
CUTOFF = '2026-09-25T03:01:00+09:00'


def save(path: Path, value: object) -> None:
    """機能: 日本語の監査値を UTF-8 で保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def digest(path: Path) -> str:
    """機能: 原本の内容を変更せず SHA256 を計算する。

    引数: path (Path)。返り値: ハッシュ文字列 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            value.update(chunk)
    return value.hexdigest()


def bounds(session: str) -> tuple[datetime, datetime]:
    """機能: 保存ファイルに対応する場内時刻範囲を作る。

    引数: session (str)。返り値: 開始以上・終了未満の組 (tuple[datetime, datetime])。
    """
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith('Day'):
        return date.replace(hour=8, minute=45), date.replace(hour=15, minute=40)
    return date.replace(hour=17), (date + timedelta(days=1)).replace(hour=6)


def old_hashes() -> dict[str, str]:
    """機能: 前回の７完全セッションのハッシュ記録を読み込む。

    引数: なし。返り値: 相対パスとハッシュの辞書 (dict[str, str])。
    """
    previous = json.loads((ROOT/'work/wave_v14/今回データ棚卸し.json').read_text(encoding='utf-8'))
    return {row['原本'].replace('\\', '/'): row['SHA256'] for row in previous['原本']
            if row['原本'].replace('\\', '/').split('/')[0] in ['book', 'candle_1min', 'candle_5min']}


def prefix_check(symbol: str) -> dict:
    """機能: 前回ライブの全バイト列が今回原本の場前行を除いた連続部分と一致するか調べる。

    引数: symbol (str)。返り値: 先頭位置・一致判定などの監査辞書 (dict)。
    """
    old = ROOT/'work/wave_v15/live/book'/symbol/'2026-09-24_Night.jsonl'
    source = ROOT/'book'/symbol/'2026-09-24_Night.jsonl'
    old_size = old.stat().st_size
    with old.open('rb') as past, source.open('rb') as current:
        first = past.readline()
        line_number, offset = 0, None
        while line := current.readline():
            line_number += 1
            if line == first:
                offset = current.tell() - len(line)
                break
            if line_number > 10000:
                break
        equal, compared, first_mismatch = offset is not None, 0, None
        if offset is not None:
            past.seek(0)
            current.seek(offset)
            while expected := past.read(1048576):
                actual = current.read(len(expected))
                if actual != expected:
                    equal = False
                    first_mismatch = compared + next((i for i, (a, b) in enumerate(zip(expected, actual)) if a != b), min(len(expected), len(actual)))
                    break
                compared += len(expected)
    return dict(銘柄=symbol, 前回原本=old.relative_to(ROOT).as_posix(), 今回原本=source.relative_to(ROOT).as_posix(),
                前回SHA256=digest(old), 既知排他的締切=CUTOFF, 前回バイト数=old_size,
                今回原本開始行=line_number if offset is not None else None, 今回原本開始バイト=offset,
                先行除外行数=line_number-1 if offset is not None else None,
                既知部分連続バイト一致=equal, 照合済みバイト数=compared, 最初の不一致位置=first_mismatch)


def scan_book(path: Path, session: str) -> tuple[dict, dict]:
    """機能: 原本の品質を全行監査し、足照合用の場内 OHLC だけを内部集計する。

    引数: path (Path)、session (str)。返り値: 価格非表示の監査と分別 OHLC (tuple[dict, dict])。
    """
    start, end = bounds(session)
    hasher = hashlib.sha256()
    seen = set()
    minute = {}
    counts = dict(行数=0, 空行数=0, JSON不正行数=0, 時刻欠損行数=0, 時刻逆行数=0,
                  同一約定時刻継続行数=0, 完全同一行重複数=0, 直前と完全同一行数=0,
                  場内行数=0, 場前行数=0, 場後行数=0, 現在価格欠損不正行数=0,
                  売買気配不正行数=0, 出来高時刻が約定時刻より未来の行数=0)
    first = last = valid_first = valid_last = previous_time = previous_line = None
    symbols, names, changes = set(), set(), []
    max_gap = 0.
    for line in path.open('rb'):
        hasher.update(line)
        counts['行数'] += 1
        if not line.strip():
            counts['空行数'] += 1
            continue
        marker = hashlib.blake2b(line, digest_size=16).digest()
        counts['完全同一行重複数'] += int(marker in seen)
        counts['直前と完全同一行数'] += int(line == previous_line)
        seen.add(marker)
        previous_line = line
        try:
            raw = json.loads(line)
        except (ValueError, TypeError):
            counts['JSON不正行数'] += 1
            continue
        symbols.add(str(raw.get('Symbol')))
        names.add(str(raw.get('SymbolName')))
        stamp = raw.get('CurrentPriceTime')
        price = raw.get('CurrentPrice')
        price_good = isinstance(price, (float, int)) and np.isfinite(price) and price > 0
        counts['現在価格欠損不正行数'] += int(not price_good)
        sell, buy = raw.get('Sell1') or {}, raw.get('Buy1') or {}
        ask, bid = sell.get('Price') or 0, buy.get('Price') or 0
        counts['売買気配不正行数'] += int(not (ask > bid > 0 and (sell.get('Qty') or 0) > 0 and (buy.get('Qty') or 0) > 0))
        if not stamp:
            counts['時刻欠損行数'] += 1
            continue
        time = datetime.fromisoformat(stamp)
        if time.tzinfo is None:
            raise ValueError(f'時刻にタイムゾーンがありません: {path}')
        first = first or stamp
        last = stamp
        if previous_time is not None:
            counts['時刻逆行数'] += int(time < previous_time)
            counts['同一約定時刻継続行数'] += int(time == previous_time)
        previous_time = time
        volume_stamp = raw.get('TradingVolumeTime')
        if volume_stamp:
            counts['出来高時刻が約定時刻より未来の行数'] += int(datetime.fromisoformat(volume_stamp) > time)
        if time < start:
            counts['場前行数'] += 1
            continue
        if time >= end:
            counts['場後行数'] += 1
            continue
        counts['場内行数'] += 1
        valid_first = valid_first or stamp
        if valid_last is not None:
            gap = (time - datetime.fromisoformat(valid_last)).total_seconds()
            max_gap = max(max_gap, gap)
            if gap >= 300:
                changes.append(dict(前=valid_last, 後=stamp, 秒=gap))
        valid_last = stamp
        if price_good:
            key = time.replace(second=0, microsecond=0).isoformat()
            if key not in minute:
                minute[key] = [price, price, price, price]
            else:
                row = minute[key]
                row[1], row[2], row[3] = max(row[1], price), min(row[2], price), price
    counts.update(dict(原本=path.relative_to(ROOT).as_posix(), SHA256=hasher.hexdigest(), バイト数=path.stat().st_size,
                  最初の約定時刻=first, 最後の約定時刻=last, 場内最初=valid_first, 場内最後=valid_last,
                  最大約定時刻間隔秒=max_gap, 五分以上の約定時刻間隔=changes,
                  銘柄コード=sorted(symbols), 銘柄名=sorted(names), 損益計算=False))
    return counts, minute


def candle_audit(path: Path, session: str, interval: int, minute: dict) -> dict:
    """機能: 足の時刻・品質と原本由来 OHLC の整合を価格非表示で確認する。

    引数: path (Path)、session (str)、interval (int)、minute (dict)。返り値: 監査辞書 (dict)。
    """
    frame = pd.read_csv(path)
    stamps = pd.to_datetime(frame.time)
    start, end = bounds(session)
    expected = pd.date_range(start, end, freq=f'{interval}min', inclusive='left')
    bars = pd.DataFrame.from_dict(minute, orient='index', columns=['open', 'high', 'low', 'close'])
    bars.index = pd.to_datetime(bars.index)
    bars = bars.resample(f'{interval}min').agg(dict(open='first', high='max', low='min', close='last')).dropna()
    saved = frame.set_index(stamps)
    common = saved.index.intersection(bars.index)
    equal = np.isclose(saved.loc[common, ['open', 'high', 'low', 'close']].to_numpy(float), bars.loc[common].to_numpy(float), rtol=0, atol=1e-8)
    invalid = (frame.high < frame.low) | (frame.open > frame.high) | (frame.open < frame.low) | (frame.close > frame.high) | (frame.close < frame.low)
    return dict(原本=path.relative_to(ROOT).as_posix(), SHA256=digest(path), バイト数=path.stat().st_size, 行数=len(frame),
                最初=str(stamps.iloc[0]), 最後=str(stamps.iloc[-1]), 確定足数=int(frame.closed.astype(str).str.lower().eq('true').sum()),
                出来高完全足数=int(frame.volume_complete.astype(str).str.lower().eq('true').sum()),
                時刻重複数=int(stamps.duplicated().sum()), 時刻逆行数=int(stamps.diff().lt(pd.Timedelta(0)).sum()),
                場外足数=int((~stamps.between(start, end, inclusive='left')).sum()),
                定間隔に対する未保存足数=len(expected.difference(stamps)), 未保存時刻=[x.isoformat() for x in expected.difference(stamps)],
                OHLC不正足数=int(invalid.sum()), 価格欠損セル数=int(frame[['open', 'high', 'low', 'close']].isna().sum().sum()),
                原本集計共通足数=len(common), 原本集計OHLC全一致足数=int(equal.all(axis=1).sum()),
                原本集計OHLC別不一致数=dict(zip(['open', 'high', 'low', 'close'], (~equal).sum(axis=0).astype(int).tolist())),
                保存足のみの時刻数=len(saved.index.difference(bars.index)), 原本のみの時刻数=len(bars.index.difference(saved.index)))


def inventory() -> dict:
    """機能: 原本60件を監査し、旧完全区間と03:01までの既知範囲を照合する。

    引数: なし。返り値: 保存済み監査 (dict)。通信や売買計算を行わない。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    expected = old_hashes()
    rows = []
    for session in SESSIONS:
        for symbol in SYMBOLS:
            book, minute = scan_book(ROOT/'book'/symbol/f'{session}.jsonl', session)
            row = dict(セッション=session, 銘柄=symbol,
                       用途='既知完全' if session in KNOWN else '最終保留' if session == HOLDOUT else '追加検証', 生板=book)
            for interval in [1, 5]:
                row[f'{interval}分足'] = candle_audit(ROOT/f'candle_{interval}min'/symbol/f'{session}.csv', session, interval, minute)
            for kind in ['生板', '1分足', '5分足']:
                item = row[kind]
                item['前回SHA256'] = expected.get(item['原本'])
                item['前回一致'] = item['SHA256'] == item['前回SHA256'] if item['前回SHA256'] else None
            rows.append(row)
            save(OUT/'データ棚卸し_途中.json', rows)
            print(json.dumps(dict(セッション=session, 銘柄=symbol, 原本行数=book['行数'], 場内最後=book['場内最後'], 用途=row['用途']), ensure_ascii=False), flush=True)
    files = [row[kind] for row in rows for kind in ['生板', '1分足', '5分足']]
    prefixes = [prefix_check(symbol) for symbol in SYMBOLS]
    result = dict(監査時刻=datetime.now(JST).isoformat(), API取得数=0, セッション数=10, 銘柄数=2,
                  原本ファイル数=len(files), 原本生板行数=sum(row['生板']['行数'] for row in rows),
                  旧完全原本数=len(expected), 旧原本一致数=sum(item['前回一致'] is True for item in files),
                  旧原本変更=[item['原本'] for item in files if item['前回一致'] is False],
                  新規原本=[item['原本'] for item in files if item['前回一致'] is None],
                  既知完全区間=KNOWN, 既知ナイト境界=CUTOFF, 最終保留=HOLDOUT,
                  前回現在原本の照合=prefixes, 原本=rows,
                  注意=['同一約定時刻の板更新は重複除去しない。約定時刻の反復と完全同一行は別集計。',
                        '分足の未保存時刻は約定のない時間を含み、通信欠落とは断定できない。',
                        'CurrentPriceTime は受信時刻ではない。生板の完全なリアルタイム因果性には限界がある。',
                        '最終保留の監査は品質件数のみ。価格要約・方向・損益は出力しない。'])
    save(OUT/'データ棚卸し.json', result)
    lines = ['# 一週間の保存原本の棚卸し', '',
             f'保存データは 10 セッション × 2 銘柄、生板 20 件・１分足 20 件・５分足 20 件。生板合計 {result["原本生板行数"]:,} 行。API 取得は０回。', '',
             f'旧７完全セッションの 42 原本のうち {result["旧原本一致数"]} 件が前回 SHA256 と一致。変更 {len(result["旧原本変更"])} 件。', '',
             '既知範囲は 9/21 日中〜9/24 日中および 9/24 ナイトの 9/25 03:01 未満。新規評価はその続きと 9/25 日中。9/25 ナイトは最後まで選択から外す。', '',
             '|セッション|銘柄|原本行数|場前/場後|時刻欠損|時刻逆行|場内最初|場内最後|１分足/５分足|',
             '|---|---|---:|---:|---:|---:|---|---|---:|']
    for row in rows:
        b = row['生板']
        lines.append(f'|{row["セッション"]}|{row["銘柄"]}|{b["行数"]:,}|{b["場前行数"]}/{b["場後行数"]}|{b["時刻欠損行数"]}|{b["時刻逆行数"]}|{b["場内最初"]}|{b["場内最後"]}|{row["1分足"]["行数"]}/{row["5分足"]["行数"]}|')
    lines += ['', '## 既知ナイトとの連続性', '']
    for row in prefixes:
        lines.append(f'- {row["銘柄"]}：先行 {row["先行除外行数"]} 行を除いた位置から、前回 {row["前回バイト数"]:,} バイトと完全一致={row["既知部分連続バイト一致"]}。')
    lines += ['', '## 品質と解釈', ''] + [f'- {note}' for note in result['注意']]
    lines += ['- 場前の残存約定価格、時刻欠損、不正気配は旧特徴抽出器の固定処理で除外する。生板の順番は並べ替えない。',
              '- OHLC 不一致の詳細、未保存時刻、完全同一行数、五分以上の約定時刻間隔は JSON を参照。価格値は監査報告に出力していない。', '']
    (OUT/'データ棚卸し.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ['原本', '注意']}, ensure_ascii=False), flush=True)
    return result


def prepare(stage: str) -> dict:
    """機能: 確認済み旧７区間を再利用し、許可された追加区間の因果的入力を生成する。

    引数: stage (str): development または holdout。返り値: 入力準備記録 (dict)。
    """
    import reference

    if stage not in ['development', 'holdout']:
        raise ValueError('対象段階が不正です')
    if stage == 'holdout' and not (OUT/'最終保留_凍結記録.json').exists():
        raise RuntimeError('最終保留の条件固定前には入力を準備しません')
    if stage == 'holdout':
        import selection
        selection.freeze_check()
    target = OUT/f'入力_{stage}.pkl'
    if target.exists():
        raise FileExistsError('既存の入力を上書きしません')
    inventory_result = json.loads((OUT/'データ棚卸し.json').read_text(encoding='utf-8'))
    if inventory_result['旧原本変更'] or inventory_result['旧原本一致数'] != 42:
        raise RuntimeError('旧７区間の原本一致を確認できません')
    prepared = {}
    reused = ROOT/'work/wave_v14/既知入力.pkl'
    if stage == 'development':
        with reused.open('rb') as stream:
            prior = pickle.load(stream)
        prepared = {key: value for key, value in prior.items() if key[0] in KNOWN}
        if set(prepared) != {(session, symbol) for session in KNOWN for symbol in SYMBOLS}:
            raise ValueError('旧７区間の再利用セルが足りません')
    sessions = SESSIONS[7:9] if stage == 'development' else [HOLDOUT]
    feature_dir = OUT/'features'
    feature_dir.mkdir(parents=True, exist_ok=True)
    data = reference.previous.data
    extractor = reference.source_module(ROOT/'work/wave_v8/raw_features.py', 'v16_saved_raw_features')
    audits = []
    for session in sessions:
        for symbol in SYMBOLS:
            source = ROOT/'book'/symbol/f'{session}.jsonl'
            quotes = []
            frame, audit = extractor.extract_features(source, symbol, session, quotes=quotes)
            extractor.write_features(frame, audit, feature_dir, quotes=quotes)
            book, original = data.scan_book(source, collect_prices=True)
            stem = f'{symbol}_{session}'
            tape_path = feature_dir/f'約定系列_{stem}.npz'
            tape = dict(np.load(tape_path, allow_pickle=False))
            indices = tape['seq'].astype(int)
            tape['last'], tape['volume'] = original['last'][indices], original['volume'][indices]
            tape['current_price'] = tape['last'].copy()
            np.savez_compressed(tape_path, **tape)
            audit_path = feature_dir/f'{stem}_audit.json'
            feature_audit = json.loads(audit_path.read_text(encoding='utf-8'))
            feature_audit['追加前の約定系列NPZ_SHA256'] = feature_audit.get('約定系列NPZ_SHA256')
            feature_audit['約定系列NPZ_SHA256'] = digest(tape_path)
            feature_audit['今回追加列'] = 'last/current_price は同じ seq 行の CurrentPrice、volume は TradingVolume。補完なし。'
            reference.save(audit_path, feature_audit)
            expected_book = next(row['生板']['SHA256'] for row in inventory_result['原本'] if row['セッション'] == session and row['銘柄'] == symbol)
            if expected_book != book['SHA256'] or audit['原本SHA256'] != book['SHA256']:
                raise RuntimeError('棚卸し後に生板原本が変わっています')
            row = dict(セッション=session, 銘柄=symbol, 原本SHA256=book['SHA256'], 原本行数=book['行数'],
                       約定系列行数=len(indices), 有効現在価格数=int(np.isfinite(tape['last']).sum()),
                       約定系列SHA256=digest(tape_path), 特徴行数=len(frame),
                       特徴参照行が評価行より前=feature_audit['特徴参照行が評価行より前'])
            audits.append(row)
            save(OUT/f'入力準備_{stage}_途中.json', audits)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        prepared.update(reference.previous.build_inputs([session], roots={session: (ROOT, feature_dir)}))
    with target.open('xb') as stream:
        pickle.dump(prepared, stream, protocol=pickle.HIGHEST_PROTOCOL)
    result = dict(準備時刻=datetime.now(JST).isoformat(), 段階=stage, API取得数=0, 損益計算=False,
                  旧７区間再利用可能=inventory_result['旧原本一致数'] == 42 and not inventory_result['旧原本変更'],
                  旧入力再利用元=reused.relative_to(ROOT).as_posix() if stage == 'development' else None,
                  旧入力SHA256=digest(reused) if stage == 'development' else None,
                  旧入力再利用セル数=14 if stage == 'development' else 0,
                  入力ファイル=target.relative_to(ROOT).as_posix(), 入力SHA256=digest(target),
                  入力セル数=len(prepared), 入力原本有効行数=sum(len(value['seq']) for value in prepared.values()),
                  追加原本からの準備=audits,
                  セル=[dict(セッション=session, 銘柄=symbol, 行数=len(value['seq']),
                             最初=datetime.fromtimestamp(float(value['time_s'][0]), JST).isoformat(),
                             最後=datetime.fromtimestamp(float(value['time_s'][-1]), JST).isoformat())
                        for (session, symbol), value in prepared.items()])
    save(OUT/f'入力準備_{stage}.json', result)
    if stage == 'development':
        save(OUT/'入力準備記録.json', result)
    else:
        save(OUT/'入力準備記録_holdout.json', result)
        selection.freeze_check()
    print(json.dumps({key: value for key, value in result.items() if key not in ['追加原本からの準備', 'セル']}, ensure_ascii=False), flush=True)
    return result


def main() -> None:
    """機能: 明示された保存原本監査のみを実行する。

    引数: コマンドライン。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='一週間の原本監査・入力準備')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--inventory', action='store_true')
    group.add_argument('--prepare', choices=['development', 'holdout'])
    args = parser.parse_args()
    if args.inventory:
        inventory()
    else:
        prepare(args.prepare)


if __name__ == '__main__':
    main()
