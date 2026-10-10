"""全方向性条件の保存台帳を、元気配・注文現金・全行資産から独立照合する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'directional'
OLD=HERE.parent.parent/'wave_v60'


def equal(actual: float, expected: float, label: str) -> None:
    """機能: 金額又は指標を丸め前で照合する。

    引数: actual/expected(float)、label(str)。返り値: なし(None)。
    """
    if not np.isclose(actual,expected,rtol=1e-10,atol=1e-5):
        raise AssertionError((label,actual,expected))


def audit(account: dict, ledger: dict, ready: dict, quotes: dict, config: dict) -> dict:
    """機能: 一口座の次行気配、費用、ロット会計と全原本行の資産を別計算する。

    引数: account/ledger/ready/quotes/config(dict)。返り値: 検査件数と独立集計(dict)。
    """
    orders,trades=ledger['orders'],ledger['trades']
    seq,times=ready['seq'],ready['time_s'];n=len(seq)
    value,cap,fee=(1000.,10,418) if account['symbol']=='TOPIX' else (10.,20,110)
    quote=account['price_mode']=='quote'
    cash=np.zeros(n);quantity=np.zeros(n)
    if len(orders):
        decision=np.searchsorted(seq,orders[:,2]);fill=np.searchsorted(seq,orders[:,3])
        np.testing.assert_array_equal(fill,decision+1)
        np.testing.assert_array_equal(seq[decision],orders[:,2]);np.testing.assert_array_equal(seq[fill],orders[:,3])
        np.testing.assert_array_equal(times[decision],orders[:,0]);np.testing.assert_array_equal(times[fill],orders[:,1])
        prices=np.where(orders[:,5]>0,quotes['ask'][fill],quotes['bid'][fill]) if quote else quotes['mid'][fill]
        np.testing.assert_array_equal(orders[:,7],prices)
        fees=orders[:,6].astype(np.int64)*fee//10
        np.testing.assert_array_equal(orders[:,9],fees)
        assert np.all(orders[:,1]<ready['limit']+300)
        entry=orders[:,4]!=2
        assert np.all(orders[entry,1]<ready['limit']-300)
        np.add.at(cash,fill,-orders[:,5]*orders[:,6]*orders[:,7]*value-fees)
        np.add.at(quantity,fill,orders[:,5]*orders[:,6])
        np.testing.assert_array_equal(np.cumsum(orders[:,5]*orders[:,6]),orders[:,13])
    quantity=np.cumsum(quantity)
    marks=np.where(quantity>=0,quotes['bid'],quotes['ask']) if quote else quotes['mid']
    curve=np.cumsum(cash)+quantity*marks*value
    assert quantity[-1]==0 and np.max(np.abs(quantity),initial=0)<=cap
    equal(account['net'],curve[-1],'現金純益')
    peak=np.maximum.accumulate(np.r_[0.,curve])[1:]
    equal(account['drawdown'],np.max(peak-curve,initial=0),'全行DD')
    equal(account['equity_min'],np.min(curve,initial=0),'資産最小')
    equal(account['equity_max'],np.max(curve,initial=0),'資産最大')
    equal(account['max_long_qty'],np.max(quantity,initial=0),'買上限')
    equal(account['max_short_qty'],np.max(-quantity,initial=0),'売上限')
    gross=trades[:,2]*trades[:,3]*(trades[:,5]-trades[:,4])*value
    np.testing.assert_allclose(trades[:,6],gross,rtol=0,atol=1e-6)
    np.testing.assert_allclose(trades[:,7],trades[:,24]+trades[:,25],rtol=0,atol=1e-6)
    np.testing.assert_allclose(trades[:,8],gross-trades[:,7],rtol=0,atol=1e-6)
    np.testing.assert_allclose(trades[:,17],(trades[:,1]-trades[:,0])/60.,rtol=0,atol=1e-10)
    equal(trades[:,7].sum(),orders[:,9].sum(),'全費用')
    equal(account['fees'],orders[:,9].sum(),'表示費用')
    equal(account['gross_pnl'],gross.sum(),'粗収支')
    equal(account['net'],trades[:,8].sum(),'玉合計')
    net=trades[:,8];positive=net>0;negative=net<0
    for key,number in [('profit',net[positive].sum()),('loss',-net[negative].sum()),
                      ('win_qty',trades[positive,3].sum()),('loss_qty',trades[negative,3].sum()),
                      ('flat_qty',trades[net==0,3].sum()),('lot_trades',len(trades)),
                      ('additions',np.count_nonzero(orders[:,4]==3)),
                      ('added_lot_net',net[trades[:,23]==3].sum()),('initial_lot_net',net[trades[:,23]==1].sum())]:
        equal(account[key],number,key)
    groups=[]
    for gid in np.unique(trades[:,21]):
        legs=trades[trades[:,21]==gid];group_orders=orders[orders[:,12]==gid]
        opened=group_orders[group_orders[:,4]!=2];closed=group_orders[group_orders[:,4]==2]
        assert len(closed)==1 and len(opened)==len(legs)<=4
        np.testing.assert_array_equal(legs[:,0],opened[:,1])
        np.testing.assert_array_equal(legs[:,4],opened[:,7])
        np.testing.assert_array_equal(legs[:,3],opened[:,6])
        np.testing.assert_array_equal(legs[:,24],opened[:,9])
        np.testing.assert_array_equal(legs[:,12],opened[:,3])
        np.testing.assert_array_equal(legs[:,18],opened[:,2])
        equal(legs[:,25].sum(),closed[0,9],'返済費用配賦')
        equal(legs[:,3].sum(),closed[0,6],'全玉返済')
        assert np.all(legs[:,22]==opened[0,1])
        if closed[0,11]==3:assert closed[0,0]>=opened[0,1]+config['minutes']*60
        groups.append(legs[:,8].sum())
    equal(account['cycles'],len(groups),'組数')
    equal(account['group_wins'],np.count_nonzero(np.array(groups)>0),'勝組数')
    equal(account['group_losses'],np.count_nonzero(np.array(groups)<0),'負組数')
    return dict(orders=len(orders),trades=len(trades),cycles=len(groups),raw_rows=n)


def main() -> None:
    """機能: 270条件・全27,000口座と銘柄別集計を検査する。

    引数: なし。返り値: なし(None)。結果を表示せず監査合否だけ保存する。
    """
    target=SOURCE/'集計結果.json'
    result=json.loads(target.read_text(encoding='utf-8'))
    inputs=pickle.loads((OLD/'inputs.pkl').read_bytes());quotes=pickle.loads((OLD/'quotes.pkl').read_bytes())
    total=dict(accounts=0,orders=0,trades=0,cycles=0,raw_rows=0,summaries=0)
    for number,method in enumerate(result['methods'],1):
        path=SOURCE/method['ledger'];payload=path.read_bytes()
        assert hashlib.sha256(payload).hexdigest()==method['ledger_sha256']
        ledgers=pickle.loads(payload)
        for account in method['accounts']:
            key=(account['session'],account['symbol'])
            checked=audit(account,ledgers[tuple(account['ledger_key'])],inputs[key],quotes[key],method['config'])
            total['accounts']+=1
            for field,amount in checked.items():total[field]+=amount
        for symbol in ('TOPIX','NK225'):
            for mode,skey,wkey in [('quote','summary','weeks'),('mid','mid_summary','mid_weeks')]:
                accounts=[a for a in method['accounts'] if a['symbol']==symbol and a['price_mode']==mode]
                groups=[(method[skey][symbol],accounts)]
                groups.extend((data,[a for a in accounts if a['week']==week]) for week,data in method[wkey][symbol].items())
                for summary,chosen in groups:
                    for field in ('net','fees','profit','loss','gross_pnl','win_qty','loss_qty','cycles','added_lot_net'):
                        equal(summary[field],sum(a[field] for a in chosen),'集計_'+field)
                    equal(summary['without_best'],sum(a['net'] for a in chosen)-max(0.,max(a['net'] for a in chosen)),'大勝場除外')
                    total['summaries']+=1
        if number%30==0:print(json.dumps({'監査済条件':number,'全条件':270},ensure_ascii=False),flush=True)
    record=dict(合格=True,件数=total,全行資産独立照合=True,原本次行気配一致=True,
                数量費用配賦照合=True,追加玉と初回玉分離=True,保存台帳のみ使用=True,
                結果SHA256=hashlib.sha256(target.read_bytes()).hexdigest())
    (HERE/'方向性全台帳の独立監査.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
