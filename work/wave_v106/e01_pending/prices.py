"""価格窓からpublicgap拒否だけを分離し、未約定中の当時逆進行を測る。"""

import numpy as np

import common


legacy=common.module('106旧E01の固定価格窓',common.ROOT/'work/wave_v106/e01_pair_filter/core.py')


def windows(raw: dict, public: dict, tick: float, policy: dict) -> dict:
    """
    機能: 旧10/30/60秒窓の基準を保ち、public価格gapを不正気配と同一視する条件だけを外す。
    引数: raw/public/policy(dict)、tick(float)は不変旧原行と数値規則。
    返り値: dictは新窓。価格・clock・原seq・端点資格・曖昧・asof条件は維持する。
    """
    old=legacy.public_windows(raw,public,tick,policy);new=dict(old,windows={})
    for key,value in old['windows'].items():
        reasons=value['unknown_reason'] & np.uint16(65535^32);known=reasons==0
        db,da=value['bid_change_ticks'],value['ask_change_ticks']
        spread=value['current_spread_ticks']>np.maximum(policy['spread_max_ticks'],
            value['reference_spread_ticks']+policy['spread_increment_ticks'])
        sign=((db>0)&(da<0))|((db<0)&(da>0));ambiguous=known&(spread|sign)
        direction=np.full(len(reasons),3,np.int8);ordinary=known&~ambiguous
        direction[ordinary]=0;direction[ordinary&(db>=1)&(da>=1)]=1
        direction[ordinary&(db<=-1)&(da<=-1)]=-1;direction[ambiguous]=2
        current=dict(value,unknown_reason=reasons,ambiguous=ambiguous,
            ambiguous_spread=known&spread,ambiguous_sign=known&sign,direction_t1=direction)
        assert np.all((value['unknown_reason']&np.uint16(65535^32))==current['unknown_reason'])
        for name in ('reference_public_index','reference_raw_row','reference_raw_seq','reference_time_s',
                     'public_rows','source_raw_seq','source_time_s','bid_change_ticks','ask_change_ticks'):
            np.testing.assert_array_equal(current[name],value[name])
        new['windows'][key]=current
    new['publicgap_is_missing_quote']=False
    return new


def project(raw: dict, feature: dict, times: np.ndarray, mapping: np.ndarray | None,
            window: int, strictpast: bool, actual_self_valid: np.ndarray) -> dict:
    """
    機能: 自己同原行以下またはstrict過去相手へ、当時公表窓を一括投影する。
    引数: raw/feature(dict)、times(ndarray)、mapping(ndarray|None)、window(int)、strictpast(bool)、actual_self_valid(ndarray[bool])。
    返り値: dictは方向・公表番号・当時年齢。未来正常行への移動は行わない。
    """
    public=feature['public'];position=np.searchsorted(public['times'],times,side='left' if strictpast else 'right')-1
    if mapping is not None:
        position=np.minimum(position,np.searchsorted(public['rows'],mapping,side='right')-1)
    safe=np.maximum(position,0);value=feature['windows'][str(window)]
    direction=np.full(len(times),3,np.int8);age=np.full(len(times),np.nan)
    available=position>=0;age[available]=times[available]-value['source_time_s'][position[available]]
    fresh=(age>0)&(age<=15.) if strictpast else (age>=0)&(age<=15.)
    known=available&fresh&actual_self_valid&np.isfinite(times)
    if len(public['times']):
        known&=(value['unknown_reason'][safe]==0)&~value['ambiguous'][safe]
        if mapping is not None:
            rows=public['rows'][safe]
            known&=(feature['raw_bad_prefix'][mapping+1]-feature['raw_bad_prefix'][rows])==0
        direction[known]=value['direction_t1'][position[known]]
    else:
        known[:]=False
    assert np.all(np.isin(direction[known],[-1,0,1]))
    return dict(direction=direction,public_index=position.astype(np.int32),age_seconds=age)


def account(packet: dict, symbol: str, prepared: dict) -> dict:
    """
    機能: 元E01と同じ正常原行へ、自己/相手の10/30/60秒観測を接続する。
    引数: packet(dict)は旧104、symbol(str)、prepared(dict)は両商品分の新窓。
    返り値: dictは正常行の六方向列と公表系譜。口座利益を参照しない。
    """
    other='NK225' if symbol=='TOPIX' else 'TOPIX';raw=packet['raw'][symbol]
    record=packet['normal'][symbol]['record'];mapping=raw['execution_to_raw_index'];times=record['time_s']
    np.testing.assert_array_equal(raw['raw_seq'][mapping],record['seq'])
    np.testing.assert_array_equal(raw['price_time_s'][mapping],times)
    current_valid=(raw['bbo_valid'][mapping]&(raw['price_reset_reason'][mapping]==0)
        &~raw['clock_or_sequence_invalid'][mapping]&record['quote_valid'])
    result=dict(current_valid=current_valid,windows={},source_windows=prepared,
        normal_record=dict(price=record['price'],seq=record['seq'],time_s=times,
            start=record['start'],end=record['end'],limit=record['limit'],tick=record['tick']))
    for window in (10,30,60):
        result['windows'][str(window)]=dict(
            own=project(raw,prepared[symbol],times,mapping,window,False,current_valid),
            peer=project(packet['raw'][other],prepared[other],times,None,window,True,current_valid))
    return result

