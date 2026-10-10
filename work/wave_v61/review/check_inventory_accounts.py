"""全在庫条件の台帳を原本気配・注文現金・方向別数量から独立照合する。"""

import hashlib
import json
import pickle
from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'inventory'
OLD=HERE.parent.parent/'wave_v60'


def equal(actual: float, expected: float, label: str) -> None:
    """機能: 台帳の独立計算値と表示集計を照合する。

    引数: actual/expected(float)、label(str)。返り値: なし(None)。
    """
    if not np.isclose(actual,expected,rtol=1e-10,atol=1e-5):raise AssertionError((label,actual,expected))


def audit(account: dict, ledger: dict, ready: dict, quotes: dict, method: dict) -> dict:
    """機能: 全行の買玉と売玉を別に保ち、注文費用と返済損益を再構成する。

    引数: account/ledger/ready/quotes/method(dict)。返り値: 件数(dict)。
    """
    orders,trades=ledger['orders'],ledger['trades']
    seq,times=ready['seq'],ready['time_s'];n=len(seq)
    value,unit,fee=(1000.,1,418) if account['symbol']=='TOPIX' else (10.,2,110)
    config=method['config'];cap=config['top_cap']*unit;mode=method['price_mode']
    cash=np.zeros(n);long=np.zeros(n);short=np.zeros(n)
    if len(orders):
        d=orders[:,1].astype(int);i=orders[:,2].astype(int)
        assert np.all(i>d) and np.all(i<n)
        np.testing.assert_array_equal(orders[:,7],seq[d]);np.testing.assert_array_equal(orders[:,8],seq[i])
        np.testing.assert_array_equal(orders[:,3],times[d]);np.testing.assert_array_equal(orders[:,4],times[i])
        assert np.all(orders[:,5:7]==0)
        fee_values=orders[:,11].astype(np.int64)*fee//10
        np.testing.assert_array_equal(orders[:,13],fee_values)
        passive=np.zeros(len(orders),bool)
        if mode=='passive':
            passive=(np.isin(orders[:,15],[8,14])|((orders[:,15]==0)&(config['family']!=3)))
        assert np.all(i[~passive]==d[~passive]+1)
        prices=quotes['mid'][i] if mode=='mid' else np.where(orders[:,10]>0,quotes['ask'][i],quotes['bid'][i])
        np.testing.assert_array_equal(orders[~passive,12],prices[~passive])
        if passive.any():
            p=orders[passive];pi=i[passive]
            assert np.all(np.where(p[:,10]>0,quotes['ask'][pi]<=p[:,12]-ready['tick']+1e-8,
                                   quotes['bid'][pi]>=p[:,12]+ready['tick']-1e-8))
            np.testing.assert_allclose(p[:,12]/(ready['tick']/2),np.rint(p[:,12]/(ready['tick']/2)),atol=1e-7)
        assert np.all(orders[:,4]<ready['limit']+300)
        core_entry=(orders[:,9]==1)&(orders[:,18]==0)
        assert np.all(orders[core_entry,4]<ready['limit']-300)
        np.add.at(cash,i,-orders[:,10]*orders[:,11]*orders[:,12]*value-fee_values)
        entry=orders[:,9]==1
        long_change=np.where((entry&(orders[:,10]>0))|(~entry&(orders[:,10]<0)),
                             np.where(entry,orders[:,11],-orders[:,11]),0.)
        short_change=np.where((entry&(orders[:,10]<0))|(~entry&(orders[:,10]>0)),
                              np.where(entry,orders[:,11],-orders[:,11]),0.)
        np.add.at(long,i,long_change);np.add.at(short,i,short_change)
    long=np.cumsum(long);short=np.cumsum(short);cash=np.cumsum(cash)
    assert long[-1]==short[-1]==0 and long.min()>=0 and short.min()>=0
    assert max(long.max(),short.max())<=cap
    curve=cash+(long-short)*quotes['mid']*value if mode=='mid' else cash+(long*quotes['bid']-short*quotes['ask'])*value
    midcurve=cash+(long-short)*quotes['mid']*value
    for field,values in [('drawdown',curve),('mid_drawdown',midcurve)]:
        peak=np.maximum.accumulate(np.r_[0.,values])[1:]
        equal(account[field],np.max(peak-values,initial=0),field)
    for field,number in [('equity_min',np.min(curve,initial=0)),('equity_max',np.max(curve,initial=0)),
                         ('mid_equity_min',np.min(midcurve,initial=0)),('mid_equity_max',np.max(midcurve,initial=0)),
                         ('max_long_qty',long.max()),('max_short_qty',short.max()),
                         ('max_gross_qty',(long+short).max()),('max_abs_net_qty',np.abs(long-short).max()),
                         ('net',curve[-1]),('equity_change',curve[-1]),('fees',orders[:,13].sum())]:equal(account[field],number,field)
    gross=trades[:,3]*trades[:,4]*(trades[:,14]-trades[:,13])*value
    np.testing.assert_allclose(trades[:,15],gross,atol=1e-6,rtol=0)
    np.testing.assert_allclose(trades[:,18],gross-trades[:,16]-trades[:,17],atol=1e-6,rtol=0)
    np.testing.assert_allclose(trades[:,22],(trades[:,10]-trades[:,9])/60,atol=1e-10,rtol=0)
    equal(trades[:,16:18].sum(),orders[:,13].sum(),'全費用配賦')
    equal(trades[:,18].sum(),curve[-1],'全返済会計')
    net=trades[:,18]
    for field,number in [('closed_net_profit',net[net>0].sum()),('closed_net_loss',-net[net<0].sum()),
                         ('gross_profit',gross[gross>0].sum()),('gross_loss',-gross[gross<0].sum()),
                         ('win_qty',trades[net>0,4].sum()),('loss_qty',trades[net<0,4].sum()),
                         ('flat_qty',trades[net==0,4].sum()),('cycles',len(trades))]:equal(account[field],number,field)
    for trade in trades:
        initial=orders[int(trade[5])];final=orders[int(trade[6])]
        assert initial[9]==1 and final[9]==2
        assert initial[2]==trade[7] and final[2]==trade[8]
        assert initial[10]==trade[3] and final[10]==-trade[3]
        assert initial[11]==trade[4] and initial[12]==trade[13] and final[12]==trade[14]
        assert initial[13]==trade[16]
        if trade[19]==11:assert final[3]>=initial[4]+config['minutes']*60
    if len(trades):
        # 注文番号をキーに数量と費用配賦を同方向合計する。
        qty=np.bincount(trades[:,6].astype(int),weights=trades[:,4],minlength=len(orders))
        fees=np.bincount(trades[:,6].astype(int),weights=trades[:,17],minlength=len(orders))
        exits=orders[:,9]==2
        np.testing.assert_allclose(qty[exits],orders[exits,11],atol=0,rtol=0)
        np.testing.assert_allclose(fees[exits],orders[exits,13],atol=1e-6,rtol=0)
    return dict(orders=len(orders),trades=len(trades),raw_rows=n)


def main() -> None:
    """機能: 180条件×3モデル・27,000口座の台帳と全期間/週集計を検査する。

    引数: なし。返り値: なし(None)。売買を再実行せず原本と台帳を照合する。
    """
    target=SOURCE/'集計結果.json'
    schema_only='--schema' in sys.argv
    if schema_only:
        lines=(SOURCE/'中間集計.jsonl').read_text(encoding='utf-8').splitlines()
        result={'methods':[json.loads(lines[0])]}
    else:
        result=json.loads(target.read_text(encoding='utf-8'))
    inputs=pickle.loads((OLD/'inputs.pkl').read_bytes());quotes=pickle.loads((OLD/'quotes.pkl').read_bytes())
    total=dict(accounts=0,orders=0,trades=0,raw_rows=0,summaries=0)
    for number,method in enumerate(result['methods'],1):
        payload=(SOURCE/method['ledger_path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest()==method['ledger_sha256']
        ledgers=pickle.loads(payload)
        for account in method['accounts']:
            key=(account['session'],account['symbol'])
            checked=audit(account,ledgers[key],inputs[key],quotes[key],method)
            total['accounts']+=1
            for name,amount in checked.items():total[name]+=amount
        for symbol in ('TOPIX','NK225'):
            selected=[a for a in method['accounts'] if a['symbol']==symbol]
            summaries=[(method['summary'][symbol],selected)]
            summaries.extend((data,[a for a in selected if a['week']==week]) for week,data in method['weeks'][symbol].items())
            for summary,chosen in summaries:
                for field in ('net','fees','gross_profit','gross_loss','closed_net_profit','closed_net_loss','win_qty','loss_qty','cycles'):
                    equal(summary[field],sum(a[field] for a in chosen),'集計_'+field)
                equal(summary['without_best'],sum(a['net'] for a in chosen)-max(0.,max(a['net'] for a in chosen)),'大勝場除外')
                total['summaries']+=1
        if number%60==0:print(json.dumps({'監査済モデル':number,'全モデル':540},ensure_ascii=False),flush=True)
    record=dict(合格=True,件数=total,原本気配と指値通過照合=True,全行資産独立照合=True,
                両建て双方数量と費用照合=True,場内全返済=True,
                結果SHA256=None if schema_only else hashlib.sha256(target.read_bytes()).hexdigest())
    name='在庫最初の50口座形式監査.json' if schema_only else '在庫全台帳の独立監査.json'
    (HERE/name).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
