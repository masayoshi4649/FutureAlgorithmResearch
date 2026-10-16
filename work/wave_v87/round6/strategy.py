"""取引再生を変更せず、複数返済へ対応した局所会計を公開する。"""

from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def module(name, path):
    """
    機能: 凍結した再生器と新会計器を別名で読む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


prior = module('wave87_round4_strategy', HERE.parent / 'round4/strategy.py')
fee_account = module('wave87_multi_fee_account', HERE / 'fee_account.py')
assert fee_account.VALUES == prior.previous.VALUES and fee_account.FEES == prior.previous.FEES
previous = SimpleNamespace(VALUES=prior.previous.VALUES, FEES=prior.previous.FEES,
                           account=fee_account.account, aggregate=prior.previous.aggregate)
base = prior.base


def initialize(inputs, signals):
    """
    機能: 数量段階と同じ元特徴を生成する。
    引数: inputs/signals(dict)。
    返り値: dict。
    """
    return prior.initialize(inputs, signals)


def play(config, ready, features, observed=False):
    """
    機能: 凍結した数量再生器を同じ条件で実行する。
    引数: config/ready/features(dict)、observed(bool)。
    返り値: tuple[dict,dict]。修正は会計に限定される。
    """
    return prior.play(config, ready, features, observed)
