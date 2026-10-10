"""サイクル評価の平均勝敗・未完了分離・単位と旧脚束ねを別計算で検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import metrics

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'wave_v13'


def raw_rows(specifications: list[tuple]) -> np.ndarray:
    """機能: 損益を事前計算した脚だけを22列形式へ並べる。

    引数: specifications (list[tuple]): cycle/leg/損益/完了/新規行/返済行。
    返り値: ndarray: 人工の全脚。
    """
    output = []
    for cycle, leg, pnl, closed, enter, exit_index in specifications:
        row = np.zeros(22)
        row[[0,1,2,4,5,6,7,8,9,14,15,20,21]] = [cycle,leg,1,enter-1,enter,exit_index,100,1000,1000+pnl,closed,pnl,enter*2,exit_index*2]
        output.append(row)
    return np.asarray(output)


def simple_cycle(pnl: float, session: str, order: int) -> dict:
    """機能: 単建玉の完了サイクルを人工的に作る。

    引数: pnl (float)、session (str)、order (int)。返り値: dict: 標準単位を備えたサイクル。
    """
    row = dict(method='試験',symbol='NK225',session=session,cycle_id=order,complete=True,
               legs=1,closed_legs=1,open_legs=0,cap=2,entry_order=order,exit_order=order+1)
    for unit, value in [('points',pnl),('yen',pnl*1000),('atr',pnl/100),('r',pnl/50)]:
        row.update({f'net_{unit}':value,f'closed_{unit}':value,f'open_{unit}':0.})
    return row


def hand_tests() -> list[str]:
    """機能: 手計算で完成・未完成・勝率・PF・尾部・除外後比率を確認する。

    引数: なし。返り値: list[str]: 合格した独立ケース。
    """
    checks = []
    raw = raw_rows([(0,0,300,1,1,4),(0,1,-100,1,1,4),(1,0,60,1,6,8),(1,1,-500,0,6,10)])
    cycles = metrics.from_raw(raw,'試験','NK225','日中',2)
    result = metrics.summarize(cycles,['日中'],'points')
    expected = dict(complete_cycles=1,incomplete_cycles=1,gross_profit=200.,gross_loss=0.,
                    complete_net=200.,incomplete_closed_net=60.,incomplete_open_net=-500.,
                    incomplete_net=-440.,all_closed_net=260.,all_open_net=-500.,all_net=-240.)
    for key,value in expected.items():
        assert result[key] == value, (key,result[key],value)
    assert result['profit_factor'] is None and result['payoff_ratio'] is None and result['loo_ratio_score'] == 0
    checks.append('利益玉だけ返済した未完了サイクルを勝ちへ計上せず全含み損を保持')
    cycles = metrics.from_raw(raw[:2],'試験','NK225','日中',2,incomplete_cycle_ids=[0])
    result = metrics.summarize(cycles,['日中'],'points')
    assert result['complete_cycles'] == 0 and result['incomplete_closed_net'] == 200 and result['open_legs'] == 0
    checks.append('全脚返済でも中心を継続する再配置グリッドを未完了として扱う')
    recycled = raw_rows([(0,0,10,1,1,2),(0,0,10,1,3,4),(0,0,-100,1,5,6)])
    cycles = metrics.from_raw(recycled,'試験','NK225','日中',1)
    result = metrics.summarize(cycles,['日中'],'points')
    assert len(cycles) == 1 and result['losses'] == 1 and result['avg_loss'] == 80 and result['profit_factor'] == 0
    checks.append('同じ格子枠の再配置３脚を一つの損失サイクルとして集約')

    values = [100,-40,0,50,-20,-10,20]
    sessions = ['１','１','１','２','２','３','３']
    cycles = [simple_cycle(value,session,index) for index,(value,session) in enumerate(zip(values,sessions))]
    result = metrics.summarize(cycles,['１','２','３'],'points')
    expected = dict(count=7,wins=3,losses=3,flats=1,gross_profit=170,gross_loss=70,
                    avg_win=170/3,avg_loss=70/3,payoff_ratio=17/7,profit_factor=17/7,
                    win_rate=3/7,nonflat_win_rate=.5,breakeven_win_rate=7/24,expectancy=100/7,
                    max_loss_streak=2,max_loss=40,max_win=100,tail10_mean=-40,tail10_count=1,
                    session_mean=100/3,session_median=30,session_worst=10,session_best=60,
                    net_without_best_session=40,positive_sessions=3,loo_min_pf=7/3,loo_min_payoff=7/3,
                    loo_ratio_score=7/3,closed_cycle_drawdown=40)
    for key,value in expected.items():
        np.testing.assert_allclose(result[key],value,rtol=1e-10,atol=1e-10,err_msg=key)
    checks.append('平均勝敗・損益分岐勝率・ゼロ損益・跨セッション連敗・下位10%を手計算')
    checks.append('一セッションずつ除外したPFと平均勝敗比の最悪値を手計算')
    yen, normalized = metrics.summarize(cycles,['１','２','３'],'yen'), metrics.summarize(cycles,['１','２','３'],'atr_cap')
    np.testing.assert_allclose(yen['all_net'],result['all_net']*1000)
    np.testing.assert_allclose(normalized['all_net'],result['all_net']/200)
    np.testing.assert_allclose([yen['profit_factor'],normalized['profit_factor']],[17/7,17/7])
    checks.append('同一の固定換算ではPFと平均勝敗比が円倍率や設定枚数で変化しない')
    for sample in [[],[10,20],[0,0],[-10,-20]]:
        result = metrics.distribution(sample)
        assert not any(isinstance(value,float) and np.isinf(value) for value in result.values())
    checks.append('勝ちゼロ・負けゼロ・全ゼロ・無取引を無限大PFで優遇しない')
    invalid = [simple_cycle(1,'１',0),dict(simple_cycle(-1,'１',1),symbol='TOPIX')]
    try:
        metrics.summarize(invalid,['１'],'yen')
    except ValueError:
        checks.append('異なる銘柄の円額を混ぜたPF算出を拒否')
    else:
        raise AssertionError('銘柄混合を受け入れた')
    return checks


def sampled_raw_test() -> dict:
    """機能: 保存全脚の分散したセルで逐次サイクル集計と一括CSV集計を照合する。

    引数: なし。返り値: dict: セル・サイクル比較数。
    """
    schema = json.loads((OLD/'数値形式.json').read_text(encoding='utf-8'))
    configs = {r['id']:r for r in json.loads((OLD/'条件一覧.json').read_text(encoding='utf-8'))}
    raw = np.load(OLD/'全取引数値.npz', allow_pickle=False)['trades']
    expected = pd.read_csv(OUT/'旧6123_サイクル.csv')
    keys = np.unique(raw[:,:2].astype(int),axis=0)
    selected = keys[np.linspace(0,len(keys)-1,100).astype(int)]
    count = 0
    for method_index,cell_index in selected:
        mask = (raw[:,0] == method_index) & (raw[:,1] == cell_index)
        method = schema['条件'][method_index]
        session,symbol = schema['セル'][cell_index]
        actual = metrics.from_raw(raw[mask,2:],method,symbol,session,configs[method]['max_legs'])
        frame = expected.loc[(expected.method_index == method_index)&(expected.cell_index == cell_index)]
        assert len(actual) == len(frame)
        for row in actual:
            match = frame.loc[frame.cycle_id == row['cycle_id']].iloc[0]
            for key in ['net_points','net_yen','net_atr','closed_points','open_points','legs','closed_legs','open_legs','entry_order','exit_order']:
                np.testing.assert_allclose(row[key],match[key],rtol=1e-10,atol=1e-8)
            count += 1
    return dict(比較セル数=len(selected),比較サイクル数=count)


def main() -> None:
    """機能: 共通指標の手計算と旧raw別経路照合を実行する。

    引数: なし。返り値: None: サイクル指標の独立監査.jsonを保存する。
    """
    checks = hand_tests()
    result = dict(成功=True,手計算数=len(checks),手計算=checks,保存脚比較=sampled_raw_test(),
                  API取得数=0,metrics_SHA256=hashlib.sha256((OUT/'metrics.py').read_bytes()).hexdigest())
    (OUT/'サイクル指標の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
