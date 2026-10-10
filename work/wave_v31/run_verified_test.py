"""開始ガードの不足・重複・偽合格と、拒否時の未起動を検査する。"""

from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

import run_verified as guard

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 損益を使わず、合成監査の正常系と不正資料の拒否を確かめる。

    引数: なし。返り値: なし (None)。
    """
    keys = {(f'試験{i:02}', symbol) for i in range(13) for symbol in ('TOPIX', 'NK225')}
    old = {'signals': [{'id': f'H{i:03}'} for i in range(12)],
           'managers': [{'id': f'L{i:03}'} for i in range(7)], 'own_signals': {}}
    fixed = dict(old, variants=[{'id': name, 'delay_seconds': value[0], 'mode': value[1]} for name, value in guard.VARIANTS.items()],
                 全組合せ数=420, 元条件数=84, 新補助対照数=336)
    rows = [dict(signal=s['id'], session=session, symbol=symbol, **guard.COUNTS,
                 各変形SHA256={v: 'a' * 64 for v in guard.VARIANTS}, 価格ATRと元入力不変=True)
            for s in old['signals'] for session, symbol in sorted(keys)]
    audit = dict(構造検査合格=True, 損益参照前=True, 売買再生実行=False, 現在データ使用=False, API取得数=0,
                 全入口数=12, 全入力数=312, 全変形数=5, 全方向列数=4680, 各入力=rows,
                 検査件数={k: v * 312 for k, v in guard.COUNTS.items()},
                 元3列SHA256={str(i): 'a' * 64 for i in range(36)}, 原本78SHA256={str(i): 'b' * 64 for i in range(78)})
    guard.verify_payload(fixed, old, audit, keys)
    rejected = []
    for name, change in (
        ('偽合格', lambda a: a.update(構造検査合格=False)),
        ('監査入力不足', lambda a: a['各入力'].pop()),
        ('監査入力重複', lambda a: a['各入力'].__setitem__(1, a['各入力'][0])),
        ('変形不足', lambda a: a['各入力'][0]['各変形SHA256'].pop('V060')),
        ('指紋形式不正', lambda a: a['各入力'][0]['各変形SHA256'].update(V000='x')),
        ('要約偽装', lambda a: a['検査件数'].update(prefix列数=0)),
        ('原本不足', lambda a: a['原本78SHA256'].pop('0')),
        ('現在参照', lambda a: a.update(現在データ使用=True)),
        ('損益後監査', lambda a: a.update(損益参照前=False)),
        ('売買再生済み', lambda a: a.update(売買再生実行=True))):
        broken = deepcopy(audit)
        change(broken)
        try:
            guard.verify_payload(fixed, old, broken, keys)
        except (AssertionError, KeyError):
            rejected.append(name)
        else:
            raise AssertionError('不正資料を許容: ' + name)
    with patch.object(sys, 'argv', ['run_verified.py']), patch.object(guard, 'freeze', return_value={}), \
         patch.object(guard, 'verify_sources', side_effect=AssertionError('固定SHA不一致')), \
         patch.object(guard.subprocess, 'run') as launch:
        try:
            guard.main()
        except AssertionError:
            pass
        else:
            raise AssertionError('固定SHA不一致を許容')
        launch.assert_not_called()
    result = {'合成検査全合格': True, '正常312入力': True, '不正資料拒否': rejected,
              '固定SHA不一致時runner未起動': True, '新損益参照': False, '売買再生実行': False}
    guard.save(HERE / 'run_verified_test.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
