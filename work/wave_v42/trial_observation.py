"""旧帯を変えず、試行内の原本数量差分だけを次の公開行で確定する。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path

import numpy as np


def number(value: object) -> float:
    """機能: 有限数だけを抽出し、欠測をNaNとして保持する。

    引数: value (object)。返り値: 数値又はNaN (float)。
    """
    if isinstance(value,bool):return float('nan')
    try:result=float(value)
    except (TypeError,ValueError):return float('nan')
    return result if math.isfinite(result) else float('nan')


def ranges_for(settings: dict) -> list[tuple[int,int]]:
    """機能: 旧試行の原本範囲を作り、重複区間を束ねる。

    引数: settings (dict[str,list[dict]]) は1市場の10設定。返り値: 両端包含区間 (list[tuple])。
    """
    ranges=[]
    for bands in settings.values():
        for band in bands:
            for trial in band['trials']:
                first=int(trial['start']['seq'])
                last=int(trial['end']['seq'] if trial['end'] is not None else trial['samples'][-1]['seq'])
                assert first<=last
                ranges.append((first,last))
    merged=[]
    for first,last in sorted(ranges):
        if merged and first<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(last,merged[-1][1]))
        else:merged.append((first,last))
    return merged


def read_material(path: Path, settings: dict, events: dict) -> dict:
    """機能: 試行範囲内の原本10段を直接読み、初めて利用できる公開seqを割り当てる。

    引数: path (Path)、settings/events (dict)。返り値: 生板列と公開列 (dict[str,ndarray])。
    公開後続まで同秒行を封印する。旧5段mapや完成済み集計は使わない。
    """
    spans=ranges_for(settings);index=0;seqs=[];times=[];values=[]
    if spans:
        with path.open('rb') as stream:
            for seq,line in enumerate(stream):
                while index<len(spans) and seq>spans[index][1]:index+=1
                if index==len(spans):break
                if seq<spans[index][0]:continue
                raw=json.loads(line);stamp=raw.get('CurrentPriceTime');time=float('nan')
                if stamp:
                    parsed=datetime.fromisoformat(stamp)
                    assert parsed.tzinfo is not None
                    time=parsed.timestamp()
                row=np.full((4,10),np.nan)
                for side,pi,qi in [('Buy',0,2),('Sell',1,3)]:
                    for level in range(1,11):
                        item=raw.get(f'{side}{level}') or {}
                        p,q=number(item.get('Price')),number(item.get('Qty'))
                        if p>0:row[pi,level-1]=p
                        if q>=0:row[qi,level-1]=q
                seqs.append(seq);times.append(time);values.append(row)
    seqs=np.asarray(seqs,np.int64);times=np.asarray(times,float)
    array=np.asarray(values,float).reshape((-1,4,10))
    release=np.searchsorted(events['seq'],seqs,side='left')
    assert np.all(release<len(events['seq']))
    release_seq=events['seq'][release];release_time=events['time_s'][release]
    assert np.all(seqs<=release_seq)
    finite=np.isfinite(times);assert np.all(times[finite]<=release_time[finite])
    return dict(seq=seqs,time_s=times,bid_prices=array[:,0],ask_prices=array[:,1],
        bid_qty=array[:,2],ask_qty=array[:,3],release_seq=release_seq.copy(),
        release_time_s=release_time.copy(),release_ready_index=events['ready_index'][release].copy())


def quantities(material: dict, direction: int, price: float) -> tuple[np.ndarray,np.ndarray]:
    """機能: 固定Pの同側数量と、排他的な不明理由を全原本行で求める。

    引数: material (dict)、direction (int)、price (float)。
    返り値: 数量と理由番号 (tuple[ndarray,ndarray])。他側や見えない価格を0にしない。
    """
    prefix='ask' if direction==1 else 'bid'
    prices=material[prefix+'_prices'];amounts=material[prefix+'_qty']
    matches=prices==price;count=matches.sum(axis=1);n=len(count)
    output=np.full(n,np.nan);reason=np.zeros(n,np.int8)
    one=count==1;selected=np.argmax(matches,axis=1)
    found=amounts[np.arange(n),selected]
    good=one & np.isfinite(found) & (found>=0)
    output[good]=found[good]
    reason[count>1]=1;reason[one & ~good]=2
    missing=count==0;complete=np.isfinite(prices).all(axis=1)
    reason[missing & ~complete]=3
    if n:
        safe=np.where(np.isfinite(prices),prices,price)
        outside=(price<safe.min(axis=1)) | (price>safe.max(axis=1))
        reason[missing & complete & outside]=4
        reason[missing & complete & ~outside]=5
    assert np.array_equal(reason==0,np.isfinite(output))
    return output,reason


REASONS={1:'同側P重複',2:'P数量不正',3:'価格段欠損でP不明',4:'同側10段価格範囲外',5:'同側範囲内だが非掲載'}


def observe_trial(material: dict, quantity: np.ndarray, reasons: np.ndarray, trial: dict,
                  asof_seq: int | None = None) -> dict | None:
    """機能: 開始数量以後の差分を集計し、公開境界と終了確認を守って保存する。

    引数: material (dict)、quantity/reasons (ndarray)、trial (dict)、asof_seq (int|None)。
    返り値: 試行の公開累積記録 (dict|None)。未開始はNone、未完比率もNone。
    """
    start=int(trial['start']['seq'])
    end=int(trial['end']['seq'] if trial['end'] is not None else trial['samples'][-1]['seq'])
    cutoff=int(material['release_seq'][-1]) if asof_seq is None and len(material['seq']) else asof_seq
    if cutoff is None or start>cutoff:return None
    left=int(np.searchsorted(material['seq'],start,side='left'))
    right=int(np.searchsorted(material['seq'],end,side='right'))
    assert left<right and material['seq'][left]==start and material['seq'][right-1]==end
    assert np.all(np.diff(material['seq'][left:right])==1)
    right=min(right,int(np.searchsorted(material['release_seq'],cutoff,side='right')))
    if left>=right:return None
    unknown_old=[int(s['seq']) for s in trial['samples'] if s['quantity'] is None]
    sample_seq=np.asarray([s['seq'] for s in trial['samples']],np.int64)
    old_failure=min(unknown_old) if unknown_old else None
    previous=None;decrease=0.;increase=0.;first_decrease=None;unknown=Counter();missing_time=0
    public=[];count=0
    for i in range(left,right):
        q=float(quantity[i]) if np.isfinite(quantity[i]) else None
        count+=1
        if not np.isfinite(material['time_s'][i]):missing_time+=1
        if q is None:unknown[REASONS[int(reasons[i])]]+=1
        elif previous is not None:
            difference=q-previous
            if difference<0:
                decrease-=difference
                if first_decrease is None:first_decrease=int(material['seq'][i])
            elif difference>0 and first_decrease is not None:increase+=difference
        previous=q
        # ----------------------------------------
        # 同秒群の途中では公開しない。必ず公開seqまで処理済みの境界に限る。
        if i+1<right and material['release_seq'][i+1]==material['release_seq'][i]:continue
        release=int(material['release_seq'][i]);assert material['seq'][i]==release
        complete=bool(trial['complete'] and trial['end'] is not None and release>=trial['end']['seq'])
        old_known=old_failure is None or release<old_failure
        raw_known=not unknown
        local=increase/decrease if complete and raw_known and decrease>0 else None
        strict=local if old_known else None
        none_reasons=[]
        if not complete:none_reasons.append('試行の完了未確認')
        if not raw_known:none_reasons.append('原本P不明あり')
        if decrease==0:none_reasons.append('可視減少0')
        strict_reasons=none_reasons+([] if old_known else ['旧公開数量品質不明'])
        public.append(dict(release_seq=release,release_time_s=float(material['release_time_s'][i]),
            ready_index=int(material['release_ready_index'][i]),material_first_seq=start,
            material_last_seq=int(material['seq'][i]),raw_row_count=count,
            decrease=decrease,increase_after_decrease=increase,first_decrease_seq=first_decrease,
            raw_quantity_known=raw_known,old_quantity_known_so_far=old_known,
            raw_unknown_reason_counts=dict(unknown),missing_time_count=missing_time,
            public_sample_count=int(np.searchsorted(sample_seq,release,side='right')),
            complete_available=complete,u_strict=strict,u_local=local,
            strict_none_reasons=strict_reasons,local_none_reasons=none_reasons))
    assert public
    last=public[-1]
    return dict(number=int(trial['number']),start=trial['start'],
        end=trial['end'] if trial['end'] is not None and trial['end']['seq']<=cutoff else None,
        complete_available=last['complete_available'],
        ratio_available_seq=int(trial['end']['seq']) if last['complete_available'] else None,
        u_strict=last['u_strict'],u_local=last['u_local'],
        raw_row_count=last['raw_row_count'],public_sample_count=sum(s['seq']<=cutoff for s in trial['samples']),
        publications=public)


def features(band: dict, trials: list[dict], mode: str) -> dict:
    """機能: 二試行が利用可能になった場合だけ追加特徴を作る。

    引数: band (dict)、trials (list[dict])、mode (str)。返り値: 追加特徴 (dict)。
    """
    complete=len(trials)==2 and all(t['complete_available'] for t in trials)
    if not complete:
        return dict(two_trials_complete=False,quantity_comparable=False,price_comparable=False,
            u1=None,u2=None,b1=None,b2=None,quantity_change=None,pushback_change=None,
            quantity_weakens=None,price_weakens=None,available_seq=None)
    u1,u2=[t['u_'+mode] for t in trials]
    known=u1 is not None and u2 is not None
    old=band['features']
    assert old['two_trials_complete']
    return dict(two_trials_complete=True,quantity_comparable=known,price_comparable=True,
        u1=u1,u2=u2,b1=old['b1'],b2=old['b2'],quantity_change=u2-u1 if known else None,
        pushback_change=old['pushback_change'],quantity_weakens=bool(u2<u1) if known else None,
        price_weakens=old['price_weakens'],available_seq=max(t['ratio_available_seq'] for t in trials))


def build(material: dict, bands: list[dict], asof_seq: int | None = None) -> list[dict]:
    """機能: 旧帯の時刻をそのまま参照し、新数量特徴の独立パネルを作る。

    引数: material (dict)、bands (list[dict])、asof_seq (int|None)。
    返り値: 原帯に対応する追加パネル (list[dict])。旧帯は書き換えない。
    """
    result=[]
    for band in bands:
        if asof_seq is not None and band['created']['seq']>asof_seq:continue
        trials=[]
        for trial in band['trials']:
            start=trial['start']['seq']
            end=trial['end']['seq'] if trial['end'] is not None else trial['samples'][-1]['seq']
            left=int(np.searchsorted(material['seq'],start,side='left'))
            right=int(np.searchsorted(material['seq'],end,side='right'))
            portion={key:value[left:right] for key,value in material.items()}
            quantity,reasons=quantities(portion,band['direction'],band['price'])
            observation=observe_trial(portion,quantity,reasons,trial,asof_seq)
            if observation is not None:trials.append(observation)
        terminal=band['terminal']
        if asof_seq is not None and terminal is not None and terminal['seq']>asof_seq:terminal=None
        result.append(dict(band_id=band['band_id'],direction=band['direction'],price=band['price'],
            atr=band['atr'],tick=band['tick'],created=band['created'],terminal=terminal,
            trials=trials,features_strict=features(band,trials,'strict'),features_local=features(band,trials,'local')))
    return result
