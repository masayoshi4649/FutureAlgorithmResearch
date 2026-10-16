"""追加予約と未知源・不利実fill・初回期限を、少数人工だけで検査する。"""

import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from support import HERE, ROOT, WORK, attach_support, load
from selfcheck import prepared_fixture, run


def expiry_fixture(config: dict, symbol: str, side: int) -> dict:
    """
    機能: 初回期限の1秒前に追加を判断できる、長い明示人工原板を作る。
    引数: config(dict)、symbol(str)、side(int)。
    返り値: dict[tuple,dict]。原本や新正式損益を使わない。
    """
    data = prepared_fixture(config, symbol, side)
    key = next(iter(data)); current = data[key]
    record, signal = current['record'], current['signal']
    size, base, tick = 3001, current['reference_open'], record['tick']
    width = max(2, math.ceil(base*.001/tick-1e-10))*tick
    progress = np.zeros(size);progress[340:] = .5;progress[2140:] = 3.
    quote = base+(tick if side == 1 else 0.)+side*np.round(progress*width/tick)*tick
    record.update(time_s=np.arange(size,dtype=float),seq=np.arange(size,dtype=np.int64)+1000,
        price_valid=np.ones(size,bool),quote_valid=np.ones(size,bool),limit=3000.,end=3100.,
        bid=quote-tick if side == 1 else quote.copy(),ask=quote.copy() if side == 1 else quote+tick)
    record['price'] = .5*(record['bid']+record['ask'])
    grid=np.arange(300.,3001.,5.);source=grid.astype(int)-1
    event=np.zeros(size,np.int8);event[330]=side
    mapped=np.full(size,-1,np.int32);mapped[grid.astype(int)]=np.arange(len(grid),dtype=np.int32)
    peer_base, peer_tick=(50000.,10.) if symbol=='TOPIX' else (4000.,.5)
    peer_width=max(2,math.ceil(peer_base*.001/peer_tick-1e-10))*peer_tick
    peer_quote=peer_base+(peer_tick if side==1 else 0.)+side*np.round(progress*peer_width/peer_tick)*peer_tick
    peer_bid=peer_quote-peer_tick if side==1 else peer_quote
    peer_ask=peer_quote if side==1 else peer_quote+peer_tick
    signal.update(grid=grid,mapped=mapped,event=event,quality=np.ones(size,bool),reset=np.zeros(size,bool),
        mode=np.zeros(len(grid),np.int8),entry_j2_long=np.ones(len(grid),bool),entry_j2_short=np.ones(len(grid),bool),
        wait_opposite_long=np.zeros(len(grid),bool),wait_opposite_short=np.zeros(len(grid),bool),
        entry_peer_bbo=np.column_stack((source,source+9000,source.astype(float),peer_bid[source],peer_ask[source],np.ones(len(grid)))))
    return attach_support({key:current})


def named_state(output: dict, row: int, name: str) -> float:
    """
    機能: 追加状態の公開列名から一つの値を取得する。
    引数: output(dict)、row(int)、name(str)。
    返り値: float。列番号の別台帳との混同を防ぐ。
    """
    return float(output['growth_state_trace'][row,output['growth_state_columns'].index(name)])


def main() -> None:
    """
    機能: 実際に予約された追加だけを未来気配へ接続し、巻戻しや同行再追加を検査する。
    引数: なし。
    返り値: None。全31の新損益及び現在APIを読まず証跡を保存する。
    """
    strategy=load('101少数競合の現在実行',WORK/'strategy.py')
    catalog=load('101少数競合の20定義',WORK/'catalog.py')
    configs={value['id']:value for value in catalog.catalog()}; config=configs['G1_Q1_X1']
    counts=dict(不利追加fill後に全玉停止=0,force前取消=0,初回期限前取消=0,
        未知初回peer復帰の基準同行禁止=0,予約後資格悪化でも実fill=0,
        費用超過予算非clamp=0,wholeprice費用床=0,返済料金最大剰余=0)
    cases=[]
    for symbol in catalog.SYMBOLS:
        for side in (1,-1):
            data=prepared_fixture(config,symbol,side);key=next(iter(data));value=data[key]
            normal=run(strategy,config,copy.deepcopy(data))
            decision=int(normal['growth_events'][normal['growth_events'][:,1]==2][0,0]);fill=decision+1
            tick=value['record']['tick']
            name='ask' if side==1 else 'bid'
            value['record'][name][fill]+=side*20.*tick
            bad=run(strategy,config,data)
            cohort=bad['growth_cohorts'][1]
            assert cohort[8]==fill and cohort[11]==value['record'][name][fill]
            exits=bad['orders'][bad['orders'][:,7]==0]
            assert len(exits)==1 and exits[0,1]==fill and exits[0,0]>fill and exits[0,5]==2
            assert len(bad['growth_cohorts'])==2 and bad['growth_parent_diagnostics'][0,18]>0
            assert bad['growth_parent_diagnostics'][0,19]>=bad['growth_parent_diagnostics'][0,18]
            assert named_state(bad,fill,'eligible')==0
            counts['不利追加fill後に全玉停止']+=1
            cases.append(dict(商品=symbol,方向=side,追加判断=decision,実追加=fill,
                初回R0=float(bad['growth_parent_diagnostics'][0,7]),
                実純額=float(bad['trades'][0,11]),実超過=float(bad['growth_parent_diagnostics'][0,18])))

            # ----------------------------------------
            # 場末は現在気配の追加fillより先。原proxy時計の大きな飛びだけを人工で作る。
            data=prepared_fixture(config,symbol,side);value=data[key]
            value['record']['time_s'][fill:]=np.linspace(1040.,1100.,len(value['record']['time_s'])-fill)
            value['signal']['mapped'][fill:]=-1
            forced=run(strategy,config,data)
            assert len(forced['growth_cohorts'])==1 and not np.any(forced['orders'][:,8]==16)
            assert ((forced['growth_events'][:,0]==fill)&(forced['growth_events'][:,1]==4)&(forced['growth_events'][:,2]==1)).any()
            counts['force前取消']+=1

            data=expiry_fixture(config,symbol,side)
            expired=run(strategy,config,data)
            first=expired['growth_cohorts'][0,10]
            deadline=first+1800.
            assert ((expired['growth_events'][:,0]==deadline-1)&(expired['growth_events'][:,1]==2)).any()
            assert ((expired['growth_events'][:,0]==deadline)&(expired['growth_events'][:,1]==4)&(expired['growth_events'][:,2]==3)).any()
            assert len(expired['growth_cohorts'])==1 and expired['trades'][0,5]==1
            counts['初回期限前取消']+=1

            # ----------------------------------------
            # 初回triggerは既知peerで359、実fill360で初めてpeer不明にし、365は基準設定だけ。
            data=prepared_fixture(config,symbol,side);value=data[key];signal=value['signal']
            signal['quality'][345:359]=False
            grid_index=int(np.flatnonzero(signal['grid']==360.)[0]);signal['entry_peer_bbo'][grid_index,5]=0
            resumed=run(strategy,config,data)
            assert resumed['growth_cohorts'][0,8]==360
            assert named_state(resumed,360,'anchor_valid')==0
            assert ((resumed['growth_events'][:,0]==365)&(resumed['growth_events'][:,1]==5)).any()
            assert named_state(resumed,365,'eligible')==0
            assert resumed['growth_events'][resumed['growth_events'][:,1]==2][0,0]>365
            counts['未知初回peer復帰の基準同行禁止']+=1

            # 追加予約369→fill370でreset/quality/peer/LPを悪化させ、既予約成行のfillを維持する。
            data=prepared_fixture(config,symbol,side);value=data[key];signal=value['signal']
            signal['quality'][365:369]=False
            signal['quality'][370]=False;signal['reset'][370]=True
            index=int(np.flatnonzero(signal['grid']==370.)[0]);signal['entry_peer_bbo'][index,5]=0
            material=value['artificial_support_material']
            material['trend_prices']['I3'][key[0]]['markets'][symbol]['current']['valid'][index]=False
            value['trend_lp_allowed']=strategy.lp_allowed(material['trend_prices']['I3'][key[0]],material['grids'][key[0]])
            value['entry_support_base']=strategy.support_basis(key,material,value)
            degraded=run(strategy,config,data)
            assert ((degraded['growth_events'][:,0]==369)&(degraded['growth_events'][:,1]==2)).any()
            assert ((degraded['growth_events'][:,0]==370)&(degraded['growth_events'][:,1]==3)).any()
            assert degraded['growth_cohorts'][1,8]==370 and named_state(degraded,370,'anchor_valid')==0
            counts['予約後資格悪化でも実fill']+=1

    # ----------------------------------------
    # 数学の狭い境界は同じhelperへ接続するが、実際の損益や将来を使用しない。
    for side in (1,-1):
        budget,fee,effective,active=strategy.ENGINE.growth_lines(side,16,1600000.,352.,222.,
            10000.-side*20.,10000.+side*20.,40.,10000.-side*10.,False,10000.+side*20.,1,20.,10.,10.,0)
        assert budget==10000.+side*10. and effective==budget and not active
        counts['費用超過予算非clamp']+=1
    budget,fee,effective,active=strategy.ENGINE.growth_lines(1,2,4005.25*2000.,165.,4082.,
        3996.5,4010.,16.,3996.5,False,4010.,1,4.,1000.,.5,1)
    assert fee==4006. and active
    unused_budget,unused_fee,unused_stop,still_active=strategy.ENGINE.growth_lines(1,2,4005.25*2000.,165.,4082.,
        3996.5,4010.,16.,effective,True,4005.5,1,4.,1000.,.5,1)
    assert still_active and unused_stop>=effective
    counts['wholeprice費用床']+=1
    cohorts=np.full((4,25),np.nan);cohorts[:,3]=1.;cohorts[:,4]=[1,1,2,4];cohorts[:,11]=4000.;cohorts[:,12]=[41,41,83,167]
    strategy.ENGINE.growth_cohort_close(cohorts,0,4,100,1100,100.,4001.,334.,1000.,8)
    np.testing.assert_array_equal(cohorts[:,18],[42.,42.,83.,167.]);assert cohorts[:,18].sum()==334.
    counts['返済料金最大剰余']+=1
    paths=[Path(__file__),HERE/'selfcheck.py',HERE/'support.py',WORK/'engine.py',WORK/'strategy.py',WORK/'catalog.py']
    proof=dict(全合格=True,検査件数=counts,不利fill例=cases,
        範囲='保存された次成行予約を人工の未来自己気配へ接続。実fillを不都合な価格から巻き戻さない。',
        新正式101損益=0,API取得=0,実注文=0,
        SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    target=HERE/'追加予約の不利実fillと期限及び未知基準と費用床の少数自己検査.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k!='SHA256'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
