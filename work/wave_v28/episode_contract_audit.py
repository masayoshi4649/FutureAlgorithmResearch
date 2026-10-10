"""実相場を再生せず、二入力の波計測契約と旧数値定義を合成で確認する。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import socket
import urllib.request

import numpy as np

import episode_audit as episode

HERE = Path(__file__).resolve().parent


def save(path: Path, value: object) -> None:
    """機能: 新しい合成フィクスチャのJSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def metric_test() -> dict:
    """機能: 同値時刻・20分境界・入口と主方向の時間差・独立会計を手計算で確かめる。

    引数: なし。返り値: 合成計測の検算 (dict)。
    """
    times = np.array([0., 600., 600., 1200., 1800.])
    state, context = np.array([1, 0, 0, 0, 0], dtype=np.int8), np.ones(5, dtype=np.int8)
    ready = {'session': '合成', 'symbol': 'TOPIX', 'seq': np.arange(5), 'time_s': times,
             'last': np.array([100., 101., 102., 103., 104.])}
    curve = np.array([[0, 0, 0, 0, 0, 0, 0, -1], [0, 0, 1, 0, 0, -101, 1, 0],
                      [1, 0, 1, 0, 0, -101, 1, 0], [2, 0, 1, 0, 0, -101, 1, 0],
                      [3, 3, 0, 0, 0, 3, 0, 0]], dtype=float)
    orders = np.array([[1, 0, 0, 1, 1, 101, 20, 1], [4, 3, 0, -1, 1, 104, 9, 0]], dtype=float)
    trades = np.array([[0, 0, 1, 1, 101, 104, 1, 4, 0, 9, 3]], dtype=float)
    result = {'curve': curve, 'orders': orders, 'trades': trades}
    method = {'id': '合成', 'manager': {'context_source': 'main'}}
    wave = {'id': '合成波', 'session': '合成', 'name': '合成30分', 'side': 1,
            'start': episode.stamp(0.), 'end': episode.stamp(1800.)}
    records = episode.order_records(ready, state, result, {9: '場末'}, context)
    actual = episode.episode_metrics(method, wave, ready, state, result, records, 1000., context)
    assert actual['正方向信号分'] == 10 and actual['正方向管理分'] == 30
    assert actual['正方向ネット保有分'] == 20 and actual['正方向ネット20分目安達成']
    assert actual['時価損益差円'] == 3000 and actual['実現損益差円'] == 3000 and actual['含み損益差円'] == 0
    assert records[1]['発注元信号'] == 0 and records[1]['発注元管理方向'] == 1
    middle = episode.boundary(ready, curve, 600., 1000.)
    assert middle['参照行'] == 2 and middle['last'] == 102. and middle['時価損益円'] == 1000.
    ledger = [{'method': '合成', 'session': '合成', 'symbol': 'TOPIX', '全約定': records}]
    checked = episode.accounting_checks([actual], ledger)
    assert checked['比較境界数'] == 2
    altered = dict(actual, 終了境界=dict(actual['終了境界'], 時価損益円=4000.))
    try:
        episode.accounting_checks([altered], ledger)
    except AssertionError:
        pass
    else:
        raise AssertionError('波終点の損益改ざんを見逃した')
    old = episode.load_module(HERE.parent / 'wave_v27' / 'episode_audit.py', 'episode_v27_contract_reference')
    old_records = old.order_records(ready, state, result, {9: '場末'})
    prior = old.episode_metrics(method, wave, ready, state, result, old_records, 1000.)
    backward = episode.episode_metrics(method, wave, ready, state, result, old_records, 1000.)
    assert all(backward[key] == value for key, value in prior.items())
    assert backward['正方向管理分'] == backward['正方向信号分']
    assert episode.trade_records(ready, result, 1000.) == old.trade_records(ready, result, 1000.)
    sell_wave = dict(wave, side=-1)
    sold = episode.episode_metrics(method, sell_wave, ready, state, result, records, 1000., context)
    assert sold['正方向ネット保有分'] == 0 and sold['逆方向ネット保有分'] == 20
    assert not sold['正方向ネット20分目安達成']
    return {'旧数値項目の全一致': True, '入口10分と管理30分を分離': True,
            '約定後の正方向保有20分': True, '同値時刻の最後の原本行を境界参照': True,
            '上下方向の保有を区別': True, '独立会計2境界一致と改ざん検出': True}


def routing_test() -> dict:
    """機能: 新保存入口・別context・旧主案・一次反証全通過の読取り経路を合成で確認する。

    引数: なし。返り値: ファイル経路と全件追加の検算 (dict)。実保存方向は読み込まない。
    """
    base = HERE / 'episode_contract_fixture' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    v25, v27, v28 = (base / part for part in ('v25', 'v27', 'v28'))
    old_refs = episode.HERE, episode.V25, episode.V27
    try:
        episode.HERE, episode.V25, episode.V27 = v28, v25, v27
        save(v25 / '探索条件の固定.json', {'signals': [{'id': 'F32', 'params': {}}, {'id': 'D016', 'params': {}}],
             'managers': [{'id': 'G08'}, {'id': 'D065'}]})
        save(v27 / '探索条件の固定.json', {'signals': [{'id': 'H019', 'params': {}}], 'managers': [{'id': 'D273'}]})
        save(v28 / '探索条件の固定.json', {'signals': [{'id': 'H001', 'name': '合成1'}, {'id': 'H002', 'name': '合成2'}],
             'managers': [{'id': 'J000', 'name': '管理1', 'context_source': 'main'}, {'id': 'J001', 'name': '管理2', 'context_source': 'entry'}]})
        save(v28 / 'episode_audit_fixed.json', {'合成': True})
        first = [dict(candidate={'id': 'H001__J000', 'signal_id': 'H001', 'manager_id': 'J000'}, first_stage_failures=[]),
                 dict(candidate={'id': 'H002__J001', 'signal_id': 'H002', 'manager_id': 'J001'}, first_stage_failures=[]),
                 dict(candidate={'id': 'H002__J000', 'signal_id': 'H002', 'manager_id': 'J000'}, first_stage_failures=['合成棄却'])]
        save(v28 / '一次反証の結果.json', first)
        methods = episode.methods(None, v28 / '一次反証の結果.json')
        assert {method['id'] for method in methods} == {'F32__G08', 'D016__D065', 'P02__D065', 'H019__D273', 'H001__J000', 'H002__J001'}
        assert all(method['signal']['実装元'] == '二入力階層' for method in methods if '__J' in method['id'])
        try:
            episode.require_saved_directions(methods)
        except AssertionError:
            pass
        else:
            raise AssertionError('未生成の方向で再生開始できた')
        inputs = {('合成', 'TOPIX'): {'last': np.ones(3)}, ('合成', 'NK225'): {'last': np.ones(3)}}
        enter, main = np.array([1, 0, -1], dtype=np.int8), np.array([1, 1, -1], dtype=np.int8)
        for root, folder, identifier, value in [(v28, 'directions', 'H001', enter), (v28, 'directions', 'H002', enter),
                                                (v28, 'contexts', 'H001', main), (v27, 'directions', 'H019', -enter)]:
            (root / folder).mkdir(parents=True, exist_ok=True)
            np.savez_compressed(root / folder / (identifier + '.npz'), **{'|'.join(key): value for key in inputs})
        episode.require_saved_directions(methods)
        by_id = {method['id']: method for method in methods}
        actual = episode.directions(by_id['H001__J000'], inputs, {}, None)
        context = episode.management_context(by_id['H001__J000'], inputs)
        old = episode.directions(by_id['H019__D273'], inputs, {}, None)
        for key in inputs:
            np.testing.assert_array_equal(actual[key], enter)
            np.testing.assert_array_equal(context[key], main)
            np.testing.assert_array_equal(old[key], -enter)
        assert episode.management_context(by_id['H002__J001'], inputs) is None
        assert episode.management_context(by_id['H019__D273'], inputs) is None
        return {'通過2件を選別せず全追加': True, '不合格1件を除外': True, '固定比較3件と旧主案を保持': True,
                '未生成方向では開始拒否': True, '新旧方向の参照根を区別': True,
                'main指定だけ保存contextを返す': True, '実保存方向の読取り': False}
    finally:
        episode.HERE, episode.V25, episode.V27 = old_refs


def main() -> None:
    """機能: 合成契約だけを確認し、新しい監査記録を保存する。

    引数: なし。返り値: なし (None)。実相場の損益・現在スナップショットを使用しない。
    """
    socket.socket.connect = episode.reject_network
    socket.create_connection = episode.reject_network
    urllib.request.OpenerDirector.open = episode.reject_network
    sources = [HERE.parent / 'wave_v27' / 'episode_audit.py', HERE / 'episode_audit.py', HERE / 'engine_context.py']
    before = {str(path): episode.digest(path) for path in sources}
    results = {'合成数値': metric_test(), '合成参照経路': routing_test(), 'API取得': 0,
               '新候補の損益再生': False, '現在スナップショット参照': False}
    assert before == {str(path): episode.digest(path) for path in sources}
    results['ソース不変SHA256'] = before
    save(HERE / 'episode_contract_audit.json', results)
    print(json.dumps(results, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
