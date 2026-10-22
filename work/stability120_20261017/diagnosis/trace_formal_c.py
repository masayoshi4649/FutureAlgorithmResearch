"""cの最悪二場で、保存注文の追加資格・反復停止・実損失を診断する。"""

from io import BytesIO
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent/'formal_c'
ROOT=HERE.parents[3]
EXPECTED='1071dc7f296d8ffbf3483e26b863d79cde48b82bcca986a7b5810c8e18f9ee9f'


def saved_helper() -> object:
    """
    機能: 既存の保存注文診断関数だけを読み込む。
    引数: なし。
    返り値: objectはbの独立診断モジュール。数値エンジンやmainは実行しない。
    """
    path=HERE.parent/'trace_formal_b.py'
    spec=importlib.util.spec_from_file_location('既保存注文の原因診断',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def extra(orders: np.ndarray,lots: np.ndarray,q: dict,row: dict,columns: dict,helper: object) -> dict:
    """
    機能: 固定実注文から追加当時の清算余力、方向停止と次気配差を記述する。
    引数: orders/lots(float二次元配列)、q(dict)は保存記録、row/columns(dict)は会計と列名、helper(object)は純診断関数。
    返り値: dictは追加資格下限・反復停止・未追尾損失。取消済予約の未保存を補わない。
    """
    od=[dict(zip(columns['order_columns'],x)) for x in orders]
    ld=[dict(zip(columns['lot_columns'],x)) for x in lots]
    entered={int(x['uid']):x for x in od if x['kind']==1}
    unit=row['step']*(1000 if row['symbol']=='TOPIX' else 10);mult=1000 if row['symbol']=='TOPIX' else 10
    fee=41 if row['symbol']=='TOPIX' else 11
    def point(raw: float) -> dict:
        """
        機能: 原行と完全一致する保存quoteを取得する。
        引数: raw(float)は保存整数原行。
        返り値: dictは当該原行の価格時計とLast/BBO。
        """
        i=int(np.searchsorted(q['row'],int(raw)));assert q['row'][i]==raw
        return {k:float(v[i]) for k,v in q.items()}
    reservations=[]
    for lot in ld:
        order=entered[int(lot['uid'])];d=lot['entry_decision_row'];side=lot['side'];p=point(d)
        held=[x for x in ld if x['side']==side and x['entry_row']<=d<x['exit_row']]
        current=sum(side*((p['bid'] if side==1 else p['ask'])-x['entry_price'])*mult-2*fee for x in held)
        saved_pending=sum(x['side']==side and ((x['entry_decision_row']<d<x['entry_row']) or
            (x['entry_decision_row']==d and x['rung']<lot['rung'])) for x in ld)
        risk=3*unit*(saved_pending+1)
        assert not held or current>=risk-1e-6
        fill=point(lot['entry_row']);newcost=(fill['ask']-fill['bid'])*mult+2*fee
        entriesideprice=p['ask'] if side==1 else p['bid']
        reservations.append(dict(uid=lot['uid'],side=side,initial=not held,existing_quantity=len(held),
            current_same_side_net=current,minimum_saved_pending=saved_pending,required_risk_lower_bound=risk,
            decision_row=d,decision_time=helper.clock(p['time']),decision_bid=p['bid'],decision_ask=p['ask'],
            fill_time=helper.clock(fill['time']),fill_price=order['price'],initial_liquidation_cost=newcost,
            fill_adverse_from_decision_quote=side*(order['price']-entriesideprice)*mult,
            final_net=lot['net'],mfe=lot['mfe'],mae=lot['mae']))
    grouped={}
    for lot in ld:
        if lot['reason']==8:grouped.setdefault((lot['side'],lot['exit_decision_row']),[]).append(lot)
    stops=[]
    for (side,d),group in grouped.items():
        p=point(d);held=[x for x in ld if x['side']==side and x['entry_row']<=d<x['exit_row']]
        net=sum(side*((p['bid'] if side==1 else p['ask'])-x['entry_price'])*mult-2*fee for x in held)
        assert net<=-3*unit+1e-6
        ownnet=sum(side*((p['bid'] if side==1 else p['ask'])-x['entry_price'])*mult-2*fee for x in group)
        actual=sum(x['net'] for x in group);end=max(x['exit_row'] for x in group)
        following=[x for x in ld if x['side']==side and x['entry_decision_row']>=end]
        nxt=min(following,key=lambda x:x['entry_decision_row']) if following else None
        stops.append(dict(side=side,decision_row=d,decision_time=helper.clock(p['time']),decision_bid=p['bid'],decision_ask=p['ask'],
            direction_quantity=len(held),direction_liquidation_net=net,reserved_UIDs=[x['uid'] for x in group],
            reserved_quantity=len(group),reserved_at_decision_net=ownnet,actual_net=actual,next_quote_change=actual-ownnet,
            last_exit_time=helper.clock(max(x['exit_time'] for x in group)),
            next_same_side_entry=None if nxt is None else dict(uid=nxt['uid'],decision_row=nxt['entry_decision_row'],
                time=entered[int(nxt['uid'])]['decision_time'],time_display=helper.clock(entered[int(nxt['uid'])]['decision_time']),
                seconds_after_last_exit=entered[int(nxt['uid'])]['decision_time']-max(x['exit_time'] for x in group))))
    stops.sort(key=lambda x:x['decision_row'])
    losers=[x for x in ld if x['net']<0]
    before_arm=[x for x in losers if x['mfe']<2*unit]
    never_positive=[x for x in losers if x['mfe']<=0]
    selected=[]
    if losers:selected.append(min(losers,key=lambda x:x['net']))
    added_uids={int(x['uid']) for x in reservations if not x['initial']}
    additions=[x for x in losers if int(x['uid']) in added_uids]
    if additions:
        a=min(additions,key=lambda x:x['net'])
        if all(x['uid']!=a['uid'] for x in selected):selected.append(a)
    worst_stop=min(stops,key=lambda x:x['actual_net']) if stops else None
    return dict(unit_cash=unit,initial_entries=sum(x['initial'] for x in reservations),add_entries=sum(not x['initial'] for x in reservations),
        reservation_checks=reservations,
        reservation_limit='取消された未約定予約は個別未保存。保存された実追加の必要予算下限を確認し、未知の予約を0と断定しない。完全な実装同値は所有人工・独立会計へ委譲。',
        stops=stops,stop_count=len(stops),stop_net=sum(x['actual_net'] for x in stops),
        stop_gap_change=sum(x['next_quote_change'] for x in stops),worst_stop=worst_stop,
        loss_before_trail=dict(count=len(before_arm),net=sum(x['net'] for x in before_arm),
            all_losing_count=len(losers),all_losing_net=sum(x['net'] for x in losers)),
        no_positive_before_loss=dict(count=len(never_positive),net=sum(x['net'] for x in never_positive)),
        selected_lots=[dict(lot=x,reservation=next(v for v in reservations if v['uid']==x['uid']),
            entry_order=entered[int(x['uid'])],exit_order=next(v for v in od if v['kind']==2 and v['uid']==x['uid'])) for x in selected])


def main() -> None:
    """
    機能: 根指定のCOST二場だけを同bytes保全後に読み、四管理を同時に射影する。
    引数: なし。
    返り値: None。原市場・元prepared・金融再生・d結果読取は0。
    """
    helper=saved_helper()
    plan=json.loads((HERE/'正式cのCOST最悪二場を各一読する目録.json').read_text(encoding='utf8'))
    small=json.loads((HERE/'全二十四小会計と保存b基準の比較.json').read_text(encoding='utf8'))
    raw=(HERE/'正式c結果の同bytes保全.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==EXPECTED
    result=json.loads(raw)
    bresult=json.loads((HERE.parent/'formal_b/正式b結果の同bytes保全.json').read_text(encoding='utf8'))
    ownedbase=ROOT/'work/stability120_20261017/audit_result120c/owned'
    items=[dict(x,owned_path=(ownedbase/x['symbol']/(x['session']+'.npz')).relative_to(ROOT).as_posix()) for x in plan['inputs']]
    save=helper.save
    # bの保存関数はb所有域に限定されるため、cは標準JSONを直接新規保存する。
    extra_plan=HERE/'監査所有c二copyとb既所有一場を再利用する目録.json'
    assert not extra_plan.exists()
    extra_plan.write_text(json.dumps(dict(全合格=True,c_inputs=items,c各copy読取=1,c原cache読取=0,
        b='既読formal_b/ownedに同場がある場合だけ再使用。TOP新場のb追加cacheなし。',原市場読取=0,金融再生=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    scenes=[];logs=[]
    for item in items:
        data=(ROOT/item['owned_path']).read_bytes();assert hashlib.sha256(data).hexdigest()==item['sha256']
        copy=HERE/'owned'/item['symbol']/(item['session']+'.npz');copy.parent.mkdir(parents=True,exist_ok=True);assert not copy.exists();copy.write_bytes(data)
        start,close,end=helper.scene_times(item['session'])
        with np.load(BytesIO(data),allow_pickle=False) as src:
            q={k:src['quotes__'+k].copy() for k in ('row','time','last','bid','ask')}
            arrays={k:src[k].copy() for k in ('orders','lots','curves')}
        del data
        good=np.isfinite(q['time'])&(q['time']>=start)&(q['time']<=end)&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['bid']<=q['ask'])
        accepted=np.flatnonzero(good&(q['time']>=np.maximum.accumulate(np.where(good,q['time'],-np.inf))))
        policies=[]
        for method,index in item['policy_indices'].items():
            row=next(x for x in result['runs'] if x['method']==method and x['symbol']==item['symbol'] and x['session']==item['session'])
            filtered={k:v[v[:,0]==index,1:] for k,v in arrays.items()}
            common=helper.inspect(filtered['orders'],filtered['lots'],filtered['curves'],q,small['columns'],row,accepted,close)
            policies.append(dict(method=method,**common,credit_and_stop=extra(filtered['orders'],filtered['lots'],q,row,small['columns'],helper)))
        b_row=next(x for x in bresult['runs'] if x['method']=='HEDGE_S2_T1' and x['symbol']==item['symbol'] and x['session']==item['session'])
        bowned=HERE.parent/'formal_b/owned'/item['symbol']/(item['session']+'.npz')
        b_detail=None
        if bowned.is_file():
            br=bowned.read_bytes();brmeta=next(x for x in bresult['cache'] if x['symbol']==item['symbol'] and x['session']==item['session'])
            assert hashlib.sha256(br).hexdigest()==brmeta['sha256']
            idx=next(i for i,s in enumerate(bresult['specs']) if s['id']=='HEDGE_S2_T1')
            with np.load(BytesIO(br),allow_pickle=False) as src:
                ba={k:src[k] for k in ('orders','lots','curves')}
                ba={k:v[v[:,0]==idx,1:].copy() for k,v in ba.items()}
            bc={k:bresult[k] for k in ('order_columns','lot_columns','curve_columns')}
            b_detail=helper.inspect(ba['orders'],ba['lots'],ba['curves'],q,bc,b_row,accepted,close)
            logs.append(dict(type='b既所有copy再使用',path=bowned.relative_to(ROOT).as_posix(),reads=1,SHA256=brmeta['sha256']))
        scenes.append(dict(symbol=item['symbol'],session=item['session'],baseline_b=b_row,baseline_b_detail=b_detail,policies=policies))
        logs.append(dict(type='監査所有c同bytescopy',path=item['owned_path'],reads=1,SHA256=item['sha256']))
        print(item['symbol']+' '+item['session']+' 四管理の固定実注文を診断',flush=True)
    out=HERE/'COST最悪二場の追加余力と反復停止及び未追尾損失の診断.json';assert not out.exists()
    out.write_text(json.dumps(helper.clean(dict(全合格=True,結果SHA256=EXPECTED,source_SHA256=small['source_SHA256'],
        scenes=scenes,read_log=logs,原measurement_cache読取=0,原市場読取=0,原prepared読取=0,金融再生=0,d結果読取=0)),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'全合格':True,'c詳細cache':len(items),'b既所有再使用':sum(x['type'].startswith('b') for x in logs)},ensure_ascii=False))


if __name__=='__main__':main()
