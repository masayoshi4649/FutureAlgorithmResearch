"""損益を計算せず、旧候補と同値価格の演算境界及び発火機会消費を検査する。"""

import copy
from pathlib import Path
import sys
import types

import numba
import numpy as np

import support


def legacy() -> object:
    """
    機能: 原75の候補関数を読み取り、旧キャッシュへの保存を防ぐ。
    引数: なし。
    返り値: objectは比較対象。売買及び会計を実行しない。
    """
    if 'inputs' not in sys.modules:
        sys.modules['inputs']=types.ModuleType('inputs')
    old_core=sys.modules.get('inputs.core')
    try:
        support.module('inputs.core',support.ROOT/'work/wave_v75/inputs/core.py')
        return support.module('旧75候補のnull読取95',support.ROOT/'work/wave_v75/signals.py')
    finally:
        if old_core is None:
            sys.modules.pop('inputs.core',None)
        else:
            sys.modules['inputs.core']=old_core
        numba.config.CACHE_DIR=str(support.WORK/'numba_cache')


def material(old: object, side: int, rate: float) -> dict:
    """
    機能: LPとmidを同値・同源へ置いた二市場の人工候補素材を作る。
    引数: old(object)、side(int)、rate(float)は秒当たり相対変位。
    返り値: dictは旧候補、新価格格子と旧気配。実損益は含まない。
    """
    times=np.arange(1501,dtype=float);grid=np.arange(300.,1200.,5.);candidate=grid[::3]
    ready={};books={};stats={};stats5={};legacy_saved={};markets={};execution={};features={}
    for j,symbol in enumerate(('TOPIX','NK225')):
        key='人工',symbol;tick=.001;base=1000./(j+1)
        mid=base*(1+side*rate*times);bid=mid-tick/2;ask=mid+tick/2
        ready[key]=dict(time_s=times,seq=np.arange(len(times))+j*3000,tick=tick,start=0.,limit=1500.,
                        bid=bid,ask=ask)
        books[key]=dict(valid=np.ones(len(times),bool),reset=np.zeros(len(times),bool),
                        bid=bid,ask=ask,mid=mid,best_ofi=np.zeros(len(times)))
        stats[symbol]=old.features(candidate,1,300,30,ready[key],books[key])
        stats5[symbol]=old.features(grid,1,300,30,ready[key],books[key])
        f=stats5[symbol];now=np.maximum(f['now'],0);short=np.maximum(f['short'],0);origin=np.maximum(f['old'],0)
        windows={}
        for seconds,ix,name in ((15,short,'short_ret'),(300,origin,'ret')):
            windows[seconds]=dict(source_valid=f['valid'].copy(),ratio_ret_bp=f[name].copy(),
                ret_bp=(mid[now]-mid[ix])/mid[ix]*10000.)
            windows[seconds]['ret_bp'][~f['valid']]=np.nan
        markets[symbol]=dict(current=dict(index=f['now'],raw_seq=f['now']+j*3000,
            time_s=times[now],value=mid[now],valid=f['now']>=0),windows=windows)
        execution[symbol]=dict(current=dict(valid=f['now']>=0),flow={15:dict(source_valid=f['valid'],
            bid_change_ticks=(bid[now]-bid[short])/tick,ask_change_ticks=(ask[now]-ask[short])/tick,
            valid=np.zeros(len(grid),bool),missing_ofi=np.zeros(len(grid),bool),
            nonzero_ofi_count=np.zeros(len(grid),int),ofi_ratio=np.full(len(grid),np.nan))})
        features[key]=dict(quality=np.ones(len(times),bool),reset=np.zeros(len(times),bool))
    for symbol in ('TOPIX','NK225'):
        peer='NK225' if symbol=='TOPIX' else 'TOPIX';key='人工',symbol
        state,valid=old.conditions(stats[symbol],stats[peer],300,0,True)
        pulse=old.event_pulses(candidate,state[0],valid)
        mapped=old.map_pulses(candidate,pulse,stats[symbol],stats[peer],ready[key],books[key])
        legacy_saved[key]=dict(states=state[0],valid=valid,pulse=pulse,candidates=mapped,
            own_source=stats[symbol]['now'],peer_source=stats[peer]['now'])
    price=dict(grid=grid,candidate_grid=candidate,candidate_positions=np.arange(0,len(grid),3),markets=markets)
    return dict(prices=ready,legacy=legacy_saved,features=features,
                trend_prices={'I3':{'人工':price}},grids={'人工':dict(grid=grid,markets=execution)})


def main() -> None:
    """
    機能: 同値価格の旧候補完全一致、旧資格mask対照及び欠測中立を検査する。
    引数: なし。
    返り値: Noneは実装SHA付きnull証跡。会計再生を行わない。
    """
    strategy,_,_=support.components();old=legacy();matches=0
    rates=(3/10000/300,np.nextafter(3/10000/300,0),np.nextafter(3/10000/300,np.inf),4/10000/300)
    for side in (-1,1):
        for rate in rates:
            m=material(old,side,rate)
            for symbol in ('TOPIX','NK225'):
                key='人工',symbol
                for source in ('P2','P3'):
                    result=strategy.lp_candidates(key,m,source,m['features'][key]);reference=m['legacy'][key]
                    for name in ('states','valid','pulse','candidates','own_source','peer_source'):
                        np.testing.assert_array_equal(result[name],reference[name])
                    matches+=1
    grid=np.arange(0.,1500.,15.);state=np.zeros(len(grid),np.int8);valid=np.ones(len(grid),bool)
    state[0]=1;state[40]=1;valid[1:39]=False
    pulse=strategy.event_pulses(grid,state,valid)
    np.testing.assert_array_equal(pulse,old.event_pulses(grid,state,valid))
    assert pulse[0]==1 and pulse[40]==0
    # 発火後の最初原行が不正でも、次の正常行へ再写像しない。
    m=material(old,1,4/10000/300);key='人工','TOPIX'
    good=strategy.lp_candidates(key,m,'P3',m['features'][key])
    assert len(good['candidates'])
    rejected=copy.deepcopy(m['features'][key]);row=int(good['candidates'][0,1]);rejected['quality'][row]=False
    bad=strategy.lp_candidates(key,m,'P3',rejected)
    np.testing.assert_array_equal(good['pulse'],bad['pulse'])
    assert not np.any(bad['candidates'][:,1]==row+1)
    # P2だけ旧資格を保持。P3は新LPが正常なら旧価格資格の欠測へ巻き込まれない。
    old_missing=copy.deepcopy(m);old_missing['legacy'][key]['valid'][:]=False
    p2=strategy.lp_candidates(key,old_missing,'P2',old_missing['features'][key])
    p3=strategy.lp_candidates(key,old_missing,'P3',old_missing['features'][key])
    assert not p2['valid'].any() and not p2['pulse'].any() and len(p3['candidates'])
    support.save('価格同値同源の旧候補nullと演算境界及び旧資格分離と発火消費.json',
        dict(全合格=True,同値同源候補完全一致=matches,候補は旧ratio演算型=True,J2は旧差分演算型=True,
             欠測を中立に数えない=True,最初原行却下後の再写像なし=True,P2旧資格保持とP3分離=True),
        [Path(__file__),support.ROOT/'work/wave_v75/signals.py',support.ROOT/'work/wave_v75/inputs/core.py'])


if __name__=='__main__':
    main()
