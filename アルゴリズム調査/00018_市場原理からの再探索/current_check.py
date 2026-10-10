"""凍結済み５候補だけを、一回取得した現在セッションの途中データで照合する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import urllib.parse
from zoneinfo import ZoneInfo

import numpy as np

import depth_features
import engine
import managers
import signals

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
LIVE = OUT / 'live'
JST = ZoneInfo('Asia/Tokyo')
SYMBOLS = ['TOPIX', 'NK225']
sys.dont_write_bytecode = True


def load_module(path: Path, name: str):
    """機能: 過去実装を変更せず固有名で読み込む。

    引数: path (Path)、name (str)。返り値: モジュール (module)。
    """
    definition = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(definition)
    sys.modules[name] = module
    definition.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    """機能: 凍結対象の内容を読み取り専用でハッシュ化する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 今回の現在照合領域だけへ有限 JSON を保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    assert path.resolve().is_relative_to(LIVE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def fetch_once(helper) -> dict:
    """機能: 条件を凍結してから状態１回・６データ URL 各１回だけ取得する。

    引数: helper (module)。返り値: 保存された取得記録 (dict)。失敗しても再取得しない。
    """
    LIVE.mkdir(exist_ok=True)
    selected = json.loads((OUT / '選択結果.json').read_text(encoding='utf-8'))
    items = {item['id']: item for item in json.loads((OUT / '全条件一覧.json').read_text(encoding='utf-8'))}
    source_paths = [OUT / name for name in ['research.py', 'signals.py', 'engine.py', 'managers.py',
                                           'learned_flow.py', 'depth_features.py', 'current_check.py',
                                           '選択結果.json', '全条件一覧.json']]
    source_paths += [ROOT / 'work' / path for path in ['wave_v7/fetch_once.py', 'wave_v8/raw_features.py',
                    'wave_v11/signals.py', 'wave_v13/data.py', 'wave_v13/research.py',
                    'wave_v13/exact_engine.py', 'wave_v13/new_signals.py', 'wave_v16/reference.py']]
    frozen = dict(凍結時刻=datetime.now(JST).isoformat(), 主候補=selected['primary'],
                  最終候補=[items[identifier] for identifier in selected['finalists']],
                  ファイルSHA256={path.relative_to(ROOT).as_posix(): sha(path) for path in source_paths},
                  条件の再選択なし=True, 取得前未閲覧の現在セッション=True,
                  位置付け='凍結後の一回取得。取得前から進行しているセッションの再生であり、前向き実発注試験ではない。')
    with (LIVE / '現在照合の凍結記録.json').open('x', encoding='utf-8') as stream:
        json.dump(frozen, stream, ensure_ascii=False, indent=2)
    now = datetime.now(JST)
    cutoff = now.replace(second=0, microsecond=0)
    record = dict(取得開始=now.isoformat(), 共通締切=cutoff.isoformat(), 各URL一回=True,
                  再取得禁止=True, 凍結記録SHA256=sha(LIVE / '現在照合の凍結記録.json'), requests=[], ok=False)
    with (LIVE / '一回取得開始.json').open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    try:
        status = helper.fetch_one('status', helper.BASE_URL + '/status', LIVE / 'status.json')
        record['requests'].append(status)
        save(LIVE / '取得記録.json', record)
        if not status['ok']:
            raise RuntimeError('状態取得失敗。再試行しません。')
        payload = json.loads((LIVE / 'status.json').read_text(encoding='utf-8-sig'))
        session, start, end = helper.identify_session(payload, cutoff)
        record.update(session=session, session_start=start.isoformat(), session_end=end.isoformat())
        query = urllib.parse.urlencode(dict(**{'from': start.isoformat()}, to=cutoff.isoformat()))
        requests = []
        for symbol in SYMBOLS:
            requests.append((f'{symbol}_book', f'{helper.BASE_URL}/{symbol}/book?{query}', LIVE / 'book' / symbol / f'{session}.jsonl'))
            for minutes in [1, 5]:
                name = f'{symbol}_{minutes}min'
                requests.append((name, f'{helper.BASE_URL}/{symbol}/candles/{minutes}min?{query}', LIVE / '応答原本' / f'{name}.json'))
        with ThreadPoolExecutor(max_workers=6) as pool:
            record['requests'].extend(list(pool.map(lambda args: helper.fetch_one(*args), requests)))
        record['ok'] = all(row['ok'] for row in record['requests'])
        if not record['ok']:
            raise RuntimeError('一部 URL の取得失敗。保存物だけ残し再取得しません。')
    except Exception as error:
        record['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        record['取得終了'] = datetime.now(JST).isoformat()
        save(LIVE / '取得記録.json', record)
    return record


def partial_accounting(ready: dict, result: dict, config: dict) -> dict:
    """機能: セッション途中の確定・含み損益と保有を独立計算する。

    引数: ready/result/config (dict)。返り値: 円額・数量と監査 (dict)。
    場末用の架空行や仮の返済を追加しない。
    """
    orders, trades, curve = result['orders'], result['trades'], result['curve']
    n = len(ready['last'])
    quantity = orders[:, 3] * orders[:, 4]
    rows = orders[:, 0].astype(int)
    cash = np.cumsum(np.bincount(rows, weights=-quantity * orders[:, 5], minlength=n))
    net = np.cumsum(np.bincount(rows, weights=quantity, minlength=n))
    equity = cash + net * ready['last']
    realised_values = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
    realised = np.cumsum(np.bincount(trades[:, 7].astype(int), weights=realised_values, minlength=n))
    opening = orders[:, 7] == 1
    long = np.cumsum(np.bincount(rows, weights=orders[:, 4] * ((opening & (orders[:, 3] > 0)).astype(int) - (~opening & (orders[:, 3] < 0)).astype(int)), minlength=n))
    short = np.cumsum(np.bincount(rows, weights=orders[:, 4] * ((opening & (orders[:, 3] < 0)).astype(int) - (~opening & (orders[:, 3] > 0)).astype(int)), minlength=n))
    np.testing.assert_allclose(curve[:, :4], np.column_stack([equity, realised, long, short]), rtol=0, atol=1e-7)
    np.testing.assert_allclose(realised_values, trades[:, 10], rtol=0, atol=1e-7)
    assert np.all(orders[:, 0] > orders[:, 1]) and np.all(trades[:, 6] < trades[:, 7])
    assert max(long.max(), short.max()) <= config['audit_cap']
    assert min(long.min(), short.min()) >= 0
    multiplier = 1000. if ready['symbol'] == 'TOPIX' else 10.
    values = realised_values * multiplier
    return dict(実現利益円=float(np.maximum(values, 0).sum()), 実現損失円=float(-np.minimum(values, 0).sum()),
                実現収支円=float(values.sum()), 含み損益円=float((equity[-1] - realised[-1]) * multiplier),
                合算損益円=float(equity[-1] * multiplier), 保有買い枚数=int(long[-1]), 保有売り枚数=int(short[-1]),
                利益決済枚数=int(trades[values > 0, 3].sum()), 損失決済枚数=int(trades[values < 0, 3].sum()),
                最大片方向保有枚数=int(max(long.max(), short.max())), 新規約定件数=int(opening.sum()),
                原本最終時刻=datetime.fromtimestamp(ready['time_s'][-1], JST).isoformat(),
                全行会計一致=True, 次行以降約定=True, 架空末尾返済なし=True)


def evaluate_saved(helper) -> dict:
    """機能: 一回保存した応答だけを入力化し、凍結済み５候補の途中損益を照合する。

    引数: helper (module)。返り値: 途中結果と取得・条件監査 (dict)。
    """
    record = json.loads((LIVE / '取得記録.json').read_text(encoding='utf-8'))
    frozen = json.loads((LIVE / '現在照合の凍結記録.json').read_text(encoding='utf-8'))
    assert record['ok'] and len(record['requests']) == 7
    session = record['session']
    start, end, cutoff = [datetime.fromisoformat(record[key]) for key in ['session_start', 'session_end', '共通締切']]
    conversions = []
    for symbol in SYMBOLS:
        for minutes in [1, 5]:
            target = LIVE / f'candle_{minutes}min' / symbol / f'{session}.csv'
            if not target.exists():
                conversions.append(helper.convert_candles(LIVE / '応答原本' / f'{symbol}_{minutes}min.json', symbol, minutes, session, start, end, cutoff))
    if conversions:
        save(LIVE / '足変換記録.json', conversions)
    reference = load_module(ROOT / 'work/wave_v16/reference.py', 'v23_current_reference')
    reference.previous.OUT = LIVE
    import numba
    numba.config.CACHE_DIR = str(LIVE / 'numba_cache')
    extractor = load_module(ROOT / 'work/wave_v8/raw_features.py', 'v23_current_raw')
    features, input_audits = {}, []
    for symbol in SYMBOLS:
        path = LIVE / 'book' / symbol / f'{session}.jsonl'
        quotes = []
        frame, extraction = extractor.extract_features(path, symbol, session, quotes=quotes)
        extractor.write_features(frame, extraction, LIVE / 'features', quotes=quotes)
        raw_audit, raw = reference.previous.data.scan_book(path, collect_prices=True)
        assert datetime.fromisoformat(raw_audit['最後の約定時刻']) < cutoff
        tape_path = LIVE / 'features' / f'約定系列_{symbol}_{session}.npz'
        tape = dict(np.load(tape_path, allow_pickle=False))
        indices = tape['seq'].astype(int)
        tape['last'] = raw['last'][indices]
        tape['volume'] = raw['volume'][indices]
        tape['current_price'] = tape['last'].copy()
        np.savez_compressed(tape_path, **tape)
        depth, audit = depth_features.extract(path, symbol, session, frame)
        features[(session, symbol)] = depth
        input_audits.append(dict(銘柄=symbol, 原本=raw_audit, 抽出=extraction, 追加深度=audit))
    inputs = reference.previous.build_inputs([session], roots={session: (LIVE, LIVE / 'features')})
    (LIVE / 'inputs.pkl').write_bytes(pickle.dumps(inputs, pickle.HIGHEST_PROTOCOL))
    (LIVE / 'features_depth.pkl').write_bytes(pickle.dumps(features, pickle.HIGHEST_PROTOCOL))
    signals.ROOT = LIVE
    signals.clear_cache()
    results, saved = [], {}
    for item in frozen['最終候補']:
        directions = signals.build(item['signal'], inputs, features)
        for key, ready in inputs.items():
            config = managers.make_config(item['manager'], key[1], ready)
            replay = engine.run(ready, directions[key], config, detail=True)
            row = dict(手法ID=item['id'], 手法名=item['name'], セッション=session, 銘柄=key[1])
            row.update(partial_accounting(ready, replay, config))
            row['信号買い行数'] = int((directions[key] > 0).sum())
            row['信号売り行数'] = int((directions[key] < 0).sum())
            results.append(row)
            saved[(item['id'], key[1])] = dict(config=config, **replay)
    unchanged = {path: sha(ROOT / path) == expected for path, expected in frozen['ファイルSHA256'].items()}
    assert all(unchanged.values()), unchanged
    (LIVE / 'replay.pkl').write_bytes(pickle.dumps(saved, pickle.HIGHEST_PROTOCOL))
    output = dict(合格=True, 主候補=frozen['主候補'], セッション=session, 共通締切=record['共通締切'],
                  凍結時刻=frozen['凍結時刻'], セッション途中=True, 各URL取得回数=1, 状態取得回数=1, データ取得回数=6,
                  条件再選択なし=True, 凍結SHA256一致=unchanged, 原本監査=input_audits,
                  位置付け='凍結後に一回取得した途中スナップショット。場末へ架空価格を足さず、実現と含み損益を分離。未完成セッションを完了分合計へ加えない。',
                  結果=results)
    save(LIVE / 'current_result.json', output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['fetch', 'saved'])
    args = parser.parse_args()
    helper = load_module(ROOT / 'work/wave_v7/fetch_once.py', 'v23_current_fetch_helper')
    helper.LIVE = LIVE
    helper.FROZEN = LIVE / '現在照合の凍結記録.json'
    if args.mode == 'fetch':
        fetch_once(helper)
    result = evaluate_saved(helper)
    print(json.dumps(dict(合格=result['合格'], 共通締切=result['共通締切'], セッション=result['セッション'], 結果=result['結果']), ensure_ascii=False, indent=2))
