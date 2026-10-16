"""保険の相殺・再露出・元玉終了という実データの分岐点を選んで未来を切断する。"""

from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks
import prefixes


def main():
    """
    機能: 二つの異なる保険入口と三実行方式の分岐を日夜・両商品で切断する。
    引数: なし。
    返り値: None。分岐の時刻だけを使い、損益の大小で対象を選ばない。
    """
    _, _, catalog = checks.load()
    strategy = checks.module('監査87相殺分岐接続', checks.WORK / 'strategy.py')
    before = checks.hashes()
    helper = checks.module('監査87相殺分岐切断', checks.ROOT / 'work/wave_v86/audit/support.py')
    prepare = checks.module('監査87相殺分岐入力', checks.ROOT / 'work/wave_v85/prepare.py')
    inputs, signals, _ = prepare.load_inputs(False)
    selected = {key: inputs[key] for key in [(s, p)
        for s in ('2026-09-25_Day', '2026-09-28_Night') for p in ('TOPIX', 'NK225')]}
    features = strategy.initialize(selected, signals)
    configs = [c for c in catalog.catalog() if c['source_id'] in ('C_H05_S25', 'I_P00_R50_C1')]
    records = []
    for key, ready in selected.items():
        feature = features[key]
        for config in configs:
            result, _ = strategy.play(config, ready, feature, True)
            cuts = set()
            points = []
            feed = result['virtual_feed']
            for label, subset in (('保険新規', feed[(feed[:, 8] == 1) & (feed[:, 7] == 1)]),
                                  ('保険返済', feed[(feed[:, 8] == 1) & (feed[:, 7] == 0)])):
                if len(subset):
                    source = int(subset[0, 0])
                    valid = np.flatnonzero(np.isfinite(ready['last'][source + 1:]) & (ready['last'][source + 1:] > 0))
                    fill = source + 1 + int(valid[0])
                    cuts.update((source, source + 1, fill, fill + 1))
                    points.append(dict(種別=label, 観測行=source, 次有効行=fill))
            virtual = result['virtual_result']
            core_cycles = result['core_result']['cycles']
            sat = virtual['satellite_orders']
            for cycle in core_cycles:
                related = sat[(sat[:, 2] == cycle[0]) & (sat[:, 7] == 1)]
                if len(related):
                    source = int(cycle[2])
                    valid = np.flatnonzero(np.isfinite(ready['last'][source + 1:]) & (ready['last'][source + 1:] > 0))
                    fill = source + 1 + int(valid[0])
                    cuts.update((source, source + 1, fill, fill + 1))
                    points.append(dict(種別='保険がある親の元玉終了', 観測行=source, 次有効行=fill))
                    break
            state = result['execution_states']
            candidate = np.flatnonzero((state[:, 4] + state[:, 5] == 0) & ((state[:, 1] != 0) | (state[:, 2] != 0)))
            for row in candidate:
                opened = result['orders'][(result['orders'][:, 2] == state[row, 3]) &
                                           (result['orders'][:, 7] == 1) & (result['orders'][:, 0] < row)]
                if len(opened):
                    cuts.update((int(row), int(row) + 1))
                    points.append(dict(種別='同じ実親の差引ゼロ・仮想は継続', 観測行=int(row)))
                    break
            compared = 0
            selected_cuts = sorted(c for c in cuts if 2 < c < len(ready['last']))
            for count in selected_cuts:
                small = helper.clip(ready, count, len(ready['last']))
                small_feature = helper.clip(feature, count, len(ready['last']))
                prefix, _ = strategy.play(config, small, small_feature, True)
                compared += prefixes.same_execution(result, prefix, count)
                compared += prefixes.same_virtual(result['virtual_result'], prefix['virtual_result'], helper, count)
                compared += prefixes.same_virtual(result['core_result'], prefix['core_result'], helper, count)
            records.append(dict(セッション=key[0], 商品=key[1], 条件=config['id'],
                分岐=points, 切断地点=len(selected_cuts), 配列照合数=compared))
            print(key, config['id'], len(selected_cuts), '保険新規・相殺・元終了の分岐一致', flush=True)
    assert before == checks.hashes()
    checks.save('差引実行の保険相殺と元玉終了の分岐切断.json', dict(全合格=True, 条件口座数=len(records),
        切断地点=sum(r['切断地点'] for r in records), 配列照合数=sum(r['配列照合数'] for r in records),
        検査=records, コードSHA256=before))


if __name__ == '__main__':
    main()
