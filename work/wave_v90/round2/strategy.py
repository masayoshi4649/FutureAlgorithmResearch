"""旧固定状態と入口を読取専用で用い、追加二軸の執行器へ接続する。"""

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
OLD = HERE.parent


def module(name, path):
    """
    機能: 旧又は追加の実装を固有名で取り込み、通常名の衝突を避ける。
    引数: name (str)、path (Path)。
    返り値: object は読取モジュール。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


ENGINE = module('二市場追加執行90r2', HERE / 'engine.py')
# 旧strategyのimport engineを旧実装へ結び、追加名を混ぜない。
previous_engine = sys.modules.get('engine')
sys.modules['engine'] = module('二市場固定執行90r1', OLD / 'engine.py')
try:
    LEGACY = module('二市場固定状態90r1', OLD / 'strategy.py')
finally:
    if previous_engine is None:
        del sys.modules['engine']
    else:
        sys.modules['engine'] = previous_engine


def prepare(material, config):
    """
    機能: 旧固定の状態・入口準備をそのまま使用する。
    引数: material/config (dict)。
    返り値: dict は口座別record/signal。損益と追加フラグは参照しない。
    """
    return LEGACY.prepare(material, config)


def play(config, key, prepared, finish=True):
    """
    機能: 同一の過去入力で気配改善と往復開始時基準の二軸を執行する。
    引数: config (dict)、key (tuple[str,str])、prepared (dict)、finish (bool)。
    返り値: dict は旧列を保つ全会計と、新しい基準更新イベント。
    """
    value = prepared[key]
    return ENGINE.execute(value['record'], value['signal'], config, finish=finish)
