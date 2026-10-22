"""一週間の検証で、旧条件と旧再生器を今回専用の入出力へ接続する。"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numba

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
OLD = ROOT / 'work/wave_v14'
SYMBOLS = ['NK225', 'TOPIX']
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
TRAIN = SESSIONS[:7]
DEVELOPMENT = SESSIONS[:9]
HOLDOUT = SESSIONS[9]
KNOWN_NIGHT = SESSIONS[7]
KNOWN_CUTOFF = '2026-09-25T03:01:00+09:00'
FIXED_TARGETS = {'NK225': 'N03_R-1_L3_U1', 'TOPIX': 'N15_R-1_A4_U0'}
numba.config.CACHE_DIR = str(OUT / 'numba_cache_v2')
sys.dont_write_bytecode = True


@contextmanager
def module_aliases(mapping: dict):
    """機能: 旧コードの読込み中だけ依存名を指定し、終了後に復元する。

    引数: mapping (dict[str, module])。返り値: コンテキスト管理器。
    """
    missing = object()
    previous_names = {name: sys.modules.get(name, missing) for name in mapping}
    sys.modules.update(mapping)
    try:
        yield
    finally:
        for name, value in previous_names.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def source_module(path: Path, name: str):
    """機能: 旧実装を変更せず、今回固有の名前で読み込む。

    引数: path (Path)、name (str)。返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_runtime() -> tuple:
    """機能: 確定済みの信号・注文再生器を今回の保存先へ接続する。

    引数: なし。返り値: 旧調査モジュールと注文再生器 (tuple[module, module])。
    """
    origin = ROOT / 'work/wave_v13'
    data = source_module(origin / 'data.py', 'v16_saved_data')
    exact = source_module(origin / 'exact_engine.py', 'v16_exact_engine')
    signals = source_module(origin / 'new_signals.py', 'v16_saved_signals')
    with module_aliases(dict(data=data, exact_engine=exact, new_signals=signals)):
        catalog = source_module(origin / 'catalog.py', 'v16_saved_catalog')
        with module_aliases(dict(catalog=catalog)):
            research = source_module(origin / 'research.py', 'v16_saved_research')
    research.OUT = OUT
    return research, exact


previous, engine = load_runtime()
_MODULES = {}


def import_v14(name: str):
    """機能: 旧会計・選択・格子・NTの関数を今回の参照と保存先へ接続する。

    引数: name (str)。返り値: module。保存済み旧ファイルを変更しない。
    """
    if name not in {'details', 'metrics', 'risk_guard', 'grid_engine', 'pair_engine', 'research'}:
        raise ValueError('許可した補助実装ではありません')
    if name in _MODULES:
        return _MODULES[name]
    aliases = dict(reference=sys.modules[__name__])
    if name == 'details':
        aliases.update({k: import_v14(k) for k in ['metrics', 'risk_guard', 'grid_engine', 'pair_engine']})
    elif name == 'research':
        aliases.update({k: import_v14(k) for k in ['metrics', 'risk_guard']})
    with module_aliases(aliases):
        module = source_module(OLD / f'{name}.py', f'v16_v14_{name}')
    if hasattr(module, 'OUT'):
        module.OUT = OUT
    _MODULES[name] = module
    return module


def save(path: Path, value: object) -> None:
    """機能: 非有限数を明示して日本語JSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    previous.save(path, value)


def sha256(path: Path) -> str:
    """機能: 原本を書き換えず内容のSHA256を計算する。

    引数: path (Path)。返り値: str。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def configs() -> list[dict]:
    """機能: 前回から変更しない11,253条件を読む。

    引数: なし。返り値: list[dict]。
    """
    value = json.loads((OLD / '全条件一覧.json').read_text(encoding='utf-8'))
    if len(value) != 11253 or len({c['id'] for c in value}) != len(value):
        raise ValueError('旧条件一覧の件数・一意性が一致しません')
    return value


def load_inputs(stage: str = 'development') -> dict:
    """機能: 保存済みの先頭９区間または開封許可済み最終夜の入力を読む。

    引数: stage (str): development/holdout。返り値: dict[(str,str),dict]。
    """
    if stage not in ('development', 'holdout'):
        raise ValueError('未知の検証段階です')
    if stage == 'holdout' and not (OUT / '最終保留_凍結記録.json').exists():
        raise RuntimeError('最終保留の条件固定前です')
    with (OUT / f'入力_{stage}.pkl').open('rb') as stream:
        value = pickle.load(stream)
    expected = DEVELOPMENT if stage == 'development' else [HOLDOUT]
    if set(value) != {(s, k) for s in expected for k in SYMBOLS}:
        raise ValueError('入力の対象セッションが一致しません')
    return value
