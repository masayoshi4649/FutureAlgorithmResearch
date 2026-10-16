"""逆行保険の公開根拠、元玉不変、未来切断と注文会計を独立に検査する。"""

from pathlib import Path
import math
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks


def permissions(config, ready, feature, result):
    """
    機能: 保険実新規の最終許可時点へ戻り、価格極値と両市場の公開根拠を検算する。
    引数: config/ready/feature/result(dict)。
    返り値: intの照合済み実新規数。
    """
    core = result['core_result']
    initial = {int(o[2]): o for o in core['orders'] if o[7]}
    short = feature['short']
    seen = set()
    for proof in result['insurance_events']:
        row, cid, reserved, permitted = map(int, proof[:4])
        assert cid not in seen
        seen.add(cid)
        order = initial[cid]
        start, side, entry = int(order[0]), int(order[3]), float(order[5])
        atr = float(core['shadow']['execution_plans'][start, 24])
        extreme, extreme_row, line = proof[4], int(proof[5]), proof[6]
        assert start <= extreme_row <= permitted < row
        assert start <= reserved <= permitted < row
        prices = ready['last'][start:permitted + 1]
        prices = prices[np.isfinite(prices) & (prices > 0)]
        expected = max(entry, float(prices.max())) if side > 0 else min(entry, float(prices.min()))
        assert abs(expected - extreme) < 1e-8
        if extreme_row == start and abs(extreme - entry) < 1e-8:
            pass
        else:
            assert extreme == ready['last'][extreme_row]
        assert side * (extreme - entry) >= config['prepare_atr'] * atr - 1e-8
        raw_line = extreme - side * max(ready['tick'], config['pullback_atr'] * atr)
        expected_line = (math.floor(raw_line / ready['tick'] + 1e-9) if side > 0
                         else math.ceil(raw_line / ready['tick'] - 1e-9)) * ready['tick']
        assert abs(line - expected_line) < 1e-8
        fields = ('self_value', 'peer_value', 'self_valid', 'peer_valid',
                  'self_source_seq', 'peer_source_seq', 'self_source_time', 'peer_source_time',
                  'self_release_seq', 'peer_release_seq', 'self_release_time', 'peer_release_time')
        np.testing.assert_array_equal(proof[7:], [short[f][permitted] for f in fields])
        if config['confirm']:
            assert bool(proof[9]) and bool(proof[10])
            assert -side * proof[7] > .05 and -side * proof[8] > .05
            assert proof[15] <= ready['seq'][permitted]
            assert proof[18] < ready['time_s'][permitted]
            assert proof[11] <= proof[15] and proof[12] <= proof[16]
            assert proof[13] <= proof[17] and proof[14] <= proof[18]
        sat = result['satellite_orders']
        opened = sat[(sat[:, 2] == cid) & (sat[:, 7] == 1)]
        assert len(opened) == 1 and opened[0, 0] == row
        assert opened[0, 1] == reserved and opened[0, 3] == -side
        assert opened[0, 4] == order[4]
    assert len(seen) == int(result['satellite_orders'][:, 7].sum())
    return len(seen)


def main():
    """
    機能: 日夜・両商品・両約定モデルの代表条件について未来の価格と注文を切断する。
    引数: なし。
    返り値: None。監査証跡を保存し、全セッション成績の選抜は行わない。
    """
    strategy, configs, prior = checks.load()
    before = checks.hashes()
    helper = checks.module('監査87保険未来切断道具', checks.ROOT / 'work/wave_v86/audit/support.py')
    prepare = checks.module('監査87保険基礎入力', checks.ROOT / 'work/wave_v85/prepare.py')
    inputs, signals, _ = prepare.load_inputs(verify=False)
    selected = {key: inputs[key] for key in [(s, p)
        for s in ('2026-09-25_Day', '2026-09-28_Night') for p in ('TOPIX', 'NK225')]}
    features = strategy.initialize(selected, signals)
    records = []
    for key, ready in selected.items():
        feature = features[key]
        for observed in (False, True):
            core, _ = strategy.old.play(dict(id='E01_G_U', mask=1, time_mode='U', changes={}),
                                         ready, feature, observed)
            for ident in ('I_P00_R25_C0', 'I_P25_R25_C1', 'I_P50_R50_C0', 'I_P50_R50_C1'):
                result, settings = strategy.play(configs[ident], ready, feature, observed)
                for name in ('orders', 'trades', 'cycles', 'curve', 'stats'):
                    np.testing.assert_array_equal(result['core_result'][name], core[name])
                tally = prior.accounting(ready, result, settings, strategy)
                proved = permissions(configs[ident], ready, feature, result)
                events = result['satellite_events']
                cuts = {int(len(ready['last']) * .37), int(len(ready['last']) * .77)}
                for code in range(1, 10):
                    for event in events[events[:, 2] == code][:2]:
                        cuts.update((int(event[0]), int(event[0]) + 1))
                for proof in result['insurance_events'][:2]:
                    for row in (int(proof[0]), int(proof[2]), int(proof[3])):
                        cuts.update((row, row + 1))
                cuts = sorted(i for i in cuts if 2 < i < len(ready['last']))
                checked = 0
                for count in cuts:
                    shortened = helper.clip(ready, count, len(ready['last']))
                    short_feature = helper.clip(feature, count, len(ready['last']))
                    prefix, _ = strategy.play(configs[ident], shortened, short_feature, observed)
                    checked += helper.compare_prefix(result, prefix, count)
                    checked += helper.compare_prefix(result['core_result'], prefix['core_result'], count)
                    for name, column in (('satellite_orders', 0), ('satellite_trades', 7),
                                         ('satellite_events', 0), ('insurance_events', 0)):
                        values = result[name]
                        np.testing.assert_array_equal(values[values[:, column] < count], prefix[name], err_msg=name)
                        checked += 1
                    np.testing.assert_array_equal(result['satellite_curve'][:count], prefix['satellite_curve'])
                    checked += 1
                records.append(dict(セッション=key[0], 商品=key[1], 条件=ident, 観測約定=observed,
                    切断地点=len(cuts), 配列照合数=checked, 元支持照合新規=proved, **tally))
                print(key, ident, observed, len(cuts), '元玉不変・支持公開・会計・未来切断一致', flush=True)
    assert before == checks.hashes()
    checks.save('逆行保険の元玉不変と公開根拠と未来切断.json', dict(全合格=True, 条件口座数=len(records),
        切断地点=sum(r['切断地点'] for r in records), 配列照合数=sum(r['配列照合数'] for r in records),
        元支持照合新規=sum(r['元支持照合新規'] for r in records), 検査=records, コードSHA256=before))


if __name__ == '__main__':
    main()
