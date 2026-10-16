"""八つの人工経路だけでPython/JIT全列と保護診断の予約・約定対応を確認する。"""

import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numba
import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(WORK / 'numba_cache')
numba.config.CACHE_DIR = os.environ['NUMBA_CACHE_DIR']


def module() -> object:
    """
    機能: 新96の実装だけを固有名で読み、旧領域への書込みを防ぐ。
    引数: なし。
    返り値: objectは新戦略。正式入力・正式損益はロードしない。
    """
    spec = importlib.util.spec_from_file_location('利益床の八人工自己検査96', WORK / 'strategy.py')
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


def fixture(symbol: str, side: int, kind: str) -> tuple:
    """
    機能: 初期停止・費用床・半分床・三十分超保有を分ける人工原板を作る。
    引数: symbol(str)、side(int)、kind(str)。
    返り値: tuple[dict,dict,float]は原板・旧入口相当の共通信号・初期から既知の場始値。
    """
    base, tick = (4000., .5) if symbol == 'TOPIX' else (50000., 10.)
    size = 2501
    times = np.arange(size, dtype=float)
    bid = np.full(size, base)
    ask = bid + tick
    entry = base + tick if side == 1 else base
    initial = max(2, math.ceil(base * 10. / 10000. / tick - 1e-10)) * tick
    d = max(2, math.ceil(base * .004 / tick - 1e-10)) * tick
    q, multiplier, fee_unit = (8, 1000., 41.8) if symbol == 'TOPIX' else (16, 10., 11.)
    c = math.ceil((2. * math.floor(q * fee_unit + 1e-8) / (q * multiplier)) / tick) * tick + tick

    def at(row: int, progress: float) -> None:
        """
        機能: 返済側の気配を方向付き利益幅で設定し買売の対称性を保つ。
        引数: row(int)、progress(float)。
        返り値: Noneは以後の人工bid/askの更新。原本には接続しない。
        """
        quote = entry + side * progress
        if side == 1:
            bid[row:] = quote
            ask[row:] = quote + tick
        else:
            ask[row:] = quote
            bid[row:] = quote - tick

    if kind == 'sl':
        at(340, -initial)
    elif kind == 'be':
        at(340, 2. * initial)
        at(350, c - tick)
        at(351, -2. * initial)
    elif kind == 'half':
        at(340, 6. * initial)
        at(350, 3. * initial - tick)
    else:
        assert kind == 'unlimited'
        at(332, 0.)
    grid = np.arange(300., 2450., 5.)
    mapped = np.full(size, -1, np.int32)
    mapped[grid.astype(int)] = np.arange(len(grid), dtype=np.int32)
    event = np.zeros(size, np.int8)
    event[330] = side
    qvalid = np.ones(size, bool)
    if kind == 'be':
        qvalid[351:355] = False
    record = dict(symbol=symbol, time_s=times, price=(bid + ask) * .5, bid=bid, ask=ask,
                  seq=np.arange(size, dtype=np.int64) + 1000, price_valid=np.ones(size, bool),
                  quote_valid=qvalid, tick=tick, start=0., limit=2500., end=2600.)
    signal = dict(grid=grid, mapped=mapped, quality=np.ones(size, bool), reset=np.zeros(size, bool),
                  event=event, mode=np.zeros(len(grid), np.int8), trend_width=d)
    return record, signal, base


def immutable(original: dict, actual: dict) -> None:
    """
    機能: playの浅いコピーが共有preparedを変更していないことを確認する。
    引数: original/actual(dict)。
    返り値: None。一つでも変更があれば検査失敗。
    """
    assert original.keys() == actual.keys()
    for key in original:
        left, right = original[key], actual[key]
        if isinstance(left, dict):
            immutable(left, right)
        elif isinstance(left, np.ndarray):
            np.testing.assert_array_equal(left, right)
        else:
            assert left == right


def diagnostic(output: dict, record: dict, kind: str, side: int) -> None:
    """
    機能: 別診断の予約理由・行・気配・実決済値を旧注文台帳へ一致させる。
    引数: output/record(dict)、kind(str)、side(int)。
    返り値: None。床の突破を利益保証と誤認しない人工境界も確認する。
    """
    parents = output['trend_parent_diagnostics']
    assert parents.shape == (1, 27)
    p = parents[0]
    orders = output['orders']
    assert len(orders) == 2 and len(output['trades']) == 1
    entry, exit_order = orders
    assert p[0] == entry[2] == exit_order[2]
    assert p[1] == entry[0] and p[2] == exit_order[0]
    assert p[14] == exit_order[1] and p[15] == exit_order[10]
    assert p[23] == exit_order[8] and p[24] == exit_order[6] and p[25] == output['trades'][0, 11]
    observed = int(p[26])
    quote = record['bid'][observed] if side == 1 else record['ask'][observed]
    assert p[16] == quote
    state = output['trend_exit_state_trace']
    held = state[state[:, 1] >= 2]
    assert (side * np.diff(held[:, 17]) >= 0).all(), '停止線が後退しました'
    if kind == 'sl':
        assert p[23] == 1 and p[18] == 1 and p[12] == 0
    elif kind == 'be':
        assert p[12] == 1 and p[20] == 1 and int(p[21]) & 4
        assert p[2] == 355 and p[14] == 350 and p[25] < 0
        pending = state[350:355]
        assert (pending[:, 1] == 3).all() and (pending[:, 17] == p[17]).all()
    elif kind == 'half':
        assert p[12] == 1 and int(p[21]) & 8 and p[25] > 0
    else:
        assert state[2200, 1] == 2 and p[22] == 0
        assert p[23] == 4 and p[14] == 2439 and p[26] == 2440 and p[2] == 2440
        assert p[17] == state[2439, 17], '場末stop_beforeが直前合成線と違います'


def main() -> None:
    """
    機能: 八つの人工だけをPythonとJITで再生し全旧及び新配列を照合する。
    引数: なし。
    返り値: Noneは対象SHA付き自己検査証跡。正式96の損益を計算しない。
    """
    strategy = module()
    engine = strategy.ENGINE
    fixed_path = ROOT / 'work/wave_v95/事前固定.json'
    fixed = json.loads(fixed_path.read_text(encoding='utf-8'))
    base_config = next(c for c in fixed['条件'] if c['id'] == 'P0_R0')
    cases = [('TOPIX', 1, 'sl'), ('NK225', -1, 'sl'), ('TOPIX', -1, 'be'), ('NK225', 1, 'be'),
             ('TOPIX', 1, 'half'), ('NK225', -1, 'half'), ('TOPIX', 1, 'unlimited'), ('NK225', -1, 'unlimited')]
    names = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
             'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
             'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics')
    jit = engine.simulate
    results = []
    for symbol, side, kind in cases:
        record, signal, opening = fixture(symbol, side, kind)
        config = dict(base_config, trend_initial_stop_bp=10.,
                      trend_protection_mode={'sl': 0, 'be': 1, 'half': 2, 'unlimited': 0}[kind],
                      trend_hold_seconds=0. if kind == 'unlimited' else 1800.)
        key = ('2000-01-03_人工', symbol)
        prepared = {key: dict(record=record, signal=signal, reference_open=opening)}
        before = copy.deepcopy(prepared)
        try:
            engine.simulate = jit.py_func
            py = strategy.play(config, key, prepared)
        finally:
            engine.simulate = jit
        compiled = strategy.play(config, key, prepared)
        for name in names:
            np.testing.assert_array_equal(py[name], compiled[name])
        immutable(before, prepared)
        diagnostic(compiled, record, kind, side)
        results.append(dict(商品=symbol, 方向=side, 種類=kind, 全15配列同値=True, 親予約及び約定対応=True))
    paths = [Path(__file__), WORK / 'engine.py', WORK / 'strategy.py', fixed_path]
    proof = dict(全合格=True, 人工ケース数=len(cases), Python及びJIT配列比較=len(cases)*len(names),
                 共有prepared変更=0, 診断予約及び約定の一致=True, 保護床の次気配ギャップ損失を計上=True,
                 三十分超保有及び既知場末返済=True, 検査=results, 正式96損益実行=0, API取得=0, 実注文=0,
                 SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    path = HERE / '八人工のPythonとJIT及び停止線と親予約約定診断の自己検査.json'
    path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key not in ('SHA256', '検査')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
