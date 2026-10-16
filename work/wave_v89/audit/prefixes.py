"""代表実観測の未来を切断・改変し、完了ゲートまでの判断が変わらないことを確認する。"""

from copy import deepcopy
from pathlib import Path
import json
import pickle
import numpy as np
import common
import checks
import independent


def inputs():
    """
    機能: 固定済み共通入力と旧三源注文を、保存指紋に照合して読み込む。
    引数: なし。
    返り値: tuple[dict,dict,dict]。
    """
    prepare = common.module('監査89原入力準備', common.ROOT / 'work/wave_v85/prepare.py')
    data, _, input_hashes = prepare.load_inputs(verify=True)
    path = common.ROOT / 'work/wave_v88/prepared/source_orders.pkl'
    proof = json.loads((path.parent / '準備完了.json').read_text(encoding='utf-8'))
    assert common.sha(path) == proof['源注文SHA256']
    with path.open('rb') as stream:
        feeds = pickle.load(stream)
    assert set(data) == set(feeds)
    return data, feeds, input_hashes


def relevant_cuts(ready, result):
    """
    機能: 最初・最後の新規返済と完了公開の前後へ、未来切断地点を置く。
    引数: ready/result(dict)。
    返り値: list[int]。
    """
    n = len(ready['last'])
    counts = {int(n * .31), int(n * .71)}
    for field in ('orders',):
        orders = result['virtual_result'][field]
        for new in (0, 1):
            subset = orders[orders[:, 8] == new]
            if len(subset):
                for order in (subset[0], subset[-1]):
                    row = int(order[0])
                    counts.update((row, row + 1, row + 2))
    if result['completion_records']:
        for record in (result['completion_records'][0], result['completion_records'][-1]):
            row = record['publish_row']
            counts.update((row, row + 1, row + 2))
    return sorted(count for count in counts if 3 < count < n)


def compare_prefix(partial, full, count):
    """
    機能: 全再生の当時公開分だけを切出し、途中再生の全証跡と照合する。
    引数: partial/full(dict)、count(int)。
    返り値: intの配列照合数。
    """
    arrays = 0
    for world in (None, 'virtual_result'):
        a, b = (partial, full) if world is None else (partial[world], full[world])
        for name in ('orders', 'target_trace'):
            np.testing.assert_array_equal(a[name], b[name][b[name][:, 0] < count])
            arrays += 1
    common.OLD.same(partial['completion_records'], [record for record in full['completion_records'] if record['publish_row'] < count])
    common.OLD.same(partial['gate_trace'], [record for record in full['gate_trace'] if record['row'] < count])
    for name in common.SOURCES:
        common.OLD.same(partial['history_out'][name], [record for record in full['history_out'][name]
            if record['session'] == '人工前場' or record['publish_row'] < count])
    return arrays


def main():
    """
    機能: 全81条件の代表四口座を未来切断し、将来価格と成績毒入れも検査する。
    引数: なし。
    返り値: None。新条件の全30場損益集計は行わない。
    """
    engine = common.module('監査89未来対象実行', common.WORK / 'engine.py')
    strategy = common.module('監査89未来対象接続', common.WORK / 'strategy.py')
    catalog = common.module('監査89未来対象条件', common.WORK / 'catalog.py')
    before = checks.fingerprints() | common.fingerprints([Path(__file__)])
    data, feeds, input_hashes = inputs()
    selected = [(session, symbol) for session in ('2026-09-24_Night', '2026-10-08_Day') for symbol in ('TOPIX', 'NK225')]
    records, poisons = [], 0
    for key in selected:
        ready = data[key]
        source = {name: feeds[key][name]['orders'] for name in common.SOURCES}
        n = len(ready['last'])
        for config in catalog.catalog():
            inherited = checks.history(ready, config['budgets'], [3., -2., 0., -4., 10., -2., -5., 0., 2.],
                clock=float(ready['time_s'][0] - 100))
            full = strategy.play(config, key, ready, feeds, inherited)
            expected = independent.execution(ready, source, config['budgets'], config['gate'], inherited)
            checks.compare(full, expected)
            counts = relevant_cuts(ready, full)
            arrays = 0
            for count in counts:
                short = dict(ready, last=ready['last'][:count], time_s=ready['time_s'][:count])
                partial = strategy.play(config, key, short, feeds, inherited, finish=False)
                arrays += compare_prefix(partial, full, count)
            # ----------------------------------------
            # 将来価格と源の全期間成績を極端に改変し、当時までの判断だけを再照合する。
            count = int(n * .31)
            poisoned = dict(ready, last=ready['last'].copy())
            poisoned['last'][count:] = poisoned['last'][count:] * 17 + 3000
            poisoned_feed = deepcopy(feeds[key])
            for name in common.SOURCES:
                poisoned_feed[name]['future_final_net'] = 10**12 if name != 'M3' else -(10**12)
                poisoned_feed[name]['trades'] = np.full((7, 15), 10**12)
                poisoned_feed[name]['all_period_score'] = -1. if name != 'M3' else 1.
            changed = strategy.play(config, key, poisoned, poisoned_feed, inherited)
            for world in (None, 'virtual_result'):
                a, b = (changed, full) if world is None else (changed[world], full[world])
                for name in ('orders', 'target_trace'):
                    np.testing.assert_array_equal(a[name][a[name][:, 0] < count], b[name][b[name][:, 0] < count])
            common.OLD.same([r for r in changed['gate_trace'] if r['row'] < count], [r for r in full['gate_trace'] if r['row'] < count])
            common.OLD.same([r for r in changed['completion_records'] if r['publish_row'] < count],
                [r for r in full['completion_records'] if r['publish_row'] < count])
            poisons += 1
            records.append(dict(セッション=key[0], 商品=key[1], 条件=config['id'], 切断地点数=len(counts),
                配列照合数=arrays, 完了公開数=len(full['completion_records']), 採否数=len(full['gate_trace'])))
        print(key, '全81条件の未来切断・将来成績毒入れ一致', flush=True)
    assert before == checks.fingerprints() | common.fingerprints([Path(__file__)])
    common.save('完了ゲート全81条件の実観測未来切断と将来成績毒入れ.json', dict(全合格=True,
        条件数=len(catalog.catalog()), 代表口座数=len(selected), 口座条件数=len(records),
        未来切断地点数=sum(record['切断地点数'] for record in records),
        配列照合数=sum(record['配列照合数'] for record in records), 将来価格成績毒入れ数=poisons,
        検査=records, コード素材SHA256=before, 原入力SHA256=input_hashes,
        源注文SHA256=common.sha(common.ROOT / 'work/wave_v88/prepared/source_orders.pkl'),
        対象範囲='代表四口座で当時の注文・目標・確定公開・採否・履歴を照合。原板から三源までの旧因果監査は変更していない。',
        新全期間損益計算=False, API取得数=0, 実注文数=0))
    print(json.dumps(dict(全合格=True, 口座条件数=len(records), 未来切断地点数=sum(r['切断地点数'] for r in records),
        将来価格成績毒入れ数=poisons), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
