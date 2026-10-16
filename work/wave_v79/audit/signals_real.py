"""実データの防止旗と旧入口の参照行を独立検算し、未来を切断・改変する。"""

from __future__ import annotations

import copy
import json

import numpy as np

from full_accounts import HERE, ROOT, study
from independent_account import save


def confirmed(grid: np.ndarray, condition: np.ndarray, valid: np.ndarray,
              first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """機能: 有効な真の連続区間を先に分割し、各区間の始点から15秒と両更新を判定する。

    引数: grid/condition/valid/first/second(ndarray)。返り値: 確認旗(ndarray[bool])。
    """
    good=condition&valid
    start=good & (~np.r_[False,good[:-1]] | np.r_[True,np.diff(grid)>5.+1e-8])
    anchor=np.maximum.accumulate(np.where(start,np.arange(len(grid)),0))
    return good&(grid-grid[anchor]>=15.)&(first>first[anchor])&(second>second[anchor])


def oracle(session: dict) -> dict:
    """機能: 防止入力から支持・効率・板符号と二つの逆行確認を直接再計算する。

    引数: session(dict)。返り値: 商品別防止旗(dict)。
    """
    grid=session['grid'];m=session['markets'];names=('TOPIX','NK225');a,b=(m[s] for s in names)
    valid=a['current']['valid']&b['current']['valid'];v30=valid.copy();eff=valid.copy();depth=valid.copy()
    for z in m.values():
        w=z['windows'][30];v30 &= w['source_valid']&np.isfinite(w['ret_bp'])&np.isfinite(w['bid_change_ticks'])&np.isfinite(w['ask_change_ticks'])
        w=z['windows'][300];eff &= w['source_valid']&np.isfinite(w['efficiency'])&(w['efficiency']>=.2)
        depth &= z['current']['q_valid']&np.isfinite(z['current']['depth_imbalance'])
    result={s:{} for s in names}
    for direction,word in ((1,'long'),(-1,'short')):
        support=valid.copy();consistent=depth.copy();reverse={}
        for s,z in m.items():
            f=z['flow'][15]
            support &= f['source_valid']&f['valid']&~f['missing_ofi']&(f['nonzero_ofi_count']>=3)&np.isfinite(f['ofi_ratio'])&(direction*f['ofi_ratio']>=.1)
            consistent &= direction*z['current']['depth_imbalance']>=0
            w=z['windows'][30];reverse[s]=(-direction*w['bid_change_ticks']>=1.-1e-8)&(-direction*w['ask_change_ticks']>=1.-1e-8)
        for s in names:
            peer=names[1] if s==names[0] else names[0]
            result[s][f'support_{word}']=support;result[s][f'efficient_{word}']=eff;result[s][f'depth_{word}']=consistent
            result[s][f'x1_{word}']=confirmed(grid,reverse[names[0]]&reverse[names[1]],v30,a['current']['index'],b['current']['index'])
            result[s][f'x2_{word}']=confirmed(grid,reverse[s]&(direction*m[peer]['windows'][30]['ret_bp']<=0),v30,a['current']['index'],b['current']['index'])
    return result


def clip(value: object, end: int, total: int) -> object:
    """機能: 格子の長さを持つ配列だけを指定位置で切断する。

    引数: value(object)、end/total(int)。返り値: 切断構造(object)。
    """
    if isinstance(value,dict):return {k:clip(v,end,total) for k,v in value.items()}
    if isinstance(value,np.ndarray) and len(value)==total:return value[:end].copy()
    return value


def main() -> None:
    """機能: 全90場素材の独立信号と未来不変、旧candidate源泉行、E2参照値を照合する。

    引数: なし。返り値: なし(None)。新規の損益を探索しない。
    """
    comparisons=prefixes=source_count=event_cases=0;grid_count=0
    for delay in (1,5,15):
        material=study.material(delay);ready,book,state,maps,entries,legacy,meta,prevent=material
        grids=study.load(ROOT/f'work/wave_v77/inputs/grids_delay{delay}.pkl')
        for session,value in grids.items():
            full=prevent[session];expected=oracle(value);n=len(value['grid']);grid_count+=n
            for symbol,fields in expected.items():
                for name,array in fields.items():
                    np.testing.assert_array_equal(full['markets'][symbol][name],array);comparisons+=1
            for end in sorted({max(1,n//4),n//2,n*3//4}):
                partial=study.prevention.session_state(clip(value,end,n));mutant=copy.deepcopy(value)
                for m in mutant['markets'].values():
                    m['current']['valid'][end:]=False;m['current']['q_valid'][end:]=False
                    m['current']['index'][end:]+=100000;m['current']['depth_imbalance'][end:]*=-1
                    m['flow'][15]['ofi_ratio'][end:]*=-1;m['flow'][15]['valid'][end:]=False
                    m['windows'][30]['ret_bp'][end:]*=-1;m['windows'][30]['bid_change_ticks'][end:]*=-1
                    m['windows'][30]['ask_change_ticks'][end:]*=-1;m['windows'][300]['efficiency'][end:]=np.nan
                changed=study.prevention.session_state(mutant)
                for symbol,fields in full['markets'].items():
                    for name,array in fields.items():
                        np.testing.assert_array_equal(partial['markets'][symbol][name],array[:end])
                        np.testing.assert_array_equal(changed['markets'][symbol][name][:end],array[:end]);comparisons+=2
                prefixes+=1
        for key,r in ready.items():
            peer=(key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX');candidates=legacy[key]['candidates']
            expected=np.zeros(len(r['time_s']),dtype=np.int8)
            for candidate in candidates:
                old,decision,direction,own,other=map(int,candidate);clock=r['start']+300.+15.*old
                assert own==legacy[key]['own_source'][old] and other==legacy[key]['peer_source'][old]
                assert 0<=own<decision and r['time_s'][own]<clock-delay
                assert ready[peer]['time_s'][other]<clock-delay and np.searchsorted(r['time_s'],clock,side='left')==decision
                assert own==np.searchsorted(r['time_s'],r['time_s'][own],side='left')
                assert other==np.searchsorted(ready[peer]['time_s'],ready[peer]['time_s'][other],side='left')
                source_count+=1;g=maps[key][decision];word='long' if direction==1 else 'short'
                if g<0 or not entries[key[0]]['entries']['J2'][f'{word}_allowed'][g]:continue
                quotes=book[key]['ask'] if direction==1 else book[key]['bid']
                difference=direction*(quotes[decision]-quotes[own])
                if np.isfinite(quotes[own]) and difference<=r['tick']+1e-8:expected[decision]=direction
            actual=study.arguments(dict(entry=2,exit_mode=0),key,*material)[5]
            np.testing.assert_array_equal(actual,expected);event_cases+=1
        print(f'遅延{delay}秒の全信号と旧入口参照を独立確認',flush=True)
    proof=dict(合格=True,遅延数=3,素材場数=90,格子数=grid_count,配列照合数=comparisons,
        実格子切断地点数=prefixes,旧入口candidate因果照合数=source_count,E2全候補配列照合口座数=event_cases,
        E2参照='旧15秒入口candidate[3]の自原本気配。J2追加5秒格子の参照行と混同しない。',
        時計の限定='最終約定代理時計に基づく確認。真の共通受信時計ではない。',
        prevention_SHA256=study.digest(HERE.parent/'prevention.py'),experiment_SHA256=study.digest(HERE.parent/'experiment.py'),
        新損益探索=0,API取得=0,実注文=0)
    save(HERE/'全実格子と旧入口参照の独立信号未来監査.json',proof)
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
