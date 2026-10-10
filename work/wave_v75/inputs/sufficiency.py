"""損益を見ずに、鮮度制限ごとの二銘柄同時観測と履歴窓の入力十分性だけを比較する。"""

import numpy as np

import core
import prepare


def availability(grid: np.ndarray, ready: dict, features: dict, session: str,
                 delay: int, max_age: int, window: int) -> tuple[np.ndarray,np.ndarray]:
    """機能: 両銘柄の参照終点と履歴始点が使えるか、途中resetがないか検査する。

    引数: grid(ndarray)、ready/features(dict)、session(str)、delay/max_age/window(int)。
    返り値: 始終点とも利用可能なマスクと途中resetもないマスク(tuple[ndarray,ndarray])。
    時刻の空白そのものを受信停止とはみなさず、損益と価格変化の方向を採点しない。
    """
    endpoints=np.ones(len(grid),dtype=bool)
    uninterrupted=endpoints.copy()
    for symbol in ('TOPIX','NK225'):
        key=(session,symbol)
        r,f=ready[key],features[key]
        end,_=core.asof_indices(grid-delay,r['time_s'],f['valid'],f['reset'],max_age)
        start,_=core.asof_indices(grid-delay-window,r['time_s'],f['valid'],f['reset'],max_age)
        good=(end>=0)&(start>=0)
        endpoints&=good
        bad=np.concatenate(([0],np.cumsum((~f['valid'])|f['reset'],dtype=np.int64)))
        clean=np.zeros(len(grid),dtype=bool)
        clean[good]=(bad[end[good]+1]-bad[start[good]])==0
        uninterrupted&=clean
    return endpoints,uninterrupted


def main() -> None:
    """機能: 鮮度10・30・60秒を同じ判断グリッドで比較し、統計だけを別JSONへ保存する。

    引数: なし。返り値: なし(None)。凍結前の入力十分性評価であり、既存syncを変更しない。
    """
    ready,features=prepare.load_material()
    sessions=sorted({k[0] for k in ready})
    rows=[]
    for session in sessions:
        r=ready[(session,'TOPIX')]
        grid=np.arange(r['start']+300.,r['limit']-300.,15.,dtype=np.float64)
        for freshness in (10,30,60):
            for delay in prepare.DELAYS:
                d=dict(session=session,delay=delay,max_age=freshness,grid_count=len(grid))
                for window in (0,15,60,300):
                    endpoints,clean=availability(grid,ready,features,session,delay,freshness,window)
                    d[f'endpoints_{window}']=int(endpoints.sum())
                    d[f'uninterrupted_{window}']=int(clean.sum())
                rows.append(d)
    totals=[]
    for freshness in (10,30,60):
        for delay in prepare.DELAYS:
            current=[r for r in rows if r['max_age']==freshness and r['delay']==delay]
            values={k:sum(r[k] for r in current) for k in current[0] if k not in ('session','delay','max_age')}
            totals.append(dict(delay=delay,max_age=freshness,**values,
                fractions={k:values[k]/values['grid_count'] for k in values if k!='grid_count'}))
    prepare.save_json('鮮度別の入力十分性.json',dict(sessions=sessions,accounts=len(ready),rows=rows,totals=totals,
        定義='双方のstrict過去同時計先頭と、同じ方法で過去15・60・300秒の始点を採取。端点利用数と区間resetなし数を別記。方向性条件は課していない。',
        注意='CurrentPriceTimeの空白は板受信停止ではない。鮮度を緩めるほど代理時計上の過去板が古くなり、実受信順保証は増えない。',
        既存sync変更=False,損益閲覧=0,API取得=0,実注文=0))
    for t in totals:
        if t['delay']==5:
            print(f"鮮度{t['max_age']}秒: 両終点{t['endpoints_0']}/{t['grid_count']}、15秒無reset{t['uninterrupted_15']}、60秒{t['uninterrupted_60']}、300秒{t['uninterrupted_300']}",flush=True)


if __name__=='__main__':
    main()
