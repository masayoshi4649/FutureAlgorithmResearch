"""現在在庫の期首・既知境界・未決済・追加区間を人工データだけで照合する。"""

import json
from pathlib import Path

import numpy as np

import inventory_replay as live


def main() -> None:
    """機能: 同時計の別行を含む全境界で、注文現金と残玉時価の一致を検査する。

    引数: なし。返り値: なし(None)。現在資料とネットワークには触れない。
    """
    checks=[]
    opened_checks=0
    for symbol,value,large_tick in (('TOPIX',1000.,1.),('NK225',10.,1.)):
        for family in range(5):
            for mode in (0,1):
                for trending in (False,True):
                    times=np.r_[np.arange(10)*300.,2701.,2701.,2710.,2730.,2730.]
                    mid=np.r_[10000.+np.arange(10)*10.,10100.,10100.,10112.,10125.,10125.] if trending else np.r_[np.full(10,10000.),9990.,9990.,9993.,10002.,10002.]
                    ready=dict(seq=np.arange(len(mid)),time_s=times,start=0.,limit=20000.,symbol=symbol,session='2026-10-07_Night',tick=large_tick)
                    quote=dict(seq=ready['seq'],time_s=times,mid=mid,bid=mid-1.,ask=mid+1.)
                    config=dict(id='人工',price_mode='quote' if mode==0 else 'mid',
                        config=dict(family=family,steps=5,mode=mode,fraction=.001,top_cap=5,minutes=60,cooldown_seconds=60))
                    for count in range(len(mid)+1):
                        result=live.partial_account(ready,quote,config,count)
                        point=result['既知境界']
                        added=result['追加区間']
                        assert result['現在末尾']['net']==point['net']+added['net']
                        orders=np.asarray(result['orders'],float).reshape((-1,20))
                        trades=np.asarray(result['trades'],float).reshape((-1,23))
                        entered={int(o[0]):o for o in orders if o[9]==1 and o[2]<count}
                        for leg in trades:
                            if leg[8]<count:
                                entered.pop(int(leg[5]))
                        marked=0.
                        if count:
                            for entry in entered.values():
                                side=entry[10]
                                price=mid[count-1] if mode==1 else (quote['bid'][count-1] if side>0 else quote['ask'][count-1])
                                marked+=side*entry[11]*price*value
                        np.testing.assert_allclose(point['cash']+marked,point['net'],atol=1e-5)
                        if entered:
                            opened_checks+=1
                        if count==len(mid):
                            assert added['net']==0 and added['fees']==0 and added['unrealized']==0
                        checks.append(dict(銘柄=symbol,family=family,mode=mode,上向き=trending,境界=count))
    assert opened_checks>0
    output=dict(合格=True,境界検査数=len(checks),残玉あり境界数=opened_checks,
                API取得数=0,現在入力未読=True,詳細=checks)
    path=Path(__file__).resolve().parent/'在庫途中会計の合成監査.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in output.items() if k!='詳細'},ensure_ascii=False))


if __name__=='__main__':
    main()
