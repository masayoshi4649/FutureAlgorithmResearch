"""全31場の既知入力と指紋を変更せず読み、次の入口検証へ渡す。"""

import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = '全31入力91の読取93'
spec = importlib.util.spec_from_file_location(NAME, HERE.parent / 'wave_v91/data.py')
previous = importlib.util.module_from_spec(spec)
sys.modules[NAME] = previous
spec.loader.exec_module(previous)
digest = previous.digest


def load_inputs(verify: bool = True) -> dict:
    """
    機能: 前段で検証済みの31場素材を読み取り専用で接続する。
    引数: verify(bool、すべての旧入力指紋を照合するか)。
    返り値: dict。原板、両市場の厳密過去格子、既存入口と素材目録。
    """
    material = previous.load_inputs(verify=verify)
    assert len(material['grids']) == 31 and len(material['prices']) == 62
    return material
