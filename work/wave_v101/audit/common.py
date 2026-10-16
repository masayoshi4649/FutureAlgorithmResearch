"""101独立監査の読取・指紋・保存を、所有ディレクトリに限定して行う。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
sys.path.insert(1,str(BASE))


def module(name: str, path: Path) -> object:
    """
    機能: 読取専用資料を固有名で読み込み、旧ディレクトリへのbytecode書込を避ける。
    引数: name(str)は固有名、path(Path)は既存コード。
    返り値: object。読取モジュール。金融実行を自動で呼び出さない。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    try:
        spec.loader.exec_module(value)
    finally:
        os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
        loaded_numba = sys.modules.get('numba')
        if loaded_numba is not None and getattr(loaded_numba,'config',None) is not None:
            loaded_numba.config.CACHE_DIR = str(HERE / 'jit')
    return value


def read(path: Path) -> object:
    """
    機能: JSON又は保存pickleを読取専用で開く。
    引数: path(Path)は保存済み資料。
    返り値: object。読取内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: ファイルの現在SHA256を算定する。
    引数: path(Path)は読取対象。
    返り値: str。16進指紋。原本を変更しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fingerprints(paths: list[Path]) -> dict[str, str]:
    """
    機能: 参照根拠の現在指紋をプロジェクト相対パスへ対応させる。
    引数: paths(list[Path])は参照根拠。
    返り値: dict[str,str]。現在SHA256。
    """
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def save(path: Path, value: dict) -> None:
    """
    機能: 新101監査の所有範囲だけにUTF-8証跡を保存し再読込する。
    引数: path(Path)は101/audit内、value(dict)は有限JSON資料。
    返り値: None。逸脱又は保存不一致で例外。
    """
    assert path.resolve().is_relative_to(HERE.resolve()), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert read(path) == value


def old_immutable() -> int:
    """
    機能: 旧100の1159金融依存が固定時と同じであることを確認する。
    引数: なし。
    返り値: int。照合した依存件数。原本及び旧固定資料を変更しない。
    """
    fixed = read(ROOT / 'work/wave_v100/事前固定.json')
    assert len(fixed['SHA256']) == 1159
    for relative, expected in fixed['SHA256'].items():
        assert sha(ROOT / relative) == expected, relative
    return len(fixed['SHA256'])
