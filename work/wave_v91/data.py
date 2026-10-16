"""保存31場の入力読取を専用inputs実装へ接続する。"""

import importlib.util
from pathlib import Path
import sys


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
_NAME = '保存入力91の専用実装'
_SPEC = importlib.util.spec_from_file_location(_NAME, HERE / 'inputs/data.py')
_INPUT = importlib.util.module_from_spec(_SPEC)
sys.modules[_NAME] = _INPUT
_SPEC.loader.exec_module(_INPUT)


def digest(path):
    """
    機能: 指定資料の内容指紋を専用入力実装へ委譲する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    return _INPUT.digest(path)


def immutable(value):
    """
    機能: 入力配列を書換え不可にする処理を委譲する。
    引数: value (object)。
    返り値: None。
    """
    _INPUT.immutable(value)


def load_inputs(verify=True):
    """
    機能: 旧30不変・追加1場の素材を指紋確認付きで接続する。
    引数: verify (bool) は資料と依存コードの指紋照合要否。
    返り値: dict のprices/grids/legacy/entries/features/metadata/paths。
    現在API、実注文、損益台帳、将来ラベルの読取を行わない。
    """
    value = _INPUT.load_inputs(verify=verify)
    value['paths'] = [*value['paths'], Path(__file__)]
    return value
