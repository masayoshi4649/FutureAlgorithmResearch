"""完了済み50場の保存結果のみから、最後の集約保存を復元する。"""

import json
import pickle
from pathlib import Path
import numpy as np
import run_residual145 as driver


def main():
    """既存の会計結果・約定記録を照合し、集約資料を保存する。

    引数: なし。
    返り値: None。売買シミュレーションや会計の再計算は実行しない。
    """
    root, here = driver.ROOT, driver.HERE
    receipt = root / 'work/research145_report/会計修正登録受領145.json'
    inventory = json.loads((root / 'work/research145_data/全保存資料の再照合145.json').read_text(encoding='utf-8'))
    configs = json.loads((here / '残玉条件145.json').read_text(encoding='utf-8'))
    rows, manifest, audits = [], [], []
    for scene in inventory['known_sessions']:
        saved = json.loads((here / 'results' / f'{scene}.json').read_text(encoding='utf-8'))
        assert saved['session'] == scene and len(saved['rows']) == len(configs)
        item = saved['cache']
        for part in ('orders', 'traces', 'cache'):
            assert driver.ref(root / item[part]['path']) == item[part]
        with (root / item['cache']['path']).open('rb') as stream:
            packet, data, raw, baseline, label = pickle.load(stream)
        with np.load(root / item['orders']['path']) as orders:
            for cfg in configs:
                method = cfg['id']
                check = driver.verify(data, orders[method], 10)
                if method == 'R00':
                    np.testing.assert_array_equal(orders['CG_R00'], baseline['CG04'])
                    np.testing.assert_array_equal(orders['CS_R00'], baseline['CS04'])
                check.update(session=scene, method=method, reference_equal=method == 'R00')
                audits.append(check)
        rows.extend(saved['rows'])
        manifest.append(item)
    assert len(rows) == len(audits) == 800
    driver.save(here / '残玉と部分利確後の全場結果145.json', dict(
        rows=rows, cache=manifest, configs=configs,
        registration=driver.ref(receipt),
        implementation=[driver.ref(here / 'run_residual145.py'), driver.ref(here / 'residual145.py')],
        financial_accounts=len(rows), API=0, real_orders=0, source_readonly=True,
        recovery=dict(
            reason='全50場の保存完了後、受領書の相対パスを絶対パス基準で変換して集約保存だけが失敗した。',
            action='保存済み会計・約定・追跡記録のSHAを照合し、約定の機械検査を再適用して集約を復元。金融再生・会計再計算なし。',
            script=driver.ref(Path(__file__).resolve()), financial_replays=0)))
    driver.save(here / '全注文機械検査145.json', dict(all_passed=True, rows=audits))
    print('保存済み50場・800会計の集約復元完了。金融再生なし。', flush=True)


if __name__ == '__main__':
    main()
