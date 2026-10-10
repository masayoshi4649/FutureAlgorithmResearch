"""事前生成された入口・市場悪化列を読み、無関係方向対照だけを機械的に作る。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
_INPUTS: dict = {}
_ENTRIES: dict = {}
_CONDITIONS: dict = {}


def initialize(inputs: dict | None = None) -> None:
    """機能: 既知入力を設定して配列キャッシュを初期化する。

    引数: inputs (dict|None) は既に読み込んだ固定原本入力。返り値: なし (None)。
    """
    global _INPUTS
    _INPUTS = inputs if inputs is not None else pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    assert 0 < len(_INPUTS) <= 26
    _ENTRIES.clear(); _CONDITIONS.clear()


def entry(signal_id: str, entry_clock_scale: float, key: tuple) -> np.ndarray:
    """機能: 同じ旧入口の時計0.8/1/1.2だけを変更した保存列を返す。

    引数: signal_id (str)、entry_clock_scale (float)、key (tuple[str,str])。
    返り値: 原本行対応の入口方向 (ndarray[int8])。返された列は変更しないこと。
    """
    assert entry_clock_scale in (.8, 1., 1.2)
    label = f'{signal_id}__C{round(entry_clock_scale * 100):03d}'
    if label not in _ENTRIES:
        with np.load(HERE / 'entries' / (label + '.npz')) as archive:
            _ENTRIES[label] = {tuple(name.split('|')): archive[name] for name in archive.files}
    values = _ENTRIES[label][key]
    assert values.dtype == np.int8 and len(values) == len(_INPUTS[key]['last'])
    return values


def randomize_direction(values: np.ndarray, ready: dict, seed: int) -> np.ndarray:
    """機能: 非中立の時間帯を保ち、セッション共通30分ブロックで方向だけを反転する。

    引数: values (ndarray[int8])、ready (dict)、seed (int)。返り値: 無関係方向列 (ndarray[int8])。
    同じ符号反転でも、保有と逆になる回数・実際の追跡短縮回数まで一致する保証はない。
    """
    assert isinstance(seed, int) and 0 <= seed <= 63
    blocks = np.floor((ready['time_s'] - ready['start']) / 1800.).astype(np.int64)
    signs = {}
    for block in np.unique(blocks):
        raw = f'v35|{seed}|{ready["session"]}|{int(block)}'.encode('utf-8')
        bit = int.from_bytes(hashlib.sha256(raw).digest()[:8], 'little') & 1
        signs[int(block)] = 1 if bit == 0 else -1
    factor = np.array([signs[int(block)] for block in blocks], dtype=np.int8)
    output = values * factor
    assert np.array_equal(values == 0, output == 0)
    return output


def deterioration(condition_id: str | None, key: tuple, random_seed: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """機能: 市場方向と最新自市場解放行を読み、必要な場合だけ方向対照を適用する。

    引数: condition_id (str|None)、key (tuple[str,str])、random_seed (int|None)。
    返り値: 方向と解放原本行 (tuple[ndarray[int8],ndarray[int64]])。Noneは固定/常時最小幅用の中立列。
    """
    ready = _INPUTS[key]
    if condition_id is None:
        return np.zeros(len(ready['last']), np.int8), np.full(len(ready['last']), -1, np.int64)
    if condition_id not in _CONDITIONS:
        with np.load(HERE / 'deterioration' / (condition_id + '.npz')) as archive:
            _CONDITIONS[condition_id] = {name: archive[name] for name in archive.files if not name.startswith('event_index::')}
    name = '|'.join(key)
    values = _CONDITIONS[condition_id]['direction::' + name]
    rows = _CONDITIONS[condition_id]['source_row::' + name]
    assert values.dtype == np.int8 and rows.dtype == np.int64 and len(values) == len(rows) == len(ready['last'])
    if random_seed is not None:
        values = randomize_direction(values, ready, random_seed)
    return values, rows
