"""確定した六点資格を維持し、直近三点と当行実気配の価格位相を分ける。"""

import numpy as np


def at_row(value: dict, index: int, known: bool | None=None, reason: int | None=None) -> dict:
    """
    機能: 旧selection用の六点表示を、元range_priceと同じ算式で返す。
    引数: value(dict)、index(int)、known/reason(bool|int|None)は共有点と原行尾部資格。
    返り値: dictは旧六点表示。不明を未来正常行へ置換しない。
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


def phase(points: np.ndarray, known: np.ndarray, tick: float) -> dict:
    """
    機能: 三点の効率と純進行幅を算出し、強い買1/売-1又は中立0へ分ける。
    引数: points(ndarray[float64,N,3])、known(ndarray[bool,N])、tick(float)は価格三点・資格・呼値。
    返り値: dictはknown/ER/TV/net_ticks/direction。TV0は既知中立であり未知へ変えない。
    """
    assert points.ndim==2 and points.shape[1]==3 and known.dtype==np.bool_ and known.shape==(len(points),)
    assert np.isfinite(tick) and tick>0
    valid=known&np.all(np.isfinite(points)&(points>0),axis=1)
    net=np.full(len(points),np.nan);tv=net.copy();er=net.copy();direction=np.zeros(len(points),np.int8)
    net[valid]=(points[valid,2]-points[valid,0])/tick
    tv[valid]=np.abs(np.diff(points[valid],axis=1)).sum(axis=1)/tick
    er[valid&(tv==0)]=0.
    moving=valid&(tv>0);er[moving]=np.abs(net[moving])/tv[moving]
    strong=valid&(er>=.6)&(np.abs(net)>=2.)
    direction[strong]=np.sign(net[strong]).astype(np.int8)
    return dict(known=valid,net_ticks=net,TV_ticks=tv,ER=er,direction=direction)


def build(packet: dict, symbol: str) -> dict:
    """
    機能: 自己120/60秒六点＋当行実mid、相手strictpast末三点から全normalの短期位相を一回作る。
    引数: packet(dict)、symbol(str)は確定range_price入力と商品名。
    返り値: dictは自己/相手位相と原normal対応。元C/R候補・資格・費用を変更しない。
    """
    record=packet['prepared'][symbol]['record'];measured=packet['measured'][symbol]
    tables=measured['sample_tables'];index=measured['normal_sample_index'];n=len(record['seq'])
    other='NK225' if symbol=='TOPIX' else 'TOPIX'
    assert index.shape==(n,) and measured['raw_mapping'].shape==(n,)
    assert np.all(tables['own']['rows'][index,-1]<=measured['raw_mapping'])
    midpoint=(record['bid']+record['ask'])/2.
    own_points=np.column_stack((tables['own']['midpoint'][index,-3],tables['own']['midpoint'][index,-2],midpoint))
    peer_points=tables['peer']['midpoint'][index,-3:].copy()
    own_known=measured['own_known']&measured['qok']
    peer_known=measured['peer_known'].copy()
    assert np.all(tables['peer']['times'][index[peer_known],-1]<record['time_s'][peer_known])
    own=phase(own_points,own_known,float(record['tick']))
    peer=phase(peer_points,peer_known,float(packet['prepared'][other]['record']['tick']))
    own['points']=own_points;peer['points']=peer_points
    return dict(schema_version=1,normal_rows=n,own=own,peer=peer,
        normal_sample_index=index,raw_mapping=measured['raw_mapping'],
        自己定義='同じ六点の120/60秒端点＋当行実bid/ask中値。自己原row尾部資格と正常気配を維持。',
        相手定義='strictpast六点の120/60/0秒端点。相手呼値、当行自己時計より厳密過去を維持。',
        強い方向='ER=|net|/(|差1|+|差2|)>=0.6かつ|net|>=2呼値。TV0は既知中立。')


def decisions(short: dict, side: int, policy: str) -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 指定R意図へ入口許可と未約定取消を方向別に算出する。
    引数: short(dict)、side(int)、policy(str)は自己相手位相と買1/売-1/3政策。
    返り値: tuple[ndarray[bool],ndarray[bool]]は入口許可、待機取消。ALIGNEDの同方向消失だけでは取消しない。
    """
    assert side in (-1,1) and policy in ('OWN_VETO','BOTH_VETO','ALIGNED')
    own=short['own'];peer=short['peer']
    own_opposite=own['known']&(own['direction']==-side)
    both_opposite=own_opposite&peer['known']&(peer['direction']==-side)
    if policy=='OWN_VETO':return ~own_opposite,own_opposite
    if policy=='BOTH_VETO':return ~both_opposite,both_opposite
    aligned=own['known']&peer['known']&(own['direction']==side)&(peer['direction']==side)
    return aligned,both_opposite


def at_phase(short: dict, row: int) -> dict:
    """
    機能: 入口/約定/取消の当時短期位相を、未知None付きで説明用に抜き出す。
    引数: short(dict)、row(int)は全normal位相と当該行。
    返り値: dictは自己/相手の三点と方向。時刻や未知値を補完しない。
    """
    result={}
    for symbol in ('own','peer'):
        value=short[symbol];known=bool(value['known'][row])
        result[symbol]=dict(known=known,direction=int(value['direction'][row]),
            points=value['points'][row].tolist() if known else [],
            ER=float(value['ER'][row]) if known else None,
            TV_ticks=float(value['TV_ticks'][row]) if known else None,
            net_ticks=float(value['net_ticks'][row]) if known else None)
    return result
