"""登録済み16条件を全50場で比較し、各担当の全注文と会計を保存する。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pickle
import numpy as np

import source145 as src
import trader145 as trader
import account145
from config145 import configurations

HERE, ROOT, shared = src.HERE, src.ROOT, src.shared


def save_json(path, value):
    """
    機能: UTF-8の研究資料を非有限値なしで保存する。
    引数: path(Path)、value(dict又はlist)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def check_orders(rows, data, cap):
    """
    機能: 費用0、判断後約定、BBO、建玉ID別残数、方向別上限、最後の全返済を検査する。
    引数: rows(ndarray)、data(dict)、cap(int)。返り値: dictは確認した件数と最大保有。
    """
    rows = np.asarray(rows)
    assert rows.ndim == 2 and rows.shape[1] == 10
    assert np.isfinite(rows).all()
    assert np.all(rows[:, 0] > rows[:, 1]) and np.all(np.diff(rows[:, 0]) >= 0.)
    assert np.all(rows[:, 9] == 0.)
    q = data['quotes']
    good = q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['ask'] > q['bid']) & (q['bid'] > 0.)
    positions = {}
    maximum = 0
    for row in rows:
        fill, decision = int(row[0]), int(row[1])
        assert good[fill] and not np.any(good[decision+1:fill])
        assert row[5] == (q['ask'][fill] if row[3] > 0. else q['bid'][fill])
        key = (int(row[2]), int(row[8]))
        qty = int(row[4])
        assert qty == row[4] and qty > 0
        if row[7]:
            assert key not in positions or positions[key][0] == row[3]
            prior = positions.get(key, (int(row[3]), 0))
            positions[key] = (prior[0], prior[1]+qty)
        else:
            assert key in positions and positions[key][0] == -row[3] and positions[key][1] >= qty
            side, old = positions[key]
            positions[key] = (side, old-qty)
        for side in (-1, 1):
            total = sum(value[1] for value in positions.values() if value[0] == side)
            maximum = max(maximum, total)
            assert total <= cap
    assert not any(value[1] for value in positions.values())
    return dict(orders=len(rows), maximum_per_side=maximum, all_closed=True, next_normal_bbo=True, fee=0)


def same_path(a, b):
    """
    機能: 手数料列を除いた約定経路を比較する。
    引数: a/b(ndarray)。返り値: bool。
    """
    return a.shape == b.shape and np.array_equal(a[:, :9], b[:, :9])


def run(registration):
    """
    機能: 事前登録受領後だけ、全保存場を固定条件で再生する。
    引数: registration(Path)はreturncode=0の登録受領JSON。返り値: None。
    """
    receipt = json.loads(registration.read_text(encoding='utf-8-sig'))
    assert receipt.get('returncode') == 0, '事前登録完了の受領記録が必要です'
    packets, _, _ = shared.material()
    rows, checks, fee_changes = [], [], []
    for item in packets:
        scene = item['session']
        target = HERE / 'results' / f'{scene}.json'
        if target.exists():
            old = shared.read(target)
            rows.extend(old['rows']); checks.extend(old['checks']); fee_changes.append(old['fee_change'])
            continue
        packet, data, raw, baseline, label = src.prepare_scene(scene)
        # ----------------------------------------
        # 同じ情報を第二巡が再計算しないよう、当場・当商品の必要資料だけを保存する。
        key = (scene, 'NK225')
        packet = dict(session=scene, inputs={key:data['ready']}, quotes={key:data['quotes']})
        cache = HERE / 'cache' / f'{scene}.pkl'
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix('.tmp')
        with tmp.open('wb') as stream:
            pickle.dump((packet, data, raw, baseline, label), stream, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cache)
        arrays = dict(CG=raw['CG'], CS=raw['CS'], **baseline)
        with np.load(src.OLD / 'round3/measurement' / f'NK225_{scene}.npz') as archive:
            old_cg = archive['CG04']
            old_cs = archive['CS04']
            old_tg = archive['TG04'].copy()
        old_tg[:, 9] = 0.
        arrays['旧経路の費用列のみ0'] = old_tg
        prior_addon = src.replay_active(data, src.first143.addon_config(scene, 3), fee10=385)
        with np.load(src.OLD / 'round1/measurement' / f'NK225_{scene}.npz') as archive:
            np.testing.assert_array_equal(prior_addon, archive['A3'], err_msg=scene+'旧追加の完全一致')
        new_tg = shared.merge(baseline['CG04'], baseline['A3'], baseline['CS04'])
        change = dict(session=scene, core_path_changed=not same_path(old_cg, baseline['CG04']),
                      secondary_path_changed=not same_path(old_cs, baseline['CS04']),
                      addon_path_changed=not same_path(prior_addon, baseline['A3']),
                      full_path_changed=not same_path(old_tg, new_tg))
        own_checks = []
        for config in configurations():
            code = config['id']
            addon, _, _ = trader.replay(data, src.first143.addon_config(scene, 3), config)
            if code == 'V00':
                np.testing.assert_array_equal(addon, baseline['A3'], err_msg=scene+'V00完全一致')
            orders = shared.merge(baseline['CG04'], addon, baseline['CS04'])
            arrays['A_'+code], arrays[code] = addon, orders
            own_checks.append(dict(session=scene, method=code, **check_orders(orders, data, 10)))
        accounts = [account145.account(arrays[c['id']], packet, c['id'], label) for c in configurations()]
        for account in accounts:
            assert account['fees'] == 0. if 'fees' in account else True
            account['split'] = '既知開発50場・手数料0'
        path = HERE / 'measurement' / f'NK225_{scene}.npz'
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **arrays)
        record = dict(session=scene, rows=accounts, checks=own_checks, fee_change=change,
                      orders_path=str(path.relative_to(ROOT)), cache_path=str(cache.relative_to(ROOT)))
        save_json(target, record)
        rows.extend(accounts); checks.extend(own_checks); fee_changes.append(change)
        print(scene, '追加16条件完了', flush=True)
    save_json(HERE/'結果145.json', dict(rows=rows, checks=checks, fee_changes=fee_changes,
              configs=configurations(), fee=0, actual_api_orders=0, registration=str(registration)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--registration', required=True, type=Path)
    run(parser.parse_args().registration)
