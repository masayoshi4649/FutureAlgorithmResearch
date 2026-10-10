"""新管理条件の会計・因果性・対称性と、旧入力による実行速度だけを検査する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import time

import numpy as np

import discovery_managers as discovery
import engine
import managers

OUT=Path(__file__).resolve().parent
OLD=OUT.parent/'wave_v23'


def verify(result: dict, ready: dict, cap: int) -> None:
    """機能: 注文から現金・両方向枚数・時価を独立に復元する。

    引数: result/ready (dict)、cap (int)。返り値: なし (None)。
    """
    n=len(ready['last'])
    orders=result['orders'];rows=orders[:,0].astype(int)
    side,qty,price,opened=orders[:,3],orders[:,4],orders[:,5],orders[:,7]
    cash=-np.bincount(rows,weights=side*qty*price,minlength=n).cumsum()
    long_delta=np.where((opened==1)&(side==1),qty,np.where((opened==0)&(side==-1),-qty,0))
    short_delta=np.where((opened==1)&(side==-1),qty,np.where((opened==0)&(side==1),-qty,0))
    longs=np.bincount(rows,weights=long_delta,minlength=n).cumsum()
    shorts=np.bincount(rows,weights=short_delta,minlength=n).cumsum()
    assert np.all(longs>=0) and np.all(shorts>=0)
    assert max(longs.max(),shorts.max())<=cap
    equity=cash+(longs-shorts)*ready['last']
    np.testing.assert_allclose(result['curve'][:,0],equity,atol=1e-7)
    np.testing.assert_allclose(result['curve'][:,2],longs,atol=0)
    np.testing.assert_allclose(result['curve'][:,3],shorts,atol=0)
    assert result['stats'][9]==0 and longs[-1]==shorts[-1]==0
    assert np.all(orders[:,0]>orders[:,1])
    np.testing.assert_allclose(result['trades'][:,10].sum(),cash[-1],atol=1e-7)


def main() -> None:
    """機能: 全条件を合成経路で検証し、既知原型の速度だけを測る。

    引数: なし。返り値: なし (None)。新実データ収支は集計・参照しない。
    """
    discovery.main()
    specs=discovery.catalog()
    n=720
    t=np.arange(n)*60.
    prices=np.round((1000+40*np.sin(np.arange(n)/45)+12*np.sin(np.arange(n)/13))*2)/2
    direction=np.where(np.arange(n)%270<135,1,-1).astype(np.int8)
    direction[(np.arange(n)%110)>97]=0
    ready={'time_s':t,'last':prices,'atr':np.full(n,4.),'tick':.5,'start':0.,'limit':t[-3],'us_open':18000.}
    reflected=dict(ready,last=2200-prices)
    checks=[]
    for symbol in ('TOPIX','NK225'):
        for spec in specs:
            cfg=managers.make_config(spec,symbol,ready)
            result=engine.run(ready,direction,cfg,True)
            verify(result,ready,cfg['audit_cap'])
            opposite=engine.run(reflected,-direction,cfg,True)
            verify(opposite,reflected,cfg['audit_cap'])
            a,b=result['trades'],opposite['trades']
            assert a.shape==b.shape
            np.testing.assert_allclose(a[:,[0,1,3,6,7,8,9,10]],b[:,[0,1,3,6,7,8,9,10]],atol=1e-6)
            np.testing.assert_allclose(a[:,2],-b[:,2],atol=0)
            np.testing.assert_allclose(a[:,4:6]+b[:,4:6],2200,atol=1e-6)
            cut=359
            prefix={key:(value[:cut] if isinstance(value,np.ndarray) else value)for key,value in ready.items()}
            early=engine.run(prefix,direction[:cut],cfg,True)
            np.testing.assert_allclose(early['curve'],result['curve'][:cut],atol=1e-7)
            np.testing.assert_allclose(early['orders'],result['orders'][result['orders'][:,0]<cut],atol=1e-7)
            checks.append({'ID':spec['id'],'銘柄':symbol,'会計':True,'上限':True,'場内返済':True,'鏡映対称':True,'未来切断':True})
    # ----------------------------------------
    # ベンチマークは以前からある原型条件と既知F32方向で行い、新探索収支は出力しない。
    inputs=pickle.loads((OLD/'inputs.pkl').read_bytes())
    directions=pickle.loads((OLD/'directions.pkl').read_bytes())['F32']
    old_specs={spec['id']:spec for spec in managers.manager_catalog()}
    timings=[]
    for identifier in ('G00','G12','G14'):
        for repeat in range(3):
            started=time.perf_counter()
            for key,item in inputs.items():
                cfg=managers.make_config(old_specs[identifier],key[1],item)
                engine.run(item,directions[key],cfg,False)
            timings.append({'原型':identifier,'反復':repeat+1,'区間数':len(inputs),'秒':time.perf_counter()-started})
    benchmark={identifier:float(np.median([row['秒']for row in timings if row['原型']==identifier]))for identifier in old_specs if identifier in ('G00','G12','G14')}
    output={'合格':True,'一意条件数':len(specs),'合成の条件銘柄数':len(checks),'合成再生数':len(checks)*3,
            '検算':checks,'ベンチマーク':timings,'26区間の中央値秒':benchmark,
            '新探索の損益参照':False,'注意':'速度は単一プロセスの現在環境。１２並列で単純に１２倍速とは限らない。'}
    (OUT/'manager_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'合格':True,'条件数':len(specs),'合成再生数':len(checks)*3,'26区間中央値秒':benchmark},ensure_ascii=False))


if __name__=='__main__':
    main()
