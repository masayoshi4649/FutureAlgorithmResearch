"""公開候補に限定しない、当時normal全行の取引更新代理を測る。"""

import numpy as np


def all_normal(raw: dict, ctx: dict, mapping: np.ndarray, window: int) -> dict:
    """
    機能: 修正votes.measureの窓内資格と票をnormal全行へ同原行で投影する。
    引数: raw/ctx(dict)、mapping(ndarray[int64])、window(int)は原行と代理窓。
    返り値: dict[str,ndarray]は既知/理由/買売票/方向釣合い/系譜。sideは実残玉から後で掛ける。
    """
    rows=mapping;assert np.issubdtype(rows.dtype,np.integer) and np.all((rows>=0)&(rows<len(raw['raw_seq'])))
    pt=ctx['price_times'];stamp=pt[rows];public=ctx['public_rows'];times=ctx['public_times'];n=len(rows)
    reason=np.zeros(n,np.uint8);finite=np.isfinite(stamp)
    position=np.searchsorted(times,stamp-window,side='right')-1
    baseline=np.full(n,-1,np.int64);first=rows+1
    if len(public):
        available=position>=0;baseline[available]=public[position[available]]
        available&=baseline<=rows;reason[~available]|=1
        next_index=position+1;has_next=(next_index>=0)&(next_index<len(public))
        first[has_next]=np.minimum(public[next_index[has_next]],rows[has_next]+1)
        baseline[~available]=-1
    else:reason[:]|=1
    # ----------------------------------------
    # 不明走査も票もCurrentPriceTime>cutの最初原行から。当時seq後の同clock後半を混ぜない。
    for bit in (4,8,16):
        prefix=ctx['bad_prefix'][str(bit)]
        reason[(prefix[rows+1]-prefix[first])>0]|=bit
    available=baseline>=0
    safe=np.maximum(baseline,0)
    reason[available&(~np.isfinite(pt[safe])|ctx['clock_reverse'][safe])]|=4
    reason[~finite]=2
    up=(ctx['up_prefix'][rows+1]-ctx['up_prefix'][first]).astype(np.int32)
    down=(ctx['down_prefix'][rows+1]-ctx['down_prefix'][first]).astype(np.int32)
    # 非有限候補clockはscalarの早期UNKNOWNと同じく、未来に依存する窓系譜を作らない。
    up[~finite]=0;down[~finite]=0;baseline[~finite]=-1;first[~finite]=rows[~finite]+1
    total=up.astype(np.int64)+down;known=reason==0;balance=np.full(n,np.nan)
    usable=known&(total>0);balance[usable]=(up[usable].astype(float)-down[usable])/total[usable]
    return dict(known=known,reason=reason,up_votes=up,down_votes=down,balance=balance,
        reference_raw_row=baseline,first_vote_raw_row=np.where(first<=rows,first,-1).astype(np.int64),
        candidate_raw_row=rows,candidate_raw_seq=raw['raw_seq'][rows],candidate_price_time_s=stamp)
