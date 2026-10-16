"""説明に使う初回主3の損失分解を、注文と原本価格から再計算する。"""

import json
from datetime import datetime

import numpy as np

from accounts import HERE,WORK,study


def main() -> None:
    """機能: 全849組の二種類の損益分解と表示時計を独立に照合する。

    引数: なし。返り値: なし(None)。監査領域だけに結果を保存する。
    """
    packet=study.load(WORK/'diagnosis/初回主3の損失原因.json')
    ready,books,signals,maps=study.material();count=fields=0
    for ident,records in packet['全取引'].items():
        ledgers=study.load(WORK/'first/ledgers'/f'{ident}.pkl')
        for row in records:
            key=(row['セッション'],row['商品']);ledger=ledgers[key]
            cid=int(row['組']);t=ledger['trades'][cid];orders=ledger['orders'][ledger['orders'][:,2]==cid]
            entry=orders[orders[:,7]==1][0];exit_order=orders[orders[:,7]==0][0]
            bid,ask=books[key]['bid'],books[key]['ask'];times=ready[key]['time_s']
            valid=np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>=bid)
            old=np.maximum.accumulate(np.where(valid,np.arange(len(times)),-1))
            er,xr=int(entry[0]),int(exit_order[0]);ed,xd=old[int(entry[1])],old[int(exit_order[1])]
            direction,quantity=int(t[3]),int(t[4]);value=1000 if key[1]=='TOPIX' else 10;scale=quantity*value
            med=(bid[er]+ask[er])/2.;mxd=(bid[xr]+ask[xr])/2.
            eq=ask[ed] if direction==1 else bid[ed];xq=bid[xd] if direction==1 else ask[xd]
            independent={
                '収支円':direction*(exit_order[5]-entry[5])*scale-entry[8]-exit_order[8],
                '手数料円':entry[8]+exit_order[8],
                '中値経路円':direction*(mxd-med)*scale,
                '新規対中値不利円':direction*(entry[5]-med)*scale,
                '返済対中値不利円':direction*(mxd-exit_order[5])*scale,
                '新規判断から約定の不利円':direction*(entry[5]-eq)*scale,
                '返済判断から約定の不利円':direction*(xq-exit_order[5])*scale,
                '判断気配の仮収支円':direction*(xq-eq)*scale-entry[8]-exit_order[8],
                '新規待ち秒':entry[12]-entry[10],
                '返済待ち秒':exit_order[12]-exit_order[10],
                '保有秒':times[xr]-times[er],
                '新規直後不利呼値':direction*(entry[5]-(bid[er] if direction==1 else ask[er]))/ready[key]['tick'],
            }
            good=valid[er:xr+1];q=(bid if direction==1 else ask)[er:xr+1]
            path=direction*(q-entry[5])*scale-entry[8]-exit_order[8]
            independent.update(MFE円=path[good].max(),MAE円=path[good].min())
            for name,value in independent.items():
                assert abs(row[name]-value)<1e-6,(ident,cid,name,row[name],value);fields+=1
            for prefix,order in [('新規',entry),('返済',exit_order)]:
                for name,col in [('判断',10),('到着予定',11),('約定',12)]:
                    assert datetime.fromisoformat(row[prefix+name]).timestamp()==order[col];fields+=1
            assert abs(row['収支円']-(row['中値経路円']-row['新規対中値不利円']-row['返済対中値不利円']-row['手数料円']))<1e-6
            assert abs(row['収支円']-(row['判断気配の仮収支円']-row['新規判断から約定の不利円']-row['返済判断から約定の不利円']))<1e-6
            count+=1
    assert count==849
    result=dict(合格=True,全初回主3決済組数=count,価格時刻と分解の照合数=fields,
        資料SHA256=study.digest(WORK/'diagnosis/初回主3の損失原因.json'),
        解釈=['中値経路の分解と判断気配の分解は代替的な二式。遅延を重ねて控除しない。',
            '指値M2の対中値不利は、通常の気配差だけでなく通過後に元指値で約定する代理仮定の負担も含む。',
            '判断気配の仮収支は固定判断列を使った原因診断。0秒で全経路を再生した実績とは区別する。'])
    (HERE/'初回主3の損失分解と表示時計監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
