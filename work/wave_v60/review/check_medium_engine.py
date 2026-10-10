"""中期の費用・呼値丸め・返済期限と実約定価格を人工経路で検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
MEDIUM=HERE.parent/'medium'
sys.path.insert(0,str(MEDIUM))
import engine


def fixture(values: list,times: list | None=None,side: int=1) -> tuple:
    """機能: 最後値を持たず同じ気配幅の人工原本を作る。

    引数: values/times(list)、side(int)。返り値: 価格入力・気配・候補(tuple)。
    """
    mid=np.asarray(values,float)
    if side<0:
        mid=200.-mid
    t=np.asarray(times if times is not None else np.arange(len(mid)),float)
    seq=np.arange(len(mid),dtype=int)*3+9
    ready=dict(seq=seq,time_s=t,start=0.,limit=2000.,symbol='TOPIX',session='人工',tick=1.)
    quotes=dict(seq=seq.copy(),time_s=t.copy(),mid=mid,bid=mid-.5,ask=mid+.5)
    return ready,quotes,np.array([[0.,side,3.]])


def check_account(account: dict,ready: dict,quotes: dict,quote_mode: bool) -> None:
    """機能: 注文時課金・返済組・MFE/MAEを独立の現金計算で照合する。

    引数: account/ready/quotes(dict)、quote_mode(bool)。返り値: なし(None)。
    """
    cash=0.;position=0;totalfee=0
    orders=account['orders'];trades=account['trades']
    for row in orders:
        d,f=np.searchsorted(ready['seq'],[row[2],row[3]])
        assert f==d+1 and row[0]==ready['time_s'][d] and row[1]==ready['time_s'][f]
        expected=quotes['mid'][f] if not quote_mode else (quotes['ask'][f] if row[5]>0 else quotes['bid'][f])
        assert row[7]==expected and row[6]==5 and row[9]==209
        cash-=row[5]*row[6]*row[7]*1000+row[9];position+=row[5]*row[6];totalfee+=row[9]
        assert abs(position)<=5
        assert row[13]==position
        if row[4]==1:
            assert row[8]==0 and row[10]==-209
    assert position==0 and cash==account['net'] and totalfee==account['fees']
    for trade in trades:
        begin,end=int(trade[19]),int(trade[20]);side=trade[2]
        price=quotes['mid'] if not quote_mode else quotes['bid'] if side>0 else quotes['ask']
        path=side*(price[begin:end+1]-trade[4])
        gross=side*trade[3]*(trade[5]-trade[4])*1000
        assert trade[6]==gross and trade[7]==418 and trade[8]==gross-418
        assert trade[15]==max(0.,path.max())/trade[10] and trade[16]==max(0.,-path.min())/trade[10]
    assert account['wins']==int((trades[:,8]>0).sum()) and account['losses']==int((trades[:,8]<0).sum())


def main() -> None:
    """機能: 二価格・売買鏡像・丸め・時間・未来切断を検査して保存する。

    引数: なし。返り値: なし(None)。実データ損益は参照しない。
    """
    cases=[('切上げ利確',[100,100,104.5,105,106,107],None,1,60,2),
           ('早期損切り',[100,100,96,95],None,1,60,1),
           ('順行後追跡',[100,100,103,104,105,102,101],None,2,60,3),
           ('30分期限',[100,100,100,100],[0,1,1801,1802],2,30,4),
           ('場内期限',[100,100,100,100],[0,1,1940,1941],2,60,5),
           ('同時計原本順',[100,100,96,95],[0,0,0,0],1,60,1)]
    checks=[];prefix=0
    for name,values,times,mode,minutes,reason in cases:
        for side in (1,-1):
            for quote_mode in (True,False):
                r,q,s=fixture(values,times,side)
                a=engine.execute(r,q,s,mode,minutes,quote_mode)
                assert len(a['trades'])==1 and a['trades'][0,9]==reason
                if name=='切上げ利確':
                    assert a['trades'][0,20]==(5 if quote_mode else 4),'1.5W呼値切上げが不一致'
                check_account(a,r,q,quote_mode)
                for n in range(1,len(values)):
                    partial={k:(v[:n] if isinstance(v,np.ndarray) else v) for k,v in r.items()}
                    pq={k:v[:n] for k,v in q.items()}
                    got=engine.execute(partial,pq,s[s[:,0]<n],mode,minutes,quote_mode,False)
                    expected=a['orders'][a['orders'][:,3]<=r['seq'][n-1]]
                    np.testing.assert_array_equal(got['orders'],expected)
                    changed={k:v.copy() for k,v in q.items()}
                    for k in ('mid','bid','ask'):
                        changed[k][n:]+=11.
                    future=engine.execute(r,changed,s,mode,minutes,quote_mode,False)
                    np.testing.assert_array_equal(future['orders'][future['orders'][:,3]<=r['seq'][n-1]],expected)
                    prefix+=1
                checks.append(dict(検査=name,売買=side,気配主=quote_mode,合格=True))
    # ----------------------------------------
    # 発注判断後に新規締切へ到達した注文は取り消し、期限超過の返済を隠さない。
    r,q,s=fixture([100,100,100],[0,1700,2001])
    a=engine.execute(r,q,s,1,60,True)
    assert len(a['orders'])==0 and a['candidate_audit']['cancelled_at_fill']==1
    r,q,s=fixture([100,100,99,98],[0,1,1940,2001])
    delayed=engine.execute(r,q,s,2,60,True)
    assert delayed['trades'][0,1]==2001 and delayed['trades'][0,9]==5
    check_account(delayed,r,q,True)
    r,q,s=fixture([100,100,99,98],[0,1,1940,2300])
    try:
        engine.execute(r,q,s,2,60,True)
    except ValueError as error:
        assert '終端' in str(error)
    else:
        raise AssertionError('期限後の返済を許可しました')
    evidence=dict(合格=True,経路検査=checks,未来切断改変比較=prefix,新規締切取消=True,返済期限超過拒否=True,
                  運用期限後かつ同一ザラバ内の次行返済=True,ザラバ終端一致拒否=True,
                  売買結果参照=False,コードSHA256=hashlib.sha256((MEDIUM/'engine.py').read_bytes()).hexdigest())
    (HERE/'中期売買器の独立合成監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'合格':True,'経路数':len(checks),'未来比較':prefix},ensure_ascii=False))


if __name__=='__main__':
    main()
