"""価格時計の当場5分bucketを逐次確定し、空足や未来の高安を埋めない。"""

import numpy as np


def closed(account: dict,normal: np.ndarray) -> dict:
    """
    機能: session start基準の直前確定5分Last高安と認定rowを各行へ渡す。
    引数: account(dict)、normal(ndarray[bool,N]) は保存recordと正常Last資格。
    返り値: dict[str,ndarray] は高安/元bucket/確定row。原行raw全経路は保証しない。
    """
    r=account['record'];t,p=r['time_s'],r['price'];n=len(t);assert normal.shape==(n,)
    high=np.full(n,np.nan);low=high.copy();bucket_id=np.full(n,-1,np.int64);confirmed=bucket_id.copy()
    active=-1;h=-np.inf;l=np.inf;observations=0;last_high=np.nan;last_low=np.nan;last_bucket=-1;confirm_row=-1
    for row in range(n):
        if not np.isfinite(t[row]) or not(r['start']<=t[row]<r['limit']):continue
        current=int(np.floor((t[row]-r['start'])/300.))
        assert active<0 or current>=active
        if current!=active:
            last_bucket=current-1;confirm_row=row
            if active==current-1 and observations>0:last_high=h;last_low=l
            else:last_high=np.nan;last_low=np.nan
            active=current;h=-np.inf;l=np.inf;observations=0
        high[row]=last_high;low[row]=last_low;bucket_id[row]=last_bucket;confirmed[row]=confirm_row
        if normal[row] and np.isfinite(p[row]) and p[row]>0:
            h=max(h,float(p[row]));l=min(l,float(p[row]));observations+=1
    return dict(high=high,low=low,bucket_id=bucket_id,confirmed_row=confirmed,
        definition='当場start基準の直前bucketだけ。確定row以前へ描き戻さず、空足はNaN、候補では確認row<突破rowを要求。')
