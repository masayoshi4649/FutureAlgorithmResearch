"""減量と復元に使う、既存公開方向と限定した窓診断の読取口。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent/'wave_v35'
SIGNALS = tuple(f'H{number:03d}' for number in (3, 11, 19, 27, 35, 43, 51, 59, 67, 75, 83, 91))
CONDITIONS = ('B00', 'B01', 'B02', 'B03', 'B06', 'B07', 'B08', 'B09')
_INPUTS: dict = {}
_ENTRIES: dict = {}
_CONDITIONS: dict = {}
_VALID: dict = {}


def initialize(inputs: dict | None = None) -> None:
    """機能: 既知入力の全体又は部分集合を設定し、読取キャッシュを初期化する。

    引数: inputs (dict|None)。返り値: なし (None)。先頭からの切断も許す。
    """
    global _INPUTS
    _INPUTS = inputs if inputs is not None else pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    assert 0 < len(_INPUTS) <= 26
    for key, ready in _INPUTS.items():
        assert key == (ready['session'], ready['symbol'])
        assert len(ready['seq']) == len(ready['time_s']) == len(ready['last'])
        assert np.all(np.diff(ready['seq']) > 0) and np.all(np.diff(ready['time_s']) >= 0)
    _ENTRIES.clear(); _CONDITIONS.clear(); _VALID.clear()


def entry_artifact(signal_id: str, clock_scale: float = 1.) -> Path:
    """機能: 許可された既存入口の保存先を一意に決める。

    引数: signal_id (str)、clock_scale (float)。返り値: 旧NPZのパス (Path)。
    """
    assert signal_id in SIGNALS
    assert clock_scale in ((.8, 1., 1.2) if signal_id == 'H019' else (1.,))
    return PRIOR/'entries'/f'{signal_id}__C{round(clock_scale*100):03d}.npz'


def condition_artifact(condition_id: str, window_scale: float = 1., evidence: bool = False) -> Path:
    """機能: 基準は旧保存物、B06窓変更だけは新保存物へ接続する。

    引数: condition_id (str)、window_scale (float)、evidence (bool)。返り値: 保存先 (Path)。
    """
    assert condition_id in CONDITIONS
    assert window_scale in ((.8, 1., 1.2) if condition_id == 'B06' else (1.,))
    folder = 'evidence' if evidence else 'deterioration'
    if window_scale == 1.:
        return PRIOR/folder/(condition_id+'.npz')
    return HERE/folder/f'{condition_id}__W{round(window_scale*100):03d}.npz'


def entry(signal_id: str, clock_scale: float, key: tuple) -> np.ndarray:
    """機能: 旧入口方向を原本行対応のまま返す。

    引数: signal_id (str)、clock_scale (float)、key (tuple[str,str])。
    返り値: 読取専用の方向 (ndarray[int8])。旧条件を再計算しない。
    """
    path = entry_artifact(signal_id, clock_scale)
    if path not in _ENTRIES:
        with np.load(path, allow_pickle=False) as archive:
            _ENTRIES[path] = {name: archive[name] for name in archive.files}
        for values in _ENTRIES[path].values(): values.flags.writeable = False
    values = _ENTRIES[path]['|'.join(key)]
    n = len(_INPUTS[key]['seq'])
    assert values.dtype == np.int8 and len(values) >= n and np.isin(values, (-1, 0, 1)).all()
    return values[:n]


def condition(condition_id: str, key: tuple, window_scale: float = 1.) -> tuple:
    """機能: 市場方向・公開元ready行・証拠イベント位置を返す。

    引数: condition_id (str)、key (tuple[str,str])、window_scale (float)。
    返り値: (direction:int8列, source_row:int64列, event_index:int32列)。
    source_rowはrawseqではなくready配列の行番号。中立でも公開元がある場合は保持する。
    """
    path = condition_artifact(condition_id, window_scale)
    if path not in _CONDITIONS:
        with np.load(path, allow_pickle=False) as archive:
            _CONDITIONS[path] = {name: archive[name] for name in archive.files}
        for values in _CONDITIONS[path].values(): values.flags.writeable = False
    label, n = '|'.join(key), len(_INPUTS[key]['seq'])
    values = tuple(_CONDITIONS[path][prefix+label][:n] for prefix in ('direction::', 'source_row::', 'event_index::'))
    assert all(len(value) == n for value in values)
    assert [value.dtype for value in values] == [np.dtype('int8'), np.dtype('int64'), np.dtype('int32')]
    direction, source, event = values
    assert np.isin(direction, (-1, 0, 1)).all() and (source <= np.arange(n)).all()
    assert ((source < 0) == (event < 0)).all() and (source[direction != 0] >= 0).all()
    return values


def publication_valid(condition_id: str, key: tuple, window_scale: float = 1.) -> np.ndarray:
    """機能: 新しい公開行を時計復元に使用できるかを方向と別に返す。

    引数: condition_id (str)、key (tuple[str,str])、window_scale (float)。
    返り値: 読取専用の自市場窓品質 (ndarray[bool])。方向0は可、peer同意は不要。
    自市場の価格/ATR・過去窓・欠測品質が有効で、公開後60秒以内の行だけTrue。
    """
    path = condition_artifact(condition_id, window_scale, evidence=True)
    label = '|'.join(key)
    if (path, key) not in _VALID:
        with np.load(path, allow_pickle=False) as archive:
            _VALID[path, key] = archive[label+'::valid'].astype(bool)
    _, _, indices = condition(condition_id, key, window_scale)
    output = np.zeros(len(indices), bool)
    present = indices >= 0
    output[present] = _VALID[path, key][indices[present]]
    output.flags.writeable = False
    return output


def randomize_recovery(direction: np.ndarray, source_row: np.ndarray, ready: dict,
                       key: tuple, seed: int) -> np.ndarray:
    """機能: B06の非0公開機会を保ち、公開元rawseq別の固定符号を元方向へ掛ける。

    引数: direction (ndarray[int8])、source_row (ndarray[int64])、ready (dict)、
    key (tuple[str,str])、seed (int、0〜63)。返り値: 読取専用乱数方向 (ndarray[int8])。
    同じ公開元の持続中は引き直さず、配列長や最後のイベント数を乱数種に使わない。
    """
    assert isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed <= 63
    assert direction.dtype == np.int8 and source_row.dtype == np.int64
    assert len(direction) == len(source_row) == len(ready['seq'])
    assert np.isin(direction, (-1, 0, 1)).all()
    present = direction != 0
    assert (source_row[present] >= 0).all() and (source_row <= np.arange(len(source_row))).all()
    output = direction.copy()
    sources, inverse = np.unique(source_row[present], return_inverse=True)
    factors = []
    for row in sources:
        rawseq = int(ready['seq'][int(row)])
        payload = f'v37|{seed}|{key[0]}|{key[1]}|{rawseq}'.encode('utf-8')
        bit = int.from_bytes(hashlib.sha256(payload).digest()[:8], 'little') & 1
        factors.append(1 if bit == 0 else -1)
    output[present] *= np.asarray(factors, np.int8)[inverse]
    assert np.array_equal(output == 0, direction == 0)
    output.flags.writeable = False
    return output


def recovery(condition_id: str, key: tuple, window_scale: float = 1.,
             random_seed: int | None = None) -> tuple:
    """機能: 悪化とは独立した回復入力を、同じ公開行契約で返す。

    引数: condition_id (str)、key (tuple[str,str])、window_scale (float)、random_seed (int|None)。
    返り値: direction/source_row/event_indexの3列 (tuple)。乱数は基準B06回復だけ許す。
    """
    direction, source, event = condition(condition_id, key, window_scale)
    if random_seed is not None:
        assert condition_id == 'B06' and window_scale == 1.
        direction = randomize_recovery(direction, source, _INPUTS[key], key, random_seed)
    return direction, source, event
