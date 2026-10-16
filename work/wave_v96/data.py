"""既に照合した31場の因果入力を読み、新しい入力や現在APIを追加しない。"""

import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
name = '確定保存入力95の読取96'
spec = importlib.util.spec_from_file_location(name, HERE.parent / 'wave_v95/data.py')
previous = importlib.util.module_from_spec(spec)
sys.modules[name] = previous
spec.loader.exec_module(previous)
digest = previous.digest


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 旧J8入口と全原板会計に必要な不変入力だけを読み込む。
    引数: verify(bool)は入力の保存指紋を照合するか。
    返り値: dict。既知31場の素材。売買損益や未来ラベルは参照しない。
    """
    return previous.load_inputs(verify=verify)
