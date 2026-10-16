"""自己と相手の未来を別々に除き、入口・通知・実注文の因果性を照合する。"""

from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks


def same_execution(full, shorter, count):
    """
    機能: 入口・相手初通知・次観測実注文と、当時確定済みの親組を切断照合する。
    引数: full/shorter(dict)、count(int)。
    返り値: intの配列照合数。
    """
    total = 0
    for name, column in (('orders', 0), ('trades', 7), ('execution_events', 0), ('peer_events', 0), ('virtual_feed', 0)):
        original = full[name]
        np.testing.assert_array_equal(original[original[:, column] < count], shorter[name], err_msg=name)
        total += 1
    for name in ('curve', 'execution_states'):
        np.testing.assert_array_equal(full[name][:count], shorter[name], err_msg=name)
        total += 1
    np.testing.assert_array_equal(full['order_uids'][:len(shorter['orders'])], shorter['order_uids'])
    finished = {int(c[0]) for c in shorter['core_result']['cycles']}
    expected = np.asarray([c for c in full['cycles'] if c[0] in finished and c[2] < count]).reshape(-1, 10)
    np.testing.assert_array_equal(expected, shorter['cycles'])
    return total + 2


def clipped(ready, feature, count, helper, remove_peer_future):
    """
    機能: 自己配列を切り、必要なら相手の厳密過去までの素材だけを残す。
    引数: ready/feature(dict)、count(int)、helper(module)、remove_peer_future(bool)。
    返り値: tuple[dict,dict]。同じ長さの別市場配列を誤って自己行数で切らない。
    """
    n = len(ready['last'])
    reduced_ready = helper.clip(ready, count, n)
    reduced_feature = helper.clip({k: v for k, v in feature.items() if k != 'peer'}, count, n)
    peer = feature['peer']
    reduced_peer = dict(peer, ref=peer['ref'][:count].copy())
    if remove_peer_future:
        until = int(np.searchsorted(peer['time_s'], reduced_ready['time_s'][-1], side='left'))
        for name in ('time_s', 'last', 'seq'):
            reduced_peer[name] = peer[name][:until].copy()
        reduced_peer['feed'] = peer['feed'][peer['feed'][:, 0] < until].copy()
        assert np.all(reduced_peer['ref'] < until)
    reduced_feature['peer'] = reduced_peer
    return reduced_ready, reduced_feature


def poisoned(feature, last_time):
    """
    機能: 未公開の相手価格・注文だけを極端な値へ改変する反証入力を作る。
    引数: feature(dict)、last_time(float)は最後の自己時計。
    返り値: dict。公開済み素材と原特徴を変更しない。
    """
    peer = dict(feature['peer'])
    cut = int(np.searchsorted(peer['time_s'], last_time, side='left'))
    prices = peer['last'].copy()
    prices[cut:] = 777777.
    feed = peer['feed'].copy()
    future = feed[:, 0] >= cut
    feed[future, 3] *= -1
    feed[future, 4] *= 7
    feed[future, 5] = 888888.
    feed[future, 9] = 9999.
    peer['last'], peer['feed'] = prices, feed
    return dict(feature, peer=peer)


def main():
    """
    機能: 固定二場・両商品・全十二改修の未来切断と公開根拠を検査する。
    引数: なし。
    返り値: None。全三十場の損益探索や代表選抜を行わない。
    """
    _, material, previous, fees = checks.load()
    strategy = checks.module('監査87相手判断戦略', checks.WORK / 'strategy.py')
    catalog = checks.module('監査87相手判断条件', checks.WORK / 'catalog.py')
    before = checks.hashes()
    helper = checks.module('監査87相手切断道具', checks.ROOT / 'work/wave_v86/audit/support.py')
    prepare = checks.module('監査87相手切断基礎入力', checks.ROOT / 'work/wave_v85/prepare.py')
    inputs, signals, _ = prepare.load_inputs(verify=False)
    selected = {key: inputs[key] for key in [(s, p) for s in ('2026-09-25_Day', '2026-09-28_Night')
                                           for p in ('TOPIX', 'NK225')]}
    features = strategy.initialize(selected, signals)
    configs = [c for c in catalog.catalog() if c['execution_mode'] != 'IDEAL']
    records = []
    for key, ready in selected.items():
        feature = features[key]
        baseline = strategy.virtual(configs[0], ready, feature)[0]
        for config in configs:
            result, settings = strategy.play(config, ready, feature, True)
            helper.compare_prefix(baseline, result['core_result'], len(ready['last']))
            tally = previous.account(ready, result, fees, settings['audit_cap'])
            evidence = checks.inspect(ready, result['virtual_feed'], feature['peer'], result,
                config['entry_mode'], config['holding_mode'], material)
            cuts = {int(len(ready['last']) * .37), int(len(ready['last']) * .77)}
            for name, codes in (('execution_events', (1, 2, 3, 4)), ('peer_events', (1, 2, 3))):
                events = result[name]
                for code in codes:
                    matching = events[events[:, 1] == code]
                    chosen = list(matching[:2])
                    if len(matching) and code in (3, 4):
                        chosen.append(matching[-1])
                    for event in chosen:
                        i = int(event[0])
                        cuts.update((i, i + 1, i + 2))
            for cycle in result['cycles'][:1]:
                cuts.update((int(cycle[2]), int(cycle[2]) + 1))
            cuts = sorted(c for c in cuts if 2 < c < len(ready['last']))
            checked = poison_count = 0
            for count in cuts:
                for remove in (False, True):
                    short_ready, short_feature = clipped(ready, feature, count, helper, remove)
                    short, _ = strategy.play(config, short_ready, short_feature, True)
                    checked += same_execution(result, short, count)
                    checked += helper.compare_prefix(result['core_result'], short['core_result'], count)
                    checked += helper.compare_prefix(result['virtual_result'], short['virtual_result'], count)
                if count in (cuts[0], cuts[-1]):
                    short_ready, short_feature = clipped(ready, feature, count, helper, False)
                    altered = poisoned(short_feature, short_ready['time_s'][-1])
                    alternative, _ = strategy.play(config, short_ready, altered, True)
                    checked += same_execution(result, alternative, count)
                    checked += helper.compare_prefix(result['core_result'], alternative['core_result'], count)
                    poison_count += 1
            records.append(dict(セッション=key[0], 商品=key[1], 条件=config['id'],
                切断地点=len(cuts), 二市場切断再生数=len(cuts) * 2, 未公開改変数=poison_count,
                配列照合数=checked, **evidence, **tally))
            print(key, config['id'], len(cuts), '自己相手切断・未来改変・公開根拠一致', flush=True)
    assert before == checks.hashes()
    checks.save('相手GU参照と自己判断の未来切断.json', dict(全合格=True,
        条件口座数=len(records), 切断地点=sum(r['切断地点'] for r in records),
        二市場切断再生数=sum(r['二市場切断再生数'] for r in records),
        未公開改変数=sum(r['未公開改変数'] for r in records), 配列照合数=sum(r['配列照合数'] for r in records),
        実縮小確認数=sum(r['実縮小数'] for r in records), 検査=records, コードSHA256=before,
        未完親組='自己paper親組が未完なら、実玉が先に空でも将来の最終損益として分類しない。',
        切断方法='自己だけを切る対照に加え、相手も自己最後の時計より厳密過去まで短縮。未公開の相手注文と価格を改変しても過去の売買は不変。'))
    print('全48口座の未来切断と相手公開根拠が合格', flush=True)


if __name__ == '__main__':
    main()
