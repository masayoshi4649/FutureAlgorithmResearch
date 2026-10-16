"""構造停止の全新規同一性と、実原板の未来を切った場合の判断不変を確認する。"""

from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks


def structural(result, ready, config):
    """
    機能: 過去極値から初期停止線を独立に復元し、当行破断フラグと照合する。
    引数: result/ready/config(dict)。
    返り値: intの構造線照合数。
    """
    evidence = result['structure_events']
    proofs = result['insurance_events']
    openings = result['satellite_orders'][result['satellite_orders'][:, 7] == 1]
    assert len(evidence) == len(proofs) == len(openings)
    for e, proof, order in zip(evidence, proofs, openings):
        row, cid, mode, source = map(int, e[:4])
        assert e[0] == proof[0] == order[0] and e[1] == proof[1] == order[2]
        assert mode == config['stop_mode'] and source == proof[5] < row
        extreme, old_line, line, entry, side, quantity, atr, broken = e[4:]
        assert extreme == proof[4] and entry == order[5] and side == order[3] and quantity == order[4]
        expected = checks.initial_line(mode, entry, extreme, side, atr, ready['tick'])
        assert abs(line - expected) < 1e-8
        expected_old = checks.initial_line(0, entry, extreme, side, atr, ready['tick'])
        assert abs(old_line - expected_old) < 1e-8
        assert bool(broken) == bool(-side * (ready['last'][row] - line) >= -1e-9)
        child = result['satellite_events']
        child = child[(child[:, 0] == row) & (child[:, 1] == cid) & (child[:, 2] == 3)]
        assert len(child) == 1 and child[0, 6] == line and child[0, 9] == 81
    return len(evidence)


def main():
    """
    機能: 主入口の四停止方式について、日夜・両商品・両モデルの会計と未来切断を検査する。
    引数: なし。
    返り値: None。全場の損益探索や条件選抜を行わない。
    """
    strategy, configs, prior, old = checks.load()
    before = checks.hashes()
    helper = checks.module('監査87構造停止切断道具', checks.ROOT / 'work/wave_v86/audit/support.py')
    prepare = checks.module('監査87構造停止基礎入力', checks.ROOT / 'work/wave_v85/prepare.py')
    permission = checks.module('監査87構造停止旧公開検査', checks.WORK.parent / 'round8/audit/prefixes.py')
    old_catalog = checks.module('監査87構造停止旧条件', checks.WORK.parent / 'round8/catalog.py')
    old_config = {c['id']: c for c in old_catalog.catalog()}['I_P50_R50_C1']
    inputs, signals, _ = prepare.load_inputs(verify=False)
    selected = {key: inputs[key] for key in [(s, p)
        for s in ('2026-09-25_Day', '2026-09-28_Night') for p in ('TOPIX', 'NK225')]}
    features = strategy.initialize(selected, signals)
    records = []
    for key, ready in selected.items():
        feature = features[key]
        for observed in (False, True):
            baseline, _ = old.play(old_config, ready, feature, observed)
            for mode in range(4):
                ident = f'K_P50_C1_S{mode}'
                result, settings = strategy.play(configs[ident], ready, feature, observed)
                for name in ('orders', 'trades', 'cycles', 'curve', 'stats'):
                    np.testing.assert_array_equal(result['core_result'][name], baseline['core_result'][name])
                openings = result['satellite_orders'][result['satellite_orders'][:, 7] == 1]
                old_openings = baseline['satellite_orders'][baseline['satellite_orders'][:, 7] == 1]
                np.testing.assert_array_equal(openings, old_openings)
                np.testing.assert_array_equal(result['insurance_events'], baseline['insurance_events'])
                if mode == 0:
                    for name in ('orders', 'trades', 'cycles', 'curve', 'stats',
                                 'satellite_orders', 'satellite_trades', 'satellite_curve', 'satellite_events'):
                        np.testing.assert_array_equal(result[name], baseline[name])
                tally = prior.accounting(ready, result, settings, strategy)
                proved = permission.permissions(configs[ident], ready, feature, result)
                assert structural(result, ready, configs[ident]) == proved
                events = result['satellite_events']
                cuts = {int(len(ready['last']) * .37), int(len(ready['last']) * .77)}
                for code in (1, 2, 3, 4, 5, 6, 7):
                    for event in events[events[:, 2] == code][:2]:
                        cuts.update((int(event[0]), int(event[0]) + 1))
                for proof in result['insurance_events'][:2]:
                    for row in (int(proof[0]), int(proof[3]), int(proof[5])):
                        cuts.update((row, row + 1))
                cuts = sorted(i for i in cuts if 2 < i < len(ready['last']))
                checked = 0
                for count in cuts:
                    short_ready = helper.clip(ready, count, len(ready['last']))
                    short_feature = helper.clip(feature, count, len(ready['last']))
                    prefix, _ = strategy.play(configs[ident], short_ready, short_feature, observed)
                    checked += helper.compare_prefix(result, prefix, count)
                    checked += helper.compare_prefix(result['core_result'], prefix['core_result'], count)
                    for name, column in (('satellite_orders', 0), ('satellite_trades', 7),
                                         ('satellite_events', 0), ('insurance_events', 0), ('structure_events', 0)):
                        values = result[name]
                        np.testing.assert_array_equal(values[values[:, column] < count], prefix[name], err_msg=name)
                        checked += 1
                    np.testing.assert_array_equal(result['satellite_curve'][:count], prefix['satellite_curve'])
                    checked += 1
                records.append(dict(セッション=key[0], 商品=key[1], 条件=ident, 観測約定=observed,
                    切断地点=len(cuts), 配列照合数=checked, 入口構造線照合数=proved, **tally))
                print(key, ident, observed, len(cuts), '元玉・保険入口不変・構造線・未来切断一致', flush=True)
    assert before == checks.hashes()
    checks.save('構造停止の入口不変と公開根拠と未来切断.json', dict(全合格=True, 条件口座数=len(records),
        切断地点=sum(r['切断地点'] for r in records), 配列照合数=sum(r['配列照合数'] for r in records),
        入口構造線照合数=sum(r['入口構造線照合数'] for r in records), 検査=records, コードSHA256=before))


if __name__ == '__main__':
    main()
