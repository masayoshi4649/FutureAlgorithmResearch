"""原行の公表出来高増とLast対直前BBOを、数量加重なしの当時方向票へ分離する。"""

import numpy as np


REASONS={0:'既知',1:'窓の観測開始不足',2:'候補価格代理時計又は原行不明',4:'窓内seq又は価格時計不正',
    8:'窓内出来高差資格不明又はreset',16:'正出来高増行のLast又は直前BBO不明'}


def context(raw: dict) -> dict:
    """
    機能: 全原行のhighwater・出来高資格・1行1方向票を、損益なしで接頭累計する。
    引数: raw(dict)は不変44列NPZの必要原列。
    返り値: dictは方向票/未知理由の接頭配列とfirst-newmax公開行。量を方向へ丸ごと配賦しない。
    """
    seq,pt=raw['raw_seq'],raw['price_time_s'];n=len(seq)
    finite=np.isfinite(pt);maximum=np.maximum.accumulate(np.where(finite,pt,-np.inf))
    reverse=finite&(pt<maximum)
    common=~finite|reverse
    if n>1:
        common[1:]|=(seq[1:]!=seq[:-1]+1)|~finite[:-1]
    common[0:1]=True
    volume=(raw['volume_delta_usable']&(raw['volume_reset_reason']==0))
    known_increase=volume&np.isfinite(raw['volume_delta'])&(raw['volume_delta']>0)
    last_ok=np.isfinite(raw['last'])&(raw['last']>0)
    prior_bid=np.r_[np.nan,raw['bid'][:-1]];prior_ask=np.r_[np.nan,raw['ask'][:-1]]
    prior_quote=np.isfinite(prior_bid)&np.isfinite(prior_ask)&(prior_bid>0)&(prior_ask>prior_bid)
    proxy_ok=known_increase&last_ok&prior_quote&~common
    direction=np.zeros(n,np.int8)
    direction[proxy_ok&(raw['last']>=prior_ask)]=1
    direction[proxy_ok&(raw['last']<=prior_bid)]=-1
    positive=np.isfinite(pt)&((pt>np.r_[-np.inf,maximum[:-1]]))
    public=np.flatnonzero(positive)
    bad=np.zeros(n,np.uint8)
    bad[common]|=4;bad[~volume]|=8
    bad[known_increase&~(last_ok&prior_quote)]|=16
    prefixes={str(bit):np.r_[0,np.cumsum((bad&bit)!=0,dtype=np.int64)] for bit in (4,8,16)}
    up=np.r_[0,np.cumsum(direction==1,dtype=np.int64)];down=np.r_[0,np.cumsum(direction==-1,dtype=np.int64)]
    # ----------------------------------------
    # 同じ代理時計の全原行を当時seqまで数える。未来の同clock後半は公開点へ混ぜない。
    return dict(public_rows=public,public_times=pt[public],bad=bad,bad_prefix=prefixes,
        direction=direction,proxy_known=proxy_ok,known_increase=known_increase,up_prefix=up,down_prefix=down,
        price_times=pt,raw_seq=seq,clock_reverse=reverse)


def measure(raw: dict, ctx: dict, row: int, window: int, side: int) -> dict:
    """
    機能: 候補原行以下の(cTime−W,cTime]取引更新代理票と窓の不明理由を測る。
    引数: raw/ctx(dict)、row/window/side(int)は当時原行・代理秒幅・入口方向。
    返り値: dictは既知/分母/方向釣合いと原seq由来。内側Lastは方向票0、不明を反対票にしない。
    """
    pt=ctx['price_times'];seq=ctx['raw_seq'];reason=0
    if row<0 or row>=len(seq) or not np.isfinite(pt[row]):
        return dict(known=False,reason=2,window_seconds=window,up_votes=None,down_votes=None,direction_votes=None,balance=None,accepted=False)
    stamp=float(pt[row]);cut=stamp-window;public=ctx['public_rows'];times=ctx['public_times']
    position=int(np.searchsorted(times,cut,side='right')-1)
    if position<0 or int(public[position])>row:
        reason|=1;baseline=-1
    else:baseline=int(public[position])
    first=int(public[position+1]) if position+1<len(public) else row+1
    if first>row:first=row+1
    # ----------------------------------------
    # 単調公表源は窓の原行境界だけを指定する。票はfirst行から候補rowまでの全更新。
    start=max(0,baseline+1)
    for bit in (4,8,16):
        prefix=ctx['bad_prefix'][str(bit)]
        if prefix[row+1]-prefix[start]>0:reason|=bit
    # 開始の外側にある基準行は時計自体を確認する。場の最初に架空の前行を要求しない。
    if baseline>=0 and (not np.isfinite(pt[baseline]) or ctx['clock_reverse'][baseline]):reason|=4
    up=int(ctx['up_prefix'][row+1]-ctx['up_prefix'][first])
    down=int(ctx['down_prefix'][row+1]-ctx['down_prefix'][first]);total=up+down
    known=reason==0;balance=side*(up-down)/total if known and total else None
    accepted=bool(known and total>=2 and balance>=.25)
    return dict(known=known,reason=int(reason),window_seconds=window,
        candidate_raw_row=row,candidate_raw_seq=int(seq[row]),candidate_price_time_s=stamp,
        cutoff_price_time_s=cut,reference_raw_row=baseline if baseline>=0 else None,
        reference_raw_seq=int(seq[baseline]) if baseline>=0 else None,
        first_vote_raw_row=first if first<=row else None,last_vote_raw_row=row,
        up_votes=up if known else None,down_votes=down if known else None,direction_votes=total if known else None,
        measured_up_votes=up,measured_down_votes=down,balance=balance,accepted=accepted,
        valid_increase_rows=int(np.count_nonzero(ctx['known_increase'][first:row+1])) if first<=row else 0,
        inside_price_rows=int(np.count_nonzero(ctx['proxy_known'][first:row+1]&(ctx['direction'][first:row+1]==0))) if first<=row else 0,
        underlying_proxy='公表出来高正増を伴うLast対直前raw BBO。1更新1票。真の攻撃注文方向ではない。')


def entry_filter(normal: dict, features: dict, scope: str='R') -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 指定R/C/両方の公開原行だけに当時自己取引更新代理gateを掛ける。
    引数: normal(dict)は元AUTO同値、features(dict[int,dict])は当時row特徴、scope(str:R/C/BOTH)は範囲。
    返り値: tuple[ndarray[bool],ndarray[int32]]は外部入口maskと理由。未対象入口及び待機/保有出口へgateを流用しない。
    """
    n=len(normal['event']);mask=np.ones(n,bool);reasons=np.zeros(n,np.int32)
    assert scope in ('R','C','BOTH')
    family=(normal['entry_families']>0) if scope=='BOTH' else (normal['entry_families']==(2 if scope=='R' else 1))
    for row in np.flatnonzero(family):
        value=features[int(row)];mask[row]=value['accepted']
        reasons[row]=0 if value['accepted'] else 100+int(value['reason']) if not value['known'] else 200 if value['direction_votes']<2 else 201
    return mask,reasons
