"""増玉の数量・実cohort会計・停止線と旧全量を、正式入力なしで自己検査する。"""

import copy
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

from support import HERE, ROOT, WORK, attach_support, load, old_prepared_fixture


OLD_NAMES = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
    'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
    'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
    'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_trace', 'entry_policy_events',
    'entry_cap_state_trace', 'entry_cap_parent_diagnostics')
NEW_NAMES = ('growth_state_trace', 'growth_events', 'growth_cohorts', 'growth_parent_diagnostics')


def prepared_fixture(config: dict, symbol: str, side: int) -> dict:
    """
    機能: 初回上限内で入り、別々の両BBO進行後に段階的に増やせる人工素材を作る。
    引数: config(dict)、symbol(str)、side(int)。
    返り値: dict[tuple,dict]は1商品の明示人工LPとBBO。全原本又は損益は開かない。
    """
    data = old_prepared_fixture(config, side=side)
    key = ('2000-01-03_人工', symbol)
    current = data[key]
    record, signal = current['record'], current['signal']
    base, tick = current['reference_open'], record['tick']
    width = max(2, math.ceil(base*.001/tick-1e-10))*tick
    progress = np.zeros(len(record['time_s']))
    for row, multiple in ((340, .5), (360, 1.5), (380, 3.), (400, 6.), (420, 10.),
                          (450, 12.), (480, 14.), (500, 20.), (700, 18.)):
        progress[row:] = multiple
    own_step = np.round(progress*width/tick)*tick
    quote = base + (tick if side == 1 else 0.) + side*own_step
    record['bid'] = quote-tick if side == 1 else quote.copy()
    record['ask'] = quote.copy() if side == 1 else quote+tick
    record['price'] = .5*(record['bid']+record['ask'])
    peer_base, peer_tick = (50000., 10.) if symbol == 'TOPIX' else (4000., .5)
    peer_width = max(2, math.ceil(peer_base*.001/peer_tick-1e-10))*peer_tick
    peer_quote = peer_base+(peer_tick if side == 1 else 0.)+side*np.round(progress*peer_width/peer_tick)*peer_tick
    indexes = signal['entry_peer_bbo'][:, 0].astype(int)
    signal['entry_peer_bbo'][:, 3] = (peer_quote-peer_tick if side == 1 else peer_quote)[indexes]
    signal['entry_peer_bbo'][:, 4] = (peer_quote if side == 1 else peer_quote+peer_tick)[indexes]
    return attach_support({key: current})


def run(strategy: object, config: dict, data: dict, python: bool = True, finish: bool = True) -> dict:
    """
    機能: 人工preparedを変更せず、実行形だけを選んで原行出力を返す。
    引数: strategy(object)、config/data(dict)、python/finish(bool)。
    返り値: dictは人工だけ。旧実行器や正式研究driverを呼ばない。
    """
    before = pickle.dumps(data, protocol=5)
    compiled = strategy.ENGINE.simulate
    try:
        if python:
            strategy.ENGINE.simulate = compiled.py_func
        output = strategy.play(config, next(iter(data)), data, finish=finish)
    finally:
        strategy.ENGINE.simulate = compiled
    assert before == pickle.dumps(data, protocol=5)
    return output


def accounting(output: dict, config: dict, symbol: str) -> None:
    """
    機能: 実orders/cohort/親/全玉時価と、絶対初回数量及び上限を独立に照合する。
    引数: output/config(dict)、symbol(str)。
    返り値: None。親内相殺でcohortの損失を隠す検算をしない。
    """
    multiplier, fee_unit, maximum = (1000., 41.8, 8) if symbol == 'TOPIX' else (10., 11., 16)
    initial = maximum if config['trend_initial_quantity'] is None else config['trend_initial_quantity']
    cohorts, parents, orders = output['growth_cohorts'], output['trades'], output['orders']
    assert cohorts.ndim == 2 and cohorts.shape[1] == 25 and len(cohorts) >= 1
    assert output['growth_state_trace'].shape[1] == 70 and output['growth_events'].shape[1] == 74
    entries = orders[orders[:, 7] == 1]
    assert entries[0, 5] == initial and entries[0, 8] != 16
    if config['trend_growth_mode'] == 0:
        assert len(entries) == 1 and parents[0, 5] == initial
        direction = int(entries[0, 4])
        assert output['stats'][2 if direction == 1 else 3] == initial
        assert output['stats'][3 if direction == 1 else 2] == 0
    else:
        assert parents[0, 5] == maximum and len(entries) >= 2
        assert np.all(entries[1:, 8] == 16)
    assert np.all(output['target_trace'][:, 2:4] <= (10 if symbol == 'TOPIX' else 20))
    for parent in parents:
        selected = cohorts[cohorts[:, 0] == parent[0]]
        assert selected[:, 4].sum() == parent[5]
        assert selected[:, 12].sum() == parent[8] and selected[:, 18].sum() == parent[9]
        assert selected[:, 19].sum() == parent[10] and selected[:, 20].sum() == parent[11]
        for cohort in selected:
            entry = entries[entries[:, 16] == cohort[13]]
            assert len(entry) == 1 and entry[0, 5] == cohort[4] and entry[0, 6] == cohort[11]
            assert cohort[12] == math.floor(cohort[4]*fee_unit+1e-8)
            assert cohort[19] == cohort[3]*(cohort[17]-cohort[11])*cohort[4]*multiplier
    assert output['curve'][-1] == parents[:, 11].sum()
    for parent in output['growth_parent_diagnostics']:
        assert parent[19] >= parent[18]
    held = output['growth_state_trace'][:, 2] > 0
    state = output['growth_state_trace'][held]
    assert np.all(state[:, 6] == state[0, 6])
    assert np.all(np.diff(state[:, 24])*parents[0, 4] >= -1e-8)
    if config['trend_hold_seconds']:
        assert np.all(state[:, 25] == state[0, 15]+1800.)
    activated = state[:, 22] == 1.
    if np.any(activated):
        assert np.all(state[np.flatnonzero(activated)[0]:, 22] == 1.)


def old_output(engine: object, config: dict, current: dict) -> dict:
    """
    機能: 100の旧全量本体へ同じ人工信号と幅を接続して旧22配列を検算する。
    引数: engine(object)は読取100、config/current(dict)は人工のみ。
    返り値: dictは旧全量出力。旧領域にキャッシュを保存しない。
    """
    signal = dict(current['signal'])
    signal['entry_j2_long'] = current['trend_lp_allowed'][1]
    signal['entry_j2_short'] = current['trend_lp_allowed'][-1]
    opening, tick = current['reference_open'], current['record']['tick']
    signal['trend_initial_stop_width'] = max(2, math.ceil(opening*config['trend_initial_stop_bp']/10000./tick-1e-10))*tick
    width = max(2, math.ceil(opening*.001/tick-1e-10))*tick
    signal['entry_wait_width'] = width
    for suffix, field in (('advance','entry_advance_widths'),('pullback','entry_pullback_widths'),('recovery','entry_recovery_widths')):
        multiple = config[field]
        signal['entry_'+suffix+'_width'] = 0. if multiple == 0 else max(1, math.ceil(width*multiple/tick-1e-10))*tick
    compiled = engine.simulate
    try:
        engine.simulate = compiled.py_func
        return engine.execute(current['record'], signal, config)
    finally:
        engine.simulate = compiled


def main() -> None:
    """
    機能: 全20の両商品買売人工、旧全量、共有不変とPython/JIT同値を保存する。
    引数: なし。
    返り値: None。新正式損益・API・実注文は扱わない。
    """
    strategy = load('101自己検査の旧入口と増玉', WORK/'strategy.py')
    catalog = load('101自己検査の有限20', WORK/'catalog.py')
    configs = {value['id']: value for value in catalog.catalog()}
    counts = dict(全20買売人工=0, 旧全量少数null=0, PythonJIT=0)
    for config in configs.values():
        for symbol in catalog.SYMBOLS:
            for side in (1,-1):
                data = prepared_fixture(config, symbol, side)
                output = run(strategy, config, data)
                accounting(output, config, symbol)
                counts['全20買売人工'] += 1
        print(config['id']+': 人工数量/実cohort/全玉会計/停止線が一致', flush=True)
    old = load('100固定全量の読取101', WORK.parent/'wave_v100/engine.py')
    for ident in ('G0_QFULL_X1','G0_QFULL_X3'):
        for symbol in catalog.SYMBOLS:
            config = configs[ident]
            data = prepared_fixture(config,symbol,1)
            current = next(iter(data.values()))
            actual = run(strategy,config,data)
            expected = old_output(old,config,current)
            for name in OLD_NAMES:
                np.testing.assert_array_equal(actual[name],expected[name],err_msg=ident+'/'+symbol+'/'+name)
            counts['旧全量少数null'] += 1
    for ident in ('G0_QFULL_X3','G0_Q1_X1','G1_Q1_X1','G2_Q4_X3'):
        for symbol,side in (('TOPIX',1),('NK225',-1)):
            config=configs[ident];data=prepared_fixture(config,symbol,side)
            expected=run(strategy,config,copy.deepcopy(data));actual=run(strategy,config,copy.deepcopy(data),python=False)
            for name in OLD_NAMES+NEW_NAMES+('entry_support_state_trace',):
                np.testing.assert_array_equal(actual[name],expected[name],err_msg=ident+'/'+name)
            assert actual['entry_support_input_SHA256']==expected['entry_support_input_SHA256']
            counts['PythonJIT'] += 1
    paths=[Path(__file__),HERE/'support.py',WORK/'engine.py',WORK/'strategy.py',WORK/'catalog.py',WORK.parent/'wave_v100/engine.py']
    proof=dict(全合格=True,検査件数=counts,PythonJIT配列照合=counts['PythonJIT']*27,
        共有prepared変更=0,新正式101損益=0,API取得=0,実注文=0,
        SHA256={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
    target=HERE/'全20人工の絶対初回数量と実cohort及び旧全量とPythonJIT自己検査.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k!='SHA256'},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
