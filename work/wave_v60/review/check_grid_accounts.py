"""グリッドの全週台帳から現金・片側在庫・含み込み場別収支を独立再構成する。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
GRID=HERE.parent/'grid'
sys.path.insert(0,str(GRID))
import features


def near(a: object,b: object) -> None:
    """機能: 集計値をNone又は浮動誤差だけ許容して照合する。

    引数: a/b(object)。返り値: なし(None)。
    """
    if b is None:assert a is None
    else:assert np.isclose(a,b,atol=1e-4,rtol=1e-10),(a,b)


def dd(curve: np.ndarray) -> float:
    """機能: 初値を含む評価曲線の最大下落幅を計算する。

    引数: curve(ndarray)。返り値: 最大下落幅(float)。
    """
    return float(np.max(np.maximum.accumulate(curve)-curve,initial=0))


def audit_week(stream: dict,accounts: list,method: dict) -> dict:
    """機能: 全原本行の現金と玉別価格評価を台帳だけから再計算し、場別会計を照合する。

    引数: stream/method(dict)、accounts(list)。返り値: 独立週集計(dict)。
    """
    o=np.asarray([row for a in accounts for row in a['orders']],float).reshape(-1,20)
    t=np.asarray([row for a in accounts for row in a['trades']],float).reshape(-1,23)
    if len(o):o=o[np.argsort(o[:,0])]
    if len(t):t=t[np.argsort(t[:,0])]
    mode=method['price_mode'];cfg=method['config'];family=cfg['family']
    symbol=stream['symbol'];cap,value,rate=(10,1000.,418) if symbol=='TOPIX' else (20,10.,110)
    n=len(stream['mid']);times=stream['time_s'];seq=stream['seq'];sessions=stream['session_index']
    cash_delta=np.zeros(n);lq_delta=np.zeros(n);sq_delta=np.zeros(n);lc_delta=np.zeros(n);sc_delta=np.zeros(n)
    long_price=stream['mid'] if mode=='mid' else stream['bid'];short_price=stream['mid'] if mode=='mid' else stream['ask']
    lost=np.zeros(n);totalfee=0.
    np.testing.assert_array_equal(o[:,0],np.arange(len(o)))
    for row in o:
        oid,d,i,side,qty=map(int,row[[0,1,2,10,11]])
        assert d<i and 0<=i<n
        np.testing.assert_array_equal(row[3:9],[times[d],times[i],sessions[d],sessions[i],seq[d],seq[i]])
        fee=(qty*rate)//10;assert row[13]==fee;totalfee+=fee
        passive=mode=='passive' and (row[15]==10 or (row[15]==0 and family!=4))
        if not passive:
            assert i==d+1
            price=stream['mid'][i] if mode=='mid' else stream['ask'][i] if side>0 else stream['bid'][i]
            assert row[12]==price
        else:
            assert np.isclose(row[12]/(stream['tick']/2),round(row[12]/(stream['tick']/2)))
            if side>0:assert stream['ask'][i]<=row[12]-stream['tick']
            else:assert stream['bid'][i]>=row[12]+stream['tick']
        cash_delta[i]-=side*qty*row[12]*value+fee
        if row[9]==1:
            assert row[14]==0
            if row[18]==0:
                assert sessions[d]==sessions[i] and times[i]<stream['limits'][int(sessions[i])]-300
            (lq_delta if side>0 else sq_delta)[i]+=qty
            (lc_delta if side>0 else sc_delta)[i]+=qty*row[12]*value
        else:
            legs=t[t[:,6]==oid]
            assert legs[:,4].sum()==qty and abs(legs[:,17].sum()-fee)<1e-5
            near(row[14],legs[:,15].sum())
            entryside=-side
            (lq_delta if entryside>0 else sq_delta)[i]-=qty
            (lc_delta if entryside>0 else sc_delta)[i]-=(legs[:,4]*legs[:,13]*value).sum()
            if cfg['carry']==0:assert np.all(legs[:,11]==legs[:,12])
    for j,leg in enumerate(t):
        e,x=map(int,leg[[7,8]]);op=o[int(leg[5])];cl=o[int(leg[6])];side=int(leg[3]);qty=int(leg[4])
        assert leg[0]==j and op[9]==1 and cl[9]==2 and op[10]==side and cl[10]==-side
        np.testing.assert_array_equal(leg[7:13],[op[2],cl[2],op[4],cl[4],op[6],cl[6]])
        assert leg[13]==op[12] and leg[14]==cl[12] and leg[16]==op[13] and leg[4]==op[11]
        near(leg[15],side*qty*(leg[14]-leg[13])*value);near(leg[18],leg[15]-leg[16]-leg[17])
        near(leg[22],(times[x]-times[e])/60)
        if mode=='passive' and leg[19]==10:
            near(leg[14],leg[13]+side*leg[21]*(2 if family==4 else 1))
        price=long_price if side>0 else short_price
        lost[e:x]+=np.minimum(side*qty*(price[e:x]-leg[13])*value,0.)
    cash=np.cumsum(cash_delta);lq=np.cumsum(lq_delta);sq=np.cumsum(sq_delta)
    lc=np.cumsum(lc_delta);sc=np.cumsum(sc_delta)
    assert lq.min(initial=0)>=0 and sq.min(initial=0)>=0 and max(lq.max(initial=0),sq.max(initial=0))<=cap
    assert lq[-1]==0 and sq[-1]==0
    lp=lq*long_price*value-lc;sp=sc-sq*short_price*value
    curve=cash+lq*long_price*value-sq*short_price*value
    midcurve=cash+(lq-sq)*stream['mid']*value
    near(curve[-1],t[:,18].sum());near(totalfee,t[:,16:18].sum())
    independent=[];offsets=np.r_[stream['offsets'],n]
    for sid,a in enumerate(sorted(accounts,key=lambda x:x['session'])):
        first,end=map(int,offsets[sid:sid+2]);prev=curve[first-1] if first else 0.;prevmid=midcurve[first-1] if first else 0.
        before=(lp[first-1]+sp[first-1]) if first else 0.;after=lp[end-1]+sp[end-1]
        orders=o[o[:,6]==sid];legs=t[t[:,12]==sid];gross=legs[:,15];netleg=legs[:,18]
        actual=dict(gross_profit=gross[gross>0].sum(),gross_loss=-gross[gross<0].sum(),gross_pnl=gross.sum(),
                    fees=orders[:,13].sum(),unrealized_start=before,unrealized_end=after,mtm_change=after-before,
                    net=gross.sum()-orders[:,13].sum()+after-before,mid_net=midcurve[end-1]-prevmid,
                    closed_net_profit=netleg[netleg>0].sum(),closed_net_loss=-netleg[netleg<0].sum(),closed_net=netleg.sum(),
                    cycles=len(legs),wins=(netleg>0).sum(),losses=(netleg<0).sum(),
                    win_qty=legs[netleg>0,4].sum(),loss_qty=legs[netleg<0,4].sum(),flat_qty=legs[netleg==0,4].sum(),
                    order_count=len(orders),drawdown=dd(np.r_[prev,curve[first:end]]),mid_drawdown=dd(np.r_[prevmid,midcurve[first:end]]),
                    max_long_qty=lq[first:end].max(),max_short_qty=sq[first:end].max(),
                    max_gross_qty=(lq[first:end]+sq[first:end]).max(),max_abs_net_qty=abs(lq[first:end]-sq[first:end]).max(),
                    end_long_qty=lq[end-1],end_short_qty=sq[end-1],
                    max_long_unrealized_loss=-lp[first:end].min(initial=0),max_short_unrealized_loss=-sp[first:end].min(initial=0),
                    max_losing_inventory=-lost[first:end].min(initial=0))
        for k,v in actual.items():near(a[k],v)
        near(actual['net'],curve[end-1]-prev)
        independent.append(actual)
    return dict(accounts=independent,net=curve[-1],mid_net=midcurve[-1],drawdown=dd(np.r_[0.,curve]),
                mid_drawdown=dd(np.r_[0.,midcurve]),minimum=curve.min(initial=0),maximum=curve.max(initial=0),
                mid_minimum=midcurve.min(initial=0),mid_maximum=midcurve.max(initial=0),orders=len(o),trades=len(t))


def audit_summary(given: dict,records: list) -> None:
    """機能: 独立時価会計から週・全期間の金額、枚数と連結下落幅を照合する。

    引数: given(dict)、records(list[dict])。返り値: なし(None)。
    """
    accounts=[a for r in records for a in r['accounts']]
    sums=('gross_profit','gross_loss','gross_pnl','fees','net','mtm_change','closed_net_profit','closed_net_loss',
          'closed_net','cycles','wins','losses','win_qty','loss_qty','flat_qty','order_count')
    totals={k:sum(a[k] for a in accounts) for k in sums}
    for k,v in totals.items():near(given[k],v)
    near(given['pf'],totals['closed_net_profit']/totals['closed_net_loss'] if totals['closed_net_loss'] else None)
    wm=totals['closed_net_profit']/totals['win_qty'] if totals['win_qty'] else None
    lm=totals['closed_net_loss']/totals['loss_qty'] if totals['loss_qty'] else None
    near(given['payoff'],wm/lm if wm is not None and lm else None)
    for k in ('max_long_qty','max_short_qty','max_gross_qty','max_abs_net_qty','max_long_unrealized_loss','max_short_unrealized_loss','max_losing_inventory'):
        near(given[k],max(a[k] for a in accounts))
    for prefix in ('','mid_'):
        balance=peak=drawdown=0.
        for r in records:
            drawdown=max(drawdown,r[prefix+'drawdown'],peak-balance-r[prefix+'minimum'])
            peak=max(peak,balance+r[prefix+'maximum']);balance+=r[prefix+'net']
        near(given[prefix+'drawdown'],drawdown)


def main() -> None:
    """機能: 40条件×三モデルの全720週・6000場を別会計で検証し証跡を保存する。

    引数: なし。返り値: なし(None)。売買条件は変更しない。
    """
    result=json.loads((GRID/'売買結果.json').read_text(encoding='utf-8'));streams=features.load_streams()
    orders=trades=weeks=accounts=summaries=0
    for mi,method in enumerate(result['methods']):
        records={}
        for key,stream in sorted(streams.items()):
            selected=[a for a in method['accounts'] if (a['symbol'],a['week'])==key]
            r=audit_week(stream,selected,method);records[key]=r
            orders+=r['orders'];trades+=r['trades'];weeks+=1;accounts+=len(selected)
            audit_summary(method['weeks'][key[0]][key[1]],[r]);summaries+=1
        for symbol in ('TOPIX','NK225'):
            audit_summary(method['summary'][symbol],[r for k,r in sorted(records.items()) if k[0]==symbol]);summaries+=1
        if (mi+1)%12==0:print(json.dumps({'条件モデル':mi+1,'週口座':weeks},ensure_ascii=False),flush=True)
    evidence=dict(合格=True,条件モデル=len(result['methods']),週口座=weeks,場口座=accounts,注文=orders,返済玉=trades,週全期間集計=summaries,
                  全原本行の現金と両側在庫再計算=True,前場含み持越しと場間gap反映=True,手数料二重控除なし=True,
                  結果SHA256=hashlib.sha256((GRID/'売買結果.json').read_bytes()).hexdigest())
    (HERE/'グリッド全口座の独立監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
