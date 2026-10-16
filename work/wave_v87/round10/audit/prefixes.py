"""旧仮想規則を固定した差引実行で、過去の注文・UID・親組確定の因果性を検査する。"""

from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks


def same_virtual(full, actual, helper, count):
    """
    機能: 元玉と仮想規則の保存済み過去部分が新実行層の影響を受けないことを確認する。
    引数: full/actual(dict)、helper(module)、count(int)。
    返り値: intの配列比較数。
    """
    compared = helper.compare_prefix(full, actual, count)
    for name, column in (('satellite_orders', 0), ('satellite_trades', 7), ('satellite_events', 0), ('insurance_events', 0)):
        if name in full:
            values = full[name]
            np.testing.assert_array_equal(values[values[:, column] < count], actual[name])
            compared += 1
    if 'satellite_curve' in full:
        np.testing.assert_array_equal(full['satellite_curve'][:count], actual['satellite_curve'])
        compared += 1
    return compared


def same_execution(full, prefix, count):
    """
    機能: 次観測実注文と状態を切断照合し、親組は仮想終了が公開済みのものだけ比較する。
    引数: full/prefix(dict)、count(int)。
    返り値: int。差引ゼロの時点で未来の親組分類を先に確定したとは扱わない。
    """
    checked = 0
    for name, column in (('orders', 0), ('trades', 7), ('execution_events', 0), ('virtual_feed', 0)):
        values = full[name]
        np.testing.assert_array_equal(values[values[:, column] < count], prefix[name], err_msg=name)
        checked += 1
    for name in ('curve', 'execution_states'):
        np.testing.assert_array_equal(full[name][:count], prefix[name], err_msg=name)
        checked += 1
    np.testing.assert_array_equal(full['order_uids'][:len(prefix['orders'])], prefix['order_uids'])
    completed = {int(c[0]) for c in prefix['virtual_result']['cycles']}
    expected = np.asarray([c for c in full['cycles'] if c[0] in completed and c[2] < count]).reshape(-1, 10)
    np.testing.assert_array_equal(expected, prefix['cycles'], err_msg='仮想親終了が既知の実親組')
    return checked + 2


def main():
    """
    機能: 四仮想規則・三実行方式を代表日夜と両商品で再生し、UID会計と未来切断を確認する。
    引数: なし。
    返り値: None。全セッションの新条件探索や条件変更は行わない。
    """
    _, fees, catalog = checks.load()
    strategy = checks.module('監査87差引接続戦略', checks.WORK / 'strategy.py')
    before = checks.hashes()
    helper = checks.module('監査87差引切断道具', checks.ROOT / 'work/wave_v86/audit/support.py')
    prepare = checks.module('監査87差引基礎入力', checks.ROOT / 'work/wave_v85/prepare.py')
    inputs, signals, _ = prepare.load_inputs(verify=False)
    selected = {key: inputs[key] for key in [(s, p)
        for s in ('2026-09-25_Day', '2026-09-28_Night') for p in ('TOPIX', 'NK225')]}
    features = strategy.initialize(selected, signals)
    configs = [c for c in catalog.catalog() if c['execution_mode'] != 'IDEAL']
    records = []
    for key, ready in selected.items():
        feature = features[key]
        source_cache, gross_cache = {}, {}
        for config in configs:
            source = config['source_id']
            if source not in source_cache:
                source_cache[source] = strategy.virtual(config, ready, feature)[0]
            baseline = source_cache[source]
            result, settings = strategy.play(config, ready, feature, True)
            same_virtual(baseline, result['virtual_result'], helper, len(ready['last']))
            original_core = baseline.get('core_result', baseline)
            same_virtual(original_core, result['core_result'], helper, len(ready['last']))
            tally = checks.account(ready, result, fees, settings['audit_cap'])
            if config['execution_mode'] == 'G':
                gross_cache[source] = result['curve'][:, [0, 5, 6]].copy()
            elif config['execution_mode'] == 'N':
                np.testing.assert_allclose(result['curve'][:, [0, 5, 6]], gross_cache[source], atol=1e-8, rtol=0)
            events = result['execution_events']
            cuts = {int(len(ready['last']) * .37), int(len(ready['last']) * .77)}
            for code in (1, 2, 3, 4):
                matching = events[events[:, 1] == code]
                for event in matching[:2]:
                    cuts.update((int(event[0]), int(event[0]) + 1))
                if len(matching) and code == 4:
                    cuts.update((int(matching[-1, 0]), int(matching[-1, 0]) + 1))
            state = result['execution_states']
            flat_open = np.flatnonzero((state[:, 4] + state[:, 5] == 0) & ((state[:, 1] != 0) | (state[:, 2] != 0)))
            if len(flat_open):
                cuts.add(int(flat_open[0]) + 1)
            for cycle in result['cycles'][:1]:
                cuts.update((int(cycle[2]), int(cycle[2]) + 1))
            cuts = sorted(i for i in cuts if 2 < i < len(ready['last']))
            checked = 0
            for count in cuts:
                short_ready = helper.clip(ready, count, len(ready['last']))
                short_feature = helper.clip(feature, count, len(ready['last']))
                prefix, _ = strategy.play(config, short_ready, short_feature, True)
                checked += same_execution(result, prefix, count)
                checked += same_virtual(result['virtual_result'], prefix['virtual_result'], helper, count)
                checked += same_virtual(result['core_result'], prefix['core_result'], helper, count)
            records.append(dict(セッション=key[0], 商品=key[1], 条件=config['id'],
                切断地点=len(cuts), 配列照合数=checked, **tally))
            print(key, config['id'], len(cuts), '仮想不変・UID会計・未来切断一致', flush=True)
    assert before == checks.hashes()
    checks.save('差引実行の旧仮想不変とUID会計と未来切断.json', dict(全合格=True,
        条件口座数=len(records), 切断地点=sum(r['切断地点'] for r in records),
        配列照合数=sum(r['配列照合数'] for r in records), 検査=records, コードSHA256=before,
        親組確定の扱い='実玉が一時ゼロでも仮想親が続く間は同じ親組。切断比較では仮想終了が当時までに公開された親組のみ確定会計を照合。'))


if __name__ == '__main__':
    main()
