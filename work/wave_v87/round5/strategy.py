"""支持の元公開値を保管したまま倍率だけを変更し、既存判定器へ渡す。"""

from pathlib import Path
import importlib.util
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def module(name, path):
    """
    機能: 既存実装を固有名で読み、同じ依存モジュールを再利用する。
    引数: name (str)、path (Path)。
    返り値: module の読取実装。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


prior = module('wave87_round3_strategy', HERE.parent/'round3/strategy.py')
previous = prior.previous
prepare = prior.prepare
base = prior.base
old = prior.old
core = prior.core
import numba
numba.config.CACHE_DIR = str(HERE/'cache')
STRENGTH_COLUMNS = ['保存配列行0始まり', '影区分0通常1出口', '元自己支持ATR', '換算自己支持',
                    '元相手支持ATR', '換算相手支持', '元値の判定閾値ATR', '倍率']


def initialize(inputs, signals):
    """
    機能: round3の入力と公開済み支持を、そのまま読取参照で初期化する。
    引数: inputs/signals (dict) は既存素材。
    返り値: dict の共通特徴。準備資料は複製しない。
    """
    return prior.initialize(inputs, signals)


def scaled_features(config, features):
    """
    機能: 支持値だけを新しい配列へ換算し、共有元特徴を変更せず返す。
    引数: config/features (dict) は固定条件と一口座の共通特徴。
    返り値: dict の浅い特徴写し。自己値・相手値だけ独立した配列を持つ。
    """
    threshold = float(config['threshold_atr'])
    assert threshold in (.05, .25, .5)
    assert config['support_mode'] in (1, 3)
    scale = .05/threshold
    assert scale == config['support_scale']
    copied = dict(features)
    short = dict(features['short'])
    for name in ('self_value', 'peer_value'):
        short[name] = np.multiply(features['short'][name], scale)
        assert not np.shares_memory(short[name], features['short'][name])
    copied['short'] = short
    return copied


def strength_events(result, original, scaled, config):
    """
    機能: 支持の注文公開状態が変わった行に、元値と換算値を対応させる。
    引数: result/original/scaled/config (dict) は再生結果・元短期列・換算短期列・条件。
    返り値: ndarray[float] の八列。欠測値は元配列のNaNのまま保持する。
    """
    blocks = []
    for kind, field in [(0, 'normal_support_events'), (1, 'support_events')]:
        rows = result[field][:, 0].astype(np.int64)
        if not len(rows):
            continue
        blocks.append(np.column_stack((rows, np.full(len(rows), kind), original['self_value'][rows],
                                       scaled['self_value'][rows], original['peer_value'][rows],
                                       scaled['peer_value'][rows], np.full(len(rows), config['threshold_atr']),
                                       np.full(len(rows), config['support_scale']))))
    return np.concatenate(blocks) if blocks else np.empty((0, 8))


def play(config, ready, features, observed=False):
    """
    機能: 強度以外を変更せずround3の売買再生を呼び、変換の証跡を付加する。
    引数: config/ready/features (dict)、observed (bool) は約定モデル。
    返り値: tuple[dict,dict] の売買結果と旧管理設定。
    """
    converted = scaled_features(config, features)
    result, settings = prior.play(config, ready, converted, observed)
    # ----------------------------------------
    # 会計に使わない診断証跡で、元の公開値と判定器へ渡した値を分ける。
    result['support_strength_events'] = strength_events(result, features['short'], converted['short'], config)
    result['support_strength_evidence'] = dict(元条件=config['round3_id'], 閾値ATR=config['threshold_atr'],
        倍率=config['support_scale'], prepared参照='work/wave_v87/round3/prepared/short.pkl',
        列=STRENGTH_COLUMNS, 元配列変更=False)
    return result, settings
