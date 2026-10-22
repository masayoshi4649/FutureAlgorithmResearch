"""元の通常親集合で担当を分類し、補完を含めた早期併用の不変性を独立監査する。"""

from collections import defaultdict
import json
from pathlib import Path
import pickle

import numpy as np

from audit139 import HERE, ROOT, compare, conditions, digest, ledger, read
from common139 import features129, product
import early139


def main():
    """
    機能: 早期の全保存口座を再売買せず独立会計と発注根拠で確認する。
    引数: なし。
    返り値: None。金融独立監査_早期_v2.jsonへ証跡を保存する。
    """
    result = read(HERE/'early_results/結果.json')
    planpath = ROOT/result['plan']['path']
    assert digest(planpath) == result['plan']['sha256']
    plan = read(planpath)
    for path, sha in plan['spec']['implementation'].items():
        assert digest(ROOT/path) == sha, path
    original_plan = read(HERE/'試行計画_v2.json')
    original_config = {c['id']: c for c in original_plan['configs']}
    early_config = {c['id']: c for c in plan['configs']}
    reference = [read(HERE/f'{stage}/結果.json') for stage in ('results', 'extra_results')]
    original_cache = {(c['session'], c['symbol']): c for res in reference for c in res['cache']}
    bykey = {(r['session'], r['symbol'], r['method']): r for r in result['rows']}
    cache = {(c['session'], c['symbol']): c for c in result['cache']}
    packets = read(HERE/'manifest139.json')['packets']+read(HERE/'manifest139_extra.json')['packets']
    counters = defaultdict(int)
    for info in packets:
        scene = info['session']
        assert digest(info['path']) == info['sha256']
        packet = pickle.loads(Path(info['path']).read_bytes())
        prepared = features129.prices_for(packet, 'mid')
        markets = features129.markets(prepared)
        early = early139.prepare(packet)
        for symbol in ('NK225', 'TOPIX'):
            current = cache[(scene, symbol)]
            original = original_cache[(scene, symbol)]
            assert digest(ROOT/current['path']) == current['sha256']
            assert digest(ROOT/original['path']) == original['sha256']
            setting = product(symbol)
            ready = prepared[(scene, symbol)]
            small = early[symbol]
            quotes = packet['quotes'][(scene, symbol)]
            with np.load(ROOT/current['path'], allow_pickle=False) as arrays, np.load(ROOT/original['path'], allow_pickle=False) as base:
                assert len(arrays.files) == len(early_config)*3
                for method in arrays.files:
                    key = method.split('_')[-1]
                    basekey = method.split('_')[0] if '_' in method else None
                    config = early_config[key]
                    orders = arrays[method]
                    independent = ledger(orders, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                         setting['fee_tenths'], setting['multiplier'])
                    counters['account_fields'] += compare(bykey[(scene, symbol, method)], independent)
                    counters['accounts'] += 1
                    counters['orders'] += len(orders)
                    counters['uids'] += independent['uids']
                    original_orders = base[basekey] if basekey is not None else np.empty((0, 10))
                    base_parents = np.unique(original_orders[:, 2]) if len(original_orders) else np.empty(0)
                    regular_mask = np.isin(orders[:, 2], base_parents)
                    own = orders[~regular_mask]
                    normal = orders[regular_mask]
                    assert not np.any(own[:, 8] == 999), ('補完を早期へ誤分類', method, scene, symbol)
                    if len(own):
                        assert np.all((own[:, 2] >= 20000) & (own[:, 2] < 1000000))
                    wrong_old = orders[(orders[:, 2] >= 20000) & regular_mask]
                    counters['old_classification_missed_regular_orders'] += len(wrong_old)
                    counters['old_classification_missed_regular_parents'] += len(np.unique(wrong_old[:, 2])) if len(wrong_old) else 0
                    checks = conditions(own, small['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                        small['atr'], small['market'], dict(config['management'], **setting))
                    for name, value in checks.items():
                        counters['early_'+name] += value
                    initials = own[(own[:, 7] == 1) & (own[:, 8] == 0)]
                    assert len(initials) == bykey[(scene, symbol, method)]['early_entries']
                    for row in initials:
                        fill, decision, side = int(row[0]), int(row[1]), int(row[3])
                        assert small['time_s'][decision] < small['candidate_until']
                        assert small['time_s'][fill] < small['window_end']
                        assert small['market'][decision, 11] == 1.
                        assert small['market'][decision, 8] < small['time_s'][decision]
                        assert small['time_s'][decision]-small['market'][decision, 8] <= 15.
                        for col in (4, 6):
                            assert side*small['market'][decision, col] >= config['entry']['threshold30']
                        for col in (5, 7):
                            assert side*small['market'][decision, col] >= config['entry']['threshold120']
                        assert small['minute_features'][decision, 7] >= 3
                        mechanism = config['entry']['mechanism']
                        if mechanism in ('ema38', 'ema520'):
                            fast = 1 if mechanism == 'ema38' else 3
                            for features in (small['minute_features'], small['peer_minute_features']):
                                assert side*(features[decision, fast]-features[decision, fast+1]) > 0.
                        assert row[4] == config['management']['initial']
                        counters['early_initials'] += 1
                    if basekey is None:
                        assert len(normal) == 0
                    else:
                        for pid in np.unique(normal[:, 2]) if len(normal) else []:
                            observed = normal[normal[:, 2] == pid]
                            expected = original_orders[original_orders[:, 2] == pid]
                            assert np.array_equal(observed, expected), ('通常担当の親を途中変更', method, scene, symbol, pid)
                            counters['unchanged_regular_parents'] += 1
                            counters['unchanged_regular_orders'] += len(observed)
                        checks = conditions(normal, ready['time_s'], quotes['bid'], quotes['ask'], quotes['quote_valid'],
                                            ready['atr'], markets[(scene, symbol)], dict(original_config[basekey], **setting))
                        for name, value in checks.items():
                            counters['regular_'+name] += value
        print(scene, '早期独立会計確認', flush=True)
    outcome = dict(status='合格', counters=dict(counters), input_sha256=digest(HERE/'early_results/結果.json'),
                   plan_sha256=digest(planpath), audit_sha256=digest(Path(__file__)), financial_replays=0,
                   corrected_scope='旧監査はID下限だけで分類し、100万台の通常補完を注文不変照合から除外していた。今回は元base親集合で分類し全採用通常親を照合した。',
                   scope='保存会計・玉別停止と利確の判断根拠・早期入口の当時支持・採用した通常親と補完の注文不変。既知探索の一般優位を証明するものではない。')
    (HERE/'金融独立監査_早期_v2.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status='合格', **dict(counters)), ensure_ascii=False))


if __name__ == '__main__':
    main()
