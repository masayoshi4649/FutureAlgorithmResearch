"""主試験の記憶期限、不明値、条件消費を設計上の具体例で検査する。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
sys.path.insert(0, str(TASK))
SPEC = importlib.util.spec_from_file_location('pressure_state_review', TASK/'backtest.py')
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def run_case(values: list[tuple], method: str = 'P01') -> list[list[int]]:
    """機能: 明示した観測列から非ゼロ判断だけを取り出す。

    引数: values(list[tuple])は起点/執行偏り/価格方向/未知率/供給、method(str)。
    返り値: 非ゼロ判断の起点と方向(list[list[int]])。
    """
    ready = dict(start=0., limit=2400., symbol='TOPIX', time_s=np.arange(0., 2461., 60.),
                 seq=np.arange(42, dtype=np.int64))
    rows = [dict(time_s=float(t), observed_time=float(t), seq=int(t//60), execution=e, r1=p,
                 unknown_fraction=u, supply=s, recovery=s, peer_repricing=s)
            for t,e,p,u,s in values]
    decisions, _ = MODULE.build_signals(ready, pd.DataFrame(rows), method,
                                       {'TOPIX': dict(execution=.5, r1=.5, supply=.5)})
    return [[int(ready['time_s'][int(i)]), int(d)] for i,d in decisions if d]


def main() -> None:
    """機能: 事前定義と異なる古い記憶・不明値・条件使い回しを検出する。

    引数: なし。返り値: なし(None)。主案の損益は比較しない。
    """
    strong = [(t,.8,.5,0.,.5) for t in range(1200, 1560, 60)]
    checks = []
    scenarios = [
        ('5分ちょうどの反転を許可', strong[:5]+[(1500,-.3,-.2,0.,-.2)], 'P01', [[1500,-1]]),
        ('同方向継続で期限を延ばさない', strong+[(1560,-.3,-.2,0.,-.2)], 'P01', []),
        ('全量不明ゼロを均衡とみなさず記憶破棄', [(1200,.8,.5,0.,.5),(1260,0.,-.2,1.,-.2),(1320,-.3,-.2,0.,-.2)], 'P01', []),
        ('分類済みの均衡ゼロは反転確認に利用', [(1200,.8,.5,0.,.5),(1260,0.,-.2,.2,-.2)], 'P01', [[1260,-1]]),
        ('欠測起点を跨がない', [(1200,.8,.5,0.,.5),(1320,-.3,-.2,0.,-.2)], 'P01', []),
        ('追加ゲート不成立でも元事象を消費', [(1200,.8,.5,0.,.5),(1260,-.3,-.2,0.,.2),(1320,-.3,-.2,0.,-.2)], 'P02', []),
        ('反対の新しい強圧力は新事象になる', [(1200,.8,.5,0.,.5),(1260,-.8,-.2,0.,-.2),(1320,.3,.2,0.,.2)], 'P01', [[1260,-1],[1320,1]]),
    ]
    for name, values, method, expected in scenarios:
        actual = run_case(values, method)
        assert actual == expected, (name, actual, expected)
        checks.append(dict(検査=name, 手法=method, 期待判断=expected, 一致=True))
    report = dict(合格=True, 検査=checks, 注意='売買成績の最適化ではなく、事前仕様の状態遷移だけを確認する。')
    (HERE/'圧力記憶の設計監査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
