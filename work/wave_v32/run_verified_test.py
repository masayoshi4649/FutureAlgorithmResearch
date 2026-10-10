"""未完成の因果検査・不足条件・偽合格・SHA不一致時の未起動を確認する。"""

from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import patch

import run_verified as guard

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 損益を含まない固定条件と構造監査を改変し、拒否を検査する。

    引数: なし。返り値: なし (None)。runnerを起動しない。
    """
    fixed = guard.read(HERE / '探索条件の固定.json')
    protocol = guard.read(HERE / 'selection_fixed.json')
    causal = guard.read(HERE / 'selector_causality_before_pnl.json')
    engine = guard.read(HERE / 'engine_selector_audit.json')
    keys = set(map(tuple, protocol['全入力キー']))
    normal = guard.verify_payload(fixed, protocol, causal, engine, keys)
    rejected = []
    for name, change in (
        ('全条件不足', lambda a: a[0]['conditions'].pop()),
        ('主評価ずらし', lambda a: a[0]['共通評価7セッション'].pop(0)),
        ('第一段だけの未完了', lambda a: a[2].update(全監査完了=False)),
        ('追加監査不足', lambda a: a[2]['追加監査']['検査件数'].update(B全近傍と13場初の未来影削除改変=1)),
        ('入口prefix不足', lambda a: a[2].update(T_R方向prefix区間数=26)),
        ('乱数seed不足', lambda a: a[2]['合成'].update(乱数合成数=64)),
        ('偽合成合格', lambda a: a[3]['合成検査'][0].update(一致=False)),
        ('合成重複', lambda a: a[3]['合成検査'].__setitem__(1, a[3]['合成検査'][0])),
        ('旧T未検査', lambda a: a[3].update(旧固定T完全一致区間数=0)),
        ('現在参照', lambda a: a[2].update(現在データ使用=True))):
        args = deepcopy((fixed, protocol, causal, engine))
        change(args)
        try:
            guard.verify_payload(*args, keys)
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
            raise AssertionError('不一致を許容')
        launch.assert_not_called()
    guard.save(HERE / 'run_verified_test.json', {'合成全合格': True, '正常全件': normal,
               '不正資料拒否': rejected, 'SHA不一致時runner未起動': True,
               '新損益参照': False, '売買再生実行': False})
    print('正常148、破損10種拒否、SHA不一致時の未起動を確認。', flush=True)


if __name__ == '__main__':
    main()
