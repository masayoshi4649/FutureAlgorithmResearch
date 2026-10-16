"""公開当行の票と保存normal両気配端点だけから、全feed用の新規maskを作る。"""

import numpy as np
import daily
import base_policy
import catalog


def vote(value: dict, threshold: float) -> tuple[bool,int]:
    """
    機能: 既知二方向票以上に限り、意図方向への釣合いが固定閾値以上なら許可する。
    引数: value(dict)、threshold(float) は旧票代理と結果前固定の釣合い。
    返り値: tuple[bool,int] は新規許可と拒否理由。UNKNOWNは方向へ補完しない。
    """
    assert threshold in (.25,.5,.75)
    if not value['known']:return False,100+int(value['reason'])
    if value['direction_votes']<2:return False,200
    balance=value['balance'];assert balance is not None and np.isfinite(balance)
    return (True,0) if balance>=threshold else (False,201)


def clock_account(account: dict) -> dict:
    """
    機能: 保存normalの原seq・価格代理時計と正常BBOを、端点選択用に確認する。
    引数: account(dict) は一場の商品口座。生原行は読まない。
    返り値: dict は価格端点列。同normal間に消えたraw経路の資格を保証しない。
    """
    record,quotes=account['record'],account['quotes'];t=quotes['time_s'];seq=quotes['seq']
    np.testing.assert_array_equal(record['time_s'],t);np.testing.assert_array_equal(record['seq'],seq)
    assert t.ndim==seq.ndim==1 and len(t)>0 and np.all(np.isfinite(t))
    assert np.all(np.diff(t)>=0) and np.all(np.diff(seq)>0)
    normal=daily.normal_mask(quotes)&(t>=record['start'])&(t<=record['limit'])
    rows=np.flatnonzero(normal)
    return dict(time=t,seq=seq,bid=quotes['bid'],ask=quotes['ask'],normal=normal,tick=record['tick'],
        normal_rows=rows,normal_times=t[rows])


def response(own: dict, peer: dict|None, row: int, side: int, entry_id: str) -> dict:
    """
    機能: 自己公開当行又はstrict過去相手と、十秒前の最後normal端点を比較する。
    引数: own/peer(dict/None)、row/side(int)、entry_id(str) は確認済み価格列と候補。
    返り値: dict は既知性、採否、端点系譜。未来normalへ置換しない。
    """
    assert entry_id in ('SELF10','PEER10') and side in (1,-1)
    assert 0<=row<len(own['time']);clock=float(own['time'][row]);source=own if entry_id=='SELF10' else peer
    assert source is not None
    unknown=dict(known=False,accepted=False,reason='端点不明',window_seconds=10,
        model='保存normal端点の価格代理時計模型。全raw経路・真の板受信先後は未保証。',
        candidate_row=row,candidate_raw_seq=int(own['seq'][row]),candidate_price_time_s=clock,
        start_row=None,end_row=None,start_raw_seq=None,end_raw_seq=None,start_age=None,end_age=None,
        bid_change_ticks=None,ask_change_ticks=None)
    normal_rows,normal_times=source['normal_rows'],source['normal_times']
    end_position=int(np.searchsorted(normal_times,clock,side='left')-1)
    start_position=int(np.searchsorted(normal_times,clock-10.,side='right')-1)
    end=row if entry_id=='SELF10' else (-1 if end_position<0 else int(normal_rows[end_position]))
    start=-1 if start_position<0 else int(normal_rows[start_position])
    if start<0 or end<0 or start>=end:return unknown
    if entry_id=='SELF10':assert end==row and source['seq'][start]<own['seq'][row]
    assert source['seq'][start]<source['seq'][end]
    end_age=clock-float(source['time'][end]);start_age=clock-10.-float(source['time'][start])
    if not (0<=start_age<=15 and 0<=end_age<=15):return unknown
    if entry_id=='PEER10' and not end_age>0:return unknown
    if not source['normal'][start] or not source['normal'][end]:return unknown
    db=(float(source['bid'][end])-float(source['bid'][start]))/source['tick']
    da=(float(source['ask'][end])-float(source['ask'][start]))/source['tick']
    return dict(unknown,known=True,accepted=side*db>=1. and side*da>=1.,reason='価格応答確認',
        start_row=start,end_row=end,start_raw_seq=int(source['seq'][start]),end_raw_seq=int(source['seq'][end]),
        start_price_time_s=float(source['time'][start]),end_price_time_s=float(source['time'][end]),
        start_age=start_age,end_age=end_age,bid_change_ticks=db,ask_change_ticks=da)


def mask(account: dict, entry_id: str, peer_account: dict|None=None) -> dict:
    """
    機能: 全紙上新規公開行だけの採否を作り、返済feed・影・後続候補を保存する。
    引数: account(dict)、entry_id(str)、peer_account(dict|None) は元口座と五入口。
    返り値: dict はnormal採否bool列、理由int32列、公開ごとの当時系譜。
    """
    assert entry_id in catalog.entry_ids();count=len(account['record']['price'])
    accepted=np.ones(count,bool);reasons=np.zeros(count,np.int32);diagnostics={}
    features=account['trade_features']['60'];own=peer=None
    if entry_id in ('SELF10','PEER10'):
        own=clock_account(account)
        if entry_id=='PEER10':peer=clock_account(peer_account)
    threshold={'CONFIRM25':.25,'CONFIRM50':.5,'CONFIRM75':.75}.get(entry_id,.25)
    for order in account['feed'][account['feed'][:,7]==1]:
        row=int(order[0]);side=int(order[3]);assert 0<=row<count and row in features
        ok,reason=vote(features[row],threshold);price=None
        if ok and own is not None:
            price=response(own,peer,row,side,entry_id)
            ok=price['accepted'];reason=0 if ok else (301 if price['known'] else 300)
        accepted[row]=ok;reasons[row]=reason
        diagnostics[row]=dict(paper_parent=int(order[2]),side=side,vote=features[row],threshold=threshold,
            accepted=ok,reason=int(reason),price_response=price)
    if entry_id=='CONFIRM25':
        old=base_policy.mask(account['feed'],count,features,'CONFIRM')
        np.testing.assert_array_equal(accepted,old[0]);np.testing.assert_array_equal(reasons,old[1])
    return dict(accepted=accepted,reasons=reasons,diagnostics=diagnostics,entry_id=entry_id,
        scope='maskの包含は実取引集合の包含を意味しない。全feedで実q・busy・次気配・再参加を機械再生する。')
