"""97と同じ保存31場だけを読み、価格時計と受信時計を混同しない。"""

import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
name = '不変保存入力97の読取98'
spec = importlib.util.spec_from_file_location(name, HERE.parent / 'wave_v97/data.py')
previous = importlib.util.module_from_spec(spec)
sys.modules[name] = previous
spec.loader.exec_module(previous)
digest = previous.digest


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 旧J8候補と既知の二市場原板を不変素材として接続する。
    引数: verify(bool)は保存指紋を照合するか。
    返り値: dict。未来ラベル、実現損益、現在APIを入力へ使わない。
    """
    return previous.load_inputs(verify=verify)
