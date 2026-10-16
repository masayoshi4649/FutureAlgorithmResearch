"""十分に観測できた新規公開候補だけで、強い逆票を拒否する。"""

import numpy as np


def verdict(value: dict, mode: str) -> tuple[bool,int]:
    """
    機能: 当時既知かつ方向票二以上の候補に、元の逆票閾値だけを適用する。
    引数: value(dict)は保存votes.measure値、mode(str)はKNOWN_VETO又は人工対照CONFIRM/VETO。
    返り値: tuple[bool,int]は許可と理由。未知/票不足を支持ありへ補完しない。
    """
    assert mode in ('KNOWN_VETO','CONFIRM','VETO')
    if not value['known']:
        return (True,0) if mode=='VETO' else (False,100+int(value['reason']))
    if value['direction_votes']<2:
        return (True,0) if mode=='VETO' else (False,200)
    balance=value['balance'];assert balance is not None and np.isfinite(balance)
    if mode=='CONFIRM':return (True,0) if balance>=.25 else (False,201)
    return (False,202) if balance<=-.25 else (True,0)


def mask(feed: np.ndarray, count: int, features: dict, mode: str) -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 紙上feedの新規公開原行にだけ判定し、後続影feedを削らず機械へ渡す。
    引数: feed(ndarray[F,10])、count(int)、features(dict[int,dict])、mode(str)は当時素材と政策。
    返り値: tuple[ndarray[bool],ndarray[int32]]は全normal行のmaskと拒否理由。待機/保有判断へ流用しない。
    """
    accepted=np.ones(count,bool);reason=np.zeros(count,np.int32)
    for entry in feed[feed[:,7]==1]:
        row=int(entry[0]);assert 0<=row<count and row in features
        accepted[row],reason[row]=verdict(features[row],mode)
    return accepted,reason
