"""固定した仮説のどの段階で収益が残らなかったかを結果として測る。"""

from pathlib import Path
import json
import pickle

import numpy as np

from features import load_inputs_only
from engine import REASONS
from backtest import save


HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 待機中の値動き、確認後の反応、目標と反証の先着を検算する。

    引数: なし。返り値: なし(None)。未来は説明用の結果であり入口へ戻さない。
    """
    result=json.loads((HERE/'売買結果.json').read_text(encoding='utf8'))
    inputs=load_inputs_only()
    quotes=pickle.loads((HERE.parent/'wave_v52/measurement/quotes.pkl').read_bytes())
    measurements=[]
    counts={}
    for key,ready in inputs.items():
        records=json.loads((HERE/'事件'/f'{key[0]}_{key[1]}.json').read_text(encoding='utf8'))
        q=quotes[key]
        for e in records:
            if not e['kind']:
                continue
            if key[1] not in counts:
                counts[key[1]]=dict(確定事件=0,幾何適合=0,狭すぎる=0,遠すぎる=0,回帰余地不足=0,供給確認=0,活動確認=0,両確認=0)
            c=counts[key[1]]
            c['確定事件']+=1
            c['幾何適合']+=int(e['geometry'])
            c['狭すぎる']+=int(e['planned_risk']<2*ready['tick'])
            c['遠すぎる']+=int(e['planned_risk']>.75*e['atr'])
            c['回帰余地不足']+=int(e['kind']==-1 and e['room']<2*e['planned_risk'])
            if not e['geometry']:
                continue
            c['供給確認']+=int(e['supply_ok'])
            c['活動確認']+=int(e['activity_ok'])
            c['両確認']+=int(e['supply_ok'] and e['activity_ok'])
            i=e['raw_index']+1
            if i>=len(q['seq']) or ready['time_s'][i]>=ready['limit']-300:
                continue
            start=int(np.searchsorted(q['seq'],e['start_seq']))
            item=dict(symbol=key[1],session=key[0],kind=e['kind'],event_id=e['event_id'],
                      supply=e['supply_ok'],activity=e['activity_ok'],
                      waiting_seconds=e['end_time']-e['start_time'],
                      waiting_atr=e['side']*(q['mid'][i]-q['mid'][start])/e['atr'])
            for horizon in (300.,900.):
                target=ready['time_s'][i]+horizon
                j=int(np.searchsorted(ready['time_s'],target,side='right'))-1
                valid=target<=ready['limit'] and j>=i and target-ready['time_s'][j]<=60
                item[str(int(horizon/60))]=float(e['side']*(q['mid'][j]-q['mid'][i])/e['atr']) if valid else None
            measurements.append(item)
    forward=[]
    for symbol in ('TOPIX','NK225'):
        for kind in (1,-1):
            for gate in (0,1,2,3):
                rows=[m for m in measurements if m['symbol']==symbol and m['kind']==kind and (not gate&1 or m['supply']) and (not gate&2 or m['activity'])]
                out=dict(symbol=symbol,kind=kind,gate=gate,count=len(rows),
                         wait_median_seconds=float(np.median([m['waiting_seconds'] for m in rows])) if rows else None,
                         wait_mean_atr=float(np.mean([m['waiting_atr'] for m in rows])) if rows else None)
                for h in ('5','15'):
                    a=np.array([m[h] for m in rows if m[h] is not None])
                    out[h]=dict(n=len(a),mean_atr=float(a.mean()) if len(a) else None,win_rate=float((a>0).mean()) if len(a) else None)
                forward.append(out)
    # ----------------------------------------
    # 早期に返済していても、同じ入口の固定2R/1R先着を30分だけ追跡する説明用対照。
    evaluations=[]
    for method in result['methods']:
        for symbol in ('TOPIX','NK225'):
            buckets=dict(利益2R先着=0,損失1R先着=0,どちらも未到達=0,反証済約定=0)
            reasons={}
            mid_net=0.
            for account in [a for a in method['accounts'] if a['symbol']==symbol]:
                key=(account['session'],symbol)
                ready,q=inputs[key],quotes[key]
                value=1000 if symbol=='TOPIX' else 10
                for order in account['orders']:
                    j=int(np.searchsorted(q['seq'],int(order[3])))
                    mid_net-=order[5]*order[6]*q['mid'][j]*value
                for group,leg in zip(account['risk_groups'],account['trades']):
                    risk,start,side,entry=group[3],int(group[5]),group[7],group[8]
                    end=int(np.searchsorted(ready['time_s'],min(ready['limit'],ready['time_s'][start]+1800.),side='right'))
                    path=side*(ready['last'][start:end]-entry)/risk
                    hit=np.flatnonzero((path>=2)|(path<=-1))
                    if group[10]:
                        buckets['反証済約定']+=1
                    elif not len(hit):
                        buckets['どちらも未到達']+=1
                    else:
                        buckets['利益2R先着' if path[hit[0]]>=2 else '損失1R先着']+=1
                    name=REASONS[int(leg[7])]
                    if name not in reasons:
                        reasons[name]=dict(組数=0,利益円=0.,損失円=0.,合計R=0.)
                    reasons[name]['組数']+=1
                    reasons[name]['利益円']+=max(leg[6],0)
                    reasons[name]['損失円']+=max(-leg[6],0)
                    reasons[name]['合計R']+=group[4]
            evaluations.append(dict(id=method['id'],symbol=symbol,barriers=buckets,exit_reasons=reasons,mid_net=mid_net,
                                    last_net=method['summary'][symbol]['net']))
    save(HERE/'仮説の反証分析.json',dict(入口件数=counts,確認後反応=forward,売買の分解=evaluations,
                                      留意='将来反応は重なった事件を含む説明用観測。未来データは売買へ戻さない。2R先着率は30分の固定経路対照で、実際のトレーリング損益とは異なる。中値評価は注文時刻と枚数を固定した価格置換で実約定保証ではない。'))
    for row in forward:
        if row['gate'] in (0,3):
            print(json.dumps(row,ensure_ascii=False))
    for row in evaluations:
        if row['id']=='S3_T':
            print(json.dumps(row,ensure_ascii=False))


if __name__ == '__main__':
    main()
