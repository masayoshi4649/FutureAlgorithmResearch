"""主グリッドの在庫・急変耐性を、実成績と分離した固定人工週で調べる。"""

from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'grid'))
import engine
import features


def week_clock() -> dict:
    """機能: 月曜Dayから金曜Nightまでの通常時刻を持つ十秒毎の人工原本を作る。

    引数: なし。返り値: 時刻・場番号・原本番号・期限・進行尺度(dict)。
    """
    zone=timezone(timedelta(hours=9));first=datetime(2026,9,21,tzinfo=zone)
    times=[];sid=[];seq=[];limits=[];starts=[];progress=[];sessions=[]
    total=0.
    for day in range(5):
        for night in (False,True):
            start=first+timedelta(days=day,hours=17 if night else 8,minutes=0 if night else 45)
            limit=(first+timedelta(days=day+1,hours=5,minutes=50)) if night else first+timedelta(days=day,hours=15,minutes=35)
            count=int((limit-start).total_seconds()//10)+2
            times.extend(start.timestamp()+np.arange(count)*10);sid.extend([len(limits)]*count);seq.extend(np.arange(count))
            limits.append(limit.timestamp());starts.append(start.timestamp())
            # 各場の最初の120分だけ進み、その後は横ばい。進行中30分で3格子となる。
            progress.extend(total+np.minimum(np.arange(count)/6,120)/10)
            total+=12.
            sessions.append(start.date().isoformat()+('_Night' if night else '_Day'))
    return dict(times=np.asarray(times),sessions=np.asarray(sid,np.int64),seqs=np.asarray(seq,np.int64),
                limits=np.asarray(limits),starts=starts,progress=np.asarray(progress),names=sessions)


def main() -> None:
    """機能: 同じ主条件を両銘柄・五経路へ固定適用し、手数料・週末全返済まで記録する。

    引数: なし。返り値: なし(None)。証拠金・発生確率・実運用の利益は推定しない。
    """
    clock=week_clock();p=clock['progress'];rows=[];series=[]
    pathways={'上昇':p,'下降':-p,'往復':6-abs((p%24)-12),
              'V反転':abs(p-60)-60,'場間8格子gap':np.minimum(p,12)+(clock['sessions']>=1)*8}
    # 往復もVも初値と終値を揃え、通過経路だけを違える。
    pathways['往復']-=pathways['往復'][0]
    for symbol,base,tick,cap,value,fee in [('TOPIX',4000.,.5,10,1000.,418),('NK225',64000.,10.,20,10.,110)]:
        opening=base+tick/2
        delta=max(2*tick,np.ceil(opening*.00125/tick-1e-10)*tick)
        for name,moves in pathways.items():
            bid=np.round((base+moves*delta)/tick)*tick;ask=bid+tick;mid=(bid+ask)/2
            events=[]
            for sid in range(10):
                selected=np.flatnonzero(clock['sessions']==sid);offset=selected[0]
                r=dict(time_s=clock['times'][selected],start=clock['starts'][sid])
                e=features.direction_events(r,dict(mid=mid[selected]));e[:,0]+=offset;events.append(e)
            for family in range(5):
                out=engine.replay(clock['times'],clock['seqs'],mid,bid,ask,clock['sessions'],clock['limits'],
                                  np.concatenate(events),1,family,5,1,0,.00125,cap,value,tick,fee)
                orders,trades,equity,mid_equity,risks=out[:5]
                assert not out[6][:,1].any() and max(risks[:,:2].max(initial=0),0)<=cap
                np.testing.assert_allclose(equity[-1],trades[:,18].sum(),atol=1e-5)
                np.testing.assert_allclose(orders[:,13].sum(),trades[:,16:18].sum(),atol=1e-5)
                assert not len(orders) or np.all(orders[:,13]==(orders[:,11].astype(int)*fee)//10)
                assert not len(orders) or orders[-1,4]<clock['limits'][-1]+300
                peak=np.maximum.accumulate(np.r_[0,equity])[1:]
                closing=orders[(orders[:,9]==2)&(orders[:,15]==1)]
                rows.append(dict(銘柄=symbol,経路=name,方式=f'G{family}',初値=float(mid[0]),終値=float(mid[-1]),
                                 格子幅=float(delta),収支=float(equity[-1]),手数料=float(orders[:,13].sum()),
                                 粗利益=float(trades[trades[:,15]>0,15].sum()),粗損失=float(-trades[trades[:,15]<0,15].sum()),
                                 最大資産減少=float((peak-equity).max()),最大負け玉含み=float(-risks[:,4].min(initial=0)),
                                 最大買枚数=int(risks[:,0].max(initial=0)),最大売枚数=int(risks[:,1].max(initial=0)),
                                 最大両側合計枚数=int(risks[:,:2].sum(axis=1).max(initial=0)),
                                 週予算返済注文=int(((orders[:,9]==2)&(orders[:,15]==4)).sum()),
                                 運用組保護返済注文=int(((orders[:,9]==2)&(orders[:,15]==5)).sum()),
                                 週末返済注文=len(closing),全玉返済=True,返済玉数=len(trades)))
                series.append(dict(銘柄=symbol,経路=name,方式=f'G{family}',
                                   価格=[float(x) for x in mid[::60]],資産=[float(x) for x in equity[::60]]))
    result=dict(合格=True,用途='固定人工相場で在庫管理の機構だけを検査。実データ成績・利益選抜には使用しない。',
                条件='事前主条件G0〜G4、週初0.125%、片側5段、週内持越し、買ask/売bidの次行約定、全注文手数料、金曜Night全返済',
                観測='十秒毎一行。各場最初の120分は進行尺度が30分3格子、その後横ばい。large呼値に丸め、spreadはlarge1呼値。',
                検査入力訂正='最初の毎分標本では価格の格子到達と5分足の中心移動が一致して全条件無取引となった。機構へ負荷をかけるため、価格形状・終点・進行速度を変えず十秒標本へ変更。実市場の条件選抜ではない。',
                同じ終点='往復とV反転はいずれも初値と同じ終値。売買へ経路名や未来形状を渡さない。',
                gap='第1Dayから第1Nightの間に8格子上方へ飛ぶ。その間の途中価格を生成しない。',
                限界='実相場の発生確率・期待利益・証拠金余力・値幅制限・市場インパクトを検証したものではない。',
                結果=rows,図示用=series,コードSHA256=hashlib.sha256((HERE.parent/'grid/engine.py').read_bytes()).hexdigest())
    (HERE/'主グリッドの人工相場検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'合格':True,'再生数':len(rows),'実データ利益選抜不使用':True},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
