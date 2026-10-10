"""新96方式の未来非参照、価格反射、注文と会計を独立の恒等式で検査する。"""
from copy import deepcopy
import hashlib
import numpy as np
import pandas as pd
import research as r


def accounting() -> dict:
    """機能: 全注文と決済を独立会計し、上限・約定順序・損益集計を照合する。

    引数: なし。返り値: 検査数(dict)。
    """
    count=orders_count=0
    for spec in r.catalog():
        rows={(v['session'],v['symbol']):v for v in r.read('sessions/'+spec['id']+'.json')}
        for ledger in r.read('ledgers/'+spec['id']+'.json.gz'):
            key=ledger['session'],ledger['symbol'];pv=1000 if key[1]=='TOPIX' else 10;cap=10 if key[1]=='TOPIX' else 20
            position=0;entry=0;side=0;balance=0
            for o in ledger['orders']:
                assert o[3]>o[2] and o[1]>=o[0]
                assert o[6]>0 and float(o[6]).is_integer()
                if o[4]==1:
                    assert position==0
                    position=int(o[6]);entry=o[7];side=o[5]
                else:
                    assert o[5]==-side and 0<o[6]<=position
                    expected=side*(o[7]-entry)*o[6]*pv
                    assert abs(expected-o[8])<1e-7
                    balance+=expected;position-=int(o[6])
                assert 0<=position<=cap
                orders_count+=1
            assert position==0 and abs(balance-rows[key]['net'])<1e-7
            trades=np.asarray(ledger['trades'],dtype=float).reshape(-1,16)
            assert np.allclose(trades[:,6],trades[:,2]*(trades[:,5]-trades[:,4])*trades[:,3]*pv,rtol=0,atol=1e-7)
            assert len(trades)==rows[key]['trades']
            assert np.all(trades[:,12]>trades[:,13])
            assert abs(trades[:,6].sum()-balance)<1e-7
            count+=1
    return dict(口座数=count,注文数=orders_count,全合格=True)


def truncate(ready: dict, end: float) -> dict:
    """機能: 指定時刻までの入力接頭辞を作る。

    引数: ready(dict)、end(float)。返り値: 接頭辞(dict)。
    """
    keep=ready['time_s']<=end
    return {k:(v[keep].copy() if isinstance(v,np.ndarray) else v) for k,v in ready.items()}


def check_prefix(inputs: dict, frames: dict) -> list[dict]:
    """機能: 原本・公開板・足の未来変更や削除が過去判断に影響しないことを確認する。

    引数: inputs/frames(dict)。返り値: 検査証跡(list[dict])。
    """
    chosen=r.read('過去10場選択.json')['系統代表']+['R04_W30_C0_X2']
    specs=[s for s in r.catalog() if s['id'] in chosen]
    records=[]
    for session in ('2026-09-21_Day','2026-10-05_Night','2026-10-06_Day'):
        keys=[(session,symbol) for symbol in ('TOPIX','NK225')]
        tables={k:pd.read_csv(r.ROOT/'candle_1min'/k[1]/(session+'.csv')) for k in keys}
        for fraction in (.35,.65):
            cutoff=min(inputs[k]['start']+(inputs[k]['limit']-inputs[k]['start'])*fraction for k in keys)
            prefix={k:truncate(inputs[k],cutoff) for k in keys}
            prefix_frames={k:frames[k].loc[frames[k].time_s<=cutoff].copy() for k in keys}
            changed={};changed_tables={};changed_frames={}
            for key in keys:
                changed[key]=deepcopy(inputs[key]);future=changed[key]['time_s']>cutoff
                changed[key]['last'][future]+=10000;changed[key]['atr'][future]*=7
                changed_tables[key]=tables[key].copy()
                published=pd.to_datetime(tables[key].time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
                for column in ('open','high','low','close'):
                    changed_tables[key].loc[published>cutoff,column]+=12345
                changed_frames[key]=frames[key].copy()
                for column in ('ofi_signed','ofi_abs','dflow_near'):
                    changed_frames[key].loc[changed_frames[key].time_s>cutoff,column]=9999
            for window in (15,30):
                normal={k:r.bars(inputs[k],frames[k],window,tables[k]) for k in keys}
                short={k:r.bars(prefix[k],prefix_frames[k],window,tables[k]) for k in keys}
                altered={k:r.bars(changed[k],changed_frames[k],window,changed_tables[k]) for k in keys}
                for spec in [s for s in specs if s['window']==window]:
                    for key in keys:
                        e=r.signals(spec,normal,key);ep=r.signals(spec,short,key);ef=r.signals(spec,altered,key)
                        common_end=min(prefix[k]['time_s'][-1] for k in keys)
                        assert np.array_equal(e[e[:,0]<=common_end],ep[ep[:,0]<=common_end],equal_nan=True),(spec['id'],key,cutoff)
                        assert np.array_equal(e[e[:,0]<=cutoff],ef[ef[:,0]<=cutoff],equal_nan=True)
                        full=r.execute(spec,inputs[key],e)
                        part=r.execute(spec,prefix[key],ep,False)
                        future_result=r.execute(spec,changed[key],ef)
                        assert np.array_equal(full[1][full[1][:,1]<=common_end],part[1][part[1][:,1]<=common_end])
                        assert np.array_equal(full[1][full[1][:,1]<=cutoff],future_result[1][future_result[1][:,1]<=cutoff])
                        records.append(dict(id=spec['id'],session=session,symbol=key[1],cutoff=cutoff,過去一致=True))
    return records


def reflection(inputs: dict, frames: dict) -> dict:
    """機能: 両市場の価格と板符号を鏡映して損益対称性を検査する。

    引数: inputs/frames(dict)。返り値: 検査数(dict)。
    """
    session='2026-10-06_Day';keys=[(session,s) for s in ('TOPIX','NK225')]
    ordinary={};mirrored={};mirrored_frames={};normal_tables={};mirror_tables={}
    centers={}
    for k in keys:
        ordinary[k]=inputs[k];mirrored[k]=deepcopy(inputs[k]);center=4*float(inputs[k]['last'][0]);centers[k]=center
        mirrored[k]['last']=center-inputs[k]['last']
        mirrored_frames[k]=frames[k].copy()
        mirrored_frames[k]['ofi_signed']*=-1;mirrored_frames[k]['dflow_near']*=-1
        tab=pd.read_csv(r.ROOT/'candle_1min'/k[1]/(session+'.csv'));normal_tables[k]=tab
        reflected=tab.copy();reflected['high']=center-tab.low;reflected['low']=center-tab.high
        reflected['open']=center-tab.open;reflected['close']=center-tab.close;mirror_tables[k]=reflected
    count=0
    for window in (15,30):
        normal={k:r.bars(ordinary[k],frames[k],window,normal_tables[k]) for k in keys}
        mirror={k:r.bars(mirrored[k],mirrored_frames[k],window,mirror_tables[k]) for k in keys}
        for spec in [s for s in r.catalog() if s['window']==window]:
            for k in keys:
                a=r.signals(spec,normal,k);b=r.signals(spec,mirror,k)
                assert np.array_equal(a[:,1],-b[:,1]),(spec['id'],k,'反射信号')
                assert np.array_equal(a[:,2],b[:,2])
                x=r.execute(spec,ordinary[k],a);y=r.execute(spec,mirrored[k],b)
                assert x[0].shape==y[0].shape,(spec['id'],k,'反射件数')
                assert np.array_equal(x[0][:,[0,1,3,7,9,10,11,12,13]],y[0][:,[0,1,3,7,9,10,11,12,13]])
                assert np.allclose(x[0][:,[6,8,14,15]],y[0][:,[6,8,14,15]],rtol=0,atol=1e-7)
                assert np.array_equal(x[0][:,2],-y[0][:,2])
                assert np.allclose(x[0][:,4:6]+y[0][:,4:6],centers[k],rtol=0,atol=1e-7)
                assert abs(x[2]-y[2])<1e-6
                count+=1
    return dict(口座数=count,全合格=True)


def activity() -> None:
    """機能: 全候補の同一売買結果数と低活動候補の参加間隔を残す。

    引数: なし。返り値: なし(None)。
    """
    signatures={};activity={}
    for spec in r.catalog():
        ledgers=r.read('ledgers/'+spec['id']+'.json.gz');fingerprint=hashlib.sha256(str(ledgers).encode()).hexdigest()
        signatures.setdefault(fingerprint,[]).append(spec['id'])
        if spec['family']!=3:continue
        activity[spec['id']]={}
        for symbol in ('TOPIX','NK225'):
            data=[x for x in ledgers if x['symbol']==symbol];quiet=[];current=[];longest=[]
            for x in data:
                if not x['orders']:
                    quiet.append(x['session']);current.append(x['session'])
                    if len(current)>len(longest):longest=current.copy()
                else:current=[]
            activity[spec['id']][symbol]=dict(無取引場=quiet,最大連続不参加場数=len(longest),最大連続不参加=longest,
                                              活動場数=len(data)-len(quiet),新規数=sum(sum(o[4]==1 for o in x['orders']) for x in data))
    r.save('活動と重複.json',dict(条件数=96,売買列の異なる結果数=len(signatures),同一結果群=[ids for ids in signatures.values() if len(ids)>1],往復候補=activity))


def main() -> None:
    """機能: 全監査を実行し、出力と実装の指紋を保存する。

    引数: なし。返り値: なし(None)。
    """
    inputs,frames=r.load()
    accounts=accounting();print('全口座会計完了',flush=True)
    prefixes=check_prefix(inputs,frames);print('未来非参照完了',flush=True)
    mirrors=reflection(inputs,frames);print('買売反射完了',flush=True)
    activity()
    r.save('監査.json',dict(全合格=True,会計=accounts,接頭辞未来改変=prefixes,価格反射=mirrors,
                           SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in r.HERE.glob('*.py')},
                           修正記録=['回帰注文の余地判定を次約定行から前行判断へ移動','相手時刻欠損では新規判断を無効化','半数利確の冷却は組全体損益で判定'],
                           条件カタログ変更=False))


if __name__=='__main__':main()
