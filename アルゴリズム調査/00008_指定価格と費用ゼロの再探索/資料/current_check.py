"""条件を一度凍結し、保存保留日中と一回だけ取得する現在セッションを照合する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import urllib.parse
from zoneinfo import ZoneInfo

import numpy as np

import data
import exact_engine
import research

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
LIVE = OUT / 'live'
FROZEN = OUT / '現在照合_凍結記録.json'
JST = ZoneInfo('Asia/Tokyo')
SYMBOLS = ['NK225', 'TOPIX']
BASE_URL = 'http://10.10.100.1:8080/api/v1/history'
LOCAL_FILES = ['research.py', 'catalog.py', 'data.py', 'exact_engine.py', 'new_signals.py',
               'current_check.py', '検証計画.md', '現在照合計画.md', '条件一覧.json',
               '最終選択.json', '信号条件一覧.json', '原本メタ監査.json']
DEPENDENCIES = ['work/wave_v11/signals.py', 'work/wave_v10/signals.py',
                'work/wave_v9/turning_signals.py', 'work/wave_v9/execution.py',
                'work/wave_v8/raw_features.py', 'work/wave_v7/fetch_once.py']


def now_jst() -> datetime:
    """機能: 日本時間の現在時刻を返す。

    引数: なし。返り値: タイムゾーン付き時刻 (datetime)。
    """
    return datetime.now(JST)


def sha256(path: Path) -> str:
    """機能: 対象を変更せず内容のハッシュを計算する。

    引数: path (Path)。返り値: SHA256文字列 (str)。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_files() -> list[Path]:
    """機能: 固定する実行コード・条件・入力監査の一覧を返す。

    引数: なし。返り値: 凍結対象一覧 (list[Path])。
    """
    return [OUT / name for name in LOCAL_FILES] + [ROOT / name for name in DEPENDENCIES]


def current_session(stamp: datetime) -> tuple[str, datetime, datetime]:
    """機能: 時計だけから現在の日中・夜間の識別子と範囲を求める。

    引数: stamp (datetime)。返り値: セッション名・開始・終了 (tuple[str, datetime, datetime])。
    """
    if stamp.tzinfo is None:
        raise ValueError('現在時刻にタイムゾーンがありません')
    stamp = stamp.astimezone(JST)
    day = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = stamp.hour * 60 + stamp.minute
    if 8 * 60 + 45 <= minutes < 15 * 60 + 45:
        return day.strftime('%Y-%m-%d') + '_Day', day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=45)
    if minutes >= 17 * 60:
        return day.strftime('%Y-%m-%d') + '_Night', day + timedelta(hours=17), day + timedelta(days=1, hours=6)
    if minutes < 6 * 60:
        previous = day - timedelta(days=1)
        return previous.strftime('%Y-%m-%d') + '_Night', previous + timedelta(hours=17), day + timedelta(hours=6)
    raise ValueError('現在は日中・夜間の監視時間外です')


def read_selection() -> tuple[dict, list[dict], list[str]]:
    """機能: 保存済みの最終選択と、既に探索済みの条件だけを照合する。

    引数: なし。返り値: 選択記録・全条件・固定ID一覧 (tuple[dict, list[dict], list[str]])。
    """
    selected = json.loads((OUT / '最終選択.json').read_text(encoding='utf-8'))
    configs = json.loads((OUT / '条件一覧.json').read_text(encoding='utf-8'))
    mapping = {cfg['id']: cfg for cfg in configs}
    ids = sorted(set(selected['照合ID']))
    if len(mapping) != len(configs) or not ids or not set(ids) <= set(mapping):
        raise ValueError('照合IDが探索済み条件と一致しません')
    if set(selected['主候補']) != set(SYMBOLS):
        raise ValueError('両銘柄の主候補記録がありません')
    for symbol, candidate in selected['主候補'].items():
        if not candidate.get('採用') or candidate['採用']['方式'] not in ids:
            raise ValueError(f'{symbol}の主候補が照合IDにありません')
    for identifier in ids:
        exact_engine.parameters(mapping[identifier])
    return selected, configs, ids


def freeze() -> dict:
    """機能: 未開封の保留評価と現在取得に使う条件を一回だけ固定する。

    引数: なし。返り値: 凍結記録 (dict)。通信・保留価格読み込みは行わない。
    """
    if (LIVE / '一回取得開始.json').exists() or (OUT / '保留日中_開封開始.json').exists():
        raise RuntimeError('保留開封または現在取得が始まっているため再凍結できません')
    if FROZEN.exists():
        raise FileExistsError('凍結記録は上書きできません')
    stamp = now_jst()
    session, start, end = current_session(stamp)
    selected, configs, ids = read_selection()
    fixed = {cfg['id']: cfg for cfg in configs}
    metadata = json.loads((OUT / '原本メタ監査.json').read_text(encoding='utf-8'))
    holdout_inputs = {}
    for row in metadata:
        if row['セッション'] == data.HOLDOUT:
            for key in ('生板', '1分足', '5分足'):
                holdout_inputs[row[key]['原本']] = row[key]['SHA256']
    if len(holdout_inputs) != 6:
        raise ValueError('最終保留の原本６ファイルの監査が揃っていません')
    record = dict(fixed_at=stamp.isoformat(), session=session, starts_at=start.isoformat(), ends_at=end.isoformat(),
        selected_ids=ids, selected_configs=[fixed[identifier] for identifier in ids],
        selected_by_symbol={symbol: candidate['採用']['方式'] for symbol, candidate in selected['主候補'].items()},
        holdout_session=data.HOLDOUT, holdout_inputs_sha256=holdout_inputs,
        files_sha256={path.relative_to(ROOT).as_posix(): sha256(path) for path in tracked_files()},
        手数料=0, 気配差控除=0, 取得後再選択=False, 保留開封後再選択=False,
        要求数=6, 各要求回数=1, 再試行=False, リダイレクト=False,
        説明='保存保留日中と現在の全セッション途中を同じ固定条件で評価する。現在取得は全６URLを各一回だけ。',
        未返済='打切り時点のCurrentPriceで全脚の含み損益を加算し、確定損益と別表示する。',
        指定価格仮定='事前指定値の到達時はギャップも指定値で約定。市場相当・時間返済は次行の現在価格。')
    with FROZEN.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f'通信なしで{len(ids)}条件・{len(record["files_sha256"])}ファイルを凍結しました', flush=True)
    return record


def freeze_check() -> dict:
    """機能: 凍結対象と採用条件の一致を確認し、不一致なら先へ進まない。

    引数: なし。返り値: 検証済み凍結記録 (dict)。通信は行わない。
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
    mapping = {cfg['id']: cfg for cfg in configs}
    if record['selected_ids'] != ids or record['selected_configs'] != [mapping[identifier] for identifier in ids]:
        raise RuntimeError('凍結後に採用IDまたは設定が変わっています')
    expected_primary = {symbol: candidate['採用']['方式'] for symbol, candidate in selected['主候補'].items()}
    if record['selected_by_symbol'] != expected_primary or record['holdout_session'] != data.HOLDOUT:
        raise RuntimeError('凍結後に主候補または保留セッションが変わっています')
    return record


def validate_book(path: Path, symbol: str, start: datetime, cutoff: datetime) -> dict:
    """機能: 保存応答の所属・代理時刻順序・共通締切を検査する。

    引数: path (Path)、symbol (str)、start/cutoff (datetime)。返り値: 原本応答監査 (dict)。
    """
    names, contracts = set(), set()
    previous = first = final = None
    rows = missing = 0
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():
                raise ValueError('生板に空行があります')
            row = json.loads(line)
            if not isinstance(row, dict) or any(key not in row for key in ('Buy1', 'Sell1', 'CurrentPriceTime', 'CurrentPrice')):
                raise ValueError('生板の必要項目が不足しています')
            rows += 1
            names.add(str(row.get('SymbolName', '')))
            contracts.add(str(row.get('Symbol', '')))
            if not row['CurrentPriceTime']:
                missing += 1
                continue
            stamp = datetime.fromisoformat(row['CurrentPriceTime'])
            if stamp.tzinfo is None:
                raise ValueError('生板の時刻にタイムゾーンがありません')
            stamp = stamp.astimezone(JST)
            if stamp >= cutoff:
                raise ValueError('生板に共通締切以降の原本行があります')
            if previous is not None and stamp < previous:
                raise ValueError('生板の時刻が逆行しています')
            previous = stamp
            if stamp >= start:
                first = stamp if first is None else first
                final = stamp
    expected = '日経' if symbol == 'NK225' else 'TOPIX'
    if not names or any(expected not in name for name in names) or len(contracts) != 1 or '' in contracts or first is None:
        raise ValueError('生板の銘柄・限月または有効な対象時刻を確認できません')
    return dict(銘柄=symbol, 行数=rows, 時刻欠損=missing, 銘柄名=sorted(names), 限月=sorted(contracts),
                最初=first.isoformat(), 最後=final.isoformat(), SHA256=sha256(path))


def jobs_for(session: str, start: datetime, cutoff: datetime) -> list[tuple[str, str, Path]]:
    """機能: 共通の排他的締切を持つ六つの読み取りURLを作る。

    引数: session (str)、start/cutoff (datetime)。返り値: 名前・URL・保存先 (list[tuple])。
    """
    query = urllib.parse.urlencode({'from': start.isoformat(), 'to': cutoff.isoformat()})
    jobs = []
    for symbol in SYMBOLS:
        jobs.append((f'{symbol}_book', f'{BASE_URL}/{symbol}/book?{query}', LIVE / 'book' / symbol / f'{session}.jsonl'))
        for minutes in (1, 5):
            jobs.append((f'{symbol}_{minutes}min', f'{BASE_URL}/{symbol}/candles/{minutes}min?{query}',
                         LIVE / '応答' / f'{symbol}_{minutes}min.json'))
    return jobs


def fetch() -> dict:
    """機能: 凍結照合後に六URLを一回ずつ保存し、所属と共通締切を確認する。

    引数: なし。返り値: 取得記録 (dict)。失敗後も再取得しない。
    """
    frozen = freeze_check()
    stamp = now_jst()
    session, start, end = current_session(stamp)
    if session != frozen['session']:
        raise ValueError('現在セッションが凍結時から変わっています')
    cutoff = stamp.replace(second=0, microsecond=0)
    if cutoff <= start:
        raise ValueError('共通締切より前のセッションデータがありません')
    LIVE.mkdir(parents=True, exist_ok=True)
    record = dict(started_at=stamp.isoformat(), cutoff=cutoff.isoformat(), session=session,
        starts_at=start.isoformat(), ends_at=end.isoformat(), fixed_at=frozen['fixed_at'],
        selected_ids=frozen['selected_ids'], manifest_sha256=sha256(FROZEN),
        files_sha256_before_fetch=dict(frozen['files_sha256']),
        requests=[], status='取得開始', 各要求回数=1, 再試行=False, リダイレクト=False)
    with (LIVE / '一回取得開始.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    research.save(LIVE / '凍結記録の写し.json', frozen)
    helper = data.import_module(ROOT / 'work/wave_v7/fetch_once.py', 'v13_current_fetch_helper')
    helper.LIVE, helper.ROOT = LIVE, ROOT
    jobs = jobs_for(session, start, cutoff)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(helper.fetch_one, *job) for job in jobs]
            record['requests'] = [future.result() for future in futures]
        research.save(LIVE / '取得記録.json', record)
        if len(record['requests']) != 6 or not all(request.get('ok') for request in record['requests']):
            raise RuntimeError('六要求の一部が失敗しました。再試行せず記録を確認してください')
        candles, books = [], []
        for symbol in SYMBOLS:
            for minutes in (1, 5):
                candles.append(helper.convert_candles(LIVE / '応答' / f'{symbol}_{minutes}min.json',
                    symbol, minutes, session, start, end, cutoff))
            books.append(validate_book(LIVE / 'book' / symbol / f'{session}.jsonl', symbol, start, cutoff))
        freeze_check()
        record.update(status='取得と検査完了', candles=candles, books=books, finished_at=now_jst().isoformat())
    except Exception as error:
        record.update(status='失敗・再試行禁止', error=f'{type(error).__name__}: {error}', finished_at=now_jst().isoformat())
        research.save(LIVE / '取得記録.json', record)
        research.save(OUT / '現在照合_取得記録.json', record)
        raise
    research.save(LIVE / '取得記録.json', record)
    research.save(OUT / '現在照合_取得記録.json', record)
    print(f'現在{session}の６要求を各一回保存。共通締切は{cutoff.isoformat()}未満。', flush=True)
    return record


def holdout() -> dict:
    """機能: 凍結後だけ保存保留日中を読み、凍結済みIDを同じ条件で再生する。

    引数: なし。返り値: 保留評価記録 (dict)。通信・再選択は行わない。
    """
    frozen = freeze_check()
    for relative, digest in frozen['holdout_inputs_sha256'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha256(path) != digest:
            raise RuntimeError(f'保留原本が事前監査から変わっています: {relative}')
    record = dict(opened_at=now_jst().isoformat(), session=data.HOLDOUT,
                  manifest_sha256=sha256(FROZEN), selected_ids=frozen['selected_ids'], status='開封開始')
    with (OUT / '保留日中_開封開始.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    try:
        data.prepare([data.HOLDOUT], allow_holdout=True)
        prepared = research.build_inputs([data.HOLDOUT], allow_holdout=True)
        research.details(prepared, frozen['selected_configs'], frozen['selected_ids'], '保留日中')
        freeze_check()
        record.update(status='固定条件の評価完了', finished_at=now_jst().isoformat(),
                      対象セル数=len(prepared) * len(frozen['selected_ids']), 再選択=False)
    except Exception as error:
        record.update(status='評価失敗', error=f'{type(error).__name__}: {error}')
        research.save(OUT / '保留日中_評価記録.json', record)
        raise
    research.save(OUT / '保留日中_評価記録.json', record)
    print(f'保存保留{data.HOLDOUT}を凍結済み{len(frozen["selected_ids"])}条件で評価しました', flush=True)
    return record


def receipt_check(frozen: dict) -> dict:
    """機能: 保存された六応答と確定足CSVが取得時のハッシュと一致するか確認する。

    引数: frozen (dict)。返り値: 照合済み取得記録 (dict)。通信は行わない。
    """
    receipt = json.loads((LIVE / '取得記録.json').read_text(encoding='utf-8'))
    if receipt['status'] != '取得と検査完了' or receipt['manifest_sha256'] != sha256(FROZEN):
        raise ValueError('取得記録または凍結記録の対応が不正です')
    if receipt['selected_ids'] != frozen['selected_ids'] or receipt['session'] != frozen['session']:
        raise ValueError('取得時の対象条件・セッションが凍結記録と異なります')
    start = datetime.fromisoformat(receipt['starts_at'])
    cutoff = datetime.fromisoformat(receipt['cutoff'])
    expected_jobs = {name: (url, destination) for name, url, destination in jobs_for(receipt['session'], start, cutoff)}
    requests = receipt['requests']
    if len(requests) != 6 or {request['name'] for request in requests} != set(expected_jobs):
        raise ValueError('取得要求は所定の六つである必要があります')
    for request in requests:
        url, destination = expected_jobs[request['name']]
        if not request['ok'] or request['attempts'] != 1 or request['url'] != url:
            raise ValueError('一回取得の要求記録が不正です')
        if request['path'] != destination.relative_to(ROOT).as_posix() or sha256(destination) != request['sha256']:
            raise RuntimeError('取得応答が保存後に変わっています')
    for candle in receipt['candles']:
        destination = (ROOT / candle['path']).resolve()
        if not destination.is_relative_to(LIVE.resolve()) or sha256(destination) != candle['sha256']:
            raise RuntimeError('現在照合の足CSVが変わっています')
    if len(receipt['candles']) != 4 or len(receipt['books']) != 2:
        raise ValueError('取得後の所属検査が不足しています')
    return receipt


def evaluate() -> dict:
    """機能: 保存された現在応答だけから特徴と真の価格を作り、固定IDを再生する。

    引数: なし。返り値: 評価監査 (dict)。通信・現在データによる再選択は行わない。
    """
    frozen = freeze_check()
    receipt = receipt_check(frozen)
    session = receipt['session']
    features = LIVE / 'features'
    features.mkdir(parents=True, exist_ok=True)
    extractor = data.import_module(ROOT / 'work/wave_v8/raw_features.py', 'v13_current_raw_features')
    audits = []
    for symbol in SYMBOLS:
        source = LIVE / 'book' / symbol / f'{session}.jsonl'
        quotes = []
        frame, audit = extractor.extract_features(source, symbol, session, quotes=quotes)
        extractor.write_features(frame, audit, features, quotes=quotes)
        book, raw = data.scan_book(source, collect_prices=True)
        target = features / f'約定系列_{symbol}_{session}.npz'
        tape = dict(np.load(target, allow_pickle=False))
        indices = tape['seq'].astype(int)
        tape['last'], tape['volume'] = raw['last'][indices], raw['volume'][indices]
        tape['current_price'] = tape['last'].copy()
        np.savez_compressed(target, **tape)
        audit_path = features / f'{symbol}_{session}_audit.json'
        feature_audit = json.loads(audit_path.read_text(encoding='utf-8'))
        feature_audit['追加前の約定系列NPZ_SHA256'] = feature_audit.get('約定系列NPZ_SHA256')
        feature_audit['約定系列NPZ_SHA256'] = sha256(target)
        feature_audit['今回追加列'] = 'last/current_priceはseq行のCurrentPrice、volumeはTradingVolume。欠損補完なし。'
        research.save(audit_path, feature_audit)
        audits.append(dict(銘柄=symbol, 原本=book, 約定系列行数=len(indices),
                           有効現在価格数=int(np.isfinite(tape['last']).sum()), 約定系列SHA256=sha256(target)))
    prepared = research.build_inputs([session], roots={session: (LIVE, features)})
    research.details(prepared, frozen['selected_configs'], frozen['selected_ids'], '現在照合')
    freeze_check()
    receipt_check(frozen)
    record = dict(evaluated_at=now_jst().isoformat(), session=session, cutoff=receipt['cutoff'],
        manifest_sha256=sha256(FROZEN), selected_ids=frozen['selected_ids'], 選択変更=False,
        要求数=6, 今回評価中の要求数=0, 入力=audits, 対象セル数=len(prepared) * len(frozen['selected_ids']),
        集計範囲='当該セッション開始から共通締切未満まで。既知部分との差分ではない。',
        未返済評価='確定利益・損失とは別に現在価格で全脚を評価。含み損を捨てない。')
    research.save(OUT / '現在照合_評価記録.json', record)
    print(f'保存した{session}だけを使用し、固定{len(frozen["selected_ids"])}条件を評価しました', flush=True)
    return record


def main() -> None:
    """機能: 凍結・保存保留・一回取得・保存応答評価を明示的に選んで実行する。

    引数: コマンドライン。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='固定条件の保存保留・現在一回照合')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--freeze', action='store_true')
    group.add_argument('--holdout', action='store_true')
    group.add_argument('--fetch', action='store_true')
    group.add_argument('--evaluate', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.holdout:
        holdout()
    elif args.fetch:
        fetch()
    else:
        evaluate()


if __name__ == '__main__':
    main()
