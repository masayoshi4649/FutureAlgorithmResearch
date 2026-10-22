"""既所有の六場から実注文の在庫推移と中値・Last・費用を記述する。"""

from datetime import datetime, timedelta
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent/'formal_b'
ROOT = HERE.parents[3]
METHODS = [tag+'_S2_T1' for tag in ('HEDGE','NET','FLIP','RECYCLE','HARD','ONCE','ALLSIDE')]


def clean(value: object) -> object:
    """
    機能: 診断のNumPy型を標準型へ変換し、非有限の未測定をnullにする。
    引数: value(object)は配列又は辞書。
    返り値: objectはJSON保存可能な値。
    """
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 新規の診断証跡だけを保存する。
    引数: path(Path)、value(dict)は出力先と内容。
    返り値: None。金融結果・経済源を上書きしない。
    """
    assert not path.exists()
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def clock(value: float) -> str:
    """
    機能: 保存価格時計を日本時間表示へ変換する。
    引数: value(float)はepoch秒。
    返り値: str。受信時計へ読み替えない。
    """
    return datetime.fromtimestamp(value,ZoneInfo('Asia/Tokyo')).isoformat()


def scene_times(session: str) -> tuple[float,float,float]:
    """
    機能: SOURCEで固定された場内時間範囲を診断用に取得する。
    引数: session(str)は日付とDay又はNight。
    返り値: tuple[float,float,float]は開始・全返済判断・観測上限。
    """
    day=datetime.fromisoformat(session[:10]).replace(tzinfo=ZoneInfo('Asia/Tokyo'))
    if session.endswith('_Day'):
        return tuple((day+timedelta(hours=h,minutes=m)).timestamp() for h,m in ((8,45),(15,20),(15,45)))
    return ((day+timedelta(hours=17)).timestamp(),(day+timedelta(days=1,hours=5,minutes=40)).timestamp(),(day+timedelta(days=1,hours=6)).timestamp())


def entry_key(lot: dict) -> tuple:
    """
    機能: 政策跨ぎのUID連番を使わず共通実入口を識別する。
    引数: lot(dict)は完結した一枚玉。
    返り値: tupleは方向・段・判断原行・約定原行・実建値。
    """
    return tuple(lot[k] for k in ('side','rung','entry_decision_row','entry_row','entry_price'))


def inspect(orders: np.ndarray, lots: np.ndarray, curves: np.ndarray, q: dict,
            columns: dict, row: dict, accepted: np.ndarray, close_time: float) -> dict:
    """
    機能: 固定された実注文から在庫清算を復元し、原因記述へ限定する。
    引数: orders/lots/curves(float二次元配列)、q(dict)は保存記録、columns(dict)は列名、
        row(dict)は当該場会計、accepted(int一次元配列)は採用quote位置、close_time(float)は場末判断時刻。
    返り値: dictは在庫・理由別損益・中値/Last群・代表UID。新規又は退出を再選択しない。
    """
    symbol=row['symbol'];mult=1000 if symbol=='TOPIX' else 10;fee=41 if symbol=='TOPIX' else 11
    unit=row['step']*mult; n=len(accepted)
    market={k:v[accepted] for k,v in q.items()}; indices=np.searchsorted(market['row'],orders[:,4].astype(np.int64))
    assert np.all(indices<n) and np.array_equal(market['row'][indices],orders[:,4])
    od=[dict(zip(columns['order_columns'],x)) for x in orders]
    ld=[dict(zip(columns['lot_columns'],x)) for x in lots]
    opened={int(x['uid']):x for x in od if x['kind']==1}
    closed={int(x['uid']):x for x in od if x['kind']==2}
    assert len(opened)==len(closed)==len(ld)==row['closed_lots']
    assert opened.keys()==closed.keys() and sum(x['net'] for x in ld)==row['net']
    assert len({entry_key(x) for x in ld})==len(ld)
    # ----------------------------------------
    # 同原行の既返済と新規fillを反映した後の在庫だけを復元する。
    delta=np.zeros((n,7)); groups={}; entries={}
    for o,i in zip(od,indices):
        uid=int(o['uid']);s=int(opened[uid]['side']);sg=0 if s==1 else 1;cost=2 if s==1 else 3
        assert o['fill_row']>o['decision_row'] and o['quantity']==1 and o['fee']==fee
        if o['kind']==1:
            delta[i,sg]+=1;delta[i,cost]+=o['price']
        else:
            gross=s*(o['price']-opened[uid]['price'])*mult
            assert gross-2*fee==o['net']
            delta[i,sg]-=1;delta[i,cost]-=opened[uid]['price']
            delta[i,4]+=o['net'];delta[i,5]+=max(o['net'],0);delta[i,6]+=max(-o['net'],0)
    state=np.cumsum(delta,axis=0);ql,qs=state[:,0],state[:,1];realized=state[:,4]
    equity=realized+(market['bid']*ql-state[:,2]+state[:,3]-market['ask']*qs)*mult-2*fee*(ql+qs)
    cash=realized-fee*(ql+qs);dd=np.maximum.accumulate(np.maximum(equity,0))-equity
    assert math.isclose(equity[-1],row['net'],abs_tol=1e-6)
    assert math.isclose(float(np.max(dd)),row['max_drawdown'],abs_tol=1e-6)
    assert math.isclose(float(np.min(equity)),row['min_equity'],abs_tol=1e-6)
    ci=np.searchsorted(market['row'],curves[:,0].astype(np.int64))
    assert np.array_equal(market['row'][ci],curves[:,0])
    assert np.allclose(curves[:,2:8],np.column_stack((equity[ci],cash[ci],realized[ci],ql[ci],qs[ci],dd[ci])),atol=1e-6,rtol=1e-10)
    # ----------------------------------------
    # 新規判断の中値とLastを混同せず、約定時の半spreadと値動きへ分ける。
    for lot in ld:
        uid=int(lot['uid']);o=opened[uid];side=int(lot['side'])
        d=int(np.searchsorted(market['row'],int(o['decision_row'])));f=int(np.searchsorted(market['row'],int(o['fill_row'])))
        assert market['row'][d]==o['decision_row'] and d>0
        mid=(market['bid'][d]+market['ask'][d])*.5;previous=(market['bid'][d-1]+market['ask'][d-1])*.5
        dm=side*(mid-previous);dl=side*(market['last'][d]-market['last'][d-1])
        assert dm>0
        category='Last不明' if not math.isfinite(dl) else ('Last不変' if dl==0 else 'Lastも同方向' if dl>0 else 'Lastは反対')
        midpoint=(market['bid'][f]+market['ask'][f])*.5
        quote_adverse=side*(o['price']-midpoint)*mult
        move_adverse=side*(midpoint-mid)*mult
        total_adverse=side*(o['price']-mid)*mult
        assert math.isclose(quote_adverse+move_adverse,total_adverse,abs_tol=1e-6)
        initial_cost=(market['ask'][f]-market['bid'][f])*mult+2*fee
        p=groups.setdefault(category,dict(count=0,net=0,gross=0,fees=0,entry_halfspread_cash=0,decision_to_fill_mid_cash=0,
                                         initial_cost_above_unit=0,initial_cost_above_three_units=0,arrival_adverse_count=0))
        p['count']+=1;p['net']+=lot['net'];p['gross']+=lot['gross'];p['fees']+=lot['fees']
        p['entry_halfspread_cash']+=quote_adverse;p['decision_to_fill_mid_cash']+=move_adverse
        p['initial_cost_above_unit']+=int(initial_cost>unit);p['initial_cost_above_three_units']+=int(initial_cost>3*unit)
        decisionprice=market['ask'][d] if side==1 else market['bid'][d]
        p['arrival_adverse_count']+=int(side*(o['price']-decisionprice)>0)
        x=int(np.searchsorted(market['row'],int(lot['exit_row'])))
        lastgross=side*(market['last'][x]-market['last'][f])*mult
        ea=side*(o['price']-market['last'][f])*mult;xa=side*(market['last'][x]-lot['exit_price'])*mult
        if all(math.isfinite(z) for z in (lastgross,ea,xa)):
            assert math.isclose(lastgross-ea-xa-lot['fees'],lot['net'],abs_tol=1e-6)
        entries[uid]=dict(category=category,decision_mid=mid,previous_mid=previous,decision_Last=market['last'][d],previous_Last=market['last'][d-1],
            direction_mid_change=dm,direction_Last_change=dl,entry_halfspread_cash=quote_adverse,decision_to_fill_mid_cash=move_adverse,
            initial_cost=initial_cost,unit_cash=unit,Last_gross=lastgross,entry_Last_adverse=ea,exit_Last_adverse=xa,
            entry_time=clock(lot['entry_time']),exit_time=clock(lot['exit_time']),entry_order=o,exit_order=closed[uid])
    assert sum(x['count'] for x in groups.values())==len(ld)
    # ----------------------------------------
    # 採用quote上の極値・場末判断・実現益と残損失の最大乖離を区別する。
    spots={'最大DD':int(np.argmax(dd)),'最低資産':int(np.argmin(equity))}
    fc=np.flatnonzero(market['time']>=close_time)
    if len(fc):spots['場末判断']=int(fc[0])
    positive=np.flatnonzero(realized>0)
    if len(positive):spots['実現益後の最大残損失']=int(positive[np.argmax((realized-equity)[positive])])
    snapshots={}
    for label,i in spots.items():
        raw=int(market['row'][i]);held=[x for x in ld if x['entry_row']<=raw<x['exit_row']]
        vals=[dict(uid=x['uid'],side=x['side'],entry_price=x['entry_price'],entry_time=clock(x['entry_time']),
                   net=x['side']*((market['bid'][i] if x['side']==1 else market['ask'][i])-x['entry_price'])*mult-2*fee) for x in held]
        assert len(held)==ql[i]+qs[i]
        snapshots[label]=dict(raw_row=raw,time=clock(market['time'][i]),bid=market['bid'][i],ask=market['ask'][i],last=market['last'][i],
            equity=equity[i],cash=cash[i],realized_net=realized[i],closed_positive_net=state[i,5],closed_negative_net=state[i,6],
            long=ql[i],short=qs[i],net_quantity=ql[i]-qs[i],drawdown=dd[i],held_positive=sum(max(x['net'],0) for x in vals),
            held_loss=sum(max(-x['net'],0) for x in vals),held_exit_fees=fee*len(held),held=vals)
        assert math.isclose(realized[i]+sum(x['net'] for x in vals),equity[i],abs_tol=1e-6)
    reasons={}
    for lot in ld:
        bucket=reasons.setdefault(str(int(lot['reason'])),dict(count=0,net=0,profit=0,loss=0))
        bucket['count']+=1;bucket['net']+=lot['net'];bucket['profit']+=max(lot['net'],0);bucket['loss']+=max(-lot['net'],0)
    selected=[]
    if ld:
        selected.append(min(ld,key=lambda x:(x['net'],x['uid'])))
        wins=[x for x in ld if x['net']>0]
        if wins:selected.append(max(wins,key=lambda x:(x['net'],-x['uid'])))
    samples=[dict(lot=x,entry=entries[int(x['uid'])]) for x in selected]
    negative_trail=[x for x in ld if x['reason']==1 and x['net']<0]
    return dict(row=row,snapshots=snapshots,reasons=reasons,mid_Last_groups=groups,
        negative_actual_trail=dict(count=len(negative_trail),net=sum(x['net'] for x in negative_trail)),
        samples=samples,lot_matches=[dict(key=list(entry_key(x)),net=x['net'],reason=x['reason']) for x in ld])


def main() -> None:
    """
    機能: 最大六場の同bytes所有コピーを一読し、七運用の原因を並べる。
    引数: なし。
    返り値: None。元measurement・元prepared・原市場・金融再生は0。
    """
    plan=json.loads((HERE/'正式b基準赤字六場の保存NPZを各一読する計画.json').read_text(encoding='utf8'))
    small=json.loads((HERE/'全四十八小会計の独立集計と詳細六場.json').read_text(encoding='utf8'))
    cachebase=ROOT/'work/stability120_20261017/audit_result120b/owned'
    planned=[dict(x,owned_path=(cachebase/x['symbol']/(x['session']+'.npz')).relative_to(ROOT).as_posix()) for x in plan['inputs']]
    save(HERE/'独立監査済み同bytes所有六cacheを再利用する追加目録.json',dict(全合格=True,inputs=planned,
        原measurement_cache読取=0,監査所有copy各読取=1,解析前同bytes保全=True,原prepared読取=0,原市場読取=0,金融再生=0,
        留保='独立監査の標本を増やさず、同じ実注文に対する別目的の原因記述として使う。'))
    result=json.loads((HERE/'正式b結果の同bytes保全.json').read_text(encoding='utf8'))
    columns=small['columns'];items=[];logs=[];curves_projection={}
    for item in planned:
        raw=(ROOT/item['owned_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        copy=HERE/'owned'/item['symbol']/(item['session']+'.npz');copy.parent.mkdir(parents=True,exist_ok=True)
        assert not copy.exists();copy.write_bytes(raw)
        start,close,end=scene_times(item['session'])
        with np.load(BytesIO(raw),allow_pickle=False) as src:
            quotes={k:src['quotes__'+k].copy() for k in ('row','time','last','bid','ask')}
            good=np.isfinite(quotes['time'])&(quotes['time']>=start)&(quotes['time']<=end)&np.isfinite(quotes['bid'])&np.isfinite(quotes['ask'])&(quotes['bid']>0)&(quotes['bid']<=quotes['ask'])
            high=np.maximum.accumulate(np.where(good,quotes['time'],-np.inf))
            accepted=np.flatnonzero(good&(quotes['time']>=high))
            arrays={k:src[k].copy() for k in ('orders','lots','curves')}
        del raw
        scene=[]
        for method,index in item['policy_indices'].items():
            row=next(x for x in result['runs'] if x['symbol']==item['symbol'] and x['session']==item['session'] and x['method']==method)
            arr={k:v[v[:,0]==index,1:] for k,v in arrays.items()}
            scene.append(dict(method=method,**inspect(arr['orders'],arr['lots'],arr['curves'],quotes,columns,row,accepted,close)))
            if method==METHODS[0]:curves_projection[item['symbol']+'__'+item['session']]=arr['curves']
        baseline={tuple(x['key']):x for x in scene[0]['lot_matches']}
        comparisons=[]
        for data in scene[1:]:
            current={tuple(x['key']):x for x in data['lot_matches']};common=baseline.keys()&current.keys()
            shared=sum(current[k]['net']-baseline[k]['net'] for k in common)
            added=sum(x['net'] for k,x in current.items() if k not in baseline)
            lost=sum(x['net'] for k,x in baseline.items() if k not in current)
            change=data['row']['net']-scene[0]['row']['net']
            assert shared+added-lost==change
            comparisons.append(dict(method=data['method'],net=data['row']['net'],change=change,common_entries=len(common),
                shared_exit_change=shared,new_entries=len(current)-len(common),new_entry_net=added,
                vanished_entries=len(baseline)-len(common),vanished_entry_net=lost))
        for data in scene:del data['lot_matches']
        items.append(dict(symbol=item['symbol'],session=item['session'],policies=scene,comparisons=comparisons))
        logs.append(dict(owned_path=item['owned_path'],sha256=item['sha256'],reads=1,original_cache_reads=0))
        print(item['symbol']+' '+item['session']+' の七運用診断を保存準備',flush=True)
    output=dict(全合格=True,結果SHA256=small['結果SHA256'],source_SHA256=small['source_SHA256'],scenes=items,read_log=logs,
                元結果追加読取=0,原measurement_cache読取=0,原prepared読取=0,原市場読取=0,金融再生=0,
                留保='基準赤字上位に条件付けた原因記述。群の収支や事後MFEを新しい規則の利益へ置換しない。')
    save(HERE/'基準赤字六場の利益回転と残損失及び中値Lastの診断.json',output)
    memory=BytesIO();np.savez_compressed(memory,**curves_projection)
    p=HERE/'基準六場の保存曲線だけの射影.npz';assert not p.exists();p.write_bytes(memory.getvalue())
    print(json.dumps({'全合格':True,'詳細場数':len(items),'所有NPZ読取':len(logs),'原cache読取':0,'金融再生':0},ensure_ascii=False))


if __name__=='__main__':
    main()
