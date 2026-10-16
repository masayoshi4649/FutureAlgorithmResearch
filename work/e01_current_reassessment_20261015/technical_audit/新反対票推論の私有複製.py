"""保存範囲和から新しい方向代理票の存在下限を証明し、個別新票seqを補完しない。"""

import math


def effective_first(value: dict) -> int:
    """
    機能: canonical全normal票が持つ空範囲sentinelだけを数学上の空区間へ写す。
    引数: value(dict) は既知窓のfirst/candidate rawrowとup/down。
    返り値: int は窓始原row。count正で始行欠落なら推論を停止する。
    """
    first=value['first_vote_raw_row'];end=value['candidate_raw_row'];total=value['up_votes']+value['down_votes']
    assert type(first) is int and type(end) is int and end>=0
    if first==-1:
        assert total==0,'正票数の窓始欠落は空窓へ補完しない'
        return end+1
    assert 0<=first<=end
    return first


def infer(previous: dict,current: dict,side: int) -> dict:
    """
    機能: 同源・同窓・既知連続の二観測から、固定方向の新反対代理票の下限を返す。
    引数: previous/current(dict)、side(int:±1) は過去/現在窓と同じ保有候補方向。
    返り値: dict は存在の証明又は未判定。真の約定量/個別最終新票seqは返さない。
    """
    assert side in (-1,1)
    if not (previous['known'] and current['known'] and current['known_continuously_from_previous']):
        return dict(status='未判定',reason='未知又は未知を跨ぐ観測。debug票を採用せず比較基準を作り直す。',new_opposite_updates_lower_bound=None,exact_new_opposite_updates=None)
    assert previous['source_SHA256']==current['source_SHA256'] and previous['window_seconds']==current['window_seconds']
    assert current['window_seconds'] in (10,30,60)
    for value in (previous,current):
        assert value['reason']==0 and all(type(value[k]) is int and value[k]>=0 for k in ('up_votes','down_votes','candidate_raw_row','candidate_raw_seq'))
        assert math.isfinite(value['candidate_price_time_s'])
    r0,r1=previous['candidate_raw_row'],current['candidate_raw_row'];s0,s1=effective_first(previous),effective_first(current)
    assert r1>r0 and current['candidate_raw_seq']>previous['candidate_raw_seq']
    assert current['candidate_price_time_s']>=previous['candidate_price_time_s'] and s1>=s0
    key='down_votes' if side>0 else 'up_votes';delta=current[key]-previous[key]
    exact=s0==s1
    if exact:assert delta>=0,'同じ窓始・候補前進で範囲和が減る素材は不整合'
    retained_start=max(s1,r0+1)
    return dict(status='同窓始の追加数' if exact else '範囲差による存在下限',fixed_side=side,opposite_counter=key,count_change=delta,
        new_opposite_updates_lower_bound=max(0,delta),exact_new_opposite_updates=delta if exact else None,
        positive_change_proves_new_opposite_update=delta>0,
        zero_or_negative_change_does_not_prove_absence=not exact and delta<=0,
        new_retained_raw_interval=[retained_start,r1] if retained_start<=r1 else [],
        candidate_sequence_bounds=[previous['candidate_raw_seq'],current['candidate_raw_seq']],
        last_actual_new_vote_seq='未保存。candidate上限を新票そのものへ置き換えない。',
        definition='1正usable出来高増更新のLast対直前raw BBOの方向代理。活動量/真攻撃/同一主体/心理ではない。')


def fixture(up: list[int],first: int,end: int,clock: float|None=None) -> dict:
    """
    機能: 純算術の検査に使う小さな既知窓観測を作る。
    引数: up(list[int])、first/end(int)、clock(float|None) は合成票と窓。
    返り値: dict は同じ源/窓の観測。実データを読まない。
    """
    selected=up[first:end+1]
    return dict(known=True,reason=0,known_continuously_from_previous=True,source_SHA256='合成同源',window_seconds=60,
        first_vote_raw_row=first if first<=end else -1,candidate_raw_row=end,candidate_raw_seq=end+100,
        candidate_price_time_s=float(end) if clock is None else clock,up_votes=sum(selected),down_votes=len(selected)-sum(selected))


def self_check() -> dict:
    """
    機能: 重複/非重複窓・空窓・失効・未知・同clockの証明境界を直接集合和で照合する。
    引数: なし。
    返り値: dict は合成検査数。cache/金融/APIは読まない。
    """
    checks=0;nonoverlap=0
    for bits in range(128):
        tape=[(bits>>j)&1 for j in range(7)]
        for r0 in range(5):
            for r1 in range(r0+1,7):
                for s0 in range(r0+2):
                    for s1 in range(s0,r1+2):
                        for side in (-1,1):
                            a,b=fixture(tape,s0,r0),fixture(tape,s1,r1);value=infer(a,b,side)
                            direction=tape if side<0 else [1-v for v in tape]
                            added=sum(direction[max(s1,r0+1):r1+1]);expired=sum(direction[s0:min(s1,r0+1)])
                            assert value['count_change']==added-expired
                            assert 0<=value['new_opposite_updates_lower_bound']<=added
                            if s0==s1:assert value['exact_new_opposite_updates']==added
                            if s1>r0+1:nonoverlap+=1
                            checks+=1
    a=fixture([0,0,1,0],0,1,clock=10.);b=fixture([0,0,1,0],0,3,clock=10.)
    assert infer(a,b,1)['exact_new_opposite_updates']==1;checks+=1
    broken=dict(b,known=False,reason=8);assert infer(a,broken,1)['new_opposite_updates_lower_bound'] is None;checks+=1
    broken=dict(b,known_continuously_from_previous=False);assert infer(a,broken,1)['status']=='未判定';checks+=1
    for field,value in (('source_SHA256','別源'),('window_seconds',30),('candidate_raw_seq',100),('candidate_price_time_s',9.)):
        try:infer(a,dict(b,**{field:value}),1)
        except AssertionError:checks+=1
        else:raise AssertionError('不整合を推論 '+field)
    nonempty=fixture([0,0,1,0],0,3)
    try:infer(a,dict(nonempty,first_vote_raw_row=-1),1)
    except AssertionError:checks+=1
    else:raise AssertionError('正票窓の欠落を補完')
    return dict(全合格=True,算術照合=checks,非重複窓の照合=nonoverlap,scope='保存範囲和からの存在下限だけ。新取引/活動量/将来正答率は未測。',実cache=0,金融=0,API=0)
