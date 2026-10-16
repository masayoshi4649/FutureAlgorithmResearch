"""合成原行だけでstrictjoin・同時計上限・符号一回・接頭資格を検査する。"""

from copy import deepcopy
import json

import numpy as np

import analysis
import normal_reference
import price_features
import volume_reference


def fixture(n: int=140,zero_votes: bool=False) -> tuple[dict,dict,dict]:
    """
    機能: 原seq/時計/両BBO・三つの紙上親を持つ二cache型の小素材を作る。
    引数: n(int) は合成normal長、zero_votes(bool) は既知零票の素材か。
    返り値: tuple[dict,dict,dict] はTradeGate型/TradeExit型/合成raw。実入力を読まない。
    """
    gate=dict(schema_version=1,session='合成_Day',accounts={});ex=dict(schema_version=1,session='合成_Day',accounts={});raws={}
    for symbol in analysis.SYMBOLS:
        index=np.arange(n);times=index.astype(float)*5.;times[41:43]=times[40]
        if symbol=='NK225':times-=.1
        step=.5 if symbol=='TOPIX' else 10.;base=4000. if symbol=='TOPIX' else 70000.
        prices=base+step*np.where((index//20)%2==0,index%20,20-index%20)
        raw=dict(raw_seq=index.astype(np.int64)+500,price_time_s=times.copy(),last=prices.copy(),
                 bid=prices-step/2,ask=prices+step/2,volume_delta=np.zeros(n) if zero_votes else np.ones(n),
                 volume_delta_usable=np.ones(n,bool),volume_reset_reason=np.zeros(n,np.uint8))
        raw['volume_delta_usable'][0]=False
        if not zero_votes:raw['volume_delta_usable'][95]=False;raw['volume_reset_reason'][95]=8
        mapping=index.astype(np.int64);ctx=volume_reference.context(raw)
        q=dict(bid=raw['bid'].copy(),ask=raw['ask'].copy(),quote_valid=np.ones(n,bool),seq=raw['raw_seq'].copy(),time_s=times.copy())
        record=dict(price=prices.copy(),seq=raw['raw_seq'].copy(),time_s=times.copy(),start=0.,end=1000.,limit=1000.,tick=step)
        quantity=5 if symbol=='TOPIX' else 10
        feed=np.asarray([[40,39,0,1,quantity,prices[40],0,1,0,8*step],
                         [60,59,0,-1,quantity//2,prices[60],1,0,0,8*step],
                         [70,69,0,-1,quantity-quantity//2,prices[70],1,0,0,8*step],
                         [80,79,1,-1,quantity,prices[80],0,1,0,8*step],
                         [90,89,1,1,quantity,prices[90],1,0,0,8*step],
                         [100,99,2,1,quantity,prices[100],0,1,0,8*step],
                         [120,119,2,-1,quantity,prices[120],1,0,0,8*step]],float)
        quiet=np.zeros(n,bool);quiet[39:44]=True
        a=dict(symbol=symbol,record=record,quotes=q,feed=feed,quiet=quiet,quiet_force=np.zeros(n,bool),mapping=mapping,
               trade_features={window:{int(o[0]):volume_reference.measure(raw,ctx,int(o[0]),int(window),int(o[3])) for o in feed if o[7]==1} for window in analysis.WINDOWS})
        gate['accounts'][symbol]=a
        ex['accounts'][symbol]=dict(symbol=symbol,record=deepcopy(record),quotes=deepcopy(q),
                                    votes={window:normal_reference.all_normal(raw,ctx,mapping,int(window)) for window in analysis.WINDOWS})
        raws[symbol]=raw
    return gate,ex,raws


def prefix(gate: dict,ex: dict,n: int) -> tuple[dict,dict]:
    """
    機能: 保存全行素材を当時接頭へ切り、将来PUB辞書とfeedだけを除く。
    引数: gate/ex(dict)、n(int) は合成cacheと接頭長。
    返り値: tuple[dict,dict] は切った二cache。時刻の未来補完をしない。
    """
    g,e=deepcopy(gate),deepcopy(ex)
    for s in analysis.SYMBOLS:
        for a in (g['accounts'][s],e['accounts'][s]):
            for group in ('record','quotes'):
                for name,value in a[group].items():
                    if isinstance(value,np.ndarray):a[group][name]=value[:n].copy()
        a=g['accounts'][s];a['mapping']=a['mapping'][:n];a['quiet']=a['quiet'][:n];a['quiet_force']=a['quiet_force'][:n]
        a['feed']=a['feed'][a['feed'][:,0]<n]
        for w in analysis.WINDOWS:
            a['trade_features'][w]={k:v for k,v in a['trade_features'][w].items() if k<n}
            for name,value in e['accounts'][s]['votes'][w].items():e['accounts'][s]['votes'][w][name]=value[:n].copy()
    return g,e


def run() -> dict:
    """
    機能: sourceだけの合成素材で境界・系譜・当時判定の不変を確認する。
    引数: なし。
    返り値: dict は検査数と対象。金融、目録、実cacheを読まない。
    """
    count=0;gate,ex,raws=fixture();base=analysis.analyze(gate,ex);count+=1
    saved=json.loads(json.dumps(base,ensure_ascii=False,allow_nan=False));assert saved==base;count+=1
    assert base['checks']['公開窓scalar全normal一致']==18
    zero_g,zero_e,_=fixture(zero_votes=True);analysis.strict_join(zero_g,zero_e);count+=1
    zero=analysis.analyze(zero_g,zero_e);assert json.loads(json.dumps(zero,ensure_ascii=False,allow_nan=False))==zero;count+=1
    # ----------------------------------------
    # 実cache由来を想定し、公開dictの数値型もNumPy scalarへ替えて全payloadを保存する。
    for candidate_g,candidate_e in ((gate,ex),(zero_g,zero_e)):
        typed=deepcopy(candidate_g)
        for account in typed['accounts'].values():
            for table in account['trade_features'].values():
                for value in table.values():
                    for name,item in tuple(value.items()):
                        if isinstance(item,bool):value[name]=np.bool_(item)
                        elif isinstance(item,int):value[name]=np.int64(item)
                        elif isinstance(item,float):value[name]=np.float64(item)
        typed_result=analysis.analyze(typed,candidate_e)
        assert json.loads(json.dumps(typed_result,ensure_ascii=False,allow_nan=False))==typed_result;count+=1
    for s in analysis.SYMBOLS:
        value=zero_g['accounts'][s]['trade_features']['60'][80]
        assert value['known'] and value['balance'] is None and np.isnan(zero_e['accounts'][s]['votes']['60']['balance'][80]);count+=1
        state=analysis.paper_state(gate['accounts'][s]);count+=1
        assert state['remaining'][60]==(3 if s=='TOPIX' else 5) and state['direction'][60]==1
        assert state['direction'][70]==0 and state['direction'][80]==-1
        p=price_features.pair(gate)[s];v=ex['accounts'][s]['votes']['60'];o=analysis.observe(gate['accounts'][s],v,p,state)
        assert o['public_reason_without_actual_state'][40]==92 and o['public_reason_without_actual_state'][80]==0;count+=2
        assert o['public_reason_without_actual_state'][100]==95;count+=1
        # ----------------------------------------
        # SELLはunsignedへsideを一回だけ。PUBは既にsignedなのでさらに向けない。
        row=80;up=int(v['up_votes'][row]);down=int(v['down_votes'][row]);total=up+down
        assert gate['accounts'][s]['trade_features']['60'][row]['balance']==-(up-down)/total;count+=1
        assert p['peer_row'][80]>=0 and gate['accounts']['NK225' if s=='TOPIX' else 'TOPIX']['record']['time_s'][p['peer_row'][80]]<gate['accounts'][s]['record']['time_s'][80];count+=1
        assert o['flags']['volume_known'][100]==False and np.isnan(o['volume_signed'][100]);count+=1
    # ----------------------------------------
    # 接頭では当時行のstate/票/資格を比較する。区間の未来最終長を不変とは呼ばない。
    full_prices=price_features.pair(gate)
    for length in (41,43,61,71,81,101,121):
        g,e=prefix(gate,ex,length);analysis.strict_join(g,e);part_prices=price_features.pair(g)
        for s in analysis.SYMBOLS:
            full_state=analysis.paper_state(gate['accounts'][s]);part_state=analysis.paper_state(g['accounts'][s])
            for name,value in part_state.items():np.testing.assert_array_equal(value,full_state[name][:length]);count+=1
            full_o=analysis.observe(gate['accounts'][s],ex['accounts'][s]['votes']['60'],full_prices[s],full_state)
            part_o=analysis.observe(g['accounts'][s],e['accounts'][s]['votes']['60'],part_prices[s],part_state)
            for group in ('flags','window_profiles','eligible'):
                for name,value in part_o[group].items():np.testing.assert_array_equal(value,full_o[group][name][:length]);count+=1
            for name in ('volume_count','volume_signed','allowance','public_reason_without_actual_state'):
                np.testing.assert_array_equal(part_o[name],full_o[name][:length]);count+=1
    # ----------------------------------------
    # 同clock後半の未来rawが増えても、先頭candidate上限までの方向票は不変。
    for s,raw in raws.items():
        changed=deepcopy(raw);changed['last'][41:]=changed['last'][41:]+1000.
        left=volume_reference.measure(raw,volume_reference.context(raw),40,60,1)
        right=volume_reference.measure(changed,volume_reference.context(changed),40,60,1)
        assert left==right;count+=1
        z=normal_reference.all_normal(raw,volume_reference.context(raw),np.arange(len(raw['raw_seq']),dtype=np.int64),60)
        raw_nan=deepcopy(raw);raw_nan['price_time_s'][40]=np.nan
        small={name:value[:41] for name,value in raw_nan.items()}
        a=normal_reference.all_normal(raw_nan,volume_reference.context(raw_nan),np.arange(41,dtype=np.int64),60)
        b=normal_reference.all_normal(small,volume_reference.context(small),np.arange(41,dtype=np.int64),60)
        for name in a:np.testing.assert_array_equal(a[name],b[name]);count+=1
        assert not a['known'][40] and a['reason'][40]==2 and a['reference_raw_row'][40]==a['first_vote_raw_row'][40]==-1
    # ----------------------------------------
    # 原row/seq/clock/BBO/公開符号の誤結合を拒否。未知は中立へ変えない。
    for group,name in (('record','seq'),('record','time_s'),('quotes','bid')):
        broken=deepcopy(ex);broken['accounts']['TOPIX'][group][name][80]+=1
        try:analysis.strict_join(gate,broken)
        except AssertionError:count+=1
        else:raise AssertionError('誤joinを許可 '+name)
    broken=deepcopy(gate);broken['accounts']['TOPIX']['mapping'][80]+=1
    try:analysis.strict_join(broken,ex)
    except AssertionError:count+=1
    else:raise AssertionError('誤mapを許可')
    wrong=deepcopy(gate);wrong['accounts']['TOPIX']['trade_features']['60'][80]['balance']*=-1
    try:analysis.strict_join(wrong,ex)
    except AssertionError:count+=1
    else:raise AssertionError('二重符号を許可')
    # 全normalには紙上zeroの観測もあり、紙上区間の母集団より大きいことを確認する。
    for s in analysis.SYMBOLS:
        z=base['accounts'][s];assert z['all_normal_directional_qualification']['BUY']['normal_observations']==140
        assert z['counts']['active_normal_observations']<140;count+=1
    return dict(全合格=True,検査数=count,scope=['strictjoin/公開三窓','SELL符号一回/既知零票/未知debug','quietと期間の暫定PUB順序',
        '同時計未来原行上限/peerstrict過去','接頭七長の当時stateと資格','誤seq/time/BBO/map/二重符号拒否','全normal両方向と紙上条件群の分離','analyze全出力/未知/既知零票のJSON原始型・非有限禁止'],
        金融=0,実cache=0,目録本文=0,API=0)
