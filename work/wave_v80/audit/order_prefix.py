"""実原本の注文待機・建玉保有・取消境界で未来を切断及び改変する。"""

from __future__ import annotations

import json
import hashlib

import numpy as np

from accounts import HERE,WORK,study,pdca


def event_prefix(events: np.ndarray, cut: int, last_time: float) -> np.ndarray:
    """機能: 原本行と論理発火時計を両方使って既知イベントだけを抜き出す。

    引数: events(ndarray)、cut(int)、last_time(float)。返り値: 過去イベント(ndarray)。
    タイマーは最後既知行を参照するため、原本行だけでは未来発火を除外できない。
    """
    return events[(events[:,0]<cut)&(events[:,3]<=last_time)]


def main() -> None:
    """機能: 固定全代表の遅延別原本再生で過去注文と全行時価の不変を確認する。

    引数: なし。返り値: なし(None)。監査領域だけへ証跡を保存する。
    """
    materials=study.material();selected=study.load(WORK/'最終前半選定.json')['確認条件']
    accounts=cuts_total=checks=holding=entry_wait=exit_wait=resting=0;records=[]
    for delay in [0,1,5]:
        base=WORK/'final'/f'delay{delay}'
        for config in selected:
            packet=study.load(base/'results'/f'{config["id"]}.json')
            saved=study.load(base/'ledgers'/f'{config["id"]}.pkl')
            keys=set()
            for symbol in ['TOPIX','NK225']:
                rows=[r for r in packet['rows'] if r['symbol']==symbol]
                for sorting in [lambda r:r['trades'],lambda r:r['net'],lambda r:-r['net'],lambda r:r['cancellations']]:
                    row=max(rows,key=sorting)
                    keys.add((row['session'],symbol))
            for key in sorted(keys):
                args=pdca.arguments(config,key,materials,delay)
                full=study.engine.simulate(*args);old=saved[key]
                for part,name in [(0,'orders'),(1,'trades'),(3,'stats'),(4,'events')]:
                    np.testing.assert_array_equal(full[part],old[name])
                assert hashlib.sha256(full[2].tobytes()).hexdigest()==old['curve_hash']
                times=args[0];n=len(times);locations={max(1,int(n*.43)),max(1,int(n*.79))}
                orders=full[0]
                selected_orders=np.r_[np.arange(min(4,len(orders))),np.arange(max(0,len(orders)-2),len(orders))]
                for index in selected_orders:
                    order=orders[index]
                    locations.update([int(order[1])+1,int(order[0]),int(order[0])+1])
                for event in full[4][np.isin(full[4][:,2],[22,23,30])][:3]:
                    row=int(np.searchsorted(times,event[3],side='left'))
                    locations.update([max(1,row),row+1])
                local=0
                for cut in sorted(c for c in locations if 0<c<n):
                    short=list(args)
                    for i in range(6):short[i]=args[i][:cut]
                    before=study.engine.simulate(*short)
                    expected_events=event_prefix(full[4],cut,times[cut-1])
                    np.testing.assert_array_equal(before[0],full[0][full[0][:,0]<cut])
                    np.testing.assert_array_equal(before[1],full[1][full[1][:,2]<cut])
                    np.testing.assert_array_equal(before[2],full[2][:cut])
                    np.testing.assert_array_equal(before[4],expected_events)
                    changed=list(args)
                    changed[1]=args[1].copy();changed[2]=args[2].copy();changed[7]=args[7].copy()
                    changed[1][cut:]+=args[12]*1000.;changed[2][cut:]+=args[12]*1000.
                    changed[7][args[6]>times[cut-1]]*=-1
                    later=study.engine.simulate(*changed)
                    np.testing.assert_array_equal(later[0][later[0][:,0]<cut],before[0])
                    np.testing.assert_array_equal(later[1][later[1][:,2]<cut],before[1])
                    np.testing.assert_array_equal(later[2][:cut],before[2])
                    np.testing.assert_array_equal(event_prefix(later[4],cut,times[cut-1]),before[4])
                    holding+=int(before[3][0]!=0);entry_wait+=int(before[3][1]!=0)
                    exit_wait+=int(before[3][2]!=0);resting+=int(before[3][3]!=0)
                    cuts_total+=1;checks+=8;local+=1
                accounts+=1
                records.append(dict(条件=config['id'],遅延秒=delay,商品=key[1],セッション=key[0],切断地点数=local))
            print(f'注文未来不変 {delay}秒 {config["id"]} 完了',flush=True)
    result=dict(合格=True,代表条件数=len(selected),遅延水準数=3,実原本口座数=accounts,
        切断地点数=cuts_total,配列照合数=checks,保有中切断数=holding,新規待ち切断数=entry_wait,
        返済待ち切断数=exit_wait,待機指値切断数=resting,全地点=records,
        エンジンSHA256=study.digest(WORK/'engine.py'),最終選定SHA256=study.digest(WORK/'最終前半選定.json'),
        注意='タイマー記録は参照原本行と論理発火時計を併用。未来の価格・状態を改変しても過去記録は不変。真の受信順や実際の指値キューは証明しない。')
    (HERE/'全最終代表と三遅延の実注文未来監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='全地点'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
