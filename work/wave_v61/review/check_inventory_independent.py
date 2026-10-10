"""場内在庫の会計・期限・カバー・将来非依存を独立人工経路で検査する。"""

import os
os.environ['NUMBA_DISABLE_JIT']='1'
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'inventory'
sys.path.insert(0,str(SOURCE))
import engine


def fixture(prices: list, events: list | None=None, times: list | None=None) -> dict:
    """機能: 気配・原本行・単一場を持つ人工入力を作る。

    引数: prices/events/times(list又はNone)。返り値: 入力辞書(dict)。
    """
    mid=np.asarray(prices,float);n=len(mid)
    stamp=np.asarray(times if times is not None else list(np.arange(n-2)*30)+[1940,1941],float)
    return dict(times=stamp,seqs=np.arange(n,dtype=np.int64)*3+7,mid=mid,bid=mid-.5,ask=mid+.5,
                sessions=np.zeros(n,np.int64),limits=np.array([2000.]),
                events=np.asarray(events if events is not None else [[0,0,0,1]],float))


def run(data: dict,family: int,mode: int,finish: bool=True,minutes: int=5,cooldown: int=0) -> tuple:
    """機能: 固定人工契約で在庫再生器を呼ぶ。

    引数: data(dict)、family/mode/minutes/cooldown(int)、finish(bool)。返り値: エンジン生出力(tuple)。
    """
    return engine.replay(**data,family=family,steps=5,mode=mode,fraction=.001,cap=10,value=1000.,
                         tick=1.,fee_tenths=418,minutes=minutes,cooldown_seconds=cooldown,finish=finish)


def independent_account(data: dict,result: tuple,mode: int,family: int) -> None:
    """機能: 元玉と返済を結び全行の現金・枚数・清算時価を別式で再構成する。

    引数: data(dict)、result(tuple)、mode/family(int)。返り値: なし(None)。
    """
    orders,trades,equity,mid_equity,risks,_,pos,_,book=result[:9]
    cash=0.;open_lots={};cursor=0
    for i in range(len(data['mid'])):
        while cursor<len(orders) and orders[cursor,2]==i:
            order=orders[cursor];oid=int(order[0]);decision=int(order[1]);side=int(order[10]);qty=int(order[11])
            assert decision<i and order[3]==data['times'][decision] and order[4]==data['times'][i]
            assert order[5]==0 and order[6]==0
            assert order[7]==data['seqs'][decision] and order[8]==data['seqs'][i]
            fee=(qty*418)//10
            assert order[13]==fee
            passive=mode==2 and (order[15] in (8,14) or (order[15]==0 and family!=3))
            if not passive:
                assert i==decision+1
                price=data['mid'][i] if mode==1 else data['ask'][i] if side>0 else data['bid'][i]
                assert order[12]==price
            else:
                assert data['ask'][i]<=order[12]-1 if side>0 else data['bid'][i]>=order[12]+1
                assert order[12]*2==round(order[12]*2)
            cash-=side*qty*order[12]*1000+fee
            if order[9]==1:
                assert oid not in open_lots
                open_lots[oid]=(side,qty,order[12],fee)
            else:
                selected=trades[trades[:,6]==oid]
                assert selected[:,4].sum()==qty and abs(selected[:,17].sum()-fee)<1e-6
                assert abs(selected[:,15].sum()-order[14])<1e-6
                for trade in selected:
                    entry=int(trade[5]);s,q,p,entry_fee=open_lots.pop(entry)
                    gross=s*q*(order[12]-p)*1000
                    assert trade[3]==s and trade[4]==q and trade[13]==p and trade[14]==order[12]
                    assert trade[15]==gross and trade[16]==entry_fee
                    assert abs(trade[18]-(gross-entry_fee-trade[17]))<1e-6
                    assert trade[22]==(trade[10]-trade[9])/60.
            cursor+=1
        mark=common=cash;long_qty=short_qty=0;lp=sp=losing=0.
        for side,qty,price,fee in open_lots.values():
            liq=data['mid'][i] if mode==1 else data['bid'][i] if side>0 else data['ask'][i]
            mark+=side*qty*liq*1000;common+=side*qty*data['mid'][i]*1000
            pnl=side*qty*(liq-price)*1000;losing+=min(pnl,0)
            if side>0: long_qty+=qty;lp+=pnl
            else: short_qty+=qty;sp+=pnl
        assert max(long_qty,short_qty)<=10
        np.testing.assert_allclose([equity[i],mid_equity[i]],[mark,common],atol=1e-6)
        np.testing.assert_allclose(risks[i],[long_qty,short_qty,lp,sp,losing],atol=1e-6)
    assert cursor==len(orders) and len(open_lots)==int((pos[:,1]>0).sum())
    assert book[1]==orders[:,13].sum()
    assert abs(book[2]-trades[trades[:,15]>0,15].sum())<1e-6
    assert abs(book[3]+trades[trades[:,15]<0,15].sum())<1e-6


def main() -> None:
    """機能: 全5系統の価格鏡像・期限・次行・受動指値・未来不変を照合する。

    引数: なし。返り値: なし(None)。人工機構検査をJSONに保存する。
    """
    paths={
        '反復':[100,100,97,97,100,100,103,103,100,100,97,97,100,100],
        '下落':[100,100,98,96,94,92,90,88,80,70,70,70],
        '方向変化':[100,100,97,97,96.5,96.5,96.5,97,97,98,98,98],
        '順行追加':[100,100,103,103,105,106,107,108,109,108,108,108],
        '期限':[100,100,97,97,97,97,97,97,97,97,97,97,97,97,97,97],
    }
    checked=[];future=0;reasons=set()
    for label,prices in paths.items():
        for mirror in (1,-1):
            for family in range(5):
                events=[[0,0,0,1],[4,-5*mirror,-3*mirror,1],[7,0,0,1]]
                if label=='順行追加':events=[[0,5*mirror,3*mirror,1]]
                data=fixture((100+mirror*(np.array(prices)-100)).tolist(),events)
                for mode in range(3):
                    result=run(data,family,mode)
                    independent_account(data,result,mode,family)
                    reasons.update(result[0][:,15].astype(int).tolist())
                    for cut in (1,3,len(prices)//2,len(prices)-1):
                        part={key:(val.copy() if key in ('events','limits') else val[:cut].copy()) for key,val in data.items()}
                        part['events']=data['events'][data['events'][:,0]<cut]
                        clipped=run(part,family,mode,False)
                        expected=result[0][result[0][:,2]<cut]
                        np.testing.assert_array_equal(clipped[0],expected)
                        np.testing.assert_array_equal(clipped[1],result[1][result[1][:,8]<cut])
                        for key in (2,3,4):np.testing.assert_array_equal(clipped[key],result[key][:cut])
                        changed={key:val.copy() for key,val in data.items()}
                        for key in ('mid','bid','ask'):changed[key][cut:]+=20.
                        modified=run(changed,family,mode,False)
                        np.testing.assert_array_equal(modified[0][modified[0][:,2]<cut],expected)
                        future+=2
                    checked.append(dict(経路=label,鏡像=mirror,系統=family,価格=mode,注文=len(result[0]),返済=len(result[1])))
    # ----------------------------------------
    # 期限・場末の遅延を実時刻で扱い、同時計次行は認め、次場の価格は拒否する。
    data=fixture([100,100,97,97,97,97],times=[0,1,2,3,1940,2240])
    result=run(data,0,0);assert result[1][-1,10]==2240
    bad=fixture([100,100,97,97,97,97],times=[0,1,2,3,1940,2300])
    try:run(bad,0,0)
    except ValueError:pass
    else:raise AssertionError('場内終端で返済できてしまいました')
    cutoff=fixture([100,100,97,97],times=[0,1,1699,1700])
    result=run(cutoff,0,0);assert not len(result[0]) and len(result[9])==1
    cross=fixture([100,100,97,97]);cross['sessions'][-1]=1
    try:run(cross,0,0)
    except AssertionError:pass
    else:raise AssertionError('複数場を受け入れました')
    equal=fixture([100,100,97,97,97,97],times=[0,1,2,2,1940,1940])
    result=run(equal,0,0);assert len(result[0])==2 and result[0][0,3]==result[0][0,4]
    # ----------------------------------------
    # カバーが後から建っても元玉の期限とともに組全体が返済される。
    covered=fixture([100,100,97,97,96.5,96.5,96.5,96.5,96.5,96.5],
                    events=[[0,0,0,1],[4,-5,-3,1]],times=[0,1,2,3,100,101,251,252,1940,1941])
    result=run(covered,4,0,minutes=5)
    assert (result[0][:,15]==5).any() and (result[0][:,15]==12).any()
    assert np.all(result[1][:,10] <= 1941)
    independent_account(covered,result,0,4)
    original_deadline=dict(covered)
    original_deadline['times']=np.array([0,1,2,3,249,250,303,304,1940,1941],float)
    result=run(original_deadline,4,0,minutes=5)
    exits=result[0][result[0][:,15]==12]
    assert len(exits)==2 and np.all(exits[:,3]==303.) and np.all(exits[:,4]==304.)
    independent_account(original_deadline,result,0,4)
    evidence=dict(合格=True,人工経路=len(checked),未来切断改変=future,注文理由の検査範囲=sorted(reasons),
                  追加境界検査=7,新実データ損益計算=False,ケース=checked,
                  コードSHA256=hashlib.sha256((SOURCE/'engine.py').read_bytes()).hexdigest())
    (HERE/'在庫の独立合成監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:val for key,val in evidence.items() if key!='ケース'},ensure_ascii=False))


if __name__=='__main__':main()
