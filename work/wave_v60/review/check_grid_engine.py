"""グリッドの建玉会計・注文順・期限と未来非依存を独立の人工経路で照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
GRID=HERE.parent/'grid'
sys.path.insert(0,str(GRID))
import engine


def fixture(prices: list, events: list | None=None, times: list | None=None, sessions: list | None=None, limits: list | None=None) -> dict:
    """機能: 呼値・気配・原本行・場番号を持つ人工入力を作る。

    引数: prices/events/times/sessions/limits(list又はNone)。返り値: 入力辞書(dict)。
    """
    mid=np.asarray(prices,float);n=len(mid)
    stamp=np.asarray(times if times is not None else list(range(n-2))+[1940,1941],float)
    sid=np.asarray(sessions if sessions is not None else np.zeros(n),np.int64)
    return dict(times=stamp,seqs=np.arange(n,dtype=np.int64)*3+7,mid=mid,bid=mid-.5,ask=mid+.5,
                sessions=sid,limits=np.asarray(limits if limits is not None else [2000.],float),
                events=np.asarray(events if events is not None else [[0,0,0,1]],float))


def run(data: dict,family: int,mode: int,carry: int=1,finish: bool=True) -> tuple:
    """機能: 固定人工契約でグリッド再生器だけを呼び出す。

    引数: data(dict)、family/mode/carry(int)、finish(bool)。返り値: エンジン生出力(tuple)。
    """
    return engine.replay(**data,final_reason=2,family=family,steps=5,carry=carry,mode=mode,
                         fraction=.001,cap=10,value=1000.,tick=1.,fee_tenths=418,finish=finish)


def independent_account(data: dict,result: tuple,mode: int,family: int=0) -> None:
    """機能: 玉単位の損益と現金・方向別評価を別式で全原本行へ再構成する。

    引数: data(dict)、result(tuple)、mode/family(int)。返り値: なし(None)。
    """
    orders,trades,equity,mid_equity,risks,_,pos,_,book=result[:9]
    cash=0.;open_lots={};cursor=0
    for i in range(len(data['mid'])):
        while cursor<len(orders) and orders[cursor,2]==i:
            order=orders[cursor];oid=int(order[0]);decision=int(order[1]);side=int(order[10]);qty=int(order[11])
            assert decision<i and order[3]==data['times'][decision] and order[4]==data['times'][i]
            assert order[5]==data['sessions'][decision] and order[6]==data['sessions'][i]
            assert order[7]==data['seqs'][decision] and order[8]==data['seqs'][i]
            fee=(qty*418)//10
            assert order[13]==fee
            passive=mode==2 and (order[15]==10 or (order[15]==0 and family!=4))
            if not passive:
                assert i==decision+1
                price=data['mid'][i] if mode==1 else data['ask'][i] if side>0 else data['bid'][i]
                assert order[12]==price
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
    """機能: 反発・単調下落・逆玉整理・両建て・順張りを三約定仮定で監査する。

    引数: なし。返り値: なし(None)。保存市場の損益は参照しない。
    """
    cases=[('反復',0,fixture([100,100,96.5,96.5,101.5,101.5,100,100])),
           ('単調下落',0,fixture([100,100,98,96,94,92,90,85,70,60,60,60])),
           ('損失保護',1,fixture([100,100,98,96,94,92,90,85,70,60,60,60])),
           ('逆玉整理',2,fixture([100,100,103,103,104,104,104,104],[[0,0,0,1],[4,5,3,1]])),
           ('両建て',3,fixture([100,100,97,97,96,96,96,97,97,98,98],[[0,0,0,1],[4,-5,-3,1],[7,0,0,1]])),
           ('順張り',4,fixture([100,100,103,103,107,105,105,105,105]))]
    counts=[];prefix=0
    for label,family,data in cases:
        for mode in range(3):
            result=run(data,family,mode);independent_account(data,result,mode,family)
            for cut in sorted(set([1,3,len(data['mid'])//2,len(data['mid'])-1])):
                partial={k:(v[:cut].copy() if k not in ('events','limits') else v.copy()) for k,v in data.items()}
                partial['events']=data['events'][data['events'][:,0]<cut]
                got=run(partial,family,mode,finish=False)
                expected=result[0][result[0][:,2]<cut]
                np.testing.assert_array_equal(got[0],expected)
                for col in (2,3,4): np.testing.assert_array_equal(got[col],result[col][:cut])
                mutated={k:v.copy() for k,v in data.items()}
                for name in ('mid','bid','ask'):mutated[name][cut:]+=12.
                future=run(mutated,family,mode,finish=False)
                np.testing.assert_array_equal(future[0][future[0][:,2]<cut],expected)
                prefix+=2
            counts.append(dict(経路=label,方式=mode,注文=len(result[0]),返済=len(result[1]),合格=True))
    # ----------------------------------------
    # 新規締切・場跨ぎは予約時と約定時を区別し、返済はザラバ終端で失敗させる。
    cutoff=fixture([100,100,97,97],times=[0,1,1699,1700])
    cancelled=run(cutoff,0,0)
    assert not len(cancelled[0]) and len(cancelled[9])==1
    crossing=fixture([100,100,97,97],times=[0,1,1600,3000],sessions=[0,0,0,1],limits=[2000,4000])
    cancelled=run(crossing,0,0)
    assert not len(cancelled[0]) and len(cancelled[9])==1
    delayed=fixture([100,100,97,97,97,97],times=[0,1,2,3,1940,2240])
    result=run(delayed,0,0);independent_account(delayed,result,0)
    assert result[1][-1,10]==2240
    invalid=fixture([100,100,97,97,97,97],times=[0,1,2,3,1940,2300])
    try:run(invalid,0,0)
    except ValueError:pass
    else:raise AssertionError('ザラバ終端一致の返済を許可しました')
    late_session=fixture([100,100,97,97,97,97],times=[0,1,2,3,1940,3000],sessions=[0,0,0,0,0,1],limits=[2000,4000])
    try:run(late_session,0,0,carry=0)
    except ValueError:pass
    else:raise AssertionError('場内版で次場へ全返済予約を持ち越しました')
    # ----------------------------------------
    # 待機指値は触値では約定せず、前行待機と一呼値通過が必要。判断更新より先に約定する。
    passive=fixture([100,100,97.5,96.5,101.5,101.5,100,100],events=[[0,0,0,1],[4,-5,-3,1]])
    result=run(passive,2,2);independent_account(passive,result,2,2)
    assert result[0][0,2]==3 and result[0][0,12]==98
    assert result[0][1,2]==4 and result[0][1,12]==100 and result[0][1,15]==10
    # ----------------------------------------
    # 逆行で補償玉を建てても買玉を消さず、gross両側を上限照合し清算価値と中値を分離する。
    hedged=run(cases[4][2],3,0)
    assert (hedged[0][:,15]==7).any()
    both=(hedged[4][:,0]>0)&(hedged[4][:,1]>0)
    assert both.any() and np.all(hedged[3][both]>=hedged[2][both])
    evidence=dict(合格=True,経路=counts,未来切断改変比較=prefix,保存市場損益参照=False,
                  境界検査=['新規締切取消','別場への新規予約取消','運用期限後ザラバ内返済','ザラバ終端拒否',
                            '触値未約定','指値通過約定と方向更新順','両建ての片側上限と評価価格分離','場内版の次場返済拒否'],
                  コードSHA256=hashlib.sha256((GRID/'engine.py').read_bytes()).hexdigest())
    (HERE/'グリッド独立合成監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'合格':True,'経路':len(counts),'未来比較':prefix},ensure_ascii=False))


if __name__=='__main__':main()
