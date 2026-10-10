"""価格過程の記述集計の三分割・母集団・未来経路を検証する。"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import analysis as a


def main() -> None:
    """機能: 確率の分母、将来経路、観測被覆、実装の因果監査を確認する。

    引数: なし。返り値: なし(None)。
    """
    aggregate=json.loads((a.HERE/'状態別集計.json').read_text(encoding='utf8'))
    transition=json.loads((a.HERE/'状態遷移集計.json').read_text(encoding='utf8'))
    data=pd.read_csv(a.HERE/'観測点と将来経路.csv');current=pd.read_csv(a.HERE/'現在状態.csv');inputs=a.load()
    count=0
    for row in aggregate:
        if row['n']==0:continue
        assert abs(row['continue_direction']+row['reverse_direction']+row['flat']-1)<1e-12
        assert abs(row['hit_win']+row['hit_loss']+row['untouched']-1)<1e-12
        if row['hit_win']+row['hit_loss']>0:
            assert abs(row['hit_win_if_hit']-row['hit_win']/(row['hit_win']+row['hit_loss']))<1e-12
        count+=1
    for row in transition:
        if row['n']==0:continue
        assert abs(sum(row['rates'].values())-1)<1e-12 and abs(sum(row['baseline_rates'].values())-1)<1e-12
        assert row['baseline_n']>=row['n']
        assert abs(row['same_rate']-row['rates'][row['state']])<1e-12
    assert (current.public_time<=current.time_s).all() and (current.peer_public_time<=current.time_s).all()
    samples=np.unique(np.linspace(0,len(data)-1,256,dtype=int));scanned=0
    for index in samples:
        row=data.iloc[index];ready=inputs[(row.session,row.symbol)];end=row.time_s+row.horizon*60
        assert end<=ready['limit']
        before=np.searchsorted(ready['time_s'],row.time_s,side='left')-1
        assert ready['seq'][before]==row.reference_seq and ready['last'][before]==row.price
        left=np.searchsorted(ready['time_s'],row.time_s,side='left');right=np.searchsorted(ready['time_s'],end,side='left')
        best=worst=0.;first=None;last=None
        for price in ready['last'][left:right]:
            if not np.isfinite(price) or price<=0:continue
            value=(price-row.price)/row.atr*row.evaluation_direction
            best=max(best,value);worst=max(worst,-value);last=value
            if first is None:
                if value>=1.5:first='順行先着'
                elif value<=-.75:first='逆行先着'
        assert first==row.barrier or (first is None and row.barrier=='未到達')
        assert abs(best-row.mfe_atr)<1e-10 and abs(worst-row.mae_atr)<1e-10 and abs(last-row.terminal_atr)<1e-10
        scanned+=1
    # 未来の価格とATRを変えても、観測時点の属性は変化しない。
    obs=current.iloc[len(current)//2].to_dict();session=obs['session'];now=obs['time_s']
    models={k:a.bar_model(k) for k in inputs if k[0]==session}
    key=session,obs['symbol'];normal=a.current_state(key,now,inputs,models)
    for k in models:
        future=inputs[k]['time_s']>=now;inputs[k]['last'][future]+=10000;inputs[k]['atr'][future]*=7
    assert normal==a.current_state(key,now,inputs,models)
    coverage=json.loads((a.HERE/'観測被覆.json').read_text(encoding='utf8'))
    assert sum(r['採用数'] for r in coverage)==len(current)
    a.save('独立確認.json',dict(全合格=True,確率三分割集計数=count,状態遷移母集団確認数=len(transition),
                              逐次将来経路再計算数=scanned,未来価格ATR変更で現在不変=True,被覆一致=True))
    print('記述統計・遷移母集団・未来経路256例の独立確認完了',flush=True)


if __name__=='__main__':main()
