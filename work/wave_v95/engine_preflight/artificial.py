"""人工経路だけで旧経済一致、実終了親の反転制限と四源確認を検査する。"""

import copy
from pathlib import Path

import numpy as np

import support


def fixture(symbol: str, mirrored: bool, kind: str = 'normal') -> tuple:
    """
    機能: 最初の追従が損失で終わり、両市場に次の反転が現れる人工経路を作る。
    引数: symbol(str)、mirrored(bool)、kind(str)。
    返り値: tuple[dict,dict]は人工原板と独立源を持つ信号。実セッション損益は読まない。
    """
    size = 1001
    times = np.arange(size, dtype=float)
    bid = np.full(size,100.)
    bid[350:] = 99.
    bid[390:] = 98.
    bid[420:] = 97.
    ask = bid+.5
    peer_bid = np.full(size,50.)
    peer_bid[390:] = 49.
    peer_bid[420:] = 48.
    if kind == 'profit_fill':
        bid[351:390] = 105.
        ask = bid+.5
    if kind == 'trailing':
        bid[340:350] = 100.75
        ask = bid+.5
    lp = .5*(bid+ask)
    peer_lp = peer_bid+.25
    if kind == 'quotes_only':
        lp[390:] = 99.25
        peer_lp[390:] = 50.25
    if mirrored:
        bid,ask = 200.-ask,200.-bid
        peer_bid,peer_ask = 100.-(peer_bid+.5),100.-peer_bid
        lp,peer_lp = 200.-lp,100.-peer_lp
    else:
        peer_ask = peer_bid+.5
    grid = np.arange(300.,945.,5.)
    mapped = np.full(size,-1,np.int32)
    mapped[grid.astype(int)] = np.arange(len(grid),dtype=np.int32)
    events = np.zeros(size,np.int8)
    side = -1 if mirrored else 1
    events[330] = side
    events[410] = -side
    if kind == 'same_direction':
        events[410] = side
    if kind == 'fallback':
        events[410] = 0
        events[400] = events[440] = -side
    index = grid.astype(int)-2
    observation = np.zeros((len(grid),22),np.float64)
    observation[:,0] = observation[:,5] = index
    observation[:,1] = 1000+index
    observation[:,6] = 3000+index
    observation[:,2] = observation[:,7] = index
    observation[:,3],observation[:,4] = bid[index],ask[index]
    observation[:,8],observation[:,9] = peer_bid[index],peer_ask[index]
    observation[:,10],observation[:,14] = 2000+index,4000+index
    observation[:,11],observation[:,15] = 1000+index,3000+index
    observation[:,12] = observation[:,16] = index
    observation[:,13],observation[:,17] = lp[index],peer_lp[index]
    observation[:,18:] = 1.
    if kind == 'fallback':
        observation[(grid>=350)&(grid<400),19] = 0
    record = dict(symbol=symbol,time_s=times,price=lp,bid=bid,ask=ask,
                  seq=np.arange(size,dtype=np.int64)+1000,price_valid=np.ones(size,bool),
                  quote_valid=np.ones(size,bool),tick=.5,start=0.,limit=1000.,end=1100.)
    zeros = np.zeros(len(grid),np.int8)
    signal = dict(grid=grid,mapped=mapped,quality=np.ones(size,bool),reset=np.zeros(size,bool),
                  event=events,mode=zeros,trend_width=1.,peer_tick=.5,loss_observations=observation,
                  execution_lp_index=np.arange(size,dtype=np.int64)+2000)
    return record,signal


def direct_boundaries(engine: object) -> dict:
    """
    機能: 四源の更新・同時計拒否・気配進行とLP進行の別資格を直接検査する。
    引数: engine(object)は新95実装。
    返り値: dictは人工正負境界の件数。
    """
    anchor=np.array([10,1010,350,100,100.5,20,2020,349,50,50.5,
                     100,1010,350,100.25,200,2020,349,50.25,1,1,1,1],float)
    observed=anchor.copy()
    for index,seq,clock in ((0,1,2),(5,6,7),(10,11,12),(14,15,16)):
        observed[index]+=1;observed[seq]+=1;observed[clock]=355
    observed[[3,4,8,9]]-=.5
    observed[[13,17]]-=1.
    assert engine.loss_gate_status(observed,anchor,350.,-1,.5,.5)==(True,True,True)
    checks=1
    for field in (0,1,2,5,6,7,10,11,12,14,15,16):
        bad=observed.copy();bad[field]=anchor[field]
        assert engine.loss_gate_status(bad,anchor,350.,-1,.5,.5)==(False,False,False)
        checks+=1
    for field in (18,19,20,21):
        bad=observed.copy();bad[field]=0
        assert engine.loss_gate_status(bad,anchor,350.,-1,.5,.5)==(False,False,False)
        checks+=1
    for field in (3,4,8,9):
        bad=observed.copy();bad[field]=anchor[field]-.25
        assert engine.loss_gate_status(bad,anchor,350.,-1,.5,.5)==(True,False,True)
        checks+=1
    for field in (13,17):
        bad=observed.copy();bad[field]=anchor[field]
        assert engine.loss_gate_status(bad,anchor,350.,-1,.5,.5)==(True,True,False)
        checks+=1
    return dict(四源の更新と時計の境界=checks)


def main() -> None:
    """
    機能: 人工全38・旧R0完全一致・反転制限正負・未来接頭を検査する。
    引数: なし。
    返り値: Noneは実装SHA付き人工証跡。正式新損益は実行しない。
    """
    strategy,catalog,_=support.components()
    engine,old = strategy.ENGINE,strategy.LEGACY.ENGINE
    # ----------------------------------------
    # 人工網羅はPython本体で行い、JIT実行の境界検査は最後に独立実施する。
    new_jit,old_jit = engine.simulate,old.simulate
    engine.simulate,old.simulate = new_jit.py_func,old_jit.py_func
    configs=catalog.catalog();byid={c['id']:c for c in configs}
    comparisons=paths=prefixes=0
    for config in configs:
        for symbol in ('TOPIX','NK225'):
            for mirrored in (False,True):
                record,signal=fixture(symbol,mirrored)
                result=engine.execute(record,signal,config)
                assert result['loss_reentry_events'].shape[1]==66
                if config['loss_reentry_kind']=='none':
                    previous=old.execute(record,signal,config)
                    for name in ('orders','trades','curve','source_curve','target_trace','events','stats','slots',
                                 'range_state_trace','risk_state_trace','range_parent_diagnostics','price_source_trace'):
                        np.testing.assert_array_equal(result[name],previous[name])
                    comparisons+=1
                paths+=1
    cases=0
    for symbol in ('TOPIX','NK225'):
        for mirrored in (False,True):
            for kind in ('normal','quotes_only','fallback','same_direction','profit_fill','trailing'):
                record,signal=fixture(symbol,mirrored,kind)
                for mode in range(1,5):
                    config=byid[f'P0_R{mode}_N']
                    result=engine.execute(record,signal,config)
                    records=result['loss_reentry_events']
                    if kind=='profit_fill':
                        assert records[0,5]>0 and records[0,8]==0
                        assert len(result['orders'][result['orders'][:,7]==1])==2
                    elif kind=='same_direction':
                        assert not np.any(records[:,1]==4)
                        assert len(result['orders'][result['orders'][:,7]==1])==2
                    elif kind=='quotes_only' and mode>=3:
                        gates=records[records[:,1]==4]
                        assert len(gates)==1 and gates[0,62]==0
                    elif kind=='fallback' and mode>=2:
                        anchors=records[records[:,1]==3]
                        gates=records[records[:,1]==4]
                        assert len(anchors)==1 and anchors[0,0]==400
                        assert len(gates)==2 and gates[0,62]==0 and gates[1,62]==1
                    elif kind=='normal':
                        gates=records[records[:,1]==4]
                        assert len(gates)==1 and bool(gates[0,62])==(mode>=2)
                    for stop in (332,351,352,401,411,441):
                        r,s=support.prefix(record,signal,stop)
                        part=engine.execute(r,s,config,finish=False)
                        support.prefix_equal(result,part,stop)
                        prefixes+=1
                    cases+=1
            record,signal=fixture(symbol,mirrored)
            for trigger in ('N','S'):
                config=dict(byid[f'P0_R1_{trigger}'],trend_hold_seconds=15.)
                result=engine.execute(record,signal,config)
                first=result['loss_reentry_events'][0]
                assert first[4]==3 and first[5]<0 and bool(first[8])==(trigger=='N')
    engine.simulate,old.simulate = new_jit,old_jit
    boundaries=direct_boundaries(engine)
    record,signal=fixture('TOPIX',False)
    compiled=engine.execute(record,signal,byid['P0_R3_N'])
    engine.simulate=new_jit.py_func
    reference=engine.execute(record,signal,byid['P0_R3_N'])
    for name in ('orders','trades','events','curve','source_curve','target_trace','risk_state_trace',
                 'range_state_trace','price_source_trace','loss_reentry_events','stats','slots'):
        np.testing.assert_array_equal(compiled[name],reference[name])
    engine.simulate=new_jit
    support.save('全38人工と旧経済及び直前損失反転の四源境界及び接頭一致.json',
        dict(全合格=True,人工経路=paths,旧R0完全一致=comparisons,反転正負経路=cases,
             人工接頭一致=prefixes,JIT及びPython完全一致=True,**boundaries),[Path(__file__)])


if __name__=='__main__':
    main()
