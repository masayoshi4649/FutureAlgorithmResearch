"""診断後の各改善ラウンドを先に固定し、全場・全flat組の成績を保存する。"""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import engine
import features


HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent.parent/'wave_v60'


def digest(path: Path) -> str:
    """機能: ファイル内容をSHA256で固定する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(4*1024*1024):
            h.update(b)
    return h.hexdigest()


def clean(value: object) -> object:
    """機能: NumPy値と非有限値をJSONへ保存可能にする。

    引数: value(object)。返り値: 変換済み値(object)。
    """
    if isinstance(value,dict):
        return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):
        return [clean(v) for v in value]
    if isinstance(value,np.ndarray):
        return clean(value.tolist())
    if isinstance(value,np.generic):
        return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value):
        return None
    return value


def save(path: Path,value: object) -> None:
    """機能: 日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def group_stats(groups: np.ndarray) -> dict:
    """機能: 費用後の全flat組を主単位として勝率と損小利大を測る。

    引数: groups(ndarray)。返り値: 成績指標(dict)。負け未観測を無限の平均比へ置換しない。
    """
    g=groups[:,11] if len(groups) else np.array([])
    positive=g[g>0]
    negative=-g[g<0]
    win=float(positive.sum())
    loss=float(negative.sum())
    average_win=float(positive.mean()) if len(positive) else None
    average_loss=float(negative.mean()) if len(negative) else None
    ratio=average_win/average_loss if average_loss and average_win else None
    rate=len(positive)/len(g) if len(g) else None
    return dict(groups=len(g),wins=len(positive),losses=len(negative),flats=int(np.sum(g==0)),
        win_rate=rate,profit=win,loss=loss,net=float(g.sum()),pf=win/loss if loss else None,
        average_win=average_win,average_loss=average_loss,payoff=ratio,
        max_win=float(positive.max(initial=0)),max_loss=float(negative.max(initial=0)),
        hold_median_minutes=float(np.median((groups[:,6]-groups[:,5])/60)) if len(g) else None,
        raw_95_pass=bool(len(g) and rate>=.95 and g.sum()>0 and (not len(negative) or (ratio is not None and ratio>1))),
        loss_unobserved=bool(len(g) and not len(negative)))


def account(key: tuple,ready: dict,quote: dict,result: tuple,quantity: int,multiplier: float) -> dict:
    """機能: 場内全返済、注文費用、全flat組と時価損益を照合して集計する。

    引数: key(tuple)、ready/quote(dict)、result(tuple)、quantity(int)、multiplier(float)。返り値: 口座会計(dict)。
    """
    orders,groups,curve,position,counts=result
    assert np.isclose(curve[-1],groups[:,11].sum())
    assert position[-1]==0
    assert np.isclose(orders[:,10].sum()-orders[:,9].sum(),curve[-1])
    assert len(orders)==2*len(groups)
    same_mid=float(np.sum(-orders[:,6]*orders[:,7]*quote['mid'][orders[:,2].astype(int)]*multiplier-orders[:,9]))
    dd=float(np.max(np.maximum.accumulate(np.r_[0.,curve])-np.r_[0.,curve]))
    result=group_stats(groups)
    gross=groups[:,9] if len(groups) else np.array([])
    result.update(session=key[0],symbol=key[1],gross_profit=float(gross[gross>0].sum()),
        gross_loss=float(-gross[gross<0].sum()),gross_pnl=float(gross.sum()),fees=float(orders[:,9].sum()),
        win_qty=int(np.sum(groups[groups[:,11]>0,2])),loss_qty=int(np.sum(groups[groups[:,11]<0,2])),
        flat_qty=int(np.sum(groups[groups[:,11]==0,2])),drawdown=dd,equity_min=float(curve.min(initial=0.)),
        equity_max=float(curve.max(initial=0.)),max_long_qty=quantity if np.any(position>0) else 0,
        max_short_qty=quantity if np.any(position<0) else 0,active=bool(len(groups)),orders=len(orders),
        raw_candidates=int(counts[0]),waiting_orders=int(counts[1]),expired_waiting=int(counts[2]),same_orders_mid_net=same_mid,
        same_orders_price_difference=same_mid-float(curve[-1]),reason={engine.REASONS[r]:dict(groups=int(np.sum(groups[:,12]==r)),
            net=float(groups[groups[:,12]==r,11].sum())) for r in engine.REASONS if r!=1})
    return result


def summary(accounts: list,ledgers: dict,symbol: str) -> dict:
    """機能: 全場の時価DDと全flat組を連結し、少数標本と95%条件を分ける。

    引数: accounts(list)、ledgers(dict)、symbol(str)。返り値: 銘柄別集計(dict)。
    """
    selected=[a for a in accounts if a['symbol']==symbol]
    allgroups=np.concatenate([v['groups'] for k,v in ledgers.items() if k[1]==symbol],axis=0)
    out=group_stats(allgroups)
    balance=peak=drawdown=0.
    for a in selected:
        drawdown=max(drawdown,peak-(balance+a['equity_min']),a['drawdown'])
        peak=max(peak,balance+a['equity_max'])
        balance+=a['net']
    for field in ('gross_profit','gross_loss','gross_pnl','fees','win_qty','loss_qty','flat_qty','orders','raw_candidates','waiting_orders','expired_waiting','same_orders_mid_net'):
        out[field]=sum(a[field] for a in selected)
    out.update(drawdown=drawdown,sessions=len(selected),active_sessions=sum(a['active'] for a in selected),
        winning_sessions=sum(a['net']>0 for a in selected),losing_sessions=sum(a['net']<0 for a in selected),
        without_best_session=balance-max(0.,max(a['net'] for a in selected)),
        max_long_qty=max(a['max_long_qty'] for a in selected),max_short_qty=max(a['max_short_qty'] for a in selected))
    out['enough_sample']=out['groups']>=50 and out['active_sessions']>=12
    out['sample_note']='50組・12活動場は参考目安でありユーザー追加条件ではない'
    assert np.isclose(balance,out['net'])
    return out


def execute(spec_path: Path) -> None:
    """機能: 指定ラウンドだけを損益前に固定し、以後の変更や結果上書きを拒否する。

    引数: spec_path(Path)。返り値: なし(None)。元25場は既読で未知検証ではない。
    """
    spec=json.loads(spec_path.read_text(encoding='utf8'))
    label=spec['round']
    target=HERE/f'{label}_集計結果.json'
    assert not target.exists(),'同ラウンドの結果を上書きしません'
    fixed=dict(round=label,spec_sha256=digest(spec_path),code={name:digest(HERE/name) for name in ('engine.py','features.py','run.py')},
        inputs={str(p.relative_to(HERE.parent.parent)):digest(p) for p in (SOURCE/'inputs.pkl',SOURCE/'quotes.pkl',HERE.parent/'tick_features.pkl',HERE.parent/'tick_events.pkl')},
        frozen_at=datetime.now(timezone.utc).isoformat(),pnl_not_yet_calculated=True,all_sessions_previously_known=True,api_calls=0)
    frozen=HERE/f'{label}_実行前固定.json'
    assert not frozen.exists(),'固定後の再実行は専用の監査が必要です'
    save(frozen,fixed)
    inputs=pickle.loads((SOURCE/'inputs.pkl').read_bytes())
    quotes=pickle.loads((SOURCE/'quotes.pkl').read_bytes())
    tickdata=pickle.loads((HERE.parent/'tick_features.pkl').read_bytes())
    events=pickle.loads((HERE.parent/'tick_events.pkl').read_bytes())
    materials={key:features.build(inputs[key],quotes[key],tickdata[key],events[key]) for key in sorted(inputs)}
    output=[]
    folder=HERE/'ledger'
    folder.mkdir(exist_ok=True)
    for config in spec['methods']:
        accounts=[]
        ledgers={}
        for key in sorted(inputs):
            ready,quote=inputs[key],quotes[key]
            tick=ready['tick']
            width=max(2*tick,np.ceil(quote['mid'][0]*config['fraction']/tick-1e-12)*tick)
            signal=features.signals(materials[key],quote['mid'],width,config['gate'])
            if config.get('spread_guard',False):
                signal=np.where(width>=2.*(quote['ask']-quote['bid'])+tick,signal,0).astype(np.int8)
            quantity,multiplier,fee_tenths=(5,1000.,418) if key[1]=='TOPIX' else (10,10.,110)
            result=engine.drive(ready['time_s'],quote['bid'],quote['ask'],signal,width,tick,quantity,multiplier,fee_tenths,
                ready['limit'],config['mode'],config.get('protect',0),config.get('session_lock',0))
            accounts.append(account(key,ready,quote,result,quantity,multiplier))
            ledgers[key]=dict(orders=result[0],groups=result[1],width=width,raw_signals=int(np.count_nonzero(signal)))
        ledger_path=folder/f"{config['id']}.pkl"
        ledger_path.write_bytes(pickle.dumps(ledgers,protocol=5))
        item=dict(**config,accounts=accounts,ledger=str(ledger_path.relative_to(HERE)),
                  summary={s:summary(accounts,ledgers,s) for s in ('TOPIX','NK225')})
        output.append(item)
        print(config['id'],{s:(item['summary'][s]['net'],item['summary'][s]['win_rate'],item['summary'][s]['groups']) for s in ('TOPIX','NK225')},flush=True)
    save(target,dict(meta=spec,freeze_sha256=digest(frozen),order_columns=engine.ORDER_COLUMNS,group_columns=engine.GROUP_COLUMNS,methods=output))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--spec',required=True)
    args=parser.parse_args()
    execute(Path(args.spec))
