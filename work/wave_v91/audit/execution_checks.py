"""新しい実損益を見る前に人工注文・仮説保持・独立返済の因果境界を検査する。"""

import copy
import math
from pathlib import Path

import numpy as np

import common
import accounting
import protocol


OLD = common.module('人工注文90読取91', common.ROOT / 'work/wave_v90/round2/audit/execution_checks.py')


def sample(symbol, scenario, reflected=False, config=None):
    """
    機能: 旧人工経路に不明保持・共同破綻・利益追跡の明示境界を加える。
    引数: symbol/scenario (str)、reflected (bool)、config (dict | None)。
    返り値: tuple[dict,dict] の原板と過去信号。
    """
    mapping = {'不明を跨ぎ指値保持': '不明状態へ取消', '共同方向で取消競合': '取消前に約定',
               '共同方向で取消成立なし': '取消して基準を再設定', '片市場無効で新規を拒否': '通常往復',
               '利益発動後に半幅反落': '通常往復', '格子10秒超で新規を拒否': '通常往復'}
    record, signal = OLD.sample(symbol, mapping.get(scenario, scenario), False)
    anchor = 4000. if symbol == 'TOPIX' else 68000.
    if symbol == 'NK225':
        for name in ('price', 'bid', 'ask'):
            record[name] = anchor + (record[name] - anchor) * 2
        record['tick'] *= 2
        signal['trend_width'] *= 2
    n, tick = len(record['time_s']), record['tick']
    signal.update(current_valid=np.ones(n, bool), arm_common=np.where(signal['mode'] == 2, 0, signal['mode']).astype(np.int8),
                  arm_trend300=np.where(signal['mode'] == 2, 0, signal['mode']).astype(np.int8),
                  reverse_long=np.zeros(n, bool), reverse_short=np.zeros(n, bool))
    if scenario == '不明を跨ぎ指値保持':
        signal['arm_common'][6:20] = signal['arm_trend300'][6:20] = 0
        record['bid'][7], record['ask'][7] = anchor - 9 * tick, anchor - 8 * tick
    elif scenario in ('共同方向で取消競合', '共同方向で取消成立なし'):
        signal['arm_common'][6:20] = signal['arm_trend300'][6:20] = 1
    elif scenario == '片市場無効で新規を拒否':
        signal['current_valid'][:60] = False
    elif scenario == '格子10秒超で新規を拒否':
        signal['mapped'][1:60] = -1
    elif scenario == '利益発動後に半幅反落':
        width = 8 * tick
        record['price'][:] = anchor
        record['price'][5:8] = anchor - 9 * tick
        record['price'][8:10] = anchor
        record['price'][10:40] = anchor - width / 2 - tick
        record['bid'], record['ask'] = record['price'] - tick / 2, record['price'] + tick / 2
        signal['mode'][:] = 2
        signal['arm_common'][:] = signal['arm_trend300'][:] = 0
        signal['event'][:] = 0
    if config and config.get('range_width_mode') == 'opening_fraction':
        signal['range_width'] = max(2, math.ceil(anchor * config['range_width_fraction'] / tick - 1e-10)) * tick
    else:
        signal['range_width'] = (config or {}).get('width_ticks', 8) * tick
    if reflected:
        record['price'] = 2 * anchor - record['price']
        record['bid'], record['ask'] = 2 * anchor - record['ask'], 2 * anchor - record['bid']
        signal['event'] *= -1
        signal['mode'] = np.where(signal['mode'] == 2, 2, -signal['mode']).astype(np.int8)
        signal['arm_common'] *= -1
        signal['arm_trend300'] *= -1
        signal['reverse_long'], signal['reverse_short'] = signal['reverse_short'], signal['reverse_long']
    return record, signal


def prefix(record, signal, stop):
    """
    機能: 原板だけを切断し未来格子は残して未参照を確かめる。
    引数: record/signal (dict)、stop (int)。
    返り値: tuple[dict,dict]。端点の強制清算は作らない。
    """
    n = len(record['time_s'])
    sliced_record = {name: value[:stop].copy() if isinstance(value, np.ndarray) and len(value) == n else value
                     for name, value in record.items()}
    sliced_signal = {name: value[:stop].copy() if name in ('mapped', 'quality', 'reset', 'event') else value
                     for name, value in signal.items()}
    return sliced_record, sliced_signal


def prefix_equal(full, part, stop):
    """
    機能: 過去注文・イベント・全行時価が未来切断後も完全に同じか比較する。
    引数: full/part (dict)、stop (int)。
    返り値: None。
    """
    for name, row in (('orders', 0), ('events', 0), ('trades', 3)):
        common.same(full[name][full[name][:, row] < stop], part[name][part[name][:, row] < stop])
    for name in ('curve', 'source_curve', 'target_trace'):
        common.same(full[name][:stop], part[name][:stop])


def faults(engine, configs):
    """
    機能: 故障した会計・占有・指値・仮説台帳を独立監査が拒絶するか確かめる。
    引数: engine (module)、configs (list[dict])。
    返り値: dict[str,int] の拒絶件数。
    """
    config = next(item for item in configs if item['id'] == 'P_G82_HUNL')
    counts = dict(最初約定の遅延=0, 手数料破損=0, 含み損の隠蔽=0, 未約定予約の抹消=0,
                  指値外の約定=0, 不明保持中の仮説解除=0, 往復準備の抹消=0)
    for symbol in common.SYMBOLS:
        for reflected in (False, True):
            record, signal = sample(symbol, '不明を跨ぎ指値保持', reflected, config)
            original = engine.execute(record, signal, config)
            indices = np.flatnonzero((original['orders'][:, 3] == 1) & (original['orders'][:, 7] == 1))
            assert len(indices)
            at = int(indices[0])
            mutants = []
            wrong = copy.deepcopy(original); wrong['orders'][at, 0] += 1
            mutants.append(('最初約定の遅延', wrong, 'protocol'))
            wrong = copy.deepcopy(original); wrong['orders'][at, 9] += 1
            mutants.append(('手数料破損', wrong, 'account'))
            wrong = copy.deepcopy(original); wrong['curve'][7] += 100
            mutants.append(('含み損の隠蔽', wrong, 'account'))
            wrong = copy.deepcopy(original); wrong['target_trace'][:, 2:4] = 0
            mutants.append(('未約定予約の抹消', wrong, 'protocol'))
            wrong = copy.deepcopy(original); wrong['orders'][at, 6] += wrong['orders'][at, 4] * record['tick'] * 20
            mutants.append(('指値外の約定', wrong, 'account'))
            wrong = copy.deepcopy(original)
            prepare = np.flatnonzero(wrong['events'][:, 3] == 12)
            wrong['events'] = np.delete(wrong['events'], prepare[0], axis=0)
            mutants.append(('往復準備の抹消', wrong, 'arm'))
            wrong = copy.deepcopy(original)
            invented = np.array([6, 0, 1, 13, 0, config['range_budget']*(1 if symbol == 'TOPIX' else 2), 6,
                                 record['price'][0], 0, record['time_s'][6], 1, 1], float)
            where = np.searchsorted(wrong['events'][:, 0], 6, side='right')
            wrong['events'] = np.insert(wrong['events'], where, invented, axis=0)
            mutants.append(('不明保持中の仮説解除', wrong, 'arm'))
            for name, wrong, kind in mutants:
                rejected = False
                try:
                    if kind == 'account': accounting.restore(record, wrong, config)
                    elif kind == 'arm': protocol.arm_state(record, signal, config, wrong)
                    else: protocol.verify(record, signal, config, wrong)
                except AssertionError:
                    rejected = True
                assert rejected, ('故障注入見逃し', name, symbol, reflected)
                counts[name] += 1
    return counts


def main():
    """
    機能: 全38条件の人工会計・仮説・上下対称性・未来不変を実損益前に検査する。
    引数: なし。
    返り値: None。
    """
    import sys
    sys.path.insert(0, str(common.WORK))
    import strategy, catalog
    configs, engine = catalog.catalog(), strategy.ENGINE
    independent_full = common.module('独立途中返済検算91', common.HERE/'full.py')
    counts = dict(人工口座=0, 注文会計=0, 将来切断=0, 将来価格毒入れ=0, 将来格子毒入れ=0,
                  上下反射=0, 不明保持の明示境界=0, 最初返済条件=0)
    scenarios = ('通常往復', '取消して基準を再設定', '取消前に約定', '失効を知る行で約定',
                 '無効気配中の取消待ち', '両源同方向予約', '両源反対方向予約', '源品質無効',
                 '原板リセット', '同時計でも次の原板', '保有期限と場末', '原板気配欠測',
                 '不明状態へ取消', '持続指値が場末で失効', '反対追従による途中撤回', '注文なし',
                 '休止後に古い基準を捨てる', '未約定中は開始基準を更新しない', '既保有中は開始基準を更新しない',
                 '不明を跨ぎ指値保持', '共同方向で取消競合', '共同方向で取消成立なし',
                 '片市場無効で新規を拒否', '格子10秒超で新規を拒否', '利益発動後に半幅反落')
    for config in configs:
        for symbol in common.SYMBOLS:
            for scenario in scenarios:
                original = None
                for reflected in (False, True):
                    record, signal = sample(symbol, scenario, reflected, config)
                    result = engine.execute(record, signal, config)
                    proof = accounting.restore(record, result, config)
                    protocol.verify(record, signal, config, result)
                    protocol.arm_state(record, signal, config, result)
                    counts['最初返済条件'] += independent_full.management(record, signal, config, result['orders'], result['trades'], result['events'])
                    if not config.get('persistent_arm'):
                        protocol.activation(record, signal, config, result)
                    counts['人工口座'] += 1
                    counts['注文会計'] += proof['orders']
                    if scenario == '不明を跨ぎ指値保持' and config.get('persistent_arm'):
                        assert not ((result['events'][:, 3] == 13) & (result['events'][:, 0] >= 6) & (result['events'][:, 0] < 7)).any()
                        counts['不明保持の明示境界'] += 1
                    if original is None:
                        original = result
                    else:
                        common.same(original['curve'], result['curve'])
                        common.same(original['source_curve'], result['source_curve'])
                        common.same(original['orders'][:, [0,1,2,3,5,7,8,9,13,14,16]], result['orders'][:, [0,1,2,3,5,7,8,9,13,14,16]])
                        common.same(original['orders'][:,4], -result['orders'][:,4])
                        counts['上下反射'] += 1
                    for stop in (1, 6, 7, 8, 9, 12, 61, 71, 421, 777, 789):
                        cut_record, cut_signal = prefix(record, signal, stop)
                        part = engine.execute(cut_record, cut_signal, config, finish=False)
                        prefix_equal(result, part, stop); counts['将来切断'] += 1
                        future_record = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in record.items()}
                        for name in ('price', 'bid', 'ask'): future_record[name][stop:] *= 10
                        poisoned = engine.execute(future_record, signal, config, finish=False)
                        prefix_equal(result, poisoned, stop); counts['将来価格毒入れ'] += 1
                        future_signal = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in signal.items()}
                        used = signal['mapped'][:stop]; last_g = int(used.max(initial=-1))
                        for name in ('mode','arm_common','arm_trend300'): future_signal[name][last_g+1:] *= -1
                        for name in ('current_valid','reverse_long','reverse_short'): future_signal[name][last_g+1:] = ~future_signal[name][last_g+1:]
                        poisoned = engine.execute(record, future_signal, config, finish=False)
                        prefix_equal(result, poisoned, stop); counts['将来格子毒入れ'] += 1
        print(f'{config["id"]} 人工会計・枠・仮説保持・上下反射・未来不変合格', flush=True)
    common.save('全38条件の人工注文と仮説保持及び将来不変の独立検査.json',
                dict(全合格=True, 条件数=len(configs), 検査件数=counts, 故障注入を拒絶=faults(engine, configs),
                     新完結実損益計算=0, 新完結実損益閲覧=0, 現在API取得=0, 実注文=0, 旧変更=0,
                     SHA256=common.fingerprint([Path(__file__), Path(common.__file__), Path(accounting.__file__),
                                               Path(protocol.__file__), common.WORK/'engine.py', common.WORK/'strategy.py', common.WORK/'catalog.py'])))


if __name__ == '__main__':
    main()
