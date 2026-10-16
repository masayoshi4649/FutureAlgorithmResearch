"""保存済み原板と厳密な過去の二市場格子を読取専用で接続する。"""

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ('TOPIX', 'NK225')


def digest(path):
    """
    機能: 保存資料の指紋を分割読取で求める。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    """
    機能: 損益を含まない保存素材だけを読む。
    引数: path (Path)。
    返り値: object はpickle又はJSON内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def immutable(value):
    """
    機能: 入力配列の意図しない書換えを禁止する。
    引数: value (object) は配列、辞書又は列。
    返り値: None。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            immutable(child)


def load_inputs(verify=True):
    """
    機能: 60口座の価格、30場の二市場格子、旧J2入口と原板品質を接続する。
    引数: verify (bool) は旧保存指紋と源行対応の照合要否。
    返り値: dict はprices/grids/legacy/entries/features/metadata/paths。
    損益結果、将来ラベル、現在APIは読み込まない。
    """
    meta_path = ROOT / 'work/wave_v77/inputs/metadata.json'
    metadata = read(meta_path)
    paths = [meta_path, ROOT / 'work/wave_v83/prepared/inputs.pkl',
             ROOT / 'work/wave_v77/inputs/grids_delay1.pkl',
             ROOT / 'work/wave_v77/prepared/legacy_delay1.pkl',
             ROOT / 'work/wave_v77/prepared/signals_delay1.pkl']
    prices, grids, legacy, entries = (read(path) for path in paths[1:])
    features = {}
    for relative in (*metadata['input_paths']['features'], 'work/wave_v77/inputs/extra_features.pkl'):
        path = ROOT / relative
        paths.append(path)
        source = read(path)
        for key, record in source.items():
            assert key not in features
            prices_record = prices[key]
            assert np.array_equal(record['seq'], prices_record['seq'])
            assert np.array_equal(record['time_s'], prices_record['time_s'])
            assert np.array_equal(record['bid'], prices_record['bid'])
            assert np.array_equal(record['ask'], prices_record['ask'])
            quality = (record['valid'] & (record['bid'] > 0) & (record['ask'] > record['bid'])
                       & (record['ask'] - record['bid'] <= 2 * prices_record['tick'] + 1e-9))
            features[key] = dict(quality=np.asarray(quality, dtype=bool), reset=np.asarray(record['reset'], dtype=bool))
        del source
    assert len(prices) == len(features) == len(legacy) == 60
    assert set(grids) == set(entries) == set(metadata['sessions'])
    assert set(prices) == {(session, symbol) for session in grids for symbol in SYMBOLS}
    if verify:
        proof = read(ROOT / 'work/wave_v83/prepared/価格入力の照合.json')
        assert digest(paths[1]) == proof['出力SHA256']
        for session, source in grids.items():
            grid = source['grid']
            assert np.array_equal(grid, entries[session]['grid'])
            for symbol in SYMBOLS:
                market = source['markets'][symbol]
                index = market['current']['index']
                good = index >= 0
                record = prices[(session, symbol)]
                assert (record['time_s'][index[good]] < grid[good] - 1.0).all()
                for name, raw_name in (('last', 'price'), ('bid', 'bid'), ('ask', 'ask')):
                    actual = market['current'][name][good]
                    expected = record[raw_name][index[good]]
                    assert np.allclose(actual, expected, rtol=0, atol=0, equal_nan=True)
    answer = dict(prices=prices, grids=grids, legacy=legacy, entries=entries,
                  features=features, metadata=metadata, paths=paths)
    immutable(answer)
    return answer
