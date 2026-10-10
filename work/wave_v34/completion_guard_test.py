"""全件完備監査で不足・重複・偽数値が拒否されることを人工資料で確認する。"""

from copy import deepcopy
from pathlib import Path
import hashlib
import numpy as np

import completion_guard as guard


def main() -> None:
    """機能: 人工26会計・1536波の正常経路と破損拒否を検査する。

    引数: なし。返り値: なし (None)。売買再生はしない。
    """
    inputs = {(f'人工{i:02d}', symbol): {'last': np.array([100., 101.])} for i in range(13) for symbol in guard.assessment.SYMBOLS}
    main_rows = [{'id': '人工', 'session': k[0], 'symbol': k[1], 'net_yen': 10., 'loss_units': 1,
                  'opening_orders': 0, 'gate': {'actual_preparations': 0, 'shadow_preparations': 0, 'actual_opening_orders': 0}, 'retracements': [{'risk_yen': 100., 'peak_yen': 20., 'final_yen': 10.}]} for k in inputs]
    summary = {'id': '人工', 'spec': {'gated': False}, 'ledger_hash': 'a', 'all_symbols': {'TOPIX': {'net_yen': 130.}, 'NK225': {'net_yen': 130.}},
               'symbols': {'TOPIX': {'net_yen': 70.}, 'NK225': {'net_yen': 70.}}}
    record = {'id': '人工', '台帳SHA256': 'a', '全入力数': 26, '原本行会計数': 52,
        'prefix検査数': 26, '未来価格入口ATR追跡ATR方向改変数': 26, '買売反射数': 26,
        '全保存数値一致': True, '全台帳配列一致': True, '全時価曲線SHA一致': True, 'ATR全保有行検算': True, '返却独立検算': True, '影会計一致': True, '準備接続検査': True,
        'sessions': [{**deepcopy(r), '検算した観測行数': 2, 'prefix検査合格': True, '未来改変合格': True, '買売反射合格': True,
                      '全台帳配列一致': True, '全時価曲線SHA一致': True, 'ATR全保有行検算': True, '返却独立検算': True, '影会計一致': True, '準備起点検査': {'新設数': 0, '新規起点数': 0, '影新設数': 0, '準備独立値一致': True, '約定起点一致': True, '影新設対応一致': False}} for r in main_rows],
        'all_symbols': deepcopy(summary['all_symbols']), 'symbols': deepcopy(summary['symbols'])}
    guard.accounting_record(record, summary, main_rows, inputs)
    cases = []

    def reject(label, operation) -> None:
        """機能: 不正な人工資料が拒否されることを確認する。

        引数: label (str)、operation (callable)。返り値: なし (None)。
        """
        try:
            operation()
        except (AssertionError, KeyError, TypeError, ValueError):
            cases.append({'破損': label, '拒否': True})
        else:
            raise AssertionError(label)

    for label, mutation in (
        ('会計1区間欠落', lambda v: v['sessions'].pop()),
        ('会計区間重複', lambda v: v['sessions'].__setitem__(1, deepcopy(v['sessions'][0]))),
        ('収支必須項目欠落', lambda v: v['sessions'][0].pop('net_yen')),
        ('負け枚数必須項目欠落', lambda v: v['sessions'][0].pop('loss_units')),
        ('組ピーク必須項目欠落', lambda v: v['sessions'][0]['retracements'][0].pop('peak_yen')),
        ('初期R改変', lambda v: v['sessions'][0]['retracements'][0].__setitem__('risk_yen', 200.)),
        ('原本行数偽装', lambda v: v.__setitem__('原本行会計数', 50)),
        ('個別原本行数偽装', lambda v: v['sessions'][0].__setitem__('検算した観測行数', 1)),
        ('未来検査数偽装', lambda v: v.__setitem__('未来価格入口ATR追跡ATR方向改変数', 25)),
        ('未来検査未完', lambda v: v['sessions'][0].__setitem__('未来改変合格', False)),
        ('追跡ATR検算未完', lambda v: v.__setitem__('ATR全保有行検算', False)),
        ('台帳指紋不一致', lambda v: v.__setitem__('台帳SHA256', '別台帳')),
        ('影会計未確認', lambda v: v.__setitem__('影会計一致', False)),
        ('準備起点欠落', lambda v: v['sessions'][0].pop('準備起点検査')),
        ('影準備数偽装', lambda v: v['sessions'][0]['準備起点検査'].__setitem__('影新設数', 1)),
        ('gate必須項目欠落', lambda v: v['sessions'][0]['gate'].pop('actual_preparations')),
        ('期間集計偽装', lambda v: v['symbols']['TOPIX'].__setitem__('net_yen', 99.)),
    ):
        value = deepcopy(record); mutation(value)
        reject(label, lambda r=value: guard.accounting_record(r, summary, main_rows, inputs))
    boundary = {'参照行': 0, 'seq': 1, 'last': 100., '買い枚数': 0, '売り枚数': 0, 'ネット枚数': 0,
                '時価損益円': 10., '実現損益円': 10., '含み損益円': 0.}
    fields = ('正方向ネット保有分', '逆方向ネット保有分', 'ネット中立分', '正方向脚保有分', '逆方向脚保有分',
              '正方向枚数分', '逆方向枚数分', '両建て保有分', '時価損益差円', '実現損益差円', '含み損益差円')
    waves = {spec['id']: [{'method': spec['id'], 'wave': w['id'], 'symbol': symbol, 'session': w['session'],
        **{name: 0. for name in fields}, '開始境界': deepcopy(boundary), '終了境界': deepcopy(boundary)}
        for w in guard.design.waves() for symbol in guard.assessment.SYMBOLS] for spec in guard.design.catalog()}
    independent = [dict(deepcopy(row), 保存値一致=True) for rows in waves.values() for row in rows]
    guard.wave_records(waves, independent)
    for label, mutation in (
        ('波1区間欠落', lambda v: v.pop()),
        ('波重複', lambda v: v.__setitem__(1, deepcopy(v[0]))),
        ('波保有時間偽装', lambda v: v[0].__setitem__('正方向ネット保有分', 20.)),
        ('境界時価改変', lambda v: v[0]['開始境界'].__setitem__('時価損益円', 20.)),
        ('境界必須項目欠落', lambda v: v[0]['終了境界'].pop('ネット枚数')),
        ('波検査未完', lambda v: v[0].__setitem__('保存値一致', False)),
    ):
        value = deepcopy(independent); mutation(value)
        reject(label, lambda r=value: guard.wave_records(waves, r))
    reject('非有限数値を拒否', lambda: guard.close(float('nan'), 0., '値'))
    reject('真偽値を件数に偽装', lambda: guard.close(True, 1, '型'))
    # ----------------------------------------
    # 許可は新しい準備行に対応し、次行約定と陰の同じ注文へ結び付く。
    actual = {'prepare_events': [[0, 0, 1, 101, 1, 300, 1]],
        'entry_preparations': [[0, 1, 0, 0]], 'orders': [[1, 0, 0, 1, 1, 101, 4, 1]],
        'cycles': [[0, 1, 1, 0, 1, 1, 1, 1, 1, 0]], 'trades': [], 'stats': [0.]*11}
    actual['result_fingerprints'] = {}
    for field, width in (('trades', 11), ('orders', 8), ('cycles', 10), ('stats', None)):
        array = np.asarray(actual[field], dtype=float)
        if width:
            array = array.reshape(-1, width)
        actual['result_fingerprints'][field] = {'shape': list(array.shape), 'SHA256': hashlib.sha256(array.tobytes()).hexdigest()}
    actual['shadow'] = deepcopy(actual)
    actual['prepare_allow_SHA256'] = hashlib.sha256(np.array([True, False], bool).tobytes()).hexdigest()
    counts = {f: 0 for f in guard.runner.GATE_FIELDS}
    counts.update(shadow_preparations=1, actual_preparations=1, shared_preparations=1,
                  shadow_opening_orders=1, actual_opening_orders=1, matched_openings=1)
    gate_row, raw, spec = {'gate': counts}, {'last': np.array([100., 101.])}, {'gated': True}
    guard.preparation_check(actual, gate_row, raw, spec)
    for label, mutation in (
        ('許可列に未来準備を混入', lambda v: v.__setitem__('prepare_allow_SHA256', '未来mask')),
        ('準備IDを別イベントへ変更', lambda v: v['entry_preparations'][0].__setitem__(2, 1)),
        ('同じ行の約定を偽装', lambda v: v['entry_preparations'][0].__setitem__(1, 0)),
        ('影にない準備価格を使用', lambda v: v['prepare_events'][0].__setitem__(3, 102)),
    ):
        value = deepcopy(actual); mutation(value)
        reject(label, lambda r=value: guard.preparation_check(r, gate_row, raw, spec))
    damaged = deepcopy(gate_row); damaged['gate']['skipped_holding'] = 1
    reject('見送り分類の合計偽装', lambda: guard.preparation_check(actual, damaged, raw, spec))
    damaged = deepcopy(gate_row); damaged['gate'].pop('unmatched_openings')
    reject('参加13項目の欠落', lambda: guard.preparation_check(actual, damaged, raw, spec))
    value = {'全検査合格': True, '人工正常会計26': True, '人工正常波1536': True, '破損拒否数': len(cases),
             '検査': cases, '採否条件変更': False, '売買再生': False, 'API取得数': 0, '現在保存物使用': False,
             'ガード実装SHA256': guard.design.digest(Path(guard.__file__))}
    guard.runner.save(guard.HERE / 'completion_guard_test.json', value)
    print('全件監査の人工破損拒否:', len(cases), '合格')


if __name__ == '__main__':
    main()
