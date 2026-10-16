"""今回の独立監査だけに読み込み先と書き込み先を限定する。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')


def module(name, path):
    """
    機能: 既存ソースを書き換えず、監査用の固有名でモジュールを読み込む。
    引数: name (str)、path (Path)。
    返り値: module。
    """
    if name in sys.modules:
        value = sys.modules[name]
        assert Path(value.__file__).resolve() == path.resolve()
        return value
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def components():
    """
    機能: 新戦略・旧会計・入力準備を読込み、キャッシュを監査領域へ向ける。
    引数: なし。
    返り値: tuple[module,module,module,module]の戦略・条件・会計・準備。
    """
    runner = module('wave86_audit_runner', WORK / 'research.py')
    os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    strategy = runner.strategy_module()
    numba.config.CACHE_DIR = str(HERE / 'cache')
    return strategy, runner.catalog, runner.old, runner.prepare


def clip(value, count, length):
    """
    機能: 原本行と同じ長さの配列だけを再帰的に切断する。
    引数: value (object)、count/length (int)。
    返り値: objectの独立コピー。
    """
    if isinstance(value, dict):
        return {k: clip(v, count, length) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(clip(v, count, length) for v in value)
    if isinstance(value, list):
        return [clip(v, count, length) for v in value]
    if isinstance(value, np.ndarray):
        return value[:count].copy() if value.ndim and len(value) == length else value.copy()
    return value


def digest(path):
    """
    機能: ファイル全体のSHA256を分割読取で作成する。
    引数: path (Path)。
    返り値: str。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(part)
    return result.hexdigest()


def source_hashes():
    """
    機能: 今回の戦略と監査のPython指紋を取得する。
    引数: なし。
    返り値: dict[str,str]。
    """
    paths = sorted(set(WORK.glob('*.py')) | set(HERE.glob('*.py')))
    return {str(p.relative_to(ROOT)): digest(p) for p in paths}


def save(name, value):
    """
    機能: 今回の監査領域だけに有限値JSONを保存する。
    引数: name (str)、value (dict)。
    返り値: None。
    """
    target = (HERE / name).resolve()
    assert target.is_relative_to(HERE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def compare_prefix(full, prefix, count):
    """
    機能: 売買・制御・影計画の過去部分を、全列で比較する。
    引数: full/prefix (dict)、count (int)。
    返り値: intの比較配列数。
    """
    event_columns = dict(orders=0, trades=7, cycles=2, prepare_events=1, entry_preparations=1,
        slot_events=0, adjustment_events=0, budget_events=0, branch_events=0, risk_events=0,
        guard_events=0, block_events=0, time_events=0, reset_events=0, dynamic_events=0,
        reentry_events=1, trail_events=0)
    curves = ('curve', 'atr_curve', 'control_curve', 'slot_curve', 'branch_curve', 'guard_curve',
              'plans', 'execution_plans', 'reentry_curve', 'dynamic_curve')
    checks = 0
    for name, col in event_columns.items():
        if name in full and isinstance(full[name], np.ndarray):
            a, b = full[name], prefix[name]
            np.testing.assert_array_equal(a[a[:, col] < count], b[b[:, col] < count], err_msg=name)
            checks += 1
    for name in curves:
        if name in full:
            np.testing.assert_array_equal(full[name][:count], prefix[name][:count], err_msg=name)
            checks += 1
    for name in ('shadow', 'scheduler', 'normal_shadow', 'exit_shadow'):
        if name in full and isinstance(full[name], dict):
            checks += compare_prefix(full[name], prefix[name], count)
    if 'gate_evidence' in full:
        for name, values in full['gate_evidence'].items():
            if isinstance(values, np.ndarray):
                np.testing.assert_array_equal(values[:count], prefix['gate_evidence'][name][:count], err_msg='半減根拠 '+name)
                checks += 1
    return checks
