"""保存された主担当の入口を固定し、実保有中の逆行確認だけで早期返済する。"""

import numpy as np
from numba import njit


@njit(cache=True)
def candidate(times, features, start, end, side, kind, hold):
    """
    機能: 保有中の二市場逆行が継続した最初の判断行を返す。
    引数: times/features(ndarray)、start/end/side/kind(int)、hold(float)は原行・方向・板確認種別・持続幅。
    返り値: intは因果的な退出判断行。条件不成立は-1。
    """
    since = -np.inf
    for i in range(start,end):
        if i>start and times[i]-times[i-1]>15.:
            since=-np.inf
        a=features[i]
        adverse=np.isfinite(a[10]) and np.isfinite(a[12]) and np.isfinite(a[13]) and np.isfinite(a[20]) and np.isfinite(a[21])
        adverse=adverse and side*a[12]<=-.1 and side*a[20]<=-.1 and side*a[13]<0. and side*a[21]<0.
        if kind==2:
            adverse=adverse and np.isfinite(a[24]) and np.isfinite(a[26]) and side*a[24]<0. and side*a[26]<0.
        if adverse:
            if not np.isfinite(since):since=times[i]
            if times[i]-since>=hold:return i
        else:since=-np.inf
    return -1


def replay(data, baseline, kind):
    """
    機能: 元の新規・部分返済を保ち、既発注返済より前に逆行確認した場合だけ残玉を次原行で返済する。
    引数: data(dict)、baseline(ndarray)、kind(int)は原行特徴・元十列注文・価格1又は板確認2。
    返り値: ndarrayは新しい十列注文。出口変更後の新規候補は元主担当の通知に限定する。
    """
    times=data['ready']['time_s'];quotes=data['quotes'];a=data['features']
    fee=385 if data['ready']['symbol']=='NK225' else 418
    valid=quotes['quote_valid']&np.isfinite(quotes['bid'])&np.isfinite(quotes['ask'])&(quotes['ask']>quotes['bid'])
    normal=np.flatnonzero(valid);out=[]
    for parent in np.unique(baseline[:,2]) if len(baseline) else []:
        rows=baseline[baseline[:,2]==parent].copy();side=int(rows[0,3])
        decision=candidate(times,a,int(rows[0,0]),int(rows[-1,1]),side,kind,15.)
        if decision<0:
            out.extend(rows);continue
        # ----------------------------------------
        # 既に発注済みの元返済を先に成立させる。約定未来を見て取消す操作はしない。
        queued=rows[(rows[:,7]==0)&(rows[:,1]<=decision)&(rows[:,0]>decision)]
        if len(queued):
            decision=max(decision,int(queued[-1,0]))
        j=np.searchsorted(normal,decision,side='right')
        assert j<len(normal)
        fill=int(normal[j]);tickets={}
        for row in rows:
            if int(row[0])>decision:break
            uid=int(row[8]);qty=int(row[4]);out.append(row)
            tickets[uid]=tickets.get(uid,0)+(qty if row[7] else -qty)
        for uid,qty in tickets.items():
            if qty:
                price=quotes['bid'][fill] if side>0 else quotes['ask'][fill]
                out.append(np.array([fill,decision,parent,-side,qty,price,1413+kind,0,uid,qty*fee//10]))
    result=np.asarray(out,dtype=float).reshape(-1,10)
    return result[np.argsort(result[:,0],kind='stable')] if len(result) else result
