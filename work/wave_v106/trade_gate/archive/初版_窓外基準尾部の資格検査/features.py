"""同じ公表六点の値を時計別に共有し、各原行の資格と実反発を分離する。"""

import numpy as np

import common


legacy=common.module('106純価格六点の確定第二観測',common.ROOT/'work/wave_v106/regime_price/features.py')
STATE_NAMES={0:'UNKNOWN',1:'RANGE',2:'TREND_UP',-2:'TREND_DOWN',3:'NEUTRAL'}


def table(raw: dict, ctx: dict, stamps: np.ndarray, tick: float, strictpast: bool) -> dict:
    """
    機能: 固有の自己価格時計ごとにsix first公表点と端点ERを一括測定する。
    引数: raw/ctx(dict)、stamps(ndarray[float])、tick(float)、strictpast(bool)は相手同時計禁止。
    返り値: dictは共有6点値。自己候補末尾の原行資格は後段で各row再確認する。
    """
    pub=ctx['public'];offset=np.array([300.,240.,180.,120.,60.,0.]);requested=stamps[:,None]-offset
    positions=np.searchsorted(pub['times'],requested,side='right')-1
    if strictpast:
        positions[:,-1]=np.searchsorted(pub['times'],stamps,side='left')-1
    available=np.all(positions>=0,axis=1)&np.isfinite(stamps);count=len(stamps)
    rows=np.full((count,6),-1,np.int64);seq=rows.copy();times=np.full((count,6),np.nan);ages=times.copy()
    bid,ask,mids=(times.copy() for _ in range(3));reason=np.zeros(count,np.uint8);reason[~available]=1
    indexes=np.flatnonzero(available)
    if len(indexes):
        selected=pub['rows'][positions[indexes]];observed=pub['times'][positions[indexes]]
        rows[indexes]=selected;seq[indexes]=raw['raw_seq'][selected];times[indexes]=observed
        ages[indexes]=requested[indexes]-observed;bid[indexes]=raw['bid'][selected];ask[indexes]=raw['ask'][selected]
        old=np.any((ages[indexes]<0)|(ages[indexes]>15.),axis=1)
        if strictpast:
            old|=observed[:,-1]>=stamps[indexes]
        reason[indexes[old]]|=2
        valid=(np.isfinite(observed)&(observed>=ctx['start'])&(observed<ctx['limit'])&
            np.isfinite(bid[indexes])&np.isfinite(ask[indexes])&(bid[indexes]>0)&(ask[indexes]>bid[indexes]))
        reason[indexes[~valid.all(axis=1)]]|=4
        bad=(ctx['bad_prefix'][selected[:,-1]+1]-ctx['bad_prefix'][selected[:,0]])>0
        reason[indexes[bad]]|=8
    known=reason==0;net,tv,er,span,high,low,centre,ret=(np.full(count,np.nan) for _ in range(8))
    if np.any(known):
        m=(bid[known]+ask[known])/2.;mids[known]=m
        net[known]=m[:,-1]-m[:,0];tv[known]=np.abs(np.diff(m,axis=1)).sum(axis=1)
        valid_tv=known&(tv>0);er[valid_tv]=np.abs(net[valid_tv])/tv[valid_tv]
        high[known]=m.max(axis=1);low[known]=m.min(axis=1);centre[known]=(high[known]+low[known])/2.
        span[known]=(high[known]-low[known])/tick;ret[known]=net[known]/m[:,0]*10000.
    return dict(stamps=stamps,known=known,reason=reason,rows=rows,raw_seq=seq,times=times,ages=ages,
        midpoint=mids,ER=er,TV=tv,span_ticks=span,high=high,low=low,centre=centre,return_bp=ret)


def at_row(value: dict, index: int, known: bool | None=None, reason: int | None=None) -> dict:
    """
    機能: 共有six点から、旧sampleと同じ小辞書を一候補分だけ返す。
    引数: value(dict)、index(int)、known/reason(bool|int|None)は各rowの尾部資格による上書き。
    返り値: dictは原seq・6点・ER/H/L。UNKNOWNの欠測を0へ補完しない。
    """
    k=bool(value['known'][index]) if known is None else bool(known)
    r=int(value['reason'][index]) if reason is None else int(reason)
    exists=not bool(r&1)
    result=dict(known=k,reason=r,rows=value['rows'][index].tolist() if exists else [],
        raw_seq=value['raw_seq'][index].tolist() if exists else [],times=value['times'][index].tolist() if exists else [],
        midpoint=value['midpoint'][index].tolist() if k else [],ages=value['ages'][index].tolist() if exists else [],
        ER=None,return_bp=None,span_ticks=None,high=None,low=None,centre=None,TV=None)
    if k:
        for name in ('ER','return_bp','span_ticks','high','low','centre','TV'):
            result[name]=float(value[name][index]) if np.isfinite(value[name][index]) else None
    return result


def build(raws: dict, records: dict, symbol: str) -> dict:
    """
    機能: 全normal行の二市場six状態を共有時計で作り、自己raw末尾を毎行再審査する。
    引数: raws/records(dict)、symbol(str)は不変旧原行と正常執行列。
    返り値: dictは観測table・原行別known・境界反発候補。新注文は生成しない。
    """
    other='NK225' if symbol=='TOPIX' else 'TOPIX';record=records[symbol];raw=raws[symbol]
    mapping=raw['execution_to_raw_index'];stamp=record['time_s']
    np.testing.assert_array_equal(raw['raw_seq'][mapping],record['seq'])
    np.testing.assert_array_equal(raw['price_time_s'][mapping],stamp)
    unique,inverse=np.unique(stamp,return_inverse=True);ctx={s:legacy.context(raws[s],start=records[s]['start'],
        limit=records[s]['limit']) for s in (symbol,other)}
    own=table(raw,ctx[symbol],unique,record['tick'],False)
    peer=table(raws[other],ctx[other],unique,records[other]['tick'],True)
    own_reason=own['reason'][inverse].copy();available=(own_reason&1)==0
    positions=np.flatnonzero(available);first=own['rows'][inverse[positions],0];end=own['rows'][inverse[positions],-1]
    assert np.all(end<=mapping[positions]),'自己同時計の未来公表行を選ばない'
    bad=(ctx[symbol]['bad_prefix'][mapping[positions]+1]-ctx[symbol]['bad_prefix'][first])>0
    own_reason[positions[bad]]|=8
    own_known=own_reason==0;peer_known=peer['known'][inverse];both=own_known&peer_known
    n=len(stamp);qok=(record['quote_valid']&np.isfinite(stamp)&np.isfinite(record['bid'])&np.isfinite(record['ask'])&
        (record['bid']>0)&(record['ask']>record['bid']))
    recent=np.maximum.accumulate(np.where(qok,np.arange(n),-1));previous=np.r_[-1,recent[:-1]]
    safe=np.maximum(previous,0)
    up=((previous>=0)&qok&((record['bid']-record['bid'][safe])>=record['tick'])&
        ((record['ask']-record['ask'][safe])>=record['tick']))
    down=((previous>=0)&qok&((record['bid']-record['bid'][safe])<=-record['tick'])&
        ((record['ask']-record['ask'][safe])<=-record['tick']))
    midpoint=(record['bid']+record['ask'])/2.;states={};events={}
    for er in (.2,.4):
        key=str(er);state=np.full(n,0,np.int8);state[both]=3
        ranged=(both&np.isfinite(own['ER'][inverse])&np.isfinite(peer['ER'][inverse])&
            (own['ER'][inverse]<=er)&(peer['ER'][inverse]<=er)&(own['span_ticks'][inverse]>=4)&(peer['span_ticks'][inverse]>=4))
        state[ranged]=1
        positive=both&~ranged&(own['return_bp'][inverse]>=2.)&(peer['return_bp'][inverse]>=2.)
        negative=both&~ranged&(own['return_bp'][inverse]<=-2.)&(peer['return_bp'][inverse]<=-2.)
        state[positive]=2;state[negative]=-2
        lower=(midpoint>=own['low'][inverse])&(midpoint<=own['low'][inverse]+.25*(own['high'][inverse]-own['low'][inverse]))
        upper=(midpoint<=own['high'][inverse])&(midpoint>=own['high'][inverse]-.25*(own['high'][inverse]-own['low'][inverse]))
        event=np.zeros(n,np.int8);event[ranged&qok&lower&up]=1;event[ranged&qok&upper&down]=-1
        assert not np.any(ranged&qok&lower&up&upper&down)
        states[key]=state;events[key]=event
    return dict(sample_tables=dict(own=own,peer=peer),normal_sample_index=inverse.astype(np.int32),
        own_known=own_known,own_reason=own_reason,peer_known=peer_known,qok=qok,previous_normal_row=previous,
        states=states,boundary_events=events,shared_clock_queries=len(unique)*12,
        normal_rows=n,raw_mapping=mapping,field_tail_per_row=True)
