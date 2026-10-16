"""二つの保存cacheを厳密に結び、当時の紙上方向と現在窓の資格だけを測る。"""

from collections import Counter
import math

import numpy as np

import price_features

SYMBOLS=('TOPIX','NK225')
WINDOWS=('10','30','60')
CAP={'TOPIX':10,'NK225':20}
MULTIPLIER={'TOPIX':1000.,'NK225':10.}
FEE={'TOPIX':(209,5),'NK225':(11,1)}
VOLUME_THRESHOLD={'TOPIX':.5,'NK225':.25}
PROFILES=('VOL_SELECTED','PRICE_BOTH','VOL_SELECTED_PRICE_BOTH')


def equal(left: object,right: object,label: str) -> None:
    """
    機能: 型・shapeと保存欠測位置を含め、二つの同原行値を照合する。
    引数: left/right(object)、label(str) は値と検査名。
    返り値: None。不一致はAssertionErrorとし別rowへ差替えない。
    """
    if isinstance(left,np.ndarray) or isinstance(right,np.ndarray):
        assert isinstance(left,np.ndarray) and isinstance(right,np.ndarray),label
        assert left.shape==right.shape and left.dtype==right.dtype,label
        np.testing.assert_array_equal(left,right,err_msg=label)
    else:assert left==right,label


def validate_public(account: dict,votes: dict,row: int,side: int,window: str) -> None:
    """
    機能: 公開scalar票と全normal票を、未知debug・既知零票・符号一回まで照合する。
    引数: account/votes(dict)、row/side(int)、window(str) は同原行の公開と窓。
    返り値: None。欠測基準seqや最後の実方向票を推定しない。
    """
    value=account['trade_features'][window][row];r=account['record'];mapping=account['mapping']
    assert value['window_seconds']==int(window)
    assert bool(votes['known'][row])==bool(value['known']) and int(votes['reason'][row])==int(value['reason'])
    assert value['candidate_raw_row']==int(mapping[row]) and value['candidate_raw_seq']==int(r['seq'][row])
    assert value['candidate_price_time_s']==float(r['time_s'][row])
    assert value['cutoff_price_time_s']==float(r['time_s'][row])-int(window)
    for name in ('reference_raw_row','first_vote_raw_row'):
        expected=-1 if value[name] is None else int(value[name])
        assert int(votes[name][row])==expected,name
    up=int(votes['up_votes'][row]);down=int(votes['down_votes'][row]);total=up+down
    assert up==int(value['measured_up_votes']) and down==int(value['measured_down_votes'])
    if value['known']:
        assert value['up_votes']==up and value['down_votes']==down and value['direction_votes']==total
        if total:
            assert math.isfinite(float(votes['balance'][row]))
            assert math.isclose(side*float(votes['balance'][row]),value['balance'],rel_tol=0.,abs_tol=1e-12)
        else:assert value['balance'] is None and np.isnan(votes['balance'][row])
    else:
        assert all(value[name] is None for name in ('up_votes','down_votes','direction_votes','balance'))
        assert np.isnan(votes['balance'][row])


def strict_join(gate: dict,exit_packet: dict) -> dict:
    """
    機能: 同sessionのrecord・両BBO・原行map・各窓・公開票を全一致させる。
    引数: gate/exit_packet(dict) は各一読の保存TradeGate/TradeExit。
    返り値: dict は検査数。型や列が不足すれば診断前に停止する。
    """
    assert gate['schema_version']==exit_packet['schema_version']==1
    assert gate['session']==exit_packet['session'] and set(gate['accounts'])==set(exit_packet['accounts'])==set(SYMBOLS)
    checks=Counter()
    for symbol in SYMBOLS:
        a=gate['accounts'][symbol];b=exit_packet['accounts'][symbol]
        assert a['symbol']==b['symbol']==symbol
        r,q=a['record'],a['quotes'];n=len(r['price']);assert n>0
        for name in ('price','seq','time_s','start','end','limit','tick'):
            equal(r[name],b['record'][name],symbol+' record '+name);checks['record全項目一致']+=1
        for name in ('bid','ask','quote_valid','seq','time_s'):
            equal(q[name],b['quotes'][name],symbol+' quote '+name);checks['quote全項目一致']+=1
        for name in ('seq','time_s'):equal(r[name],q[name],symbol+' record/quote '+name)
        assert all(len(r[name])==n for name in ('price','seq','time_s'))
        assert all(len(q[name])==n for name in ('bid','ask','quote_valid','seq','time_s'))
        assert np.all(np.isfinite(r['time_s'])) and np.all(r['time_s'][1:]>=r['time_s'][:-1])
        assert np.issubdtype(r['seq'].dtype,np.integer) and np.all(r['seq'][1:]>r['seq'][:-1])
        mapping=a['mapping'];assert mapping.shape==(n,) and np.issubdtype(mapping.dtype,np.integer)
        assert np.all(mapping>=0) and np.all(mapping[1:]>mapping[:-1])
        for name in ('quiet','quiet_force'):assert a[name].shape==(n,) and a[name].dtype==np.dtype(bool)
        feed=a['feed'];assert feed.ndim==2 and feed.shape[1]==10 and np.all(np.isfinite(feed))
        assert np.all(feed[:,0]==np.floor(feed[:,0])) and np.all((feed[:,0]>=0)&(feed[:,0]<n))
        assert np.all(feed[1:,0]>=feed[:-1,0])
        public=feed[feed[:,7]==1];assert len(set(public[:,0]))==len(public)
        assert set(b['votes'])==set(WINDOWS) and set(a['trade_features'])==set(WINDOWS)
        for window in WINDOWS:
            v=b['votes'][window]
            for name in ('known','reason','up_votes','down_votes','balance','reference_raw_row','first_vote_raw_row','candidate_raw_row','candidate_raw_seq','candidate_price_time_s'):
                assert isinstance(v[name],np.ndarray) and v[name].shape==(n,),name
            equal(v['candidate_raw_row'],mapping,symbol+' candidate/map')
            equal(v['candidate_raw_seq'],r['seq'],symbol+' candidate/seq')
            equal(v['candidate_price_time_s'],r['time_s'],symbol+' candidate/clock')
            assert v['known'].dtype==np.dtype(bool) and np.all(v['known']==(v['reason']==0))
            assert np.all(v['up_votes']>=0) and np.all(v['down_votes']>=0)
            total=v['up_votes'].astype(np.int64)+v['down_votes'];usable=v['known']&(total>0)
            assert np.all(np.isnan(v['balance'][~usable]))
            np.testing.assert_allclose(v['balance'][usable],(v['up_votes'][usable].astype(float)-v['down_votes'][usable])/total[usable],atol=0.,rtol=0.)
            assert set(a['trade_features'][window])=={int(o[0]) for o in public}
            for order in public:
                row,side=int(order[0]),int(order[3]);assert side in (-1,1)
                validate_public(a,v,row,side,window);checks['公開窓scalar全normal一致']+=1
        checks['商品原行資格照合']+=1
    return dict(checks)


def paper_state(account: dict) -> dict:
    """
    機能: 当行までの紙上feedを順番に適用し、方向・残量・公開ATRを作る。
    引数: account(dict) は変更しない保存口座。
    返り値: dict は全normal長の紙上状態。実UID/busy/勝敗を作らない。
    """
    n=len(account['record']['price']);feed=account['feed'];pointer=0;cid=-1;held=0;price=np.nan;atr=np.nan;origin=-1
    result={name:np.full(n,-1,np.int64) for name in ('paper_parent','origin_row','direction_start_row')}
    result.update(direction=np.zeros(n,np.int8),remaining=np.zeros(n,np.int64),paper_price=np.full(n,np.nan),paper_atr=np.full(n,np.nan),
                  original=np.zeros(n,bool),withdrawn_same_row=np.zeros(n,bool))
    previous=(0,-1);begin=-1
    for row in range(n):
        original=False;withdrawn=False
        while pointer<len(feed) and int(feed[pointer,0])==row:
            order=feed[pointer];pointer+=1;s=int(order[3]);qty=int(order[4]);parent=int(order[2]);new=int(order[7])
            assert s in (-1,1) and qty>0 and qty==order[4] and parent==order[2] and new in (0,1)
            if new:
                assert held==0;cid=parent;held=s*qty;price=float(order[5]);atr=float(order[9]);origin=row
                original=True;withdrawn=False
            else:
                assert cid==parent and s*held<0 and qty<=abs(held)
                held+=s*qty
                if original:withdrawn=True
        side=1 if held>0 else -1 if held<0 else 0
        key=(side,cid)
        if key!=previous:begin=row;previous=key
        result['paper_parent'][row]=cid;result['direction'][row]=side;result['remaining'][row]=abs(held)
        result['origin_row'][row]=origin;result['direction_start_row'][row]=begin
        result['paper_price'][row]=price;result['paper_atr'][row]=atr;result['original'][row]=original;result['withdrawn_same_row'][row]=withdrawn
    assert pointer==len(feed)
    return result


def observe(account: dict,current_volume: dict,price: dict,state: dict) -> dict:
    """
    機能: 現在票と市場資格を別flagにし、紙上方向へunsigned票を一度向ける。
    引数: account/current_volume/price/state(dict) は同原行口座と現在状態。
    返り値: dict は重複資格・現在profile。実busy/場停止/FAK成立は未測。
    """
    r,q=account['record'],account['quotes'];s=account['symbol'];d=state['direction'];t=r['time_s'];n=len(t)
    good=q['quote_valid']&np.isfinite(t)&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])
    usable=good&price['own']['normal']&np.isfinite(r['price'])&(r['price']>0)
    active=d!=0;period=(t>=r['start']+300.)&(t<r['limit']-300.)
    quiet=account['quiet']|account['quiet_force'];deadline=t>=r['limit']
    paper_ok=np.isfinite(state['paper_price'])&(state['paper_price']>0)&np.isfinite(state['paper_atr'])&(state['paper_atr']>0)
    spread=q['ask']-q['bid'];quote=np.where(d>0,q['ask'],q['bid']);cap=CAP[s];mult=MULTIPLIER[s];num,den=FEE[s]
    cost=spread*cap*mult+2*(cap*num//den);allowance_budget=.5*quote*cap*mult*.00075
    cost_ok=good&np.isfinite(cost)&np.isfinite(allowance_budget)&(cost<=allowance_budget)
    v=current_volume;count=v['up_votes'].astype(np.int64)+v['down_votes'];signed=d*v['balance']
    volume=v['known']&(count>=2)&np.isfinite(signed)&(signed>=VOLUME_THRESHOLD[s])
    own=price['own'];pk=price['peer_known'];pc=price['peer_count'];pb=price['peer_balance']
    price_ok=own['known']&pk&(own['count']>=2)&(pc>=2)&(d*own['balance']>=.25)&(d*pb>=.25)
    strong=own['known']&pk&(own['count']>=2)&(pc>=2)&(d*own['balance']>=.75)&(d*pb>=.75)
    market=active&~quiet&~deadline&period&usable&paper_ok&cost_ok
    flags=dict(paper_active=active,quiet=quiet,deadline=deadline,period_ok=period,usable=usable,paper_context_ok=paper_ok,cost_ok=cost_ok,
               volume_known=v['known'],volume_min2=count>=2,volume_signed_ok=np.isfinite(signed)&(signed>=VOLUME_THRESHOLD[s]),
               price_own_known=own['known'],price_peer_known=pk,price_min2=(own['count']>=2)&(pc>=2),price_balance_ok=(d*own['balance']>=.25)&(d*pb>=.25))
    profiles=dict(VOL_SELECTED=volume,PRICE_BOTH=price_ok,VOL_SELECTED_PRICE_BOTH=volume&price_ok)
    eligible={name:market&value for name,value in profiles.items()}
    reason=np.zeros(n,np.int32)
    # ----------------------------------------
    # 111のPUB順序から実stateを要するbusy/場停止だけを除外し、暫定判定と明示する。
    for row in np.flatnonzero(state['original']):
        if quiet[row] or deadline[row]:reason[row]=93 if deadline[row] else 92
        elif state['withdrawn_same_row'][row]:reason[row]=151
        elif not period[row]:reason[row]=153
        elif not active[row] or not usable[row] or not paper_ok[row]:reason[row]=96
        elif not volume[row]:reason[row]=95
        elif not cost_ok[row]:reason[row]=154
    return dict(flags=flags,window_profiles=profiles,eligible=eligible,market=market,volume_count=count,volume_signed=signed,
                allowance=np.where(strong,1,0).astype(np.int8),public_reason_without_actual_state=reason,cost=cost,cost_limit=allowance_budget)


def point(account: dict,current_volume: dict,price: dict,state: dict,observation: dict,row: int) -> dict:
    """
    機能: 当時の一観測を有限値又は明示未測で小保存する。
    引数: account/current_volume/price/state/observation(dict)、row(int) は同normal行。
    返り値: dict はseq/時計/現在票/重複flag。未来価格・実stateは含めない。
    """
    r,q=account['record'],account['quotes'];v=current_volume
    def finite(value: object) -> float|None:
        """
        機能: 非有限の観測をJSONの欠測へ写す。
        引数: value(object) は数値。
        返り値: float|None は有限観測又は未保存/不明。
        """
        return float(value) if np.isfinite(value) else None
    known=bool(v['known'][row]);begin=int(state['direction_start_row'][row])
    return dict(normal_row=row,raw_row=int(account['mapping'][row]),raw_seq=int(r['seq'][row]),price_time_s=float(r['time_s'][row]),
                price_clock='CurrentPriceTime代理。物理受信時刻ではない。',Last=finite(r['price'][row]),bid=finite(q['bid'][row]),ask=finite(q['ask'][row]),
                paper_parent=int(state['paper_parent'][row]),side=int(state['direction'][row]),paper_remaining_quantity=int(state['remaining'][row]),
                direction_age_proxy_seconds=float(r['time_s'][row]-r['time_s'][begin]) if begin>=0 else None,
                volume=dict(known=known,reason=int(v['reason'][row]),up=int(v['up_votes'][row]) if known else None,down=int(v['down_votes'][row]) if known else None,
                            count=int(observation['volume_count'][row]) if known else None,signed_balance=finite(observation['volume_signed'][row]) if known else None,
                            reference_raw_row=int(v['reference_raw_row'][row]),first_window_raw_row=int(v['first_vote_raw_row'][row])),
                price=dict(own_known=bool(price['own']['known'][row]),own_count=int(price['own']['count'][row]),own_balance=finite(price['own']['balance'][row]),
                           peer_known=bool(price['peer_known'][row]),peer_count=int(price['peer_count'][row]),peer_balance=finite(price['peer_balance'][row]),
                           peer_row=int(price['peer_row'][row]),peer_raw_seq=int(price['peer_raw_seq'][row]),peer_age_proxy_seconds=finite(price['peer_price_age_seconds'][row])),
                flags={name:bool(value[row]) for name,value in observation['flags'].items()},
                window_profiles={name:bool(value[row]) for name,value in observation['window_profiles'].items()},
                market_eligible_without_actual_state={name:bool(value[row]) for name,value in observation['eligible'].items()},
                planned_allowance_ticks=int(observation['allowance'][row]),public_cost_yen=finite(observation['cost'][row]),public_cost_limit_yen=finite(observation['cost_limit'][row]),
                busy='未測（実台帳読取0）',session_stop_state='未測（実台帳読取0）',first_goodquote_FAK='未測（実台帳読取0）')


def analyze(gate: dict,exit_packet: dict) -> dict:
    """
    機能: strictjoin後、紙上方向区間ごとの元公開と後の窓資格を小射影する。
    引数: gate/exit_packet(dict) は二つの同場一読packet。
    返り値: dict は区間・PUB・重複分類。normal行数を独立機会や勝率としない。
    """
    checks=strict_join(gate,exit_packet);prices=price_features.pair(gate);accounts={}
    for s in SYMBOLS:
        a=gate['accounts'][s];v=exit_packet['accounts'][s]['votes']['60'];p=prices[s];state=paper_state(a);o=observe(a,v,p,state);t=a['record']['time_s']
        public=[]
        for row in np.flatnonzero(state['original']):
            z=point(a,v,p,state,o,int(row));z['qualification_reason_without_actual_state']=int(o['public_reason_without_actual_state'][row]);public.append(z)
        changed=np.r_[True,(state['direction'][1:]!=state['direction'][:-1])|(state['paper_parent'][1:]!=state['paper_parent'][:-1])]
        starts=np.flatnonzero(changed);ends=np.r_[starts[1:],len(t)];episodes=[]
        for first,end in zip(starts,ends):
            if not state['direction'][first]:continue
            indices=np.arange(first,end);later=indices[indices>state['origin_row'][first]]
            episode=dict(paper_parent=int(state['paper_parent'][first]),side=int(state['direction'][first]),begin=point(a,v,p,state,o,int(first)),
                         last_observed=point(a,v,p,state,o,int(end-1)),normal_observations=int(end-first),price_clock_values=int(len(np.unique(t[first:end]))),
                         completed_paper_direction=end<len(t),later_normal_observations=int(len(later)),profiles={})
            for name in PROFILES:
                mask=o['eligible'][name];selected=later[mask[later]]
                runs=np.flatnonzero(mask[first:end]&~np.r_[False,mask[first:end-1]])+first
                prefix=np.cumsum(mask[first:end],dtype=np.int64)-mask[first:end]
                # 過去観測数は現在rowより前だけ。実新規前の観測数は実state未測なので別扱い。
                episode['profiles'][name]=dict(window_qualified_later_rows=int(o['window_profiles'][name][later].sum()),
                    market_qualified_later_rows=int(len(selected)),qualified_price_clock_values=int(len(np.unique(t[selected]))),
                    continuous_qualified_normal_runs=int(len(runs)),first_later=point(a,v,p,state,o,int(selected[0])) if len(selected) else None,
                    last_later=point(a,v,p,state,o,int(selected[-1])) if len(selected) else None,
                    eligible_observations_before_last_row=int(prefix[-1]),actual_entry_before_count='未測（実台帳0）')
            episodes.append(episode)
        active=state['direction']!=0;cross=Counter()
        for row in np.flatnonzero(active):
            key='vol'+str(int(o['window_profiles']['VOL_SELECTED'][row]))+'_price'+str(int(o['window_profiles']['PRICE_BOTH'][row]))+'_market'+str(int(o['market'][row]))
            cross[key]+=1
        all_normal={}
        # ----------------------------------------
        # 紙上CID外も同じ全normal母集団で両方向を測る。paper ATR/方向は条件にしない。
        common_market=o['flags']['period_ok']&o['flags']['usable']&~o['flags']['quiet']&~o['flags']['deadline']
        total=v['up_votes'].astype(np.int64)+v['down_votes']
        for side,label in ((1,'BUY'),(-1,'SELL')):
            vol=v['known']&(total>=2)&np.isfinite(v['balance'])&(side*v['balance']>=VOLUME_THRESHOLD[s])
            pri=p['own']['known']&p['peer_known']&(p['own']['count']>=2)&(p['peer_count']>=2)&(side*p['own']['balance']>=.25)&(side*p['peer_balance']>=.25)
            values={}
            for name,mask in (('VOL_SELECTED',vol),('PRICE_BOTH',pri),('VOL_SELECTED_PRICE_BOTH',vol&pri)):
                eligible=mask&common_market;selected=np.flatnonzero(eligible)
                values[name]=dict(window_qualified_observations=int(mask.sum()),qualified_with_common_market_observations=int(eligible.sum()),
                    qualified_price_clock_values=int(len(np.unique(t[selected]))),
                    continuous_qualified_normal_runs=int(np.count_nonzero(eligible&~np.r_[False,eligible[:-1]])),
                    window_qualified_during_quiet=int((mask&o['flags']['quiet']).sum()),
                    window_qualified_outside_period=int((mask&~o['flags']['period_ok']).sum()))
            all_normal[label]=dict(normal_observations=len(t),price_clock_values=int(len(np.unique(t))),profiles=values,
                scope='紙上zero/別方向中も含む全normal。正常/静観/新規期間だけ共通市場資格。paper ATR/実busy/場停止/FAKは不適用又は未測。')
        accounts[s]=dict(original_publications=public,paper_direction_episodes=episodes,all_normal_directional_qualification=all_normal,
            counts=dict(original_publications=len(public),paper_direction_episodes=len(episodes),active_normal_observations=int(active.sum()),
                        profile_rows={name:int(o['eligible'][name].sum()) for name in PROFILES},qualification_cross_observations=dict(cross),
                        overlapping_rejection_flags={name:int((active&~mask).sum()) for name,mask in o['flags'].items() if name not in ('quiet','deadline')},
                        quiet_observations=int((active&o['flags']['quiet']).sum()),deadline_observations=int((active&o['flags']['deadline']).sum())),
            limits=['元PUB一回の後も現在窓を測る診断。新アルゴ発注/取引は作らない。','実busy/予約/場停止/FAK失効と当該資格の交差は未測。',
                    '同時計の観測数や連続適格区間は独立機会/勝率の分母ではない。','最後に実発生した方向更新seqは未保存。新根拠発生の保証はしない。'])
    return dict(session=gate['session'],checks=checks,accounts=accounts)
