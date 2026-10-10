"""現在グリッドの全週注文から、持越しと未決済玉を独立評価する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
LIVE=WORK/'live'


def main() -> None:
    """機能: 週の注文現金・両側数量・原価を全行へ再構成し、現在場の含み増減を照合する。

    引数: なし。返り値: なし(None)。再取得・手法再生・仮想清算は行わない。
    """
    result=json.loads((LIVE/'現在グリッドの途中損益.json').read_text(encoding='utf-8'))
    frozen=json.loads((LIVE/'現在グリッド接続実装固定.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((LIVE/'grid_replay.py').read_bytes()).hexdigest()==frozen['wrapper_sha256']
    assert hashlib.sha256((LIVE/'確認候補固定.json').read_bytes()).hexdigest()==frozen['selection_sha256']
    for name,digest in frozen['inputs_sha256'].items():assert hashlib.sha256((LIVE/name).read_bytes()).hexdigest()==digest
    inputs=pickle.loads((WORK/'inputs.pkl').read_bytes());quotes=pickle.loads((WORK/'quotes.pkl').read_bytes())
    inputs.update(pickle.loads((LIVE/'inputs.pkl').read_bytes()));quotes.update(pickle.loads((LIVE/'quotes.pkl').read_bytes()))
    records=[]
    for a in result['accounts']:
        keys=[(s,a['symbol']) for s in a['sessions']]
        t=np.concatenate([inputs[k]['time_s'] for k in keys]);seq=np.concatenate([inputs[k]['seq'] for k in keys])
        sid=np.concatenate([np.full(len(inputs[k]['seq']),i,int) for i,k in enumerate(keys)])
        q={name:np.concatenate([quotes[k][name] for k in keys]) for name in ('mid','bid','ask')}
        n=len(t);first=n-len(inputs[keys[-1]]['seq']);value,rate,cap=(1000,418,10) if a['symbol']=='TOPIX' else (10,110,20)
        orders=np.asarray(a['week_orders'],float).reshape(-1,20);trades=np.asarray(a['week_trades'],float).reshape(-1,23)
        cash=np.zeros(n);long=np.zeros(n);short=np.zeros(n);longcost=np.zeros(n);shortcost=np.zeros(n)
        for row in orders:
            oid,d,i,side,qty=map(int,row[[0,1,2,10,11]])
            assert i==d+1 and row[13]==qty*rate//10
            np.testing.assert_array_equal(row[3:9],[t[d],t[i],sid[d],sid[i],seq[d],seq[i]])
            price=q['mid'][i] if a['price_mode']=='mid' else q['ask'][i] if side>0 else q['bid'][i]
            assert row[12]==price
            cash[i]-=side*qty*price*value+row[13]
            if row[9]==1:
                (long if side>0 else short)[i]+=qty
                (longcost if side>0 else shortcost)[i]+=qty*price*value
            else:
                legs=trades[trades[:,6]==oid];assert legs[:,4].sum()==qty
                np.testing.assert_allclose(legs[:,17].sum(),row[13],atol=1e-5)
                np.testing.assert_allclose(legs[:,15].sum(),row[14],atol=1e-5)
                (long if side<0 else short)[i]-=qty
                (longcost if side<0 else shortcost)[i]-=(legs[:,4]*legs[:,13]*value).sum()
        for leg in trades:
            op=orders[int(leg[5])];cl=orders[int(leg[6])]
            assert leg[4]==op[11] and leg[13]==op[12] and leg[14]==cl[12] and leg[16]==op[13]
            np.testing.assert_allclose(leg[15],leg[3]*leg[4]*(leg[14]-leg[13])*value,atol=1e-5)
            np.testing.assert_allclose(leg[18],leg[15]-leg[16]-leg[17],atol=1e-5)
        cash=np.cumsum(cash);long=np.cumsum(long);short=np.cumsum(short)
        longcost=np.cumsum(longcost);shortcost=np.cumsum(shortcost)
        assert long.min(initial=0)>=0 and short.min(initial=0)>=0 and max(long.max(initial=0),short.max(initial=0))<=cap
        buy=q['mid'] if a['price_mode']=='mid' else q['bid'];sell=q['mid'] if a['price_mode']=='mid' else q['ask']
        floating=long*buy*value-longcost+shortcost-short*sell*value
        equity=cash+long*buy*value-short*sell*value
        gross=trades[trades[:,12]==len(keys)-1,15].sum();fees=orders[orders[:,6]==len(keys)-1,13].sum()
        expected=dict(unrealized_start=floating[first-1],unrealized_end=floating[-1],
                      realized_gross_pnl=gross,fees_incurred=fees,mtm_change=floating[-1]-floating[first-1],
                      net=equity[-1]-equity[first-1],economic_net=equity[-1]-equity[first-1],
                      week_realized_gross_pnl=trades[:,15].sum(),week_fees_incurred=orders[:,13].sum(),
                      week_economic_net=equity[-1],week_before_current_net=equity[first-1],long_qty=long[-1],short_qty=short[-1],
                      drawdown=(np.maximum.accumulate(np.r_[equity[first-1],equity[first:]])-np.r_[equity[first-1],equity[first:]]).max(),
                      week_drawdown=(np.maximum.accumulate(np.r_[0.,equity])-np.r_[0.,equity]).max())
        for key,value in expected.items():np.testing.assert_allclose(a[key],value,atol=1e-4)
        np.testing.assert_allclose(gross-fees+floating[-1]-floating[first-1],a['net'],atol=1e-4)
        np.testing.assert_allclose(sum(p['含み粗損益'] for p in a['open_positions']),floating[-1],atol=1e-4)
        assert not a['調査端仮想清算']
        records.append(dict(銘柄=a['symbol'],約定=a['price_mode'],当場収支=float(a['net']),
                            開始含み=float(a['unrealized_start']),終了含み=float(a['unrealized_end']),
                            買枚数=int(long[-1]),売枚数=int(short[-1]),週時価収支=float(equity[-1]),全週注文=len(orders)))
    evidence=dict(合格=True,追加取得=0,実注文=0,再生ではなく保存注文から独立会計=True,口座=records,
                  結果SHA256=hashlib.sha256((LIVE/'現在グリッドの途中損益.json').read_bytes()).hexdigest())
    (HERE/'現在グリッドの独立監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
