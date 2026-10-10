"""全原本の出来高と売買代金の増分を読み、平均約定価格代理の識別限界を監査する。"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import pickle
import time

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ARRAY_OUT=HERE/'代金差分'
MULTIPLIER={'TOPIX':10000.,'NK225':1000.}
FIELDS=('seq','time_s','last','bid','ask','volume','value','volume_time_s')


def number(value: object) -> float:
    """機能: 有限の数値だけを採用し、欠測を補完しない。

    引数: value(object)。返り値: 数値または欠測(float)。
    """
    try:
        result=float(value)
        return result if math.isfinite(result) else float('nan')
    except (TypeError,ValueError):
        return float('nan')


def timestamp(value: object, cache: dict) -> float:
    """機能: タイムゾーン付き原本時刻を秒へ変換する。

    引数: value(object)、cache(dict)。返り値: 秒または欠測(float)。
    """
    if not isinstance(value,str) or not value:
        return float('nan')
    if value not in cache:
        parsed=datetime.fromisoformat(value)
        assert parsed.tzinfo is not None,value
        cache[value]=parsed.timestamp()
    return cache[value]


def quantiles(values: np.ndarray) -> dict:
    """機能: 有限観測の分位数を、空集合では未定義として保存する。

    引数: values(ndarray)。返り値: 分布(dict)。
    """
    values=values[np.isfinite(values)]
    if not len(values):
        return dict(件数=0,最小=None,中央値=None,百分位95=None,百分位99=None,最大=None)
    q=np.quantile(values,[0,.5,.95,.99,1.])
    return dict(件数=len(values),**{key:float(value) for key,value in zip(('最小','中央値','百分位95','百分位99','最大'),q)})


def classify(price: np.ndarray,bid: np.ndarray,ask: np.ndarray) -> np.ndarray:
    """機能: 直前最良気配に対する平均価格または最後価格の位置を分類する。

    引数: price/bid/ask(ndarray)。返り値: 買い側1・売り側-1・内側0・欠測2の配列(ndarray)。
    真の執行方向や約定内訳の判定ではない。
    """
    result=np.full(len(price),2,np.int8)
    valid=np.isfinite(price)&np.isfinite(bid)&np.isfinite(ask)
    result[valid]=np.where(price[valid]>=ask[valid],1,np.where(price[valid]<=bid[valid],-1,0))
    return result


def classification_table(old: np.ndarray,new: np.ndarray,volume: np.ndarray,mask: np.ndarray) -> dict:
    """機能: 最後価格と平均価格の代理分類の相違を件数と増分枚数で示す。

    引数: old/new/volume/mask(ndarray)。返り値: クロス集計(dict)。
    """
    names={-1:'売り側',0:'内側',1:'買い側',2:'不明'}
    rows=[]
    for a in (-1,0,1,2):
        for b in (-1,0,1,2):
            selected=mask&(old==a)&(new==b)
            rows.append(dict(最後価格分類=names[a],平均価格分類=names[b],件数=int(selected.sum()),出来高増分=float(volume[selected].sum())))
    return dict(件数=int(mask.sum()),出来高増分=float(volume[mask].sum()),
                分類不一致件数=int((mask&(old!=new)).sum()),
                買い売りが直接反転した件数=int((mask&(old*new==-1)&(abs(old)==1)&(abs(new)==1)).sum()),内訳=rows)


def analyze(job: tuple) -> dict:
    """機能: 一つの原本を読み、場内有効板行の増分・時刻・代理方向を監査する。

    引数: job(tuple) はキー、監査済み価格入力、原本ハッシュ。
    返り値: 場別の集計(dict)。個別差分は review 配下の npz だけへ保存する。
    """
    key,ready,expected_hash=job
    session,symbol=key
    begun=time.monotonic();path=ROOT/'book'/symbol/f'{session}.jsonl'
    expected=ready['seq'];n=len(expected)
    data=np.full((n,len(FIELDS)),np.nan)
    hash_value=hashlib.sha256();pointer=raw_count=0
    top_keys=set();quote_keys=set();cache={};first_raw=None
    with path.open('rb') as handle:
        for seq,line in enumerate(handle):
            raw_count+=1;hash_value.update(line)
            if pointer>=n or seq!=expected[pointer]:
                if seq==0:
                    first=json.loads(line)
                    first_raw={name:first.get(name) for name in ('CurrentPriceTime','TradingVolumeTime','TradingVolume','TradingValue','OpeningPriceTime')}
                continue
            raw=json.loads(line)
            top_keys.update(raw)
            bid,ask=raw.get('Buy1') or {},raw.get('Sell1') or {}
            quote_keys.update(bid);quote_keys.update(ask)
            bp,ap=number(bid.get('Price')),number(ask.get('Price'))
            assert 0<bp<ap and number(bid.get('Qty'))>0 and number(ask.get('Qty'))>0,(key,seq)
            last=number(raw.get('CurrentPrice'))
            now=timestamp(raw.get('CurrentPriceTime'),cache)
            vt=timestamp(raw.get('TradingVolumeTime'),cache)
            assert last==ready['last'][pointer] and now==ready['time_s'][pointer],(key,seq)
            assert ready['start']<=now<ready['limit']+300.,(key,seq)
            data[pointer]=[seq,now,last,bp,ap,number(raw.get('TradingVolume')),number(raw.get('TradingValue')),vt]
            pointer+=1
    assert pointer==n and hash_value.hexdigest()==expected_hash,(key,pointer,n)
    columns={name:data[:,i] for i,name in enumerate(FIELDS)}
    contiguous=np.diff(columns['seq'])==1
    volume,value=columns['volume'],columns['value']
    dv,da=np.diff(volume),np.diff(value)
    known_volume=np.isfinite(volume[:-1])&np.isfinite(volume[1:])&(volume[:-1]>=0)&(volume[1:]>=0)
    known_value=np.isfinite(value[:-1])&np.isfinite(value[1:])&(value[:-1]>=0)&(value[1:]>=0)
    known=known_volume&known_value
    delta_good=contiguous&known&(dv>0)&(da>0)
    any_positive=known_volume&(dv>0)
    avg=np.full(n-1,np.nan)
    avg[known&(dv>0)&(da>0)]=da[known&(dv>0)&(da>0)]/(dv[known&(dv>0)&(da>0)]*MULTIPLIER[symbol])
    before_bid,before_ask=columns['bid'][:-1],columns['ask'][:-1]
    old=classify(columns['last'][1:],before_bid,before_ask)
    new=classify(avg,before_bid,before_ask)
    tick=float(ready['tick'])
    units=da/(MULTIPLIER[symbol]*tick)
    tick_consistent=np.isfinite(units)&(abs(units-np.rint(units))<1e-7)
    low=np.minimum.reduce([columns[name][:-1] for name in ('last','bid','ask')]+[columns[name][1:] for name in ('last','bid','ask')])
    high=np.maximum.reduce([columns[name][:-1] for name in ('last','bid','ask')]+[columns[name][1:] for name in ('last','bid','ask')])
    local_range=(avg>=low-1e-7)&(avg<=high+1e-7)
    local_range_one_tick=(avg>=low-tick-1e-7)&(avg<=high+tick+1e-7)
    volume_time=columns['volume_time_s'];quote_time=columns['time_s']
    clock_known=np.isfinite(volume_time[:-1])&np.isfinite(volume_time[1:])
    clocks_not_ahead=clock_known&(volume_time[:-1]<=quote_time[:-1])&(volume_time[1:]<=quote_time[1:])
    combined=delta_good&tick_consistent&local_range_one_tick&clocks_not_ahead
    # ----------------------------------------
    # 不明や不整合を捨てず、比較に使える範囲と使えない範囲を別に残す。
    counts={
        '読取原本行':raw_count,'有効気配行':n,'隣接観測対':n-1,
        '原本行連続対':int(contiguous.sum()),'不正行を跨いだ対':int((~contiguous).sum()),
        '出来高欠測対':int((~known_volume).sum()),'代金欠測対':int((~known_value).sum()),
        '連続対で出来高減少':int((contiguous&known_volume&(dv<0)).sum()),
        '連続対で代金減少':int((contiguous&known_value&(da<0)).sum()),
        '連続対で両方減少':int((contiguous&known&(dv<0)&(da<0)).sum()),
        '連続対で出来高増加':int((contiguous&known_volume&(dv>0)).sum()),
        '連続対で両方正増分':int(delta_good.sum()),
        '連続対で出来高増加代金ゼロ':int((contiguous&known&(dv>0)&(da==0)).sum()),
        '連続対で出来高増加代金減少':int((contiguous&known&(dv>0)&(da<0)).sum()),
        '連続対で出来高ゼロ代金正増分':int((contiguous&known&(dv==0)&(da>0)).sum()),
        '連続対で出来高ゼロ代金減少':int((contiguous&known&(dv==0)&(da<0)).sum()),
        '両正増分の総代金が呼値会計不整合':int((delta_good&~tick_consistent).sum()),
        '両正増分の平均価格が呼値上にない':int((delta_good&(abs(avg/tick-np.rint(avg/tick))>1e-7)).sum()),
        '両正増分の平均が前後価格範囲外':int((delta_good&~local_range).sum()),
        '両正増分の平均が前後価格範囲から一呼値超外':int((delta_good&~local_range_one_tick).sum()),
        '有効行で出来高時刻欠測':int((~np.isfinite(volume_time)).sum()),
        '有効行で出来高時刻が約定時刻より先':int((volume_time>quote_time).sum()),
        '有効行で出来高時刻が約定時刻と同じ':int((volume_time==quote_time).sum()),
        '有効行で出来高時刻が約定時刻より前':int((volume_time<quote_time).sum()),
        '連続行で出来高増加かつ出来高時刻不変':int((contiguous&known_volume&(dv>0)&(np.diff(volume_time)==0)).sum()),
        '連続行で出来高ゼロかつ出来高時刻変更':int((contiguous&known_volume&(dv==0)&(np.diff(volume_time)!=0)).sum()),
        '連続行で約定時刻不変':int((contiguous&(np.diff(quote_time)==0)).sum()),
        '連続行で約定時刻不変かつ最良気配変更':int((contiguous&(np.diff(quote_time)==0)&((np.diff(columns['bid'])!=0)|(np.diff(columns['ask'])!=0))).sum()),
        '代金平均の整合条件を満たす対':int(combined.sum()),
    }
    indices=np.flatnonzero(any_positive)
    saved={name:columns[name][1:][indices] for name in FIELDS}
    saved.update(previous_seq=columns['seq'][:-1][indices],previous_time_s=quote_time[:-1][indices],
                 previous_bid=before_bid[indices],previous_ask=before_ask[indices],
                 previous_last=columns['last'][:-1][indices],previous_volume_time_s=volume_time[:-1][indices],
                 volume_delta=dv[indices],value_delta=da[indices],average_price=avg[indices],
                 old_class=old[indices],average_class=new[indices],raw_contiguous=contiguous[indices],
                 delta_good=delta_good[indices],value_tick_consistent=tick_consistent[indices],
                 local_range=local_range[indices],local_range_one_tick=local_range_one_tick[indices],
                 clocks_not_ahead=clocks_not_ahead[indices],consistency_pass=combined[indices])
    target=ARRAY_OUT/f'{session}_{symbol}.npz'
    np.savez_compressed(target,**saved)
    outliers=np.flatnonzero(delta_good&~local_range_one_tick)
    examples=[]
    if len(outliers):
        distances=np.maximum(low[outliers]-avg[outliers],avg[outliers]-high[outliers])/tick
        for i in outliers[np.argsort(distances)[-5:][::-1]]:
            examples.append(dict(原本行=int(columns['seq'][i+1]),時刻=float(quote_time[i+1]),
                                 出来高差=float(dv[i]),代金差=float(da[i]),平均価格=float(avg[i]),
                                 前後価格下限=float(low[i]),前後価格上限=float(high[i]),
                                 最後価格=float(columns['last'][i+1]),出来高時刻=float(volume_time[i+1])))
    clockdiff=volume_time-quote_time
    return dict(セッション=session,銘柄=symbol,原本SHA256=hash_value.hexdigest(),件数=counts,
                全体先頭行=first_raw,最初の有効行=dict(時刻=float(quote_time[0]),出来高=float(volume[0]),代金=float(value[0])),
                分布=dict(両正増分の出来高=quantiles(dv[delta_good]),
                          両正増分の平均と最後価格の差絶対値呼値=quantiles(abs(avg[delta_good]-columns['last'][1:][delta_good])/tick),
                          出来高時刻と約定時刻の差秒=quantiles(clockdiff)),
                旧分類と平均分類_両正増分=classification_table(old,new,dv,delta_good),
                旧分類と平均分類_整合条件=classification_table(old,new,dv,combined),
                top_level_keys=sorted(top_keys),best_quote_keys=sorted(quote_keys),
                一呼値超範囲外の例=examples,差分保存=str(target.relative_to(ROOT)),処理秒=round(time.monotonic()-begun,2))


def main() -> None:
    """機能: 全46原本を並列で読み、出来高と代金の同期監査を保存する。

    引数: なし。返り値: なし(None)。原本・旧成果・APIへ書き込まない。
    """
    ARRAY_OUT.mkdir(parents=True,exist_ok=True)
    inputs=pickle.loads((ROOT/'work/wave_v55/clean_inputs.pkl').read_bytes())
    baseline=json.loads((ROOT/'work/wave_v52/measurement/気配キャッシュ監査.json').read_text(encoding='utf-8'))
    hashes={(r['セッション'],r['銘柄']):r['原本SHA256'] for r in baseline['原本別']}
    assert set(inputs)==set(hashes) and len(inputs)==46
    jobs=[(key,inputs[key],hashes[key]) for key in sorted(inputs)]
    results=[]
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(analyze,job):job[0] for job in jobs}
        for future in as_completed(futures):
            row=future.result();results.append(row)
            print(row['セッション'],row['銘柄'],'正増分',row['件数']['連続対で両方正増分'],
                  '代金停滞',row['件数']['連続対で出来高増加代金ゼロ'],
                  '完了',len(results),'/46',flush=True)
    results.sort(key=lambda r:(r['セッション'],r['銘柄']))
    symbols={}
    for symbol in ('TOPIX','NK225'):
        rows=[r for r in results if r['銘柄']==symbol]
        counts={name:sum(r['件数'][name] for r in rows) for name in rows[0]['件数']}
        comparisons={}
        for name in ('旧分類と平均分類_両正増分','旧分類と平均分類_整合条件'):
            comparisons[name]={field:sum(r[name][field] for r in rows)
                               for field in ('件数','出来高増分','分類不一致件数','買い売りが直接反転した件数')}
            comparisons[name]['内訳']=[dict(最後価格分類=rows[0][name]['内訳'][i]['最後価格分類'],
                                         平均価格分類=rows[0][name]['内訳'][i]['平均価格分類'],
                                         件数=sum(r[name]['内訳'][i]['件数'] for r in rows),
                                         出来高増分=sum(r[name]['内訳'][i]['出来高増分'] for r in rows)) for i in range(16)]
        symbols[symbol]=dict(件数=counts,**comparisons)
    output=dict(合格=True,原本数=len(results),現在API取得数=0,コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                対象='保存済み46原本のDay08:45〜15:40未満/Night17:00〜翌05:55未満、最良買い<最良売り・両数量正の既存有効行。最初の行の量は基準にするだけで前場から差分を作らない。',
                平均価格='ΔTradingValue/(ΔTradingVolume×ラージ倍率)。TOPIX10000、NK2251000。正増分だけで算出。',
                整合条件='原本行連続、出来高と代金とも正増分、代金の呼値会計が整数、前後の最後/買い/売り価格範囲±1呼値以内、前後出来高時刻が各約定時刻より先でない。真の同期を証明する条件ではない。',
                呼値の注意='複数約定の平均価格は呼値単位でなくて正常。Δ代金/(倍率×呼値)の整数性を別に監査する。',
                時刻の注意='CurrentPriceTimeは最終約定時計。TradingValueTimeと受信時計は記録されず、気配のTimeもない。',
                範囲外の注意='前後価格範囲外でも中間価格の実取引があり得る。すべてを不正とは断定しない。',
                分類の注意='最後価格または増分平均が直前売気配以上なら買い側、買気配以下なら売り側、その間は内側。個別約定のaggressor、新規/返済、心理、主体は復元しない。',
                銘柄別=symbols,各場=results)
    (HERE/'売買代金と出来高の同期監査.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(合格=True,原本数=len(results),銘柄別={s:symbols[s]['件数'] for s in symbols}),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
