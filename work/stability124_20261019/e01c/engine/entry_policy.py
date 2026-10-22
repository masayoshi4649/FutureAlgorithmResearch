"""同じ当時取引更新代理の釣合いと最少票数だけから全feed用公開maskを作る。"""

import numpy as np
import base_policy
import catalog


def vote(value: dict, threshold: float, min_votes: int=2) -> tuple[bool,int]:
    """
    機能: 既知の当時方向票と釣合いが結果前閾値を満たす場合だけ新規公開を許可する。
    引数: value(dict)、threshold(float)、min_votes(int) は旧票代理・釣合い・最少票数。
    返り値: tuple[bool,int] は許可と拒否理由。未知を方向又は少票へ補完しない。
    """
    assert threshold in (.25,.5) and min_votes == 2
    if not value['known']:return False,100+int(value['reason'])
    if value['direction_votes']<min_votes:return False,200
    balance=value['balance'];assert balance is not None and np.isfinite(balance)
    return (True,0) if balance>=threshold else (False,201)


def mask(account: dict, entry_id: str, peer_account: dict|None=None) -> dict:
    """
    機能: 紙上新規公開行だけに票gateを掛け、元返済と後続候補のfeedを残す。
    引数: account(dict)、entry_id(str)、peer_account(dict|None) は口座・四gate・不使用互換項目。
    返り値: dict は採否bool、拒否int32、全公開系譜。実取引集合の包含は主張しない。
    """
    assert entry_id in catalog.GATES
    count=len(account['record']['price']);accepted=np.ones(count,bool);reasons=np.zeros(count,np.int32)
    features=account['trade_features']['60'];threshold,min_votes=catalog.GATES[entry_id];diagnostics={}
    for order in account['feed'][account['feed'][:,7]==1]:
        row=int(order[0]);side=int(order[3]);assert 0<=row<count and row in features
        ok,reason=vote(features[row],threshold,min_votes);accepted[row]=ok;reasons[row]=reason
        diagnostics[row]=dict(paper_parent=int(order[2]),side=side,vote=features[row],threshold=threshold,
            min_votes=min_votes,accepted=ok,reason=int(reason),price_response=None)
    if entry_id=='G25':
        old=base_policy.mask(account['feed'],count,features,'CONFIRM')
        np.testing.assert_array_equal(accepted,old[0]);np.testing.assert_array_equal(reasons,old[1])
    return dict(accepted=accepted,reasons=reasons,diagnostics=diagnostics,entry_id=entry_id,
        scope='全feedの影・実枚数・busy・再参加は続行。FAK未約定は未来maskに変換しない。')


def allowances(account: dict, strong_threshold: float) -> np.ndarray:
    """
    機能: 新規公開当行の既知票だけから不利許容0/1観測呼値の配列を作る。
    引数: account(dict)、strong_threshold(float) は口座と結果前固定の.75又は1.0。
    返り値: ndarray[int8,N] は公開行だけの許容。未知・票不足は0であり入口資格を救済しない。
    """
    assert strong_threshold in (.75,1.)
    count=len(account['record']['price']);result=np.zeros(count,np.int8)
    for order in account['feed'][account['feed'][:,7]==1]:
        row=int(order[0]);value=account['trade_features']['60'][row]
        if value['known'] and value['direction_votes']>=2:
            balance=value['balance'];assert balance is not None and np.isfinite(balance)
            result[row]=int(balance>=strong_threshold)
    return result
