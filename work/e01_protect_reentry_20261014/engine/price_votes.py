"""保存正常Last更新だけを数え、自己原行上限とpeer厳密過去の価格票を作る。"""

import numpy as np


def normal(account: dict) -> np.ndarray:
    """
    機能: 保存quote資格と有限正Last/BBO/価格時計を価格更新の資格へ結ぶ。
    引数: account(dict) は保存record/quotes。
    返り値: ndarray[bool,N] は価格票に使える正常行。量/出来高を補完しない。
    """
    r,q=account['record'],account['quotes']
    valid=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])&np.isfinite(r['price'])&(r['price']>0)&np.isfinite(r['time_s'])
    maximum_time=-np.inf;maximum_seq=-1
    for row,(clock,seq) in enumerate(zip(r['time_s'],r['seq'])):
        if not np.isfinite(clock) or clock<maximum_time or seq<=maximum_seq:valid[row]=False
        if np.isfinite(clock):maximum_time=max(maximum_time,clock)
        maximum_seq=max(maximum_seq,int(seq))
    return valid


def measure(account: dict, window: float=60.) -> dict:
    """
    機能: 正常行Lastの非零隣接差を各一票として現在までの直近窓を集計する。
    引数: account(dict)、window(float) は保存口座と価格代理秒。
    返り値: dict は全行known/up/down/count/balanceと基準系譜。equalは票無し。
    """
    r=account['record'];times=r['time_s'];prices=r['price'];n=len(times);valid=normal(account)
    rows=np.flatnonzero(valid);t=times[rows];last=prices[rows]
    assert np.all(t[1:]>=t[:-1])
    up=np.zeros(len(rows),np.int64);down=up.copy()
    if len(rows)>1:
        delta=last[1:]-last[:-1];up[1:]=(delta>0);down[1:]=(delta<0)
    cum_up=np.cumsum(up);cum_down=np.cumsum(down)
    known=np.zeros(n,bool);u=np.zeros(n,np.int64);d=u.copy();balance=np.full(n,np.nan)
    reference=np.full(n,-1,np.int64)
    for j,row in enumerate(rows):
        at=int(np.searchsorted(t,t[j]-window,side='right')-1)
        if at<0:continue
        # 同clock基準の後半を未来に拾わない。基準clockは現在から60秒前なので常にjより前。
        assert at<j
        reference[row]=rows[at];known[row]=True
        u[row]=cum_up[j]-cum_up[at];d[row]=cum_down[j]-cum_down[at]
        total=u[row]+d[row];balance[row]=(u[row]-d[row])/total if total else 0.
    return dict(known=known,up=u,down=d,count=u+d,balance=balance,reference_row=reference,
        end_row=np.where(known,np.arange(n),-1).astype(np.int64),price_time_s=times.copy(),normal=valid)


def pair(packet: dict, window: float=60., max_age: float=60.) -> dict:
    """
    機能: 自己は当行まで、相手は当行時計より厳密過去の正常末端から価格票を投影する。
    引数: packet(dict)、window/max_age(float) は同保存二商品と価格時計の窓/年齢。
    返り値: dict[symbol,dict] は自己/相手票の全normal長配列。同clockpeerは採用しない。
    """
    accounts=packet['accounts'];measured={s:measure(a,window) for s,a in accounts.items()};output={}
    for symbol in ('TOPIX','NK225'):
        peer='NK225' if symbol=='TOPIX' else 'TOPIX';own=measured[symbol];other=measured[peer]
        peer_rows=np.flatnonzero(other['normal']);peer_times=accounts[peer]['record']['time_s'][peer_rows]
        n=len(own['known']);known=np.zeros(n,bool);count=np.zeros(n,np.int64);balance=np.full(n,np.nan)
        selected=np.full(n,-1,np.int64);age=np.full(n,np.nan);seq=np.full(n,-1,np.int64)
        position=np.searchsorted(peer_times,accounts[symbol]['record']['time_s'],side='left')-1
        for row,pos in enumerate(position):
            if not own['normal'][row] or pos<0:continue
            end=int(peer_rows[pos]);elapsed=float(accounts[symbol]['record']['time_s'][row]-peer_times[pos]);assert elapsed>0
            selected[row]=end;age[row]=elapsed;seq[row]=accounts[peer]['record']['seq'][end]
            if elapsed<=max_age and other['known'][end]:
                known[row]=True;count[row]=other['count'][end];balance[row]=other['balance'][end]
        output[symbol]=dict(own=own,peer_known=known,peer_count=count,peer_balance=balance,
            peer_row=selected,peer_raw_seq=seq,peer_price_age_seconds=age,
            definition='正常Last非零差の価格方向代理。出来高/攻撃注文票とは別。自己当行まで、peer strict PriceTime。')
    return output
