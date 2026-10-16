"""現在60秒の出来高代理を向け、新票下限と失効を区別する。"""

import numpy as np


def measure(volume: dict,price: dict,symbol: str) -> dict:
    """
    機能: 同源W60のunsigned票・現在価格票から、各方向の資格と新更新下限を作る。
    引数: volume/price(dict)、symbol(str) は同normalの当時観測。
    返り値: dict は資格/区間既知/新up-down下限。未知を活動零と呼ばない。
    """
    n=len(volume['known']);known=volume['known'];up=volume['up_votes'].astype(np.int64);down=volume['down_votes'].astype(np.int64)
    total=up+down;first=volume['first_vote_raw_row'].copy();r=volume['candidate_raw_row'];seq=volume['candidate_raw_seq'];clock=volume['candidate_price_time_s']
    assert np.all((first>=0)|((first==-1)&(total==0)|~known))
    first=np.where(first>=0,first,r+1);interval=np.zeros(n,bool)
    if n>1:interval[1:]=known[1:]&known[:-1]&(r[1:]>r[:-1])&(seq[1:]>seq[:-1])&(clock[1:]>=clock[:-1])&(first[1:]>=first[:-1])
    du=np.r_[0,np.diff(up)];dd=np.r_[0,np.diff(down)];same=np.r_[False,first[1:]==first[:-1]]&interval
    assert not np.any(same&((du<0)|(dd<0)))
    new_up=np.where(interval,np.maximum(0,du),0);new_down=np.where(interval,np.maximum(0,dd),0)
    valid=known&(total>=2)&np.isfinite(volume['balance']);threshold=.5 if symbol=='TOPIX' else .25
    own=price['own'];price_known=own['known']&price['peer_known']
    volume_gate=np.column_stack((valid&(volume['balance']>=threshold),valid&(-volume['balance']>=threshold)))
    price_gate=np.column_stack([price_known&(own['count']>=2)&(price['peer_count']>=2)&(side*own['balance']>=.25)&(side*price['peer_balance']>=.25) for side in (1,-1)])
    strong=np.column_stack([price_known&(own['count']>=2)&(price['peer_count']>=2)&(side*own['balance']>=.75)&(side*price['peer_balance']>=.75) for side in (1,-1)])
    return dict(volume_known=known,price_known=price_known,volume_gate=volume_gate,price_gate=price_gate,strong=strong,
        interval_known=interval,new_up_lower=new_up,new_down_lower=new_down,same_first_exact=same,
        definition='隣接normalが両knownかつ単調範囲の正差。窓始不変なら追加数exact、前進なら下限。0/負差は新票なしの証明でない。')
