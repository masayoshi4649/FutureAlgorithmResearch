"""新損益を見る前に、共通注文の人工境界・全行会計と将来切断を検査する。"""

from pathlib import Path
import copy

import numpy as np

import common
import accounting as independent_accounting
import protocol


def sample(symbol, scenario, reflected=False):
    """
    機能: 指値成立・取消競合・反対源・異常板・場末を含む人工原板と信号を作る。
    引数: symbol/scenario(str)、reflected(bool)。
    返り値: tuple[dict,dict]の原板と信号。新しい実データ損益は参照しない。
    """
    tick, anchor = (.5, 4000.) if symbol == 'TOPIX' else (5., 68000.)
    times = np.arange(0., 4100. + 1e-6, 5.)
    n = len(times)
    prices = np.full(n, anchor)
    prices[5:7] = anchor - 9 * tick
    prices[7:15] = anchor + 18 * tick
    prices[15:17] = anchor + 28 * tick
    prices[17:24] = anchor + 56 * tick
    prices[24:60] = anchor + 56 * tick
    prices[60:66] = anchor + 60 * tick
    prices[66:70] = anchor + 75 * tick
    prices[70:] = anchor + 70 * tick
    bids, asks = prices - tick / 2, prices + tick / 2
    price_valid, quote_valid = np.ones(n, bool), np.ones(n, bool)
    quality, reset = np.ones(n, bool), np.zeros(n, bool)
    mode = np.full(n, 2, np.int8)
    mode[60:80] = 1
    event = np.zeros(n, np.int8)
    event[60] = 1
    event[100] = -1
    mode[100:120] = -1
    if scenario in ('取消して基準を再設定', '取消前に約定', '失効を知る行で約定', '無効気配中の取消待ち'):
        prices[5:20] = anchor - 9 * tick
        bids[5:20], asks[5:20] = anchor - 12 * tick, anchor - 3 * tick
        mode[6:20] = 1
        if scenario == '取消前に約定':
            bids[7], asks[7] = anchor - 9 * tick, anchor - 8 * tick
        elif scenario == '失効を知る行で約定':
            bids[6], asks[6] = anchor - 9 * tick, anchor - 8 * tick
        elif scenario == '無効気配中の取消待ち':
            quote_valid[7:9] = False
            bids[9], asks[9] = anchor - 9 * tick, anchor - 8 * tick
    elif scenario == '両源同方向予約':
        prices[60] = prices[59] - 20 * tick
        bids[60], asks[60] = prices[60] - tick / 2, prices[60] + tick / 2
    elif scenario == '両源反対方向予約':
        prices[60] = prices[59] + 20 * tick
        bids[60], asks[60] = prices[60] - tick / 2, prices[60] + tick / 2
    elif scenario == '源品質無効':
        quality[60] = False
    elif scenario == '原板リセット':
        reset[60] = True
    elif scenario == '同時計でも次の原板':
        times[6] = times[5]
        times[61] = times[60]
    elif scenario == '保有期限と場末':
        prices[:] = anchor
        bids[:], asks[:] = anchor - tick / 2, anchor + tick / 2
        event[:] = 0
        event[60] = event[500] = 1
        mode[:] = 1
    elif scenario == '原板気配欠測':
        quote_valid[6:10] = False
        bids[6:10] = np.nan
        asks[6:10] = np.nan
    elif scenario == '不明状態へ取消':
        mode[6:20] = 0
        prices[5:20] = anchor - 9 * tick
        bids[5:20], asks[5:20] = anchor - 12 * tick, anchor - 3 * tick
    elif scenario == '持続指値が場末で失効':
        prices[:] = anchor
        bids[:], asks[:] = anchor - tick / 2, anchor + tick / 2
        late = int((4000 - 120) / 5) - 1
        prices[late:] = anchor - 9 * tick
        bids[late:], asks[late:] = anchor - 12 * tick, anchor - 3 * tick
        bids[late + 1], asks[late + 1] = anchor - 9 * tick, anchor - 8 * tick
    elif scenario == '反対追従による途中撤回':
        prices[5:20] = anchor - 9 * tick
        bids[5:20], asks[5:20] = anchor - 9.5 * tick, anchor - 8.5 * tick
        mode[7:20] = -1
    elif scenario == '注文なし':
        prices[:] = anchor
        bids[:], asks[:] = anchor - tick / 2, anchor + tick / 2
        event[:] = 0
        mode[:] = 0
    if reflected:
        prices = 2 * anchor - prices
        bids, asks = 2 * anchor - asks, 2 * anchor - bids
        event = -event
        mode = np.where(mode == 2, 2, -mode).astype(np.int8)
    record = dict(symbol=symbol, session='人工共通注文', time_s=times, seq=np.arange(n), source_i=np.arange(n),
                  price=prices, bid=bids, ask=asks, price_valid=price_valid, quote_valid=quote_valid,
                  tick=tick, start=0., limit=4000., end=4300.)
    signal = dict(grid=times.copy(), mode=mode, mapped=np.arange(n, dtype=np.int32),
                  quality=quality, reset=reset, event=event, trend_width=4 * tick)
    return record, signal


def prefix(record, signal, stop):
    """
    機能: 原板を切断し、信号の未来格子を残したまま原板対応列だけを同じ長さへ切る。
    引数: record/signal(dict)、stop(int)。
    返り値: tuple[dict,dict]。保存原本を変更しない。
    """
    n = len(record['time_s'])
    sliced_record = {name: value[:stop].copy() if isinstance(value, np.ndarray) and len(value) == n else value
                     for name, value in record.items()}
    sliced_signal = {name: value[:stop].copy() if name in ('mapped', 'quality', 'reset', 'event') else value
                     for name, value in signal.items()}
    return sliced_record, sliced_signal


def prefix_equal(full, part, stop):
    """
    機能: 完全経路の過去注文・イベント・全行時価が、未来を切断した経路と同じか検査する。
    引数: full/part(dict)、stop(int)。
    返り値: None。切断端で強制清算はしない。
    """
    for name, row_column in (('orders', 0), ('events', 0), ('trades', 3)):
        expected = full[name][full[name][:, row_column] < stop]
        actual = part[name][part[name][:, row_column] < stop]
        common.same(expected, actual)
    for name in ('curve', 'source_curve', 'target_trace'):
        common.same(full[name][:stop], part[name][:stop])


def boundary(record, config, scenario, result, reflected):
    """
    機能: 人工経路で取消先行・約定先行・欠測待機・基準再設定を具体的に主張して検査する。
    引数: record/config/result(dict)、scenario(str)、reflected(bool)。
    返り値: intの明示境界件数。
    """
    if not config['range_budget']:
        return 0
    events = result['events']
    entries = result['orders'][(result['orders'][:, 3] == 1) & (result['orders'][:, 7] == 1)]
    if scenario == '取消前に約定' and config['cancel_pending']:
        assert ((events[:, 3] == 3) & (events[:, 0] == 6)).any()
        assert ((events[:, 3] == 7) & (events[:, 0] == 7)).any()
        assert (entries[:, 0] == 7).any()
        return 3
    if scenario == '失効を知る行で約定':
        assert (entries[:, 0] == 6).any()
        parent = entries[entries[:, 0] == 6][0, 2]
        assert not ((events[:, 3] == 3) & (events[:, 1] == parent)).any()
        return 2
    if scenario == '無効気配中の取消待ち' and config['cancel_pending']:
        assert ((events[:, 3] == 3) & (events[:, 0] == 6)).any()
        assert not ((events[:, 3] == 6) & (events[:, 0] >= 7) & (events[:, 0] < 9)).any()
        assert (entries[:, 0] == 9).any()
        return 3
    if scenario == '取消して基準を再設定' and config['cancel_pending']:
        assert ((events[:, 3] == 6) & (events[:, 0] == 7)).any()
        assert not ((events[:, 3] == 10) & (events[:, 0] == 7)).any()
        assert ((events[:, 3] == 10) & (events[:, 0] == 8)).any()
        return 3
    if scenario == '持続指値が場末で失効' and config['selection'] == 'fixed':
        late = int((record['limit'] - 120) / 5) - 1
        assert ((events[:, 3] == 1) & (events[:, 0] == late)).any()
        assert ((events[:, 3] == 6) & (events[:, 0] == late + 1)).any()
        assert not (entries[:, 0] == late + 1).any()
        return 3
    return 0


def faults(engine, catalog):
    """
    機能: わざと早期成立の約定を遅らせる等の故障を入れ、独立監査が実際に拒絶するか確認する。
    引数: engine/catalog(module)。
    返り値: dictの拒絶件数。正常結果は変更しない。
    """
    selected = next(value for value in catalog.catalog() if value['id'] == 'D_C')
    counts = dict(最初指値成立の無視=0, 取消競合の約定を抹消=0, 早すぎる取消効力=0,
                  保有予約枠の抹消=0, 手数料破損=0, 含み損清算時価破損=0)
    for symbol in common.SYMBOLS:
        for reflected in (False, True):
            record, signal = sample(symbol, '取消前に約定', reflected)
            original = engine.execute(record, signal, selected)
            entries = np.flatnonzero((original['orders'][:, 3] == 1) & (original['orders'][:, 7] == 1))
            order_index = int(entries[0])
            parent = original['orders'][order_index, 2]
            mutants = []
            wrong = copy.deepcopy(original)
            wrong['orders'][order_index, 0] += 1
            wrong['orders'][order_index, 11] = record['time_s'][int(wrong['orders'][order_index, 0])]
            mutants.append(('最初指値成立の無視', wrong, 'protocol'))
            wrong = copy.deepcopy(original)
            wrong['orders'] = wrong['orders'][wrong['orders'][:, 2] != parent]
            wrong['trades'] = wrong['trades'][wrong['trades'][:, 0] != parent]
            filtered = wrong['events'][~((wrong['events'][:, 1] == parent) & np.isin(wrong['events'][:, 3], [4, 5, 8]))]
            race = (filtered[:, 1] == parent) & (filtered[:, 3] == 7)
            filtered[race, 3] = 6
            wrong['events'] = filtered
            mutants.append(('取消競合の約定を抹消', wrong, 'protocol'))
            cancel_record, cancel_signal = sample(symbol, '取消して基準を再設定', reflected)
            cancel_original = engine.execute(cancel_record, cancel_signal, selected)
            wrong = copy.deepcopy(cancel_original)
            effects = np.flatnonzero(wrong['events'][:, 3] == 6)
            wrong['events'][effects[0], 0] -= 1
            mutants.append(('早すぎる取消効力', wrong, 'cancel'))
            wrong = copy.deepcopy(original)
            wrong['target_trace'][:, 2:4] = 0
            mutants.append(('保有予約枠の抹消', wrong, 'protocol'))
            wrong = copy.deepcopy(original)
            wrong['orders'][order_index, 9] += 1
            mutants.append(('手数料破損', wrong, 'account'))
            wrong = copy.deepcopy(original)
            wrong['curve'][7] += 100
            mutants.append(('含み損清算時価破損', wrong, 'account'))
            for name, wrong, kind in mutants:
                rejected = False
                try:
                    if kind == 'account':
                        independent_accounting.restore(record, wrong)
                    elif kind == 'cancel':
                        protocol.verify(cancel_record, cancel_signal, selected, wrong)
                    else:
                        protocol.verify(record, signal, selected, wrong)
                except AssertionError:
                    rejected = True
                assert rejected, ('故障注入を監査が見逃した', name, symbol, reflected)
                counts[name] += 1
    return counts


def main():
    """
    機能: 全27条件の人工注文会計と未来切断・未来価格毒入れを検査する。
    引数: なし。
    返り値: None。実データ新損益は計算しない。
    """
    import sys
    sys.path.insert(0, str(common.WORK))
    import engine
    import catalog
    configs = catalog.catalog()
    counts = dict(人工口座=0, 注文会計=0, 将来切断=0, 将来価格毒入れ=0, 明示境界=0, 上下反射=0)
    scenarios = ('通常往復', '取消して基準を再設定', '取消前に約定', '失効を知る行で約定',
                 '無効気配中の取消待ち', '両源同方向予約', '両源反対方向予約', '源品質無効',
                 '原板リセット', '同時計でも次の原板', '保有期限と場末', '原板気配欠測',
                 '不明状態へ取消', '持続指値が場末で失効', '反対追従による途中撤回', '注文なし')
    for config in configs:
        for symbol in common.SYMBOLS:
            for scenario in scenarios:
                original = None
                for reflected in (False, True):
                    record, signal = sample(symbol, scenario, reflected)
                    result = engine.execute(record, signal, config)
                    proof = independent_accounting.restore(record, result)
                    protocol.verify(record, signal, config, result)
                    counts['人工口座'] += 1
                    counts['注文会計'] += proof['orders']
                    counts['明示境界'] += boundary(record, config, scenario, result, reflected)
                    if original is None:
                        original = result
                    else:
                        for name in ('curve', 'source_curve'):
                            common.same(original[name], result[name])
                        np.testing.assert_array_equal(original['orders'][:, 4], -result['orders'][:, 4])
                        common.same(original['orders'][:, [0, 1, 2, 3, 5, 7, 8, 9, 13, 14, 16]],
                                    result['orders'][:, [0, 1, 2, 3, 5, 7, 8, 9, 13, 14, 16]])
                        counts['上下反射'] += 1
                    for stop in (1, 6, 7, 8, 9, 12, 61, 65, 71, 421, 777, 789):
                        cut_record, cut_signal = prefix(record, signal, stop)
                        part = engine.execute(cut_record, cut_signal, config, finish=False)
                        prefix_equal(result, part, stop)
                        counts['将来切断'] += 1
                        future_record = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in record.items()}
                        for name in ('price', 'bid', 'ask'):
                            future_record[name][stop:] *= 10
                        poisoned = engine.execute(future_record, signal, config, finish=False)
                        prefix_equal(result, poisoned, stop)
                        counts['将来価格毒入れ'] += 1
        print(f'{config["id"]} 人工注文・取消・鏡映・会計・未来切断合格', flush=True)
    fault_proof = faults(engine, catalog)
    common.save('全27条件の人工注文と取消競合及び将来不変の独立会計.json',
                dict(全合格=True, 全期間既知=True, 条件数=len(configs), 検査件数=counts,
                     故障注入を拒絶=fault_proof,
                     新実損益計算=0, 新実損益閲覧=0, 現在API取得=0, 実注文=0, 旧変更=0,
                     SHA256=common.fingerprint([Path(__file__), Path(common.__file__), Path(independent_accounting.__file__), Path(protocol.__file__),
                                               common.WORK / 'catalog.py', common.WORK / 'engine.py'])))


if __name__ == '__main__':
    main()
