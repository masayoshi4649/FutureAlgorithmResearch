"""方向採点の分子分母・打切・固定方向対照を、原配列を保存せず集計する。"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np


RULES=('A','B','C')
WIDTHS=(.0005,.001,.002)
ORIGIN_CODES=('publication_mid','next_raw_net_quote')
ORIGINS=('公開mid','次行新規・費用後気配')
GROUPS=('全候補','非重複')
DIRECTIONS=('全体','買い','売り')
STATUS={1:'favorable_first',-1:'adverse_first',0:'price_cut',2:'eof',3:'window_end',-2:'entry_unavailable'}
COUNT_FIELDS=tuple(STATUS.values())
KEYS=('rule','group','width_fraction','origin','direction')
PROFILE_KEYS=('rule','group','origin','direction')
PRIMARY=dict(rule='C',group='非重複',width_fraction=.001,origin='公開mid',direction='全体')


def _scalar(value: object) -> float:
    """
    機能: 有限実数だけを集計値として受理する。
    引数: value(object)。
    返り値: float。真偽・None・非有限は拒否する。
    """
    assert isinstance(value,Real) and not isinstance(value,(bool,np.bool_)) and math.isfinite(value)
    return float(value)


def _count(value: object) -> int:
    """
    機能: 非負の件数だけを受理する。
    引数: value(object)。
    返り値: int。
    """
    number=_scalar(value)
    assert number>=0 and number==int(number)
    return int(number)


def _finish_counts(counts: dict) -> dict:
    """
    機能: 同じ全候補分母と、±先着で解決した分母の率を別々に計算する。
    引数: counts(dict) は六状態の非負件数。
    返り値: dict。空分母はNone、打切と新規不可を勝敗へ混ぜない。
    """
    result={key:_count(counts[key]) for key in COUNT_FIELDS}
    n=sum(result.values())
    resolved=result['favorable_first']+result['adverse_first']
    result.update(n=n,resolved=resolved,
        favorable_rate_all=result['favorable_first']/n if n else None,
        favorable_rate_resolved=result['favorable_first']/resolved if resolved else None,
        resolution_rate=resolved/n if n else None)
    return result


def _labels(values: np.ndarray) -> dict:
    """
    機能: 先着・打切の整数ラベルを状態別に数える。
    引数: values(ndarray[int8]) は選定された一セルのラベル。
    返り値: dict は件数と三種類の率。
    """
    assert np.all(np.isin(values,tuple(STATUS)))
    return _finish_counts({name:int(np.count_nonzero(values==code)) for code,name in STATUS.items()})


def _quantile(ordered: list[float], fraction: float) -> float | None:
    """
    機能: 既に昇順の有限列へ線形補間の分位点を求める。
    引数: ordered(list[float])、fraction(float)。
    返り値: float|None。空列はNone。
    """
    if not ordered:return None
    at=(len(ordered)-1)*fraction
    low=int(math.floor(at));high=int(math.ceil(at))
    return ordered[low]+(ordered[high]-ordered[low])*(at-low)


def _stats(values: object) -> dict:
    """
    機能: 事後極値の有限観測だけを記述し、負のMFE/MAEもそのまま保持する。
    引数: values(object) は一次元数値列。NaNは観測空だけを表す。
    返り値: dict は件数・和・平均・範囲・分位点。原値を保存しない。
    """
    vals=[]
    for value in values:
        assert isinstance(value,Real) and not isinstance(value,(bool,np.bool_))
        number=float(value)
        assert not math.isinf(number)
        if not math.isnan(number):vals.append(number)
    vals.sort()
    total=math.fsum(vals)
    assert math.isfinite(total)
    return dict(n=len(vals),sum=total,mean=total/len(vals) if vals else None,
        min=vals[0] if vals else None,q25=_quantile(vals,.25),median=_quantile(vals,.5),
        q75=_quantile(vals,.75),max=vals[-1] if vals else None)


def _pooled_stats(values: list[dict]) -> dict:
    """
    機能: 場ごとの件数・和だけから全観測の平均を再加算する。
    引数: values(list[dict]) は_statsの結果。
    返り値: dict。全観測の分位点は未算定とし、場中央値の分布を別名にする。
    """
    known=[value for value in values if _count(value['n'])>0]
    n=sum(_count(value['n']) for value in values)
    total=math.fsum(_scalar(value['sum']) for value in values)
    assert math.isfinite(total)
    medians=[_scalar(value['median']) for value in known]
    return dict(n=n,sum=total,mean=total/n if n else None,
        min=min(_scalar(value['min']) for value in known) if known else None,
        max=max(_scalar(value['max']) for value in known) if known else None,
        q25=None,median=None,q75=None,全観測分位点='原値を保持しないため未算定。場中央値の平均を全観測中央値にしない。',
        場中央値の分布=_stats(medians))


def _key(record: dict, keys: tuple[str,...]) -> tuple:
    """
    機能: 集計セルの固定キーを作る。
    引数: record(dict)、keys(tuple[str,...])。
    返り値: tuple。
    """
    return tuple(record[key] for key in keys)


def _audit(measured: dict) -> dict:
    """
    機能: engineの配列契約、共通非重複選択、末尾と空観測を独立に検査する。
    引数: measured(dict) はmeasureの記憶内返却値。
    返り値: dict は必要配列への参照だけ。外部IOを行わない。
    """
    assert tuple(measured['widths'])==WIDTHS
    assert tuple(measured['origin_names'])==ORIGIN_CODES
    assert tuple(measured['rule_names'])==RULES
    events=measured['events'];fields=measured['fields']
    assert isinstance(events,np.ndarray) and events.dtype==np.float64 and events.ndim==2
    assert len(fields)==len(set(fields))==31 and events.shape[1]==31 and np.isfinite(events).all()
    count=len(events)
    pub=events[:,fields.index('pub_i')]
    side=events[:,fields.index('d')]
    assert np.all(pub>=0) and np.all(pub<2**53) and np.all(pub==pub.astype(np.int64))
    assert np.all(np.diff(pub)>=0) and np.all(np.isin(side,(-1.,1.)))
    pub=pub.astype(np.int64);side=side.astype(np.int8)
    shape_fields={'labels':((count,3,2),np.int8),'terminal_rows':((count,3,2),np.int64),
        'eligible':((count,3),np.bool_),'nonoverlap':((count,3),np.bool_),
        'entry_available':((count,),np.bool_),'entry_rows':((count,),np.int64),
        'entry_prices':((count,),np.float64),'mfe':((count,2),np.float64),
        'mae':((count,2),np.float64),'continuous_end_exclusive':((count,2),np.int64)}
    for name,(shape,dtype) in shape_fields.items():
        array=measured[name]
        assert isinstance(array,np.ndarray) and array.shape==shape and array.dtype==dtype,name
    labels=measured['labels'];terminal=measured['terminal_rows']
    available=measured['entry_available'];entry=measured['entry_rows'];prices=measured['entry_prices']
    assert np.all(np.isin(labels,tuple(STATUS))) and np.all(labels[:,:,0]!=-2)
    assert np.all(labels[~available,:,1]==-2) and np.all(labels[available,:,1]!=-2)
    assert np.all(entry[~available]==-1) and np.all(np.isnan(prices[~available]))
    assert np.all(entry[available]==pub[available]+1)
    assert np.all(np.isfinite(prices[available])&(prices[available]>0))
    assert np.all(terminal[~available,:,1]==-1)
    ends=measured['continuous_end_exclusive']
    assert np.all(ends[~available,1]==-1)
    for origin in range(2):
        use=np.ones(count,bool) if origin==0 else available
        starts=pub+1 if origin==0 else entry
        assert np.all(ends[use,origin]>=starts[use])
        expected_finite=use&(ends[:,origin]>starts)
        mfe,mae=measured['mfe'][:,origin],measured['mae'][:,origin]
        assert np.all(np.isfinite(mfe)==expected_finite) and np.all(np.isfinite(mae)==expected_finite)
        assert not np.isinf(mfe).any() and not np.isinf(mae).any()
        assert np.all(mfe[expected_finite]>=mae[expected_finite])
        for width in range(3):
            code=labels[:,width,origin];end=terminal[:,width,origin]
            hit=use&np.isin(code,(-1,1))
            cut=use&np.isin(code,(0,3))
            eof=use&(code==2)
            assert np.all(end[hit]>=starts[hit]) and np.all(end[hit]<ends[hit,origin])
            assert np.all(end[cut]==ends[cut,origin])
            assert np.all(end[eof]==ends[eof,origin]-1)
    eligible=measured['eligible'];chosen=measured['nonoverlap']
    assert np.all(~chosen|eligible)
    assert np.all(~eligible[:,2]|eligible[:,1])
    typ=events[:,fields.index('type')]
    q0=events[:,fields.index('opposite_q0')]
    minimum=events[:,fields.index('opposite_min_q')]
    assert np.all(~eligible[:,0]|(typ==0))
    assert np.all(~eligible[:,1]|((typ==1)&(q0>0)&(minimum>=q0)))
    bidq=events[:,fields.index('bid_q_at_public')]
    askq=events[:,fields.index('ask_q_at_public')]
    own=np.where(side>0,bidq,askq);opposite=np.where(side>0,askq,bidq)
    assert np.all(~eligible[:,2]|(own>=opposite))
    reference=np.zeros((count,3),bool)
    for rule in range(3):
        locked=-1
        for index in range(count):
            if eligible[index,rule] and pub[index]>locked:
                reference[index,rule]=True
                locked=int(max(terminal[index,2,0],terminal[index,2,1]))
    np.testing.assert_array_equal(reference,chosen)
    return dict(pub=pub,side=side,labels=labels,eligible=eligible,chosen=chosen,
        mfe=measured['mfe'],mae=measured['mae'],available=available)


def account(symbol: str, session: str, measured: dict) -> dict:
    """
    機能: 一口座の六状態と同候補の常時買売対照を、固定108セルへ集計する。
    引数: symbol/session(str)、measured(dict) はengine.measureの返却値。
    返り値: dict は小集計行。原イベント配列や価格経路を保存しない。
    """
    assert symbol in ('TOPIX','NK225') and isinstance(session,str) and session.endswith(('_Day','_Night'))
    values=_audit(measured)
    cells=[];profiles=[]
    side=values['side']
    for ri,rule in enumerate(RULES):
        for group in GROUPS:
            base=values['eligible'][:,ri] if group=='全候補' else values['chosen'][:,ri]
            for direction in DIRECTIONS:
                mask=base if direction=='全体' else base&(side==(1 if direction=='買い' else -1))
                for oi,origin in enumerate(ORIGINS):
                    profile=dict(rule=rule,group=group,direction=direction,origin=origin,origin_code=ORIGIN_CODES[oi],
                        n=int(mask.sum()),mfe=_stats(values['mfe'][mask,oi]),mae=_stats(values['mae'][mask,oi]))
                    profiles.append(profile)
                    for wi,width in enumerate(WIDTHS):
                        labs=values['labels'][mask,wi,oi]
                        result=_labels(labs)
                        assert result['n']==int(mask.sum())
                        if oi==0:
                            physical=labs.copy();resolved=np.isin(labs,(-1,1))
                            physical[resolved]=labs[resolved]*side[mask][resolved]
                            reverse=physical.copy();reverse[resolved]=-physical[resolved]
                            baseline=dict(常時買い=_labels(physical),常時売り=_labels(reverse),
                                範囲='同じ候補/起点/打切の派生対照。独立標本でも実売買成績でもない。')
                        else:baseline=None
                        cells.append(dict(rule=rule,group=group,direction=direction,origin=origin,
                            origin_code=ORIGIN_CODES[oi],width_fraction=width,**result,baseline=baseline))
    assert len(cells)==108 and len(profiles)==36
    primary=next(cell for cell in cells if all(cell[key]==value for key,value in PRIMARY.items()))
    return dict(symbol=symbol,session=session,全保存候補数=len(side),直後新規可能数=int(values['available'].sum()),
        cells=cells,profiles=profiles,primary=primary,
        方向ラベル='順先/逆先は事前方向に相対。対称幅の到達順で、実返済約定や取引勝率ではない。',
        極値='MFE=max score/MAE=min score。先着後も価格連続区間末まで。負値を0へ丸めず、事後記述だけ。')


def _merge(accounts: list[dict]) -> dict:
    """
    機能: 同商品の対象場だけから全セルの分子分母と平均極値を再加算する。
    引数: accounts(list[dict])。
    返り値: dict。全観測分位点を場分位点の平均で代用しない。
    """
    assert accounts
    reference=accounts[0]
    result=[]
    for template in reference['cells']:
        key=_key(template,KEYS)
        rows=[]
        for row in accounts:
            matching=[cell for cell in row['cells'] if _key(cell,KEYS)==key]
            assert len(matching)==1
            rows.append(matching[0])
        total=_finish_counts({name:sum(_count(cell[name]) for cell in rows) for name in COUNT_FIELDS})
        assert total['n']==sum(_count(cell['n']) for cell in rows)
        if template['baseline'] is not None:
            baseline={}
            for direction in ('常時買い','常時売り'):
                baseline[direction]=_finish_counts({name:sum(_count(cell['baseline'][direction][name]) for cell in rows) for name in COUNT_FIELDS})
                assert baseline[direction]['n']==total['n'] and baseline[direction]['resolved']==total['resolved']
            baseline['範囲']='同じ候補のラベル派生。独立標本ではない。'
        else:
            assert all(cell['baseline'] is None for cell in rows)
            baseline=None
        result.append(dict(**{name:template[name] for name in (*KEYS,'origin_code')},**total,baseline=baseline))
    profiles=[]
    for template in reference['profiles']:
        key=_key(template,PROFILE_KEYS)
        rows=[]
        for row in accounts:
            matching=[profile for profile in row['profiles'] if _key(profile,PROFILE_KEYS)==key]
            assert len(matching)==1
            rows.append(matching[0])
        profiles.append(dict(**{name:template[name] for name in (*PROFILE_KEYS,'origin_code')},
            n=sum(_count(profile['n']) for profile in rows),
            mfe=_pooled_stats([profile['mfe'] for profile in rows]),mae=_pooled_stats([profile['mae'] for profile in rows])))
    assert len(result)==108 and len(profiles)==36
    primary=next(cell for cell in result if all(cell[key]==value for key,value in PRIMARY.items()))
    reference2=next(cell for cell in result if all(cell[key]==value for key,value in
        dict(PRIMARY,origin=ORIGINS[1]).items()))
    return dict(session_count=len(accounts),cells=result,profiles=profiles,primary=primary,secondary_origin=reference2)


def combine(accounts: list[dict], sessions: list[str]) -> dict:
    """
    機能: 固定した同じ33場を、全場・前後・昼夜へ同じ定義で集計する。
    引数: accounts(list[dict]) は両商品66口座、sessions(list[str]) は事前固定順。
    返り値: dict は各場の小集計と商品別期間集計。最良幅・方法を選び直さない。
    """
    assert len(sessions)==len(set(sessions))==33
    assert all(isinstance(s,str) and s.endswith(('_Day','_Night')) for s in sessions)
    assert len(accounts)==66
    keys=[(row['symbol'],row['session']) for row in accounts]
    assert len(keys)==len(set(keys))==66
    assert set(keys)=={(symbol,session) for symbol in ('TOPIX','NK225') for session in sessions}
    groups={'全33':sessions,'前16':sessions[:16],'後17':sessions[16:],
        'デイ':[s for s in sessions if s.endswith('_Day')],'ナイト':[s for s in sessions if s.endswith('_Night')]}
    symbols={}
    for symbol in ('TOPIX','NK225'):
        own=[row for row in accounts if row['symbol']==symbol]
        periods={name:_merge([row for row in own if row['session'] in selected]) for name,selected in groups.items() if selected}
        symbols[symbol]=dict(periods=periods)
    return dict(全合格=True,sessions=list(sessions),accounts=accounts,symbols=symbols,primary_definition=dict(PRIMARY),
        label_counts=dict(順先=1,逆先=-1,価格cut=0,EOF=2,窓末=3,直後新規不可=-2),
        集計単位='3rules×3幅×2起点。全候補/共通非重複・方向別は同じ経路の切分けで独立標本数を増やさない。',
        極値の限界='全観測の平均はsum/count。全観測median/qは未算定で、場中央値の分布を別名保存。',
        有効性='非金融の方向採点。最良幅/方法の後選択や実売買P/Lを方向予測の成功と呼ばない。')
