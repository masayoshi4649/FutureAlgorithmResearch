"""全53条件を実観測の途中までで検査し、新しい完結場損益は計算しない。"""

from pathlib import Path

import numpy as np

import support


def main() -> None:
    """機能: 実10接頭部で全条件の未来切断・自己価格改変・相手信号改変を検査する。

    引数: なし。返り値: None。完結場の新損益や採用順位を算出しない。
    """
    strategy,catalog,data=support.components();material=data.load_inputs()
    sessions=('2026-09-24_Night','2026-09-28_Day','2026-10-06_Day','2026-10-09_Night','2026-10-12_Day')
    keys=[(session,symbol) for session in sessions for symbol in ('TOPIX','NK225')]
    counts=dict(実接頭部=0,未来切断=0,未来自己価格=0,未来相手及び価格状態=0)
    for config in catalog.catalog():
        prepared=strategy.prepare(material,config)
        for key in keys:
            value=prepared[key];r,s=support.prefix(value['record'],value['signal'],min(12000,len(value['record']['time_s'])))
            n=len(r['time_s']);assert r['time_s'][-1]<r['limit']-300
            full=strategy.ENGINE.execute(r,s,config,finish=False);counts['実接頭部']+=1
            for stop in np.unique(np.rint(np.linspace(1,n-1,10)).astype(int)):
                rr,ss=support.prefix(r,s,int(stop));part=strategy.ENGINE.execute(rr,ss,config,finish=False)
                support.prefix_equal(full,part,int(stop));counts['未来切断']+=1
                future={name:val.copy() if isinstance(val,np.ndarray) else val for name,val in r.items()}
                for name in ('price','bid','ask'):future[name][stop:]*=7
                poisoned=strategy.ENGINE.execute(future,s,config,finish=False)
                support.prefix_equal(full,poisoned,int(stop));counts['未来自己価格']+=1
                signal={name:val.copy() if isinstance(val,np.ndarray) else val for name,val in s.items()}
                last_g=int(s['mapped'][:stop].max(initial=-1));after=last_g+1
                for name,val in signal.items():
                    if not isinstance(val,np.ndarray):continue
                    if name in ('mapped','quality','reset','event'):
                        if val.dtype==bool:val[stop:]=~val[stop:]
                        elif name=='event':val[stop:]*=-1
                        continue
                    if name=='grid':continue
                    if val.dtype==bool:val[after:]=~val[after:]
                    elif np.issubdtype(val.dtype,np.integer):
                        if val.dtype.itemsize==1:val[after:]*=-1
                        else:val[after:]+=10000
                    else:val[after:]*=7
                poisoned=strategy.ENGINE.execute(r,signal,config,finish=False)
                support.prefix_equal(full,poisoned,int(stop));counts['未来相手及び価格状態']+=1
            del full
        print(config['id']+' 実10接頭部と未来3種が不変',flush=True)
        del prepared
    support.save('全53条件の実接頭部と価格及びBBO別源の未来不変.json',
                 dict(全合格=True,条件数=53,検査件数=counts,完結新損益計算=0,採択用新損益集計=0),
                 [Path(__file__),Path(data.__file__),*material['paths']])


if __name__=='__main__':main()
