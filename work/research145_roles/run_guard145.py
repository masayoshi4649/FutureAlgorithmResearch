"""登録後にV16/V17だけを全50場再生し、追加注文と基準合成の会計を保存する。"""

import argparse
import json
from pathlib import Path
import pickle
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT/'work/research145_engine'), str(ROOT/'work/research145_residual')]
import addon_guard145 as guard
import account145
import config145
import run145
import run_residual145 as saved
import source145
import trader_guard145


def run(registration):
    """
    機能: 登録・固定入力のSHAを確認して二条件を再生し、役割合成へ固定注文を引き渡す。
    引数: registration(Path)は事前登録完了受領書。
    返り値: None。未登録時・入力変更時は実データの再生前に停止する。
    """
    registration = registration.resolve()
    receipt = json.loads(registration.read_text(encoding='utf-8-sig'))
    assert receipt.get('returncode') == 0, '完了した事前登録が必要'
    files = ['run_guard145.py', 'addon_guard145.py', 'trader_guard145.py', 'test_guard145.py',
             'ドテン確認条件145.json', '保存入力145.json']
    for name in files:
        record = saved.ref(HERE/name)
        assert receipt['implementation'][record['path']] == record['sha256'], '登録SHAと実装が不一致'
    spec = json.loads((HERE/'ドテン確認条件145.json').read_text(encoding='utf-8'))
    assert spec['configs'] == guard.configurations()
    manifest = json.loads((HERE/'保存入力145.json').read_text(encoding='utf-8'))
    assert len(manifest['sessions']) == 50
    accounts, checks, sources = [], [], []
    reference = next(c for c in config145.configurations() if c['id'] == 'V10')
    for item in manifest['sessions']:
        scene = item['session']
        path = HERE/'new_addon'/f'{scene}.npz'
        target = HERE/'new_addon_results'/f'{scene}.json'
        assert not path.exists() and not target.exists(), '完成資料を黙って再生成しない'
        for part in ('cache', 'addon'):
            assert saved.ref(ROOT/item[part]['path']) == item[part], '登録した入力と不一致'
        with (ROOT/item['cache']['path']).open('rb') as stream:
            packet, data, raw, baseline, label = pickle.load(stream)
        # ----------------------------------------
        # 制約0の完全同値対照。変更対象以外のV10売買を変えていないことを全場で確認する。
        control = trader_guard145.replay(data, source145.first143.addon_config(scene, 3), reference)[0]
        with np.load(ROOT/item['addon']['path']) as prior:
            np.testing.assert_array_equal(control, prior['A_V10'], err_msg=scene+' V10同値対照')
        additions = guard.prepare_addons(scene, packet, data, raw, baseline, label)
        arrays, localrows, localchecks = {}, [], []
        for method, orders in additions.items():
            arrays['A_'+method] = orders
            localchecks.append(dict(method=method, role='追加', **run145.check_orders(orders, data, 3)))
            combined = source145.shared.merge(baseline['CG04'], orders, baseline['CS04'])
            arrays[method] = combined
            localchecks.append(dict(method=method, role='全体', **run145.check_orders(combined, data, 10)))
            account = account145.account(combined, packet, method, label)
            cash = float(np.sum(-combined[:,3]*combined[:,4]*combined[:,5]*100.-combined[:,9]))
            assert abs(account['net']-cash) < 1e-7
            account.update(split='既知開発50場・第二段階確認ドテン', fees_policy='手数料0・次正常気配')
            localrows.append(account)
        # ----------------------------------------
        # 全明細を先に確定し、最後のmanifestだけを役割合成の完成通知に用いる。
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **arrays)
        record = dict(session=scene, orders=saved.ref(path), rows=localrows, checks=localchecks,
                      control_v10_equal=True, input=item, registration=saved.ref(registration))
        saved.save(target, record)
        accounts.extend(localrows)
        checks.extend(dict(check, session=scene) for check in localchecks)
        sources.append(dict(session=scene, orders=record['orders']))
        print(scene+' V16/V17とV10同値確認 完了', flush=True)
    assert len(accounts) == 100 and len(checks) == 200
    saved.save(HERE/'ドテン確認の全場結果145.json', dict(rows=accounts, checks=checks, configs=guard.configurations(),
               registration=saved.ref(registration), market_replays=100, equivalence_replays=50, API=0, real_orders=0))
    saved.save(HERE/'new_addon_manifest145.json', dict(registration=saved.ref(registration), sessions=sources,
               configs=guard.configurations(), result=saved.ref(HERE/'ドテン確認の全場結果145.json')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--registration', type=Path, required=True)
    run(parser.parse_args().registration)
