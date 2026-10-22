"""追撃保護の追加比較を独立会計し、出口変更が後続追撃へ与えた影響も区別する。"""

from collections import defaultdict
import json
from pathlib import Path
import pickle

import numpy as np

from audit139 import HERE, ROOT, compare, conditions, digest, ledger, read
from common139 import features129, product


def main():
    """
    機能: 追撃保護八条件の保存会計と発火根拠を再売買せず監査する。
    引数: なし。
    返り値: None。金融独立監査_追撃保護.jsonへ証跡を保存する。
    """
    result = read(HERE/'protect_results/結果.json')
    planpath = ROOT/result['plan']['path']
    assert digest(planpath) == result['plan']['sha256']
    plan = read(planpath)
    for path, sha in plan['spec']['implementation'].items():
        assert digest(ROOT/path) == sha, path
    settings = {c['id']: c for c in plan['configs']}
    original = [read(HERE/f'{stage}/結果.json') for stage in ('results', 'extra_results')]
    originals = {(c['session'], c['symbol']): c for value in original for c in value['cache']}
    bykey = {(r['session'], r['symbol'], r['method']): r for r in result['rows']}
    cache = {(c['session'], c['symbol']): c for c in result['cache']}
    packets = read(HERE/'manifest139.json')['packets']+read(HERE/'manifest139_extra.json')['packets']
    counts = defaultdict(int)
    entry_changes = []
    for info in packets:
        scene = info['session']
        assert digest(info['path']) == info['sha256']
        packet = pickle.loads(Path(info['path']).read_bytes())
        prepared = features129.prices_for(packet, 'mid')
        markets = features129.markets(prepared)
        for symbol in ('NK225', 'TOPIX'):
            current = cache[(scene, symbol)]
            baseinfo = originals[(scene, symbol)]
            assert digest(ROOT/current['path']) == current['sha256']
            assert digest(ROOT/baseinfo['path']) == baseinfo['sha256']
            ready = prepared[(scene, symbol)]
            quotes = packet['quotes'][(scene, symbol)]
            setting = product(symbol)
            with np.load(ROOT/current['path'], allow_pickle=False) as arrays, np.load(ROOT/baseinfo['path'], allow_pickle=False) as base:
                assert set(arrays.files) == set(settings)
                for method, config in settings.items():
                    orders = arrays[method]
                    before = base[config['base']]
                    independent = ledger(orders, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                         setting['fee_tenths'], setting['multiplier'])
                    counts['account_fields'] += compare(bykey[(scene, symbol, method)], independent)
                    facts = conditions(orders, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                       ready['atr'], markets[(scene, symbol)], dict(config, **setting))
                    for key, value in facts.items():
                        counts['condition_'+key] += value
                    counts['accounts'] += 1
                    counts['orders'] += len(orders)
                    counts['uids'] += independent['uids']
                    for uid, label in ((0, 'initial'), (999, 'supplemental')):
                        assert np.array_equal(orders[orders[:, 8] == uid], before[before[:, 8] == uid]), ('初回又は補完に変更', method, scene, symbol, label)
                        counts[label+'_unchanged_orders'] += len(orders[orders[:, 8] == uid])
                    newmask = (orders[:, 7] == 1) & (orders[:, 8] > 0) & (orders[:, 8] != 999)
                    oldmask = (before[:, 7] == 1) & (before[:, 8] > 0) & (before[:, 8] != 999)
                    after_entry, before_entry = orders[newmask], before[oldmask]
                    if not np.array_equal(after_entry, before_entry):
                        entry_changes.append(dict(session=scene, symbol=symbol, method=method,
                                                  old_entries=before_entry.tolist(), new_entries=after_entry.tolist()))
                    else:
                        counts['unchanged_added_entry_accounts'] += 1
        print(scene, '追撃保護独立会計確認', flush=True)
    outcome = dict(status='合格', counters=dict(counts), changed_added_entry_accounts=len(entry_changes),
                   entry_changes=entry_changes, input_sha256=digest(HERE/'protect_results/結果.json'),
                   plan_sha256=digest(planpath), audit_sha256=digest(Path(__file__)), financial_replays=0,
                   scope='初回と補完の注文不変、玉別出口根拠、会計・上限・全返済。途中返済で後続追撃の注文が変わった場合は純出口比較としない。')
    (HERE/'金融独立監査_追撃保護.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='合格', **dict(counts), changed_added_entry_accounts=len(entry_changes)), ensure_ascii=False))


if __name__ == '__main__':
    main()
