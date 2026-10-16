"""原本の未来切断と、基準E01_G_Uの旧注文一致を検査する。"""

import argparse
import pickle

import numpy as np

from support import ROOT, WORK, components, clip, compare_prefix, save, source_hashes


def verify_orders(result, ready, config):
    """
    機能: 原本行順・返済起点の休止・新準備の公開順を台帳から検査する。
    引数: result/ready/config (dict)。
    返り値: dictの件数。損益優劣は判断しない。
    """
    orders = result['orders']
    assert np.all(orders[:, 1] < orders[:, 0]), '当行又は未来で新たに作った条件の当行約定'
    preparations = result['prepare_events']
    prep_map = {int(p[0]): p for p in preparations}
    entries = result['entry_preparations']
    for cid, fill, pid, prepared in entries:
        assert prepared < fill
        assert int(pid) in prep_map
        assert prep_map[int(pid)][1] == prepared
    if config['reentry_mode'] == 'actual':
        cycles = result['cycles']
        entry_orders = orders[orders[:, 7] == 1]
        for previous, current in zip(cycles[:-1], cycles[1:]):
            previous_row, current_row = int(previous[2]), int(current[1])
            assert current_row > previous_row
            assert ready['time_s'][current_row] >= ready['time_s'][previous_row] + config['cooldown_seconds']
            linked = entries[entries[:, 1] == current_row]
            assert len(linked) == 1
            prepared_row = int(linked[0, 3])
            assert prepared_row > previous_row
            assert ready['time_s'][prepared_row] >= ready['time_s'][previous_row] + config['cooldown_seconds']
        for exit_row, reflected, allowed, _, _, _ in result.get('reentry_events', []):
            assert reflected > exit_row
            assert allowed == ready['time_s'][int(exit_row)] + config['cooldown_seconds']
    return dict(注文数=len(orders), 実組数=len(result['cycles']), 準備数=len(preparations),
                再参加反映数=len(result.get('reentry_events', [])), 短縮数=len(result.get('dynamic_events', [])))


def verify_original_gate(strategy, result, ready, feature):
    """
    機能: 通常影のオンライン半減根拠を、旧gate_badの独立再走査に一致させる。
    引数: strategy (module)、result/ready/feature (dict)。
    返り値: None。
    """
    _, _, expected = strategy.base.integration.reference.gate.gate_bad(ready,result['normal_shadow'],
        feature['columns'][1],feature['columns'][2],1.5,mode='direction',valid=feature['valid'])
    actual=result['gate_evidence']
    for name in ('arm_row','armed','eligible'):
        np.testing.assert_array_equal(actual[name],expected[name],err_msg='旧半減根拠 '+name)
    held=result['normal_shadow']['plans'][:,0]!=0
    np.testing.assert_array_equal(actual['mfe_atr'][held],expected['mfe_atr'][held],err_msg='旧半減根拠MFE')


def main():
    """
    機能: 日中・夜間の両商品で未来を切断して再生し、過去の全配列を照合する。
    引数: コマンドライン --quick (bool) は1モデル2口座へ限定する。
    返り値: None。新結果を候補選抜に用いない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    strategy, catalog, old, prepare = components()
    inputs, signals, _ = prepare.load_inputs(verify=False)
    features = strategy.initialize(inputs, signals)
    configs = {c['id']: c for c in catalog.catalog()}
    chosen = ['T0_A5', 'T3_A1', 'T4_A0']
    keys = [(day, symbol) for day in ('2026-10-05_Day', '2026-10-09_Night')
            for symbol in ('TOPIX', 'NK225')]
    models = (True, False)
    if args.quick:
        keys = [keys[0], keys[-1]]
        models = (True,)
    records, baseline = [], []
    hashes = source_hashes()
    checks = 0
    for observed in models:
        model = 'observed' if observed else 'specified'
        reference = pickle.loads((ROOT / 'work/wave_v85' / model / 'ledgers/E01_G_U.pkl').read_bytes())
        for key in keys:
            ready, feature = inputs[key], features[key]
            n = len(ready['last'])
            base, settings = strategy.play(configs['E01_G_U'], ready, feature, observed=observed)
            generated, generated_settings = strategy.play(dict(configs['E01_G_U'],
                id='監査_新生成器の元設定'), ready, feature, observed=observed)
            assert generated_settings == settings
            for name, value in base.items():
                if isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(value, generated[name], err_msg='新生成器 '+name)
            for name, value in base['shadow'].items():
                if isinstance(value, np.ndarray):
                    np.testing.assert_array_equal(value, generated['shadow'][name], err_msg='新出口影 '+name)
            for name in ('orders', 'trades', 'cycles', 'time_events', 'prepare_events', 'entry_preparations'):
                np.testing.assert_array_equal(base[name], reference[key][name], err_msg=str((key, name)))
            row, ledger, equity = old.account(strategy.previous, ready, base, settings)
            assert ledger['curve_SHA256'] == reference[key]['curve_SHA256']
            baseline.append(dict(セッション=key[0], 銘柄=key[1], モデル=model, 旧基準完全一致=True,
                新生成器を迂回しない元設定一致=True))
            del base, generated, equity
            for ident in chosen:
                config = configs[ident]
                full, _ = strategy.play(config, ready, feature, observed=observed)
                stats = verify_orders(full, ready, config)
                verify_original_gate(strategy,full,ready,feature)
                cuts = {max(2, int(n * ratio)) for ratio in (.23, .57, .89)}
                for name, col in (('reentry_events', 1), ('dynamic_events', 0), ('time_events', 0)):
                    for event in full.get(name, [])[:2]:
                        i = int(event[col])
                        cuts.update((max(2, i), min(n - 1, i + 1), min(n - 1, i + 2)))
                for count in sorted(cuts):
                    current = clip(ready, count, n)
                    own_feature = clip(feature, count, n)
                    part, _ = strategy.play(config, current, own_feature, observed=observed)
                    checks += compare_prefix(full, part, count)
                records.append(dict(条件=ident, セッション=key[0], 銘柄=key[1], モデル=model,
                    切断数=len(cuts), 切断行=sorted(cuts), 過去の実玉と両影一致=True,
                    原半減根拠の独立再計算一致=True, **stats))
                print(ident, key, model, len(cuts), '切断一致', flush=True)
    assert source_hashes() == hashes, '監査中に実装又は監査器が変更されています'
    save('実返済時計と動的幅の未来切断.json', dict(全合格=True, 基準照合=baseline, 検査=records,
        切断数=sum(v['切断数'] for v in records), 配列照合数=checks, 実装SHA256=hashes,
        制約='公開済みの入力特徴以降を監査。EMA/ATR/B00の原本因果性は旧準備監査を参照。真の受信時計は復元しない。',
        新結果による候補選抜=False))


if __name__ == '__main__':
    main()
