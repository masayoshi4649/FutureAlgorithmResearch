"""元E01公開の当時取引更新代理だけで新規採否を決める。"""

import numpy as np


def verdict(value: dict, mode: str) -> tuple[bool,int]:
    """
    機能: 既知2票以上の方向釣合いから公開時だけの採否を返す。
    引数: value(dict)は修正済みvotes.measure、mode(str)はCONFIRM/VETO。
    返り値: tuple[bool,int]は許可と理由。未知はVETOで拒否しない。
    """
    assert mode in ('CONFIRM','VETO')
    if not value['known']:
        return (False,100+int(value['reason'])) if mode=='CONFIRM' else (True,0)
    if value['direction_votes']<2:
        return (False,200) if mode=='CONFIRM' else (True,0)
    balance=value['balance'];assert balance is not None
    if mode=='CONFIRM':return (True,0) if balance>=.25 else (False,201)
    return (False,202) if balance<=-.25 else (True,0)


def mask(feed: np.ndarray, count: int, features: dict, mode: str) -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 紙上feed新規公開行にのみ確認を加え、後の返済feedを削らない。
    引数: feed(ndarray[F,10])、count(int)、features(dict[int,dict])、mode(str)。
    返り値: tuple[ndarray[bool],ndarray[int32]]はnormal行の採否と拒否理由。
    """
    accepted=np.ones(count,bool);reason=np.zeros(count,np.int32)
    for entry in feed[feed[:,7]==1]:
        row=int(entry[0]);assert 0<=row<count and row in features
        accepted[row],reason[row]=verdict(features[row],mode)
    return accepted,reason
