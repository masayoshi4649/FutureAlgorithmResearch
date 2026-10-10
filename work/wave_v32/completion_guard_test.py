"""完備ガードの欠落・重複・偽要約拒否を人工資料で確認する。"""

from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np
import completion_guard as guard


def main() -> None:
    """機能: 人工の26会計・148波集合・所有資料を用い、破損が完了扱いされないことを確認する。

    引数: なし。返り値: なし (None)。実相場の売買再生や採否条件変更はしない。
    """
    inputs = {(f'人工{i:02d}', symbol): {'last': np.array([100., 101.])}
              for i in range(13) for symbol in guard.SYMBOLS}
    main_rows = [{'id': '人工', 'session': key[0], 'symbol': key[1], 'net_yen': 10., 'loss_units': 1,
                  'selection': {'独立意味検査': '別資料'}} for key in inputs]
    candidate = {'id': '人工', 'ledger_hash': 'a', 'request_hash': 'b', 'entries_hash': {'T': 'c', 'R': 'd'},
                 'all_symbols': {s: {'net_yen': 130., 'selection': {}} for s in guard.SYMBOLS},
                 'symbols': {s: {'net_yen': 70., 'selection': {}} for s in guard.SYMBOLS}}
    record = {'id': '人工', '全入力数': 26, '原本行会計数': 52,
              'prefix検査数': 26, '未来価格ATR両入口要求改変数': 26, '買売反射数': 26,
              '全要求再生成一致': True, '保存全数値一致': True, '独立参加時間一致': True, '全台帳配列一致': True,
              '台帳SHA256': 'a', '要求SHA256': 'b', '入口SHA256': {'T': 'c', 'R': 'd'},
              'all_symbols': {s: {'net_yen': 130.} for s in guard.SYMBOLS},
              'symbols': {s: {'net_yen': 70.} for s in guard.SYMBOLS},
              'sessions': [{**{k: v for k, v in r.items() if k != 'selection'}, '検算した観測行数': 2,
                            'prefix検査合格': True, '未来改変合格': True, '買売反射合格': True,
                            '全台帳配列一致': True, '選択曲線SHA一致': True} for r in main_rows]}
    guard.verify_accounting_record(record, candidate, main_rows, inputs)
    cases = []

    def rejected(label, operation) -> None:
        """機能: 人工破損が確実に拒否されることを確認する。

        引数: label (str)、operation (callable)。返り値: なし (None)。
        """
        try:
            operation()
        except (AssertionError, KeyError, ValueError, TypeError):
            cases.append({'破損': label, '拒否': True})
        else:
            raise AssertionError('破損を通過: ' + label)

    for label, mutate in (
        ('会計区間欠落', lambda x: x['sessions'].pop()),
        ('会計同一区間重複', lambda x: x['sessions'].__setitem__(1, deepcopy(x['sessions'][0]))),
        ('必須収支欠落', lambda x: x['sessions'][0].pop('net_yen')),
        ('必須負け枚数欠落', lambda x: x['sessions'][0].pop('loss_units')),
        ('会計収支改変', lambda x: x['sessions'][0].__setitem__('net_yen', 11.)),
        ('原本行数偽装', lambda x: x.__setitem__('原本行会計数', 51)),
        ('個別原本行数偽装', lambda x: x['sessions'][0].__setitem__('検算した観測行数', 1)),
        ('未来検査件数不足', lambda x: x.__setitem__('未来価格ATR両入口要求改変数', 25)),
        ('未来検査未完', lambda x: x['sessions'][0].__setitem__('未来改変合格', False)),
        ('台帳指紋不一致', lambda x: x.__setitem__('台帳SHA256', '別台帳')),
        ('要求指紋不一致', lambda x: x.__setitem__('要求SHA256', '別要求')),
        ('入口指紋不一致', lambda x: x['入口SHA256'].__setitem__('R', '別入口')),
        ('期間集計欠落', lambda x: x['symbols']['TOPIX'].pop('net_yen')),
        ('期間集計改変', lambda x: x['all_symbols']['NK225'].__setitem__('net_yen', 140.)),
        ('最終全数値不一致', lambda x: x.__setitem__('保存全数値一致', False)),
    ):
        changed = deepcopy(record)
        mutate(changed)
        rejected(label, lambda value=changed: guard.verify_accounting_record(value, candidate, main_rows, inputs))

    definitions = [{'id': f'W{i+1:02d}', 'session': f'人工{i}', 'start': '2026-01-01T09:00:00+09:00',
                    'end': '2026-01-01T10:00:00+09:00', 'side': 1} for i in range(4)]
    ids = {f'人工{i:03d}' for i in range(148)}
    waves = {'手法': [{'id': name} for name in sorted(ids)],
             '結果': [{'method': name, 'wave': w['id'], 'symbol': symbol, 'session': w['session'],
                       '開始': w['start'], '終了': w['end'], '波方向': w['side'], '区間分': 60.,
                       '正方向ネット保有分': 21., '正方向ネット20分目安達成': True}
                      for name in sorted(ids) for w in definitions for symbol in guard.SYMBOLS],
             '方法別要約': [{'method': name, '対象区間数': 8, '目安達成区間数': 8} for name in sorted(ids)]}
    guard.verify_waves(waves, definitions, ids)
    for label, mutate in (
        ('波区間欠落', lambda x: x['結果'].pop()),
        ('波区間重複', lambda x: x['結果'].__setitem__(1, deepcopy(x['結果'][0]))),
        ('波要約偽装', lambda x: x['方法別要約'][0].__setitem__('目安達成区間数', 7)),
        ('波合否偽装', lambda x: x['結果'][0].__setitem__('正方向ネット20分目安達成', False)),
        ('波時刻変更', lambda x: x['結果'][0].__setitem__('開始', '2026-01-01T09:01:00+09:00')),
    ):
        changed = deepcopy(waves)
        mutate(changed)
        rejected(label, lambda value=changed: guard.verify_waves(value, definitions, ids))
    rejected('非有限値', lambda: guard.finite({'値': float('nan')}))
    rejected('真偽値を件数へ偽装', lambda: guard.close(True, 1, '型'))
    output = {'全検査合格': True, '正常人工会計26入力': True, '正常人工波1184件': True,
              '破損拒否数': len(cases), '検査': cases, '採否閾値変更': False,
              '実相場売買再生': False, '現在データ使用': False, 'API取得数': 0,
              'ガード実装SHA256': guard.runner.digest(Path(guard.__file__))}
    guard.runner.save(guard.HERE / 'completion_guard_test.json', output)
    print(f'正常人工資料一致、破損{len(cases)}件拒否。', flush=True)


if __name__ == '__main__':
    main()
