"""説明専用の中値再評価・固定障壁先着・確認後反応を独立照合する。"""

import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
sys.path.insert(0,str(TASK))
from features import load_inputs_only


def main() -> None:
    """機能: 売買へ戻さない将来ラベルの説明数値を検査する。

    引数: なし。返り値: なし(None)。注文・売買条件を変更しない。
    """
    result=json.loads((TASK/'売買結果.json').read_text(encoding='utf8'))
    analysis=json.loads((TASK/'仮説の反証分析.json').read_text(encoding='utf8'))
    outputs={(x['id'],x['symbol']):x for x in analysis['売買の分解']}
    inputs=load_inputs_only()
    quotes=pickle.loads((TASK.parent/'wave_v52/measurement/quotes.pkl').read_bytes())
    count=0
    for m in result['methods']:
        for symbol in ('TOPIX','NK225'):
            mid=0.
            value=1000. if symbol=='TOPIX' else 10.
            buckets={'利益2R先着':0,'損失1R先着':0,'どちらも未到達':0,'反証済約定':0}
            for a in (a for a in m['accounts'] if a['symbol']==symbol):
                key=a['session'],symbol
                q,ready=quotes[key],inputs[key]
                for g,t in zip(a['risk_groups'],a['trades']):
                    begin,end=np.searchsorted(q['seq'],[t[11],t[12]])
                    mid+=t[2]*t[3]*(q['mid'][end]-q['mid'][begin])*value
                    bound=min(ready['limit'],ready['time_s'][begin]+1800.)
                    indexes=np.flatnonzero((np.arange(len(ready['seq']))>=begin)&(ready['time_s']<=bound))
                    path=t[2]*(ready['last'][indexes]-t[4])
                    up=np.flatnonzero(path>=2*g[3]);down=np.flatnonzero(path<=-g[3])
                    if g[10]:buckets['反証済約定']+=1
                    elif not len(up) and not len(down):buckets['どちらも未到達']+=1
                    elif len(up) and (not len(down) or up[0]<down[0]):buckets['利益2R先着']+=1
                    else:buckets['損失1R先着']+=1
                    count+=1
            assert np.isclose(mid,outputs[m['id'],symbol]['mid_net'],atol=1e-6,rtol=0)
            assert buckets==outputs[m['id'],symbol]['barriers']
    paired=[]
    for symbol in ('TOPIX','NK225'):
        records=[]
        for key,ready in inputs.items():
            if key[1]!=symbol:continue
            q=quotes[key]
            es=json.loads((TASK/'事件'/f'{key[0]}_{symbol}.json').read_text(encoding='utf8'))
            for e in es:
                if e['kind']!=1 or not e.get('geometry') or not e.get('supply_ok') or not e.get('activity_ok'):continue
                i=e['raw_index']+1
                if i>=len(q['seq']) or ready['time_s'][i]>=ready['limit']-300:continue
                start=np.searchsorted(q['seq'],e['start_seq'])
                target=ready['time_s'][i]+900.
                past=np.flatnonzero(ready['time_s']<=target)
                j=past[-1] if len(past) else -1
                valid=target<=ready['limit'] and j>=i and target-ready['time_s'][j]<=60
                wait=e['side']*(q['mid'][i]-q['mid'][start])/e['atr']
                reaction=e['side']*(q['mid'][j]-q['mid'][i])/e['atr'] if valid else None
                records.append((wait,reaction))
        expected=next(r for r in analysis['確認後反応'] if r['symbol']==symbol and r['kind']==1 and r['gate']==3)
        known=[r for r in records if r[1] is not None]
        assert len(records)==expected['count'] and len(known)==expected['15']['n']
        assert np.isclose(np.mean([r[0] for r in records]),expected['wait_mean_atr'],atol=1e-10,rtol=0)
        assert np.isclose(np.mean([r[1] for r in known]),expected['15']['mean_atr'],atol=1e-10,rtol=0)
        paired.append(dict(銘柄=symbol,待機観測数=len(records),十五分有効数=len(known),
                           同じ有効集合の待機平均ATR=float(np.mean([r[0] for r in known])),
                           同じ有効集合の確認後平均ATR=float(np.mean([r[1] for r in known]))))
    proof=dict(合格=True,固定障壁検査組数=count,中値検査条件銘柄数=len(outputs),確認後反応=paired,
               注意='TOPIXは待機45件・15分反応44件。同じ44件に揃えた待機平均も記録。未来ラベルは売買判断に使わない。')
    (HERE/'説明用結果の独立監査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
