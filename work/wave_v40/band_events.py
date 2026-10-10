"""公開された同価格の帯と二つの試行を、採否や売買から独立に列挙する。"""

from __future__ import annotations

import math

import numpy as np


DEFAULTS = dict(seed_seconds=30., momentum_atr=.10, trial_seconds=30., away_atr=.5,
    approach_ticks=1., break_ticks=2., expiry_seconds=1800., warmup_seconds=1200.,
    max_gap_seconds=60., max_delay_seconds=60., anchor_staleness_seconds=60.)


def parameters(changes: dict | None = None) -> dict:
    """機能: 状態機械の数値を明示し、未知の条件を黙って無視しない。

    引数: changes(dict|None)。返り値: 独立した設定辞書(dict)。
    """
    result = dict(DEFAULTS)
    if changes is not None:
        assert isinstance(changes, dict) and not set(changes).difference(result), '未定義の設定'
        result.update(changes)
    for name, value in result.items():
        assert not isinstance(value, bool) and math.isfinite(value) and value >= 0, name
        if name != 'warmup_seconds':assert value > 0, name
    return result


def validate(events: dict, start: float, limit: float, tick: float) -> int:
    """機能: 公開列の形と順序を検査し、品質不明は状態機械内で扱う。

    引数: events(dict[str,ndarray])、start/limit/tick(float)。返り値: 公開件数(int)。
    """
    assert math.isfinite(start) and math.isfinite(limit) and start < limit
    assert not isinstance(tick, bool) and math.isfinite(tick) and tick > 0
    n = len(events['seq'])
    one = ('seq','time_s','ready_index','atr','price_valid','depth_valid',
           'block_delay_seconds','previous_release_gap','continuity_reset_count')
    for name in one:
        values = np.asarray(events[name]);assert values.ndim==1 and len(values)==n,name
    for name in ('bid_prices','ask_prices','bid_qty','ask_qty'):
        assert np.asarray(events[name]).shape==(n,10),name
    for name in ('seq','ready_index'):
        values = np.asarray(events[name]);assert np.issubdtype(values.dtype,np.integer),name
        assert np.all(values>=0) and np.all(np.diff(values)>0),name
    times = np.asarray(events['time_s']);assert np.isfinite(times).all() and np.all(np.diff(times)>=0)
    assert np.asarray(events['price_valid']).dtype==np.bool_
    assert np.asarray(events['depth_valid']).dtype==np.bool_
    if n>1:
        np.testing.assert_allclose(events['previous_release_gap'][1:],np.diff(times),rtol=0,atol=1e-9)
    return n


def location(events: dict, index: int) -> dict:
    """機能: 公開列行・原本配列行・原本行番号を混同せず保存する。

    引数: events(dict)、index(int)。返り値: 時点情報(dict)。
    """
    return dict(event_index=int(index), ready_index=int(events['ready_index'][index]),
        seq=int(events['seq'][index]), time_s=float(events['time_s'][index]))


def quality(events: dict, params: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """機能: 価格時計と数量の品質を分け、数量不正で価格帯を中止しない。

    引数: events/params(dict)。返り値: 価格品質・数量品質・中値(tuple[ndarray,...])。
    reset総数は数量側にだけ作用し、公開間の全原本価格の連続性を主張しない。
    """
    bid, ask = events['bid_prices'][:,0], events['ask_prices'][:,0]
    middle = (bid+ask)/2.
    price = np.asarray(events['price_valid'],bool).copy()
    price &= np.isfinite(bid) & np.isfinite(ask) & (bid>0) & (bid<ask)
    price &= np.isfinite(events['atr']) & (events['atr']>0)
    delay, gap = events['block_delay_seconds'], events['previous_release_gap']
    price &= np.isfinite(delay) & (delay>0) & (delay<=params['max_delay_seconds'])
    price &= np.isfinite(gap) & (gap>0) & (gap<=params['max_gap_seconds'])
    reset = events['continuity_reset_count']
    quantity = np.asarray(events['depth_valid'],bool) & np.isfinite(reset) & (reset==0)
    return price,quantity,middle


def visible(events: dict, index: int, direction: int, price: float, valid: np.ndarray) -> tuple[float | None,str | None]:
    """機能: 固定価格が同じ側で見える時だけ数量を得る。

    引数: events(dict)、index/direction(int)、price(float)、valid(ndarray[bool])。
    返り値: 数量と不明理由(tuple[float|None,str|None])。反対側へ移った数量は使わない。
    """
    if not valid[index]:return None,'数量品質不明'
    side = 'ask' if direction==1 else 'bid'
    prices,quantities = events[side+'_prices'][index],events[side+'_qty'][index]
    found = np.flatnonzero(prices==price)
    if len(found)==0:return None,'同側10段の可視外'
    if len(found)!=1:return None,'同価格が重複'
    value=float(quantities[int(found[0])])
    if not math.isfinite(value) or value<0:return None,'数量不正'
    return value,None


def seed_quantity(events: dict, left: int, right: int, direction: int, price: float,
                  quantity_valid: np.ndarray) -> dict:
    """機能: 準備窓内で同価格の減少後に増加したかを確認する。

    引数: events(dict)、left/right/direction(int)、price(float)、quantity_valid(ndarray)。
    返り値: 準備だけの数量証拠(dict)。試行1の集計には加算しない。
    """
    samples=[];down=None;up=None;previous=None;known=True
    for i in range(left,right+1):
        q,reason=visible(events,i,direction,price,quantity_valid)
        samples.append(dict(**location(events,i),quantity=q,unknown_reason=reason))
        if q is None:
            known=False;previous=None;continue
        if previous is not None:
            if q<previous and down is None:down=location(events,i)
            if q>previous and down is not None and up is None:up=location(events,i)
        previous=q
    return dict(known=known,decrease=down,increase=up,eligible=bool(known and down is not None and up is not None),
        sample_count=len(samples),samples=samples)


def new_trial(events: dict, index: int, number: int) -> dict:
    """機能: それ以前の数量変化を含まない新しい試行を開始する。

    引数: events(dict)、index/number(int)。返り値: 作業中の試行(dict)。
    """
    return dict(number=number,start=location(events,index),end=None,complete=False,
        sample_count=0,quantity_known=True,unknown_reasons=[],quantity_start=None,
        decrease=0.,increase_after_decrease=0.,recovery_ratio=None,
        maximum_pushback_atr=0.,elapsed_seconds=None,first_decrease=None,samples=[],_last_quantity=None)


def observe(trial: dict, events: dict, index: int, band: dict, middle: float,
            quantity_valid: np.ndarray) -> None:
    """機能: 試行に所属する公開行だけの価格・数量を加算する。

    引数: trial/events/band(dict)、index(int)、middle(float)、quantity_valid(ndarray)。
    返り値: なし(None)。試行間や欠測を跨ぐ数量差分は加算しない。
    """
    q,reason=visible(events,index,band['direction'],band['price'],quantity_valid)
    trial['sample_count']+=1
    trial['samples'].append(dict(**location(events,index),quantity=q,unknown_reason=reason,mid=float(middle)))
    trial['maximum_pushback_atr']=max(trial['maximum_pushback_atr'],
        max(0.,band['direction']*(band['price']-middle))/band['atr'])
    if trial['sample_count']==1:trial['quantity_start']=q
    previous=trial['_last_quantity']
    if q is None:
        trial['quantity_known']=False
        if reason not in trial['unknown_reasons']:trial['unknown_reasons'].append(reason)
    elif previous is not None:
        difference=q-previous
        if difference<0:
            trial['decrease']-=difference
            if trial['first_decrease'] is None:trial['first_decrease']=location(events,index)
        elif difference>0 and trial['first_decrease'] is not None:
            trial['increase_after_decrease']+=difference
    trial['_last_quantity']=q


def finish_trial(trial: dict, events: dict, index: int, complete: bool) -> None:
    """機能: 完了又は中断時の試行をその時点の値で確定する。

    引数: trial/events(dict)、index(int)、complete(bool)。返り値: なし(None)。
    """
    trial['end']=location(events,index);trial['complete']=bool(complete)
    trial['elapsed_seconds']=float(events['time_s'][index]-trial['start']['time_s'])
    if complete and trial['quantity_known'] and trial['decrease']>0:
        trial['recovery_ratio']=float(trial['increase_after_decrease']/trial['decrease'])
    elif complete and trial['decrease']==0 and '可視減少0' not in trial['unknown_reasons']:
        trial['unknown_reasons'].append('可視減少0')


def trace(band: dict, kind: str, events: dict, index: int) -> None:
    """機能: 過去の状態遷移を追記し、後から上書きしない。

    引数: band/events(dict)、kind(str)、index(int)。返り値: なし(None)。
    """
    band['events'].append(dict(kind=kind,**location(events,index)))


def terminal(band: dict, reason: str, events: dict, index: int) -> None:
    """機能: 帯を消費し、同じ行で新しい帯へ差し替えない証拠を残す。

    引数: band/events(dict)、reason(str)、index(int)。返り値: なし(None)。
    """
    for trial in band['trials']:
        if trial['end'] is None:finish_trial(trial,events,index,False)
    band['status']=reason;band['terminal']=dict(reason=reason,**location(events,index))
    trace(band,reason,events,index)


def final_features(band: dict) -> dict:
    """機能: 完了した二試行の特徴を採否せず保存する。

    引数: band(dict)。返り値: 比較可能性・比率・押し返し・差(dict)。
    """
    trials=band['trials']
    if len(trials)!=2 or not all(t['complete'] for t in trials):
        return dict(two_trials_complete=False,quantity_comparable=False,price_comparable=False,
            u1=None,u2=None,b1=None,b2=None,quantity_change=None,pushback_change=None,
            quantity_weakens=None,price_weakens=None)
    first,last=trials;u1,u2=first['recovery_ratio'],last['recovery_ratio']
    b1,b2=first['maximum_pushback_atr'],last['maximum_pushback_atr']
    known=u1 is not None and u2 is not None
    return dict(two_trials_complete=True,quantity_comparable=known,price_comparable=True,
        u1=u1,u2=u2,b1=b1,b2=b2,quantity_change=u2-u1 if known else None,
        pushback_change=b2-b1,quantity_weakens=bool(u2<u1) if known else None,price_weakens=bool(b2<b1))


def summarize(records: list[dict]) -> dict:
    """機能: 発生した全帯の試行数・標本不足・不明理由を成績なしで数える。

    引数: records(list[dict])。返り値: 可用性の内訳(dict)。不明理由の件数は重複を許す。
    帯が作られなかった全公開行の不成立理由を、この集計だけで説明したとは言わない。
    """
    statuses=('breakout','early_breakout','expiry','price_quality_interruption','session_end','open_at_data_end')
    trials=[trial for record in records for trial in record['trials']]
    reasons=sorted({reason for trial in trials for reason in trial['unknown_reasons']})
    return dict(bands=len(records),terminal_counts={name:sum(record['status']==name for record in records) for name in statuses},
        seed_sample_counts={str(n):sum(record['seed']['sample_count']==n for record in records)
            for n in sorted({record['seed']['sample_count'] for record in records})},
        trials_started=len(trials),trials_complete=sum(trial['complete'] for trial in trials),
        trials_incomplete=sum(not trial['complete'] for trial in trials),
        trials_with_fewer_than_two_samples=sum(trial['sample_count']<2 for trial in trials),
        trials_with_unknown_quantity=sum(not trial['quantity_known'] for trial in trials),
        completed_trials_without_decrease=sum(trial['complete'] and trial['decrease']==0 for trial in trials),
        unknown_reason_counts={reason:sum(reason in trial['unknown_reasons'] for trial in trials) for reason in reasons},
        two_trials_complete=sum(record['features']['two_trials_complete'] for record in records),
        quantity_comparable=sum(record['features']['quantity_comparable'] for record in records),
        price_comparable=sum(record['features']['price_comparable'] for record in records))


def build(events: dict, start: float, limit: float, tick: float, *,
          require_recovery: bool = True, params: dict | None = None) -> list[dict]:
    """機能: 同時に一帯の全準備・二試行・最初突破と中止を因果順に列挙する。

    引数: events(公開dict)、start/limit/tick(float)、require_recovery(bool)、params(dict|None)。
    返り値: 全帯の記録(list[dict])。弱化採否・取引可否・口座成績は入力に持たない。
    require_recovery=Falseは帯生成の数量条件だけを外す独立母集団である。
    """
    assert isinstance(require_recovery,bool)
    count=validate(events,start,limit,tick);p=parameters(params)
    price_valid,quantity_valid,middle=quality(events,p)
    times=events['time_s'];bands=[];active=None;blocked={};valid_since=0
    for i in range(count):
        now=float(times[i])
        if not price_valid[i]:valid_since=i+1
        if active is not None:
            if now>=active['expires_at']:
                terminal(active,'expiry',events,i);active=None;continue
            if now>=limit:
                terminal(active,'session_end',events,i);active=None;continue
            if not price_valid[i]:
                terminal(active,'price_quality_interruption',events,i);active=None;continue
            before=active['phase']
            if before in ('trial1','trial2'):
                trial=active['trials'][-1]
                observe(trial,events,i,active,float(middle[i]),quantity_valid)
                if now-trial['start']['time_s']>=p['trial_seconds']:
                    finish_trial(trial,events,i,True)
                    trace(active,'trial_finished',events,i)
                    active['phase']='wait_away' if before=='trial1' else 'wait_breakout'
            crossed=(events['bid_prices'][i,0]>=active['price']+p['break_ticks']*tick if active['direction']==1
                     else events['ask_prices'][i,0]<=active['price']-p['break_ticks']*tick)
            if crossed:
                terminal(active,'breakout' if before=='wait_breakout' else 'early_breakout',events,i)
                active=None;continue
            distance=active['direction']*(active['price']-float(middle[i]))
            if active['phase']=='wait_away' and distance>=p['away_atr']*active['atr']:
                active['away']=location(events,i);active['phase']='wait_approach';trace(active,'away',events,i)
            elif active['phase']=='wait_approach' and i>active['away']['event_index'] and 0<=distance<=p['approach_ticks']*tick:
                trial=new_trial(events,i,2);active['trials'].append(trial);active['phase']='trial2'
                observe(trial,events,i,active,float(middle[i]),quantity_valid);trace(active,'trial_started',events,i)
            continue
        # ----------------------------------------
        # 帯なしの時だけ価格窓を確認し、作成後の経路は採否に依存させない。
        if now<start+p['warmup_seconds'] or now>=limit or not price_valid[i]:continue
        cutoff=now-p['seed_seconds'];left=int(np.searchsorted(times,cutoff,side='right'))-1
        if left<valid_since or left<0 or left>=i:continue
        if cutoff-float(times[left])>p['anchor_staleness_seconds']:continue
        change=float(middle[i]-middle[left]);atr=float(events['atr'][i])
        if abs(change)<p['momentum_atr']*atr:continue
        direction=1 if change>0 else -1
        price=float(events['ask_prices'][i,0] if direction==1 else events['bid_prices'][i,0])
        if now<blocked.get((direction,price),-math.inf):continue
        seed=seed_quantity(events,left,i,direction,price,quantity_valid)
        if require_recovery and not seed['eligible']:continue
        seed.update(left=location(events,left),right=location(events,i),
            window_seconds=now-float(times[left]),anchor_staleness_seconds=cutoff-float(times[left]),
            momentum=change,momentum_atr=change/atr,quantity_required=require_recovery)
        active=dict(band_id=len(bands)+1,direction=direction,price=price,atr=atr,tick=float(tick),
            created=location(events,i),expires_at=now+p['expiry_seconds'],
            status='open_at_data_end',phase='trial1',seed=seed,trials=[],away=None,terminal=None,events=[])
        bands.append(active);blocked[(direction,price)]=active['expires_at']
        trace(active,'created',events,i)
        trial=new_trial(events,i,1);active['trials'].append(trial)
        observe(trial,events,i,active,float(middle[i]),quantity_valid);trace(active,'trial_started',events,i)
    for band in bands:
        band['features']=final_features(band)
        for trial in band['trials']:
            trial.pop('_last_quantity')
    return bands
