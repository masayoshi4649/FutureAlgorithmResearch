"""不変の31保存場を読み、売買結果を入力として使わない。"""

import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
name = '不変保存入力96の読取97'
spec = importlib.util.spec_from_file_location(name, HERE.parent / 'wave_v96/data.py')
previous = importlib.util.module_from_spec(spec)
sys.modules[name] = previous
spec.loader.exec_module(previous)
digest = previous.digest


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 旧J8の候補と両市場の既知原板を不変素材として接続する。
    引数: verify(bool)は保存指紋を照合するか。
    返り値: dict。未来ラベル、実現損益、現在APIは読み込まない。
    """
    return previous.load_inputs(verify=verify)
