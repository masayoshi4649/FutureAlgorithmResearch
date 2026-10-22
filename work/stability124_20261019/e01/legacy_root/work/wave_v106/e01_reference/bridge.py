"""旧E01の数値実装を読み、保存先とJITだけを106へ隔離する。"""

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import socket
import sys

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CACHE = str(HERE / 'jit')
sys.dont_write_bytecode = True
SESSIONS_EXTRA = ('2026-10-12_Day', '2026-10-12_Night', '2026-10-13_Day')


def digest(path: Path) -> str:
    """
    機能: 保存内容のSHA256を読む。
    引数: path(Path)は既存ファイル。
    返り値: str。原本を変更しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> object:
    """
    機能: 保存済みJSON又はpickleを読む。
    引数: path(Path)は読取対象。
    返り値: object。金融再生を伴わない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix == '.pkl' else json.load(stream)


def save(path: Path, value: object) -> None:
    """
    機能: 所有範囲へ新規JSONを保存する。
    引数: path(Path)、value(object)は保存先と内容。
    返り値: None。既存成果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


class CacheConfig:
    """旧モジュールのJIT保存先変更を106へ固定する設定代理。"""

    def __init__(self, original: object) -> None:
        """
        機能: 通常Numba設定を保持する。
        引数: original(object)は元設定。
        返り値: None。
        """
        object.__setattr__(self, 'original', original)

    def __getattr__(self, name: str) -> object:
        """
        機能: JIT保存先だけを所有域へ固定する。
        引数: name(str)は設定名。
        返り値: object。その他の値は元設定。
        """
        return CACHE if name == 'CACHE_DIR' else getattr(self.original, name)

    def __setattr__(self, name: str, value: object) -> None:
        """
        機能: 旧sourceからのJIT設定変更を隔離する。
        引数: name(str)、value(object)は変更要求。
        返り値: None。
        """
        setattr(self.original, name, CACHE if name == 'CACHE_DIR' else value)


@contextmanager
def owned_cache() -> object:
    """
    機能: importと実行中の全JIT保存を106へ限定する。
    引数: なし。
    返り値: contextmanager。終了時は元設定を復元。
    """
    original, old_dir = numba.config, numba.config.CACHE_DIR
    previous = os.environ.get('NUMBA_CACHE_DIR')
    original.CACHE_DIR = CACHE
    numba.config = CacheConfig(original)
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    try:
        yield
    finally:
        numba.config = original
        original.CACHE_DIR = old_dir
        if previous is None:
            os.environ.pop('NUMBA_CACHE_DIR', None)
        else:
            os.environ['NUMBA_CACHE_DIR'] = previous


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 本比較からのネットワーク接続を禁止する。
    引数: args(tuple)、kwargs(dict)は接続要求。
    返り値: None。例外を送出する。
    """
    raise RuntimeError('保存原本によるE01比較からの通信は禁止')


def module(name: str, relative: str) -> object:
    """
    機能: 固有名で読取sourceを接続する。
    引数: name/relative(str)は識別名と根相対位置。
    返り値: object。旧mainを実行しない。
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


def runtime() -> dict:
    """
    機能: 同じ元GU・注文feed・料金部品を読み取り接続する。
    引数: なし。
    返り値: dict。金融実行は別段階。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    # ----------------------------------------
    # 旧依存名study/replayが他研究と衝突しない専用プロセスで使用する。
    strategy = module('106の読取L_D20戦略', 'work/wave_v87/round12/strategy.py')
    prepare = module('106の旧30入力接続', 'work/wave_v85/prepare.py')
    extractor = module('106の追加E01素材抽出', 'work/wave_v48/update_20261001/replay_added_session.py')
    return dict(strategy=strategy, old=strategy.old, prior=strategy.prior,
                prepare=prepare, extractor=extractor)


def source_hashes() -> dict:
    """
    機能: 接続済み数値sourceと自身の指紋を保持する。
    引数: なし。
    返り値: dict[str,str]。巨大原本の再hashはしない。
    """
    paths = {Path(value.__file__).resolve() for value in tuple(sys.modules.values())
             if getattr(value, '__file__', None) and Path(value.__file__).suffix == '.py'
             and Path(value.__file__).resolve().is_relative_to(ROOT / 'work')}
    paths.update(HERE.glob('*.py'))
    return {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in sorted(paths)}


def load_inputs(rt: dict) -> tuple[dict, dict, dict]:
    """
    機能: 旧30を再利用し、生成済み追加3場と同一仕様で接続する。
    引数: rt(dict)は隔離済みruntime。
    返り値: tuple[dict,dict,dict]。E01入力・3信号・入力指紋。
    """
    inputs, signals, hashes = rt['prepare'].load_inputs(verify=True)
    for session in SESSIONS_EXTRA:
        folder = HERE / 'prepared' / session
        extra, added = read(folder / 'new_inputs.pkl'), read(folder / 'signals.pkl')
        assert not set(inputs) & set(extra)
        inputs.update(extra)
        for key in signals:
            assert key in added and not set(signals[key]) & set(added[key])
            signals[key].update(added[key])
        for name in ('new_inputs.pkl', 'signals.pkl'):
            path = folder / name
            hashes[str(path.relative_to(ROOT)).replace('\\', '/')] = digest(path)
    assert len(inputs) == 66 and len({key[0] for key in inputs}) == 33
    return inputs, signals, hashes
