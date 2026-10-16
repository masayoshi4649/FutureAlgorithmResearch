"""二つの既知価格端点から逆方向差だけを測り、数量や未観測経路と分離する。"""

import numpy as np


def field_bad(raw: dict) -> np.ndarray:
    """
    機能: 原seq・価格代理時計の未知/高水準からの逆行だけを直接fieldで判定する。
    引数: raw(dict)は価格時計・原seq。quantity/LP/volume reset理由を使わない。
    返り値: ndarray[bool]は当該原行の時系列不明。価格経路の不明とは別に扱う。
    """
    time=raw['price_time_s'];seq=raw['raw_seq'];finite=np.isfinite(time)
    assert np.issubdtype(seq.dtype,np.integer) and len(time)==len(seq)
    maximum=np.maximum.accumulate(np.where(finite,time,-np.inf))
    previous=np.r_[-np.inf,maximum[:-1]]
    bad=~finite | (finite & (time<previous))
    if len(time)>1:
        bad[1:]|=(seq[1:]!=seq[:-1]+1)
    return bad


def endpoints(raw: dict, start: float, end: float) -> np.ndarray:
    """
    機能: 価格端点自身の有限正bid/askと場内価格代理時計だけを直接確認する。
    引数: raw(dict)、start/end(float)は場の範囲。
    返り値: ndarray[bool]は端点資格。非normal由来NaNを未来行で補完しない。
    """
    t,b,a=raw['price_time_s'],raw['bid'],raw['ask']
    return np.isfinite(t)&(t>=start)&(t<end)&np.isfinite(b)&np.isfinite(a)&(b>0)&(a>b)


def windows(raw: dict, public: dict, tick: float, policy: dict, start: float, end: float) -> dict:
    """
    機能: first公表の10/30/60秒始終点差だけを、価格field自身の資格で求める。
    引数: raw/public/policy(dict)、tick/start/end(float)は不変原行と数値規則。
    返り値: dictは端点差と系譜。途中BBO/量/volume不明から経路TVや補充を推定しない。
    """
    assert tick>0 and policy['baseline_extra_age_seconds']==15.
    rows,times=public['rows'],public['times'];count=len(rows)
    valid=endpoints(raw,start,end);bad=field_bad(raw);prefix=np.r_[0,np.cumsum(bad.astype(np.int64))]
    result={}
    for window in (10,30,60):
        index=np.searchsorted(times,times-window,side='right')-1;available=index>=0
        ref=np.full(count,-1,np.int64);ref[available]=rows[index[available]]
        refseq=np.full(count,-1,np.int64);refseq[available]=raw['raw_seq'][ref[available]]
        reftime,db,da,refspread=(np.full(count,np.nan) for _ in range(4))
        reftime[available]=raw['price_time_s'][ref[available]]
        db[available]=(raw['bid'][rows[available]]-raw['bid'][ref[available]])/tick
        da[available]=(raw['ask'][rows[available]]-raw['ask'][ref[available]])/tick
        spread=(raw['ask'][rows]-raw['bid'][rows])/tick
        refspread[available]=(raw['ask'][ref[available]]-raw['bid'][ref[available]])/tick
        reason=np.zeros(count,np.uint16);reason[~available]|=1;reason[~valid[rows]]|=2
        ref_ok=np.zeros(count,bool);ref_ok[available]=valid[ref[available]]
        reason[available&~ref_ok]|=4
        reason[available&(times-reftime>window+15.)]|=8
        positions=np.flatnonzero(available)
        reason[positions[(prefix[rows[available]+1]-prefix[ref[available]])>0]]|=16
        known=reason==0
        ambspread=known&(spread>np.maximum(policy['spread_max_ticks'],refspread+policy['spread_increment_ticks']))
        ambsign=known&(((db>0)&(da<0))|((db<0)&(da>0)));amb=ambspread|ambsign
        direction=np.full(count,3,np.int8);ordinary=known&~amb
        direction[ordinary]=0;direction[ordinary&(db>=1)&(da>=1)]=1
        direction[ordinary&(db<=-1)&(da<=-1)]=-1;direction[amb]=2
        result[str(window)]=dict(window_seconds=window,public_rows=rows,source_raw_seq=public['raw_seq'],
            source_time_s=times,reference_public_index=index,reference_raw_row=ref,
            reference_raw_seq=refseq,reference_time_s=reftime,bid_change_ticks=db,ask_change_ticks=da,
            current_spread_ticks=spread,reference_spread_ticks=refspread,unknown_reason=reason,
            ambiguous=amb,ambiguous_spread=ambspread,ambiguous_sign=ambsign,direction_t1=direction)
    return dict(windows=result,public=public,raw_bad_prefix=prefix,raw_field_bad=bad,
        endpoint_valid=valid,publicgap_is_missing_quote=False,
        quantity_volume_or_intermediate_quote_used=False,
        unknown_names={1:'過去基準なし',2:'公表終点価格又は時計不明',4:'基準価格又は時計不明',
            8:'基準age超過',16:'区間内原seq断裂又は価格時計欠測/逆行'},
        measurement='既知端点の価格差。間のTV/最大逆行/補充を計測しない')


def project(raw: dict, feature: dict, times: np.ndarray, mapping: np.ndarray | None,
            window: int, strictpast: bool, actual_self_valid: np.ndarray) -> dict:
    """
    機能: 自己原行以下またはstrict過去相手へ当時の端点価格差を投影する。
    引数: raw/feature(dict)、times(ndarray)、mapping(ndarray|None)、window(int)、strictpast(bool)、actual_self_valid(ndarray[bool])。
    返り値: dictは方向と公表番号。asof不明を逆方向や中立へ補完しない。
    """
    public=feature['public'];position=np.searchsorted(public['times'],times,side='left' if strictpast else 'right')-1
    if mapping is not None:
        position=np.minimum(position,np.searchsorted(public['rows'],mapping,side='right')-1)
    safe=np.maximum(position,0);value=feature['windows'][str(window)]
    direction=np.full(len(times),3,np.int8);age=np.full(len(times),np.nan);available=position>=0
    age[available]=times[available]-value['source_time_s'][position[available]]
    fresh=(age>0)&(age<=15.) if strictpast else (age>=0)&(age<=15.)
    known=available&fresh&actual_self_valid&np.isfinite(times)
    if len(public['times']):
        known&=(value['unknown_reason'][safe]==0)&~value['ambiguous'][safe]
        if mapping is not None:
            source=public['rows'][safe]
            known&=(feature['raw_bad_prefix'][mapping+1]-feature['raw_bad_prefix'][source])==0
        direction[known]=value['direction_t1'][position[known]]
    else:
        known[:]=False
    return dict(direction=direction,public_index=position.astype(np.int32),age_seconds=age)


def account(packet: dict, symbol: str, prepared: dict) -> dict:
    """
    機能: 変更しないE01正常原行へ六つの価格端点方向列を接続する。
    引数: packet(dict)は不変104、symbol(str)、prepared(dict)は両商品価格窓。
    返り値: dictは正常方向列と公表系譜。元E01入場の数量条件は変更しない。
    """
    other='NK225' if symbol=='TOPIX' else 'TOPIX';raw=packet['raw'][symbol]
    record=packet['normal'][symbol]['record'];mapping=raw['execution_to_raw_index'];times=record['time_s']
    np.testing.assert_array_equal(raw['raw_seq'][mapping],record['seq'])
    np.testing.assert_array_equal(raw['price_time_s'][mapping],times)
    current_valid=prepared[symbol]['endpoint_valid'][mapping]&~prepared[symbol]['raw_field_bad'][mapping]
    output=dict(current_valid=current_valid,windows={},source_windows=prepared,
        normal_record=dict(price=record['price'],seq=record['seq'],time_s=times,
            start=record['start'],end=record['end'],limit=record['limit'],tick=record['tick']))
    for window in (10,30,60):
        output['windows'][str(window)]=dict(own=project(raw,prepared[symbol],times,mapping,window,False,current_valid),
            peer=project(packet['raw'][other],prepared[other],times,None,window,True,current_valid))
    return output

