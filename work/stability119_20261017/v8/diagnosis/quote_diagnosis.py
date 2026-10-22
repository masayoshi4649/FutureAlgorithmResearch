"""保存結果の同bytes保全だけを再利用し、必要所有quotesから初期清算と残差を記述する。"""

from datetime import datetime
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

import numpy as np


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[2]
EXPECTED='2f7c15e27d7c0e20b6b14de8ab682ac62d49a55b6ba35d2079b6245d9699dcf4'
SYMBOLS=('NK225','TOPIX')


def clean(value: object) -> object:
    """
    機能: 型を有限JSONへ変換し、不明点をnullで残す。
    引数: value(object)は診断素材。
    返り値: objectは保存可能な値。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 所有域の新規診断だけを保存する。
    引数: path(Path)、value(dict)は出力先と内容。
    返り値: None。金融及び旧成果を更新しない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')


def iso(time: float) -> str:
    """
    機能: 保存価格時計をJST表示する。
    引数: time(float)はepoch秒。
    返り値: strは価格時計表示。真受信時刻へ読み替えない。
    """
    return datetime.fromtimestamp(time,ZoneInfo('Asia/Tokyo')).isoformat()


def snapshot(quotes: dict, time: float) -> dict:
    """
    機能: 同clock後半を含むその時計までの最後の保存正常気配を取得する。
    引数: quotes(dict)、time(float)は自身原順の気配と共同snapshot時計。
    返り値: dictはその時点のLast/BBO/元行/age。未来quoteは使わない。
    """
    index=int(np.searchsorted(quotes['time'],time,side='right')-1);assert index>=0
    return dict(index=index,row=int(quotes['row'][index]),time=float(quotes['time'][index]),
        last=float(quotes['last'][index]),bid=float(quotes['bid'][index]),ask=float(quotes['ask'][index]),
        age=float(time-quotes['time'][index]))


def initial(parent: dict, material: dict) -> dict:
    """
    機能: 両脚の初回fill完了時計の清算可能損益を、現在反対BBOと全往復料から求める。
    引数: parent(dict)、material(dict[str,dict])は保存実親と二脚正常気配。
    返り値: dictは共同snapshot・予算大小・残差変化。別執行の金融ではない。
    """
    now=max(parent['entry_time_nk'],parent['entry_time_top']);s=int(parent['side_nk'])
    points={symbol:snapshot(material[symbol],now) for symbol in SYMBOLS}
    qn,qt=int(parent['target_quantity_nk']),int(parent['target_quantity_top'])
    fees=2*(qn*11+qt*209//5)
    gross=s*(points['NK225']['bid' if s>0 else 'ask']-parent['entry_nk'])*qn*10
    gross+=-s*(points['TOPIX']['ask' if s>0 else 'bid']-parent['entry_top'])*qt*1000
    net=gross-fees
    delta=math.log(points['NK225']['last'])-parent['beta']*math.log(points['TOPIX']['last'])-parent['center']
    sign=-s;peak=sign*parent['extreme_delta'];margin=peak-sign*parent['entry_delta']
    nominal=qn*10*parent['reserve_reference_nk'];budget=margin*nominal+fees
    assert math.isclose(budget,parent['cash_loss_budget'],abs_tol=1e-5,rel_tol=1e-9)
    tick_n=math.log((parent['reserve_reference_nk']+10)/parent['reserve_reference_nk'])
    tick_t=parent['beta']*math.log((parent['reserve_reference_top']+.5)/parent['reserve_reference_top'])
    return dict(time=now,価格時計=iso(now),quotes=points,gross_liquidation=gross,roundtrip_fees=fees,
        net_liquidation=net,cash_budget=parent['cash_loss_budget'],net_below_budget=net<=-parent['cash_loss_budget'],
        delta=delta,reserve_delta=parent['entry_delta'],delta_change=delta-parent['entry_delta'],
        reserve_to_peak_margin=margin,margin_in_NK_observed_ticks=margin/tick_n,
        margin_in_TOP_observed_ticks=margin/tick_t,sigma=parent['sigma'],
        at_or_beyond_extreme=sign*delta>=peak,at_or_beyond_center=sign*delta<=0,
        same_Last_as_reserve=points['NK225']['last']==parent['reserve_reference_nk'] and points['TOPIX']['last']==parent['reserve_reference_top'],
        delta_nearly_unchanged=abs(delta-parent['entry_delta'])<=.1*min(tick_n,tick_t),
        near_definition='予約残差からの変化が両市場1観測呼値の残差変化の小さい方の10%以下。結果前に第二段計画で固定。')


def path_extremes(parent: dict, material: dict, orders: list[dict]) -> dict:
    """
    機能: 同clock共同snapshotと保存実fillだけから親局所清算MFE/MAEを独立復元する。
    引数: parent/material(dict)、orders(list[dict])は実親・正常気配・実注文。
    返り値: dictは全quote時計の極値と停止時計。再注文・別出口を作らない。
    """
    start=parent['decision_time'];finish=max(v['fill_time'] for v in orders)
    clocks=np.unique(np.concatenate([q['time'][(q['time']>=start)&(q['time']<=finish)] for q in material.values()]+[np.asarray([start,finish])]))
    curve=np.zeros(len(clocks));holds=np.zeros(len(clocks),np.int64)
    for leg,symbol in enumerate(SYMBOLS):
        entry=[v for v in orders if v['leg']==leg and v['kind']==1]
        exit=[v for v in orders if v['leg']==leg and v['kind']==2]
        if not entry:continue
        assert len(entry)==len(exit)==1
        a,b=entry[0],exit[0];side=int(a['side']);quantity=int(a['quantity']);m=10 if leg==0 else 1000
        q=material[symbol];ix=np.searchsorted(q['time'],clocks,side='right')-1;assert (ix>=0).all()
        holding=(clocks>=a['fill_time'])&(clocks<b['fill_time']);holds+=holding.astype(np.int64)
        curve-=a['fee']*(clocks>=a['fill_time'])
        gain=side*(b['price']-a['price'])*quantity*m
        curve+=(gain-b['fee'])*(clocks>=b['fill_time'])
        close=q['bid' if side>0 else 'ask'][ix]
        curve+=np.where(holding,side*(close-a['price'])*quantity*m-b['fee'],0.)
    assert math.isclose(curve[-1],parent['net'],abs_tol=1e-5,rel_tol=1e-10)
    mfe=max(0.,float(curve.max()));mae=min(0.,float(curve.min()))
    assert math.isclose(mfe,parent['mfe_liquidation_net'],abs_tol=1e-5,rel_tol=1e-10)
    assert math.isclose(mae,parent['mae_liquidation_net'],abs_tol=1e-5,rel_tol=1e-10)
    peak=int(np.argmax(curve));trough=int(np.argmin(curve))
    i=int(np.searchsorted(clocks,parent['exit_decision_time']));assert clocks[i]==parent['exit_decision_time']
    return dict(mfe=mfe,mae=mae,peak_time=iso(float(clocks[peak])),trough_time=iso(float(clocks[trough])),
        stop_snapshot_net=float(curve[i]),final_net=float(curve[-1]),observed_clock_groups=len(clocks),
        definition='実注文の入退出を固定した共同quote snapshot。MFEは元保存と同じく準備後の0を含む。別出口の実績ではない。')


def main() -> None:
    """
    機能: 原結果再読0で、全即cashstopの初期資産と最悪親を必要所有quotesから診断する。
    引数: なし。根が解除済みの診断第二段。
    返り値: None。原市場・金融再実行・元PAIR/legcache読取は0。
    """
    payload=(HERE/'完成結果の同bytes保全.json').read_bytes();assert hashlib.sha256(payload).hexdigest()==EXPECTED
    result=json.loads(payload);cols={k:{n:i for i,n in enumerate(v)} for k,v in result['columns'].items()}
    parents=[]
    for ep in result['episodes']:
        for row in ep['parents']:
            value={name:row[i] for name,i in cols['parents'].items()}
            if value['complete']==1:
                parents.append(dict(value,session=ep['session'],method=ep['method']))
    paired=[p for p in parents if p['filled_legs']==2]
    sessions=sorted({p['session'] for p in paired})
    meta_path=BASE/'入力目録.json';meta=json.loads(meta_path.read_text(encoding='utf8'))
    lookup={(v['session'],v['symbol']):v for v in meta['inputs']}
    wanted=[lookup[scene,symbol] for scene in sessions for symbol in SYMBOLS]
    save(HERE/'共同snapshotと全即停止親の必要quotes読取計画.json',dict(全合格=True,result_SHA256=EXPECTED,
        inputs=wanted,input_manifest_SHA256=hashlib.sha256(meta_path.read_bytes()).hexdigest(),
        個数=len(wanted),各所有NPZ読取=1,取出列=['row','time','last','bid','ask'],
        詳細例='純損失上位から同じ実入退出/数量の重複を除く最大4親。',
        不変判定='予約δ変化が小さい方の1観測T残差変化の10%以下。両Last完全不変も別count。',
        原市場読取=0,金融再生=0,原結果追加読取=0,PAIR_legcache読取=0))
    worst=[];seen=set()
    for p in sorted(parents,key=lambda v:v['net']):
        key=(p['session'],p['entry_time_nk'],p['entry_time_top'],p['side_nk'],p['target_quantity_nk'],p['target_quantity_top'])
        if key not in seen:worst.append(p);seen.add(key)
        if len(worst)==4:break
    selected={(p['method'],p['session'],p['parent']) for p in worst}
    stats=[];examples=[];logs=[]
    for scene in sessions:
        material={}
        for symbol in SYMBOLS:
            item=lookup[scene,symbol];path=ROOT/item['owned_path'];data=path.read_bytes()
            assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['SHA256']
            copy=HERE/'owned_inputs'/symbol/(scene+'.npz');copy.parent.mkdir(parents=True,exist_ok=True);assert not copy.exists();copy.write_bytes(data)
            with np.load(BytesIO(data),allow_pickle=False) as saved:
                q={name:saved['quotes__'+name].copy() for name in ('row','time','last','bid','ask')}
            assert np.all(np.diff(q['row'])>0) and np.all(np.diff(q['time'])>=0)
            material[symbol]=q;logs.append(dict(session=scene,symbol=symbol,path=item['owned_path'],SHA256=item['SHA256'],reads=1))
        for p in (v for v in parents if v['session']==scene):
            if p['filled_legs']==2:
                init=initial(p,material)
                immediate=p['reason']==3 and p['exit_decision_time']==init['time']
                if immediate:
                    assert init['net_below_budget'] and not init['at_or_beyond_extreme'] and not init['at_or_beyond_center']
                stats.append(dict(method=p['method'],session=scene,parent=p['parent'],net=p['net'],reason=p['reason'],
                                  immediate_cashstop=immediate,initial=init))
            if (p['method'],scene,p['parent']) in selected:
                ep=next(v for v in result['episodes'] if v['method']==p['method'] and v['session']==scene)
                orders=[{name:row[i] for name,i in cols['orders'].items()} for row in ep['orders'] if row[cols['orders']['parent']]==p['parent']]
                prep=next(({name:row[i] for name,i in cols['preparations'].items()} for row in ep['preparations'] if row[0]==p['preparation_id']),None)
                assert prep and p['prepare_time']<p['confirmation_clock_1']<p['confirmation_clock_2']==p['decision_time']
                stop={symbol:snapshot(material[symbol],p['exit_decision_time']) for symbol in SYMBOLS}
                sd=math.log(stop['NK225']['last'])-p['beta']*math.log(stop['TOPIX']['last'])-p['center']
                examples.append(dict(parent=p,preparation=prep,orders=orders,initial=initial(p,material) if p['filled_legs']==2 else None,
                    exit_snapshot=stop,exit_delta=sd,path=path_extremes(p,material,orders),
                    times={k:iso(p[k]) for k in ('prepare_time','confirmation_clock_1','confirmation_clock_2','exit_decision_time')}))
    summary=[]
    for spec in result['specs']:
        own=[v for v in stats if v['method']==spec['id']];immediate=[v for v in own if v['immediate_cashstop']]
        same=[v for v in immediate if v['initial']['same_Last_as_reserve']]
        near=[v for v in immediate if v['initial']['delta_nearly_unchanged']]
        summary.append(dict(method=spec['id'],paired=len(own),immediate=len(immediate),immediate_net=sum(v['net'] for v in immediate),
            immediate_same_Last=len(same),same_Last_net=sum(v['net'] for v in same),immediate_nearly_unchanged_delta=len(near),
            nearly_unchanged_net=sum(v['net'] for v in near),initial_cash_budget_breach=sum(v['initial']['net_below_budget'] for v in own),
            stop_margin_less_than_NK1T=sum(v['initial']['margin_in_NK_observed_ticks']<1 for v in own),
            stop_margin_less_than_TOP1T=sum(v['initial']['margin_in_TOP_observed_ticks']<1 for v in own)))
    save(HERE/'初期spread清算と固定極値の幅及び最悪四親の保存診断.json',dict(全合格=True,result_SHA256=EXPECTED,
        summary=summary,parents=stats,examples=examples,read_log=logs,原市場読取=0,金融再生=0,原結果追加読取=0,
        留保='全8を別条件で記述。即停止を削った救済PLやspread込み予算へ変えた実績ではない。同clockは共同snapshot、真受信順は未証明。'))
    print(json.dumps({'summary':summary,'examples':len(examples),'owned_NPZ_reads':len(logs)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
