"""旧入口部品の再生成と、管理比較用パルスの独立照合を行う。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import numba

import prepare


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def module(name: str, path: Path) -> object:
    """機能: 旧入口実装を固有名で読み、旧ファイルは変更しない。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def clip(ready: dict, count: int) -> dict:
    """機能: 入力の原本行列を途中で切断する。

    引数: ready(dict)、count(int)。返り値: 切断入力(dict)。
    """
    n = len(ready['seq'])
    return {k: v[:count].copy() if isinstance(v, np.ndarray) and v.ndim and len(v) == n else v
            for k, v in ready.items()}


def main() -> None:
    """機能: 全56入口を旧生成器で再生成し、中間切断・R01指標一致を検査する。

    引数: なし。返り値: なし(None)。注文と損益は参照しない。
    """
    sys.dont_write_bytecode = True
    socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('通信は禁止されています'))
    socket.create_connection = socket.socket.connect
    numba.config.CACHE_DIR = str(HERE / 'numba_cache')
    entry = module('管理67旧入口部品', ROOT / 'work/wave_v47/component_signals.py')
    # ----------------------------------------
    # R01指標は旧生成器と独立接続器を突き合わせる。台帳を読む関数は呼ばない。
    gate = module('管理67旧EMA確認', ROOT / 'work/wave_v49/gates/gate_replay.py')
    numba.config.CACHE_DIR = str(HERE / 'numba_cache')
    entry.set_root(ROOT)
    inputs = pickle.loads(prepare.OLD_INPUTS.read_bytes())
    levels = pickle.loads((HERE / 'levels.pkl').read_bytes())
    signals = pickle.loads((HERE / 'signals.pkl').read_bytes())
    features, source_hashes = {}, {}
    for folder in sorted((ROOT / 'work/wave_v67/prepared').iterdir()):
        source = folder / 'new_features_depth.pkl'
        if source.exists():
            frames = pickle.loads(source.read_bytes())
            assert not set(features) & set(frames)
            features.update(frames)
            source_hashes[str(source.relative_to(ROOT)).replace('\\', '/')] = prepare.digest(source)
    assert set(features) == set(inputs)
    records = []
    for session in sorted({k[0] for k in inputs}):
        keys = [(session, symbol) for symbol in ('TOPIX', 'NK225')]
        own_inputs = {k: inputs[k] for k in keys}
        frames = {k: features[k] for k in keys}
        full = entry.build(entry.specification(), own_inputs, frames)
        models = {k: gate.model(own_inputs[k]) for k in keys}
        counts = {k: len(inputs[k]['seq']) // 2 for k in keys}
        clipped = {k: clip(inputs[k], counts[k]) for k in keys}
        shortframes = {k: frames[k].loc[(frames[k].seq <= clipped[k]['seq'][-1]) &
                                      (frames[k].time_s <= clipped[k]['time_s'][-1])].copy() for k in keys}
        short = entry.build(entry.specification(), clipped, shortframes)
        for k in keys:
            np.testing.assert_array_equal(full[k], levels[k][0])
            np.testing.assert_array_equal(short[k], levels[k][0, :counts[k]])
            a, b = gate.expanded(k, models, inputs[k]['time_s'])
            mask = gate.gate_mask(dict(kind='rearm'), full[k], a, b)
            original = np.where(mask, full[k], 0).astype(np.int8)
            np.testing.assert_array_equal(original, levels[k][1])
            np.testing.assert_array_equal(prepare.pulse(full[k]), signals[k][4])
            np.testing.assert_array_equal(prepare.pulse(original), signals[k][5])
            records.append(dict(session=k[0], symbol=k[1], E01全長再生成一致=True,
                E01原素材切断一致=True, R01旧指標一致=True, 新パルス一致=True))
        entry.clear_cache()
        print(session, '旧入口再生成・切断・R01照合合格', flush=True)
    prepare.save('旧入口部品の再生成検査.json', dict(全合格=True, 口座数=56, 検査=records,
        原素材SHA256=source_hashes, 検査実装SHA256=prepare.digest(Path(__file__)),
        API取得数=0, 旧取引台帳参照=False, 損益参照=False))


if __name__ == '__main__':
    main()
