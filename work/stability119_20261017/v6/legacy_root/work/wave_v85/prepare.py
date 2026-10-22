"""原E01の旧28場素材を保持し、残る2場を元の因果生成器で準備する。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import gc
import hashlib
import importlib.util
import json
import os
import pickle
import socket
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'prepared'
OLD = ROOT / 'work/wave_v67'
ADDED = ('2026-10-09_Day', '2026-10-09_Night')
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')


def sha(path):
    """
    機能: 読取対象の内容を分割して指紋化する。
    引数: path (Path) は元資料又は今回の出力。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(part)
    return value.hexdigest()


def read(path):
    """
    機能: 保存済みJSONを読む。
    引数: path (Path)。
    返り値: dict 又は list の内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    """
    機能: 今回の準備領域に限って日本語JSONを保存する。
    引数: path (Path)、value (dict)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def check_mapping(expected):
    """
    機能: 原本又は旧キャッシュの完全な指紋一致を並列確認する。
    引数: expected (dict[str,str]) はプロジェクト相対パスと既知指紋。
    返り値: dict[str,str] の今回確認した指紋。
    """
    names = sorted(expected)
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = dict(zip(names, pool.map(sha, [ROOT / name for name in names])))
    assert actual == expected, [n for n in names if actual[n] != expected[n]]
    return actual


def old_paths():
    """
    機能: 旧28場の入力・信号を複製せず参照する。
    引数: なし。
    返り値: list[dict] の入力・信号ファイル対応。
    """
    return [dict(inputs=str((p / 'new_inputs.pkl').relative_to(ROOT)),
                 signals=str((p / 'signals.pkl').relative_to(ROOT)))
            for p in sorted((OLD / 'prepared').iterdir()) if (p / 'signals.pkl').exists()]


def load_inputs(verify=True):
    """
    機能: 完了済み全30場の元E01素材を参照から組み立てる。
    引数: verify (bool) は固定指紋の再照合要否。
    返り値: tuple[dict,dict,dict] の入力・信号・参照指紋。
    """
    proof = read(OUT / '入力準備の完了.json')
    expected = proof['使用入力SHA256']
    if verify:
        check_mapping(expected)
    inputs, signals = {}, {name: {} for name in ('entry', 'B00', 'B01')}
    for pair in proof['入力対応']:
        with (ROOT / pair['inputs']).open('rb') as stream:
            more = pickle.load(stream)
        assert not set(inputs) & set(more)
        inputs.update(more)
        with (ROOT / pair['signals']).open('rb') as stream:
            more_signals = pickle.load(stream)
        for code in signals:
            signals[code].update(more_signals[code])
    assert len(inputs) == 60 and sorted({k[0] for k in inputs}) == proof['全30']
    for mapping in signals.values():
        assert set(mapping) == set(inputs)
    return inputs, signals, expected


def prepare():
    """
    機能: 追加2場を旧抽出・信号生成・未来切断監査で準備する。
    引数: なし。
    返り値: dict の完了証拠。売買・損益の計算は行わない。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / '入力準備の完了.json').exists(), '完成済み素材は上書きしません'
    sessions = sorted(p.stem for p in (ROOT / 'book/NK225').glob('*.jsonl'))
    assert sessions == sorted(p.stem for p in (ROOT / 'book/TOPIX').glob('*.jsonl'))
    original = read(OLD / '事前固定.json')
    assert sessions == original['全セッション'] + list(ADDED) and len(sessions) == 30
    proof83 = read(ROOT / 'work/wave_v83/prepared/価格入力の照合.json')
    raw = {f"book/{r['symbol']}/{r['session']}.jsonl": r['原本SHA256'] for r in proof83['各口座']}
    old_candles = {str(Path(n)): h for n, h in original['原本SHA256'].items()}
    cache = {str((OLD / name).relative_to(ROOT)): h for name, h in read(OLD / '入力指紋.json').items()}
    print('全60原本・旧28場の足・旧入力指紋を確認', flush=True)
    verified = check_mapping(raw | old_candles | cache)
    new_candles = {str(p.relative_to(ROOT)): sha(p) for folder in ('candle_1min', 'candle_5min')
                   for symbol in ('TOPIX', 'NK225') for session in ADDED
                   for p in [ROOT / folder / symbol / (session + '.csv')]}
    # ----------------------------------------
    source = ROOT / 'work/wave_v50/update_20261001_day/replay_added_session.py'
    spec = importlib.util.spec_from_file_location('元E01追加入力85', source)
    app = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = app
    spec.loader.exec_module(app)
    previous = app.previous
    socket.socket.connect = previous.deny
    socket.create_connection = previous.deny
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    sources = {Path(m.__file__).resolve() for m in tuple(sys.modules.values()) if getattr(m, '__file__', None)
               and Path(m.__file__).suffix == '.py' and Path(m.__file__).resolve().is_relative_to(ROOT / 'work')}
    source_hash = {str(p.relative_to(ROOT)): sha(p) for p in sorted(sources)}
    old_generator = read(OLD / 'prepared/抽出前固定.json')['既存実装SHA256']
    shared = {name: value for name, value in old_generator.items() if name in source_hash}
    assert shared and all(source_hash[name] == value for name, value in shared.items())
    price_path = ROOT / 'work/wave_v83/prepared/inputs.pkl'
    assert sha(price_path) == proof83['出力SHA256']
    with price_path.open('rb') as stream:
        prices = pickle.load(stream)
    save(OUT / '入力準備の事前固定.json', dict(全30=sessions, 追加2=list(ADDED), 前16=sessions[:16], 後14=sessions[16:],
        元28入力再利用=True, 既存抽出器共有一致数=len(shared), 実装SHA256=source_hash,
        照合済原本入力SHA256=verified, 追加足SHA256=new_candles,
        旧価格キャッシュSHA256=proof83['出力SHA256'], 損益計算=False, API追加取得=0, 実注文=0))
    records = []
    pairs = old_paths()
    for session in ADDED:
        target = OUT / session
        target.mkdir(parents=True, exist_ok=True)
        assert not (target / 'signals.pkl').exists(), '完成済み追加信号は上書きしません'
        previous.HERE = target
        app.HERE = target
        print(session, '元E01抽出器を実行', flush=True)
        inputs, features = previous.extract(session)
        signals = previous.signal_audit(inputs, features)
        with (target / 'signals.pkl').open('wb') as stream:
            pickle.dump(signals, stream, protocol=5)
        for key, r in inputs.items():
            p = prices[key]
            for name in ('seq', 'time_s'):
                np.testing.assert_array_equal(r[name], p[name])
            np.testing.assert_array_equal(r['last'], p['price'])
            with np.load(target / 'features' / f'約定系列_{key[1]}_{session}.npz') as tape:
                for name in ('bid', 'ask'):
                    np.testing.assert_array_equal(tape[name], p[name])
            n = len(r['last'])
            assert np.all(np.diff(r['seq']) > 0) and np.all(np.diff(r['time_s']) >= 0)
            assert r['time_s'][-1] > r['limit']
            assert len(signals['entry'][key]) == n
            for code in ('B00', 'B01'):
                observed = signals[code][key]['source_row']
                valid = observed >= 0
                assert np.all(observed[valid] <= np.flatnonzero(valid))
            records.append(dict(session=key[0], symbol=key[1], 行数=n, 旧83価格全配列一致=True,
                原本連番単調=True, 時計非減少=True, 途中判断未来元行なし=True,
                未来切断監査=read(target / '信号監査.json')['全合格'],
                場開始=float(r['start']), 返済期限=float(r['limit']), 最終観測=float(r['time_s'][-1])))
        pair = dict(inputs=str((target / 'new_inputs.pkl').relative_to(ROOT)),
                    signals=str((target / 'signals.pkl').relative_to(ROOT)))
        pairs.append(pair)
        save(target / '抽出完了.json', dict(全合格=True, 対象=session, 口座別=records[-2:],
            出力SHA256={name: sha(ROOT / name) for name in pair.values()}, 損益計算=False))
        del inputs, features, signals
        gc.collect()
    # ----------------------------------------
    check_mapping(new_candles)
    check_mapping(source_hash)
    hashes = {name: sha(ROOT / name) for pair in pairs for name in pair.values()}
    result = dict(全合格=True, 全30=sessions, 前16=sessions[:16], 後14=sessions[16:], 入力対応=pairs,
        使用入力SHA256=hashes, 追加口座照合=records, 全原本不変確認数=len(raw), 旧足不変確認数=len(old_candles),
        追加足準備前後一致数=len(new_candles), 既存抽出コード不変=True,
        原E01発注時計='前行までに置いた条件を次の保存観測行以降で発動する。固定の追加時間遅延は0秒。真の受信時計とは区別する。',
        原E01約定='指定線と観測CurrentPriceは別々の全再運転。bid/askの固定注文置換は本比較と混ぜない。',
        損益計算=False, API追加取得=0, 実注文=0)
    save(OUT / '入力準備の完了.json', result)
    print('原E01全30場の入力準備と追加4口座因果照合が完了', flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='元E01入力のみを準備する')
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    if args.build:
        prepare()
    else:
        inputs, signals, hashes = load_inputs()
        print(f'入力{len(inputs)}口座・信号{len(signals)}種類・指紋{len(hashes)}件')
