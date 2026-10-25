"""金融判断を含まない人工板から、凍結 Python 特徴の小型基準値を作る。"""

import gzip
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "work/nikkei143_20261024"))
import common143 as shared
import raw141


def safe(value):
    """
    機能: JSON の未知値を null へ変換する。
    引数: value(list又は数値)。返り値: list又は有限数値又はNone。
    """
    if isinstance(value, list):
        return [safe(x) for x in value]
    return None if isinstance(value, float) and not np.isfinite(value) else value


def main():
    """
    機能: 同時計・欠測段・不正板・価格時計空白を含む人工二市場を参照実装へ入力する。
    引数: なし。返り値: None。特徴だけを作り、注文核や金融会計は実行しない。
    """
    scene, start = "2026-10-22_Day", 1792626300.
    packet = dict(session=scene, inputs={}, quotes={})
    books, records = {}, {}
    for symbol, tick, step, offset in (("NK225",10.,7.,1.),("TOPIX",.5,9.,2.)):
        times = np.arange(offset,3900,step)
        times = times[(times<240) | (times>420)]
        times = np.sort(np.r_[times, 1370.,1370.,1370.,2600.,2600.])+start
        n = len(times); seq=np.arange(n)
        mid = (65000 if symbol=="NK225" else 4000)+tick*np.floor((times-start)/70+7*np.sin((times-start)/180))
        bid, ask = mid-tick*.5, mid+tick*.5
        bid[seq%79==50]=np.nan
        ask[seq%79==51]=bid[seq%79==51]
        qtyb, qtya = 10+seq%11, 11+seq%13
        buyprice = bid[:,None]-np.arange(10)*tick
        sellprice = ask[:,None]+np.arange(10)*tick
        buyqty = qtyb[:,None]+np.arange(10)*2
        sellqty = qtya[:,None]+np.arange(10)*3
        buyprice[seq%17==0,8:] = np.nan
        sellprice[seq%19==0,7:] = np.nan
        buyqty = buyqty.astype(float); sellqty=sellqty.astype(float)
        buyqty[seq%53==15,0]=0.
        arrays=dict(time_s=times, buy_price=buyprice,buy_qty=buyqty,sell_price=sellprice,sell_qty=sellqty,
                    last=mid.copy(),volume=np.arange(n,dtype=float),volume_time_s=times.copy())
        raw141.features(arrays,symbol,scene); books[symbol]=arrays
        valid=np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)
        atr=np.where(times-start<300,np.nan,16*tick)
        r=dict(time_s=times,last=mid,atr=atr,tick=tick,start=start,limit=start+24600,us_open=np.nan,seq=seq,session=scene,symbol=symbol)
        packet['inputs'][scene,symbol]=r
        packet['quotes'][scene,symbol]=dict(bid=bid,ask=ask,quote_valid=valid)
        records[symbol]=dict(times=times,mid=mid,bid=bid,ask=ask,atr=atr)
    data=shared.previous.first.original.prepare(packet,40)
    evidence=shared.previous.first.evidence141
    for symbol,d in data.items():
        b=books[symbol]; seq=np.arange(len(b['time_s']))
        extras=[evidence.past_mean(b['time_s'],b[k],seq,30.) for k in ('ofi_normalized','distance_imbalance')]
        d['features']=np.column_stack((d['features'],*extras,np.full((len(seq),2),np.nan)))
    for symbol,d in data.items():
        peer=data['TOPIX' if symbol=='NK225' else 'NK225']; t=d['ready']['time_s'];pt=peer['ready']['time_s']
        j=np.searchsorted(pt,t,side='left')-1; safej=np.maximum(j,0); valid=(j>=0)&(t-pt[safej]<=15)
        d['features'][valid,26:28]=peer['features'][safej[valid],24:26]
    _,_,hist,_=shared.prior.common.features129.build(packet,'mid',0.)
    events=[]
    for symbol,d in data.items():
        t=d['ready']['time_s']; b=books[symbol]
        f=np.column_stack((d['features'],hist[scene,symbol][:,7],hist[scene,symbol][:,11]))
        h20=shared.previous.first.original.history(t,d['features'][:,10],start,20)
        h40=shared.previous.first.original.history(t,d['features'][:,10],start,40)
        for i in range(len(t)):
            events.append(dict(symbol=symbol,time=float(t[i]),row=i,last=float(b['last'][i]),bid=float(b['bid'][i]),ask=float(b['ask'][i]),
                atr=float(d['ready']['atr'][i]),bid_quantity=float(b['buy_qty'][i,0]),ask_quantity=float(b['sell_qty'][i,0]),
                bid_levels=safe(np.column_stack((b['buy_price'][i],b['buy_qty'][i])).tolist()),
                ask_levels=safe(np.column_stack((b['sell_price'][i],b['sell_qty'][i])).tolist()),
                features=safe(f[i].tolist()),band20=safe(h20[i].tolist()),band40=safe(h40[i].tolist())))
    events.sort(key=lambda e:(e['time'],e['symbol'],e['row']))
    text=json.dumps(dict(session=scene,start=start,events=events,scope='人工特徴同値。金融再生なし。'),ensure_ascii=False,allow_nan=True,separators=(',',':'))
    text=text.replace('NaN','null')
    path=ROOT/'App/SessionTrader/internal/strategy/testdata/research_features143.json.gz'
    path.write_bytes(gzip.compress(text.encode(),compresslevel=9,mtime=0))
    evidence=dict(events=len(events),path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),financial_replays=0)
    (HERE/'人工特徴基準143.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(evidence)


if __name__=='__main__': main()
