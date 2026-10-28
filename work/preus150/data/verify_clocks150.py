"""窓ごとに分末を直接探索し、保存した時刻診断を独立に検算する。"""

import json
import pickle
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent


def main() -> None:
    """50場の変化数・急変数・平均変化・気配差を照合する。

    引数: なし。
    返り値: None。検算証跡を保存する。金融再生は行わない。
    """
    saved=json.loads((OUT/'時刻前後の市場診断150.json').read_text('utf-8'))
    checked=0;windows=0
    for scene in saved['sessions']:
        data=pickle.loads((ROOT/f'work/research145_engine/cache/{scene["session"]}.pkl').read_bytes())[1]
        q,r=data['quotes'],data['ready']
        mask=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])&(r['time_s']>=r['start'])
        t,bid,ask=r['time_s'][mask],q['bid'][mask],q['ask'][mask]
        for window in scene['windows'].values():
            mids={};spreads=[];changes=[]
            for minute in np.arange(window['start']-60,window['end'],60):
                last=int(np.searchsorted(t,minute+60,side='left'))-1
                if last>=0 and t[last]>=minute:
                    mids[minute]=(bid[last]+ask[last])/2
                    if minute>=window['start']:
                        spreads.append(ask[last]-bid[last])
                        if minute-60 in mids: changes.append(abs(mids[minute]-mids[minute-60]))
            assert len(changes)==window['observed_changes']
            assert len(spreads)==window['observed_minutes']
            for threshold in (50,100,200):
                assert sum(change>=threshold for change in changes)==window[f'jump_{threshold}_count']
                assert np.isclose(np.mean(np.array(changes)>=threshold),window[f'jump_{threshold}_rate'])
                checked+=2
            for values,prefix in ((changes,'abs_change'),(spreads,'spread')):
                for suffix,function in [('mean',np.mean),('median',np.median),('max',np.max)]:
                    assert np.isclose(function(values),window[prefix+'_'+suffix])
                    checked+=1
                assert np.isclose(np.quantile(values,.9),window[prefix+'_p90'])
                checked+=1
            raw_mask=(t>=window['start'])&(t<window['end'])
            raw_mid=(bid[raw_mask]+ask[raw_mask])/2
            minute_mid=[v for k,v in mids.items() if k>=window['start']]
            assert np.isclose(max(raw_mid)-min(raw_mid),window['range_mid'])
            assert np.isclose(max(minute_mid)-min(minute_mid),window['range_minute_mid'])
            checked+=2
            windows+=1
    result=dict(all_checks_passed=True,sessions=50,windows=windows,numeric_checks=checked,
                independent_minute_lookup=True,financial_replays=0)
    (OUT/'時刻診断の独立検算150.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result))


if __name__=='__main__':
    main()
