"""短い減量根拠と長い復元分岐を、公開元を保つ固定列として提供する。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent/'wave_v37'))
import partial_inputs as prior

SIGNALS = prior.SIGNALS
CONDITIONS = ('B00', 'B01', 'B06', 'B07')
SCALES = (.8, 1., 1.2)
_INPUTS, _COLUMNS, _QUALITY = {}, {}, {}


def initialize(inputs: dict | None = None) -> None:
    """機能: 全体又は先頭部分の原本入力を設定し、読み取りキャッシュを空にする。

    引数: inputs (dict|None)。返り値: なし (None)。通信と原本書込みは行わない。
    """
    global _INPUTS
    _INPUTS = inputs if inputs is not None else pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    prior.initialize(_INPUTS)
    _COLUMNS.clear(); _QUALITY.clear()


def entry_artifact(signal_id: str, clock_scale: float = 1.) -> Path:
    """機能: 既監査14入口の保存先を返す。

    引数: signal_id (str)、clock_scale (float)。返り値: 旧保存先 (Path)。
    """
    return prior.entry_artifact(signal_id, clock_scale)


def entry(signal_id: str, clock_scale: float, key: tuple) -> np.ndarray:
    """機能: 入口を旧保存列のまま読み取る。

    引数: signal_id (str)、clock_scale (float)、key (tuple[str,str])。返り値: 読取専用方向 (ndarray[int8])。
    """
    return prior.entry(signal_id, clock_scale, key)


def condition_artifact(condition_id: str, window_scale: float = 1., evidence: bool = False) -> Path:
    """機能: 基準4条件とB06診断は再利用し、新規6窓だけ今回の保存先へ結ぶ。

    引数: condition_id (str)、window_scale (float)、evidence (bool)。返り値: NPZ保存先 (Path)。
    """
    assert condition_id in CONDITIONS and window_scale in SCALES
    if window_scale == 1. or condition_id == 'B06':
        return prior.condition_artifact(condition_id, window_scale, evidence)
    folder = 'evidence' if evidence else 'deterioration'
    return HERE/folder/f'{condition_id}__W{round(window_scale*100):03d}.npz'


def condition(condition_id: str, key: tuple, window_scale: float = 1.) -> tuple:
    """機能: 観測方向・公開元ready行・証拠位置を原本行ごとに返す。

    引数: condition_id (str)、key (tuple[str,str])、window_scale (float)。
    返り値: direction:int8、source_row:int64、event_index:int32の3列 (tuple)。
    source_rowはrawseqではない。方向0でも公開元があれば保持し、未公開/鮮度切れは-1。
    """
    path = condition_artifact(condition_id, window_scale)
    if path not in _COLUMNS:
        with np.load(path, allow_pickle=False) as archive:
            _COLUMNS[path] = {name: archive[name] for name in archive.files}
        for value in _COLUMNS[path].values(): value.flags.writeable = False
    label, n = '|'.join(key), len(_INPUTS[key]['seq'])
    values = tuple(_COLUMNS[path][kind+'::'+label][:n] for kind in ('direction','source_row','event_index'))
    assert all(len(v) == n for v in values)
    assert tuple(v.dtype for v in values) == (np.dtype('int8'),np.dtype('int64'),np.dtype('int32'))
    direction, source, event = values
    assert np.isin(direction, (-1,0,1)).all() and (source <= np.arange(n)).all()
    assert ((source < 0) == (event < 0)).all() and (source[direction != 0] >= 0).all()
    return values


def publication_valid(condition_id: str, key: tuple, window_scale: float = 1.) -> np.ndarray:
    """機能: 有効な中立と欠測を区別する自市場公開品質を返す。

    引数: condition_id (str)、key (tuple[str,str])、window_scale (float)。返り値: 品質 (ndarray[bool])。
    自市場の価格/ATR/過去窓が有効かつ公開60秒以内。direction=0でもTrueになり、peer同意は不要。
    """
    path = condition_artifact(condition_id, window_scale, True)
    if (path,key) not in _QUALITY:
        with np.load(path, allow_pickle=False) as archive:
            _QUALITY[path,key] = archive['|'.join(key)+'::valid'].astype(bool)
    _, _, events = condition(condition_id, key, window_scale)
    output = np.zeros(len(events), bool); valid = events >= 0
    output[valid] = _QUALITY[path,key][events[valid]]
    output.flags.writeable = False
    return output


def source_bits(source_row: np.ndarray, ready: dict, key: tuple, seed: int, role: str) -> np.ndarray:
    """機能: 同じ公開元・役割へ同じ固定乱数を割り当てる。

    引数: source_row (ndarray[int64])、ready (dict)、key (tuple[str,str])、seed (int,0..63)、role (str)。
    返り値: 先頭8byte little bit0の列 (ndarray[int8])。欠測公開元のrawseqは-1として保持する。
    条件IDや将来配列長を種へ入れない。銘柄間・役割間の元の依存は保持しない。
    """
    assert isinstance(seed,int) and not isinstance(seed,bool) and 0 <= seed < 64
    assert role in ('bad','good','branch')
    assert source_row.dtype == np.int64 and len(source_row) == len(ready['seq'])
    assert np.all(source_row >= -1) and np.all(source_row <= np.arange(len(source_row)))
    sources, inverse = np.unique(source_row, return_inverse=True)
    bits = np.zeros(len(sources), np.int8)
    for index, source in enumerate(sources):
        rawseq = int(ready['seq'][int(source)]) if source >= 0 else -1
        payload = f'v38|{role}|{seed}|{key[0]}|{key[1]}|{rawseq}'.encode('utf-8')
        bits[index] = int.from_bytes(hashlib.sha256(payload).digest()[:8], 'little') & 1
    return bits[inverse]


def random_direction(direction: np.ndarray, source_row: np.ndarray, ready: dict,
                     key: tuple, seed: int, role: str) -> np.ndarray:
    """機能: 元の非0公開機会を保ち、減量又は回復の方向へ固定符号を掛ける。

    引数: direction/source_row (ndarray)、ready (dict)、key (tuple)、seed (int)、role (str,bad/good)。
    返り値: 読取専用の置換方向 (ndarray[int8])。価格・公開品質・公開元を変更しない。
    """
    assert role in ('bad','good') and direction.dtype == np.int8
    assert len(direction) == len(source_row) and np.isin(direction, (-1,0,1)).all()
    assert (source_row[direction != 0] >= 0).all()
    bits = source_bits(source_row, ready, key, seed, role)
    output = direction * (1 - 2*bits)
    assert output.dtype == np.int8 and np.array_equal(output == 0, direction == 0)
    output.flags.writeable = False
    return output


def directions(condition_id: str, key: tuple, window_scale: float = 1.,
               seed: int | None = None, role: str = 'bad') -> tuple:
    """機能: 方針ごとの窓と任意の役割別方向対照を原本列へ接続する。

    引数: condition_id (str)、key (tuple)、window_scale (float)、seed (int|None)、role (str)。
    返り値: 方向・公開元ready行・イベント位置の3列 (tuple)。
    """
    direction, source, event = condition(condition_id, key, window_scale)
    if seed is not None:
        direction = random_direction(direction, source, _INPUTS[key], key, seed, role)
    return direction, source, event


def branch_choice(key: tuple, seed: int, window_scale: float = 1.) -> np.ndarray:
    """機能: B01の公開元単位で時計/信号の固定選択を生成する。

    引数: key (tuple[str,str])、seed (int)、window_scale (float)。返り値: 0時計/1信号 (ndarray[int8])。
    使用するのは減量約定行の1値だけ。方向反射で選択は不変。branch_validを真へ偽装しない。
    """
    _, source, _ = condition('B01', key, window_scale)
    output = source_bits(source, _INPUTS[key], key, seed, 'branch')
    output.flags.writeable = False
    return output
