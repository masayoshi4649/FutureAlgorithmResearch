"""起動前監査を破損させ、未完・欠落・偽件数を拒否する。"""

from copy import deepcopy
from pathlib import Path
import pickle

import run_verified as guard


def main() -> None:
    """機能: 損益を含まない起動監査資料だけで破損拒否を確認する。

    引数: なし。返り値: なし (None)。売買を実行しない。
    """
    fixed = guard.read(guard.HERE / '探索条件の固定.json')
    causal = guard.read(guard.HERE / 'input_causality_before_pnl.json')
    engine = guard.read(guard.HERE / 'dynamic_atr_engine_audit.json')
    runner = guard.read(guard.HERE / 'runner_synthetic_audit.json')
    inputs = pickle.loads((guard.HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    guard.verify_payload(fixed, causal, engine, runner, inputs)
    cases = []
    mutations = [
        ('条件1件欠落', 0, lambda x: x['conditions'].pop()),
        ('条件を別設定へ変更', 0, lambda x: x['conditions'][0].__setitem__('dynamic_trail_atr', 1)),
        ('主評価期間変更', 0, lambda x: x['共通評価7セッション'].pop()),
        ('入力監査未完', 1, lambda x: x.__setitem__('全監査完了', False)),
        ('入口監査重複', 1, lambda x: x['入口']['rows'].__setitem__(1, deepcopy(x['入口']['rows'][0]))),
        ('ATR原本件数偽装', 1, lambda x: x['ATR'].__setitem__('原本行数', 1)),
        ('ATR未来検査未合格', 1, lambda x: x['ATR']['rows'][0].__setitem__('未来足ATR2点改変一致', False)),
        ('入口未来検査件数不足', 1, lambda x: x['入口'].__setitem__('未来ATR改変比較数', 623)),
        ('保存現在データ使用', 1, lambda x: x.__setitem__('現在保存物使用', True)),
        ('注文器旧一致不足', 2, lambda x: x.__setitem__('旧固定H019完全一致入力数', 25)),
        ('注文器合成未合格', 2, lambda x: x['合成検査'][0].__setitem__('一致', False)),
        ('注文器合成重複', 2, lambda x: x['合成検査'].__setitem__(1, deepcopy(x['合成検査'][0]))),
        ('組ピーク計測検算なし', 3, lambda x: x.__setitem__('部分返済と前組の実現益を区別', False)),
    ]
    for label, index, mutation in mutations:
        values = deepcopy([fixed, causal, engine, runner])
        mutation(values[index])
        try:
            guard.verify_payload(*values, inputs)
        except (AssertionError, KeyError, TypeError, ValueError):
            cases.append({'破損': label, '拒否': True})
        else:
            raise AssertionError('破損を許容: ' + label)
    guard.save(guard.HERE / 'run_verified_test.json', {'全検査合格': True, '正常監査資料一致': True,
        '破損拒否数': len(cases), '検査': cases, '新PnL読取': False, '売買再生': False,
        'API取得数': 0, '現在保存物使用': False, 'ガード実装SHA256': guard.design.digest(Path(guard.__file__))})
    print('起動監査の破損拒否:', len(cases), '合格')


if __name__ == '__main__':
    main()
