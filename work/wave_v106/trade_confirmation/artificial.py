"""原CurrentPriceと出来高差の観測を、市場未使用の小人工で確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

import measure


def fixture() -> dict:
    """
    機能: 同価格時計と別出来高時計を持つ5原行を人工生成する。
    引数: なし。
    返り値: dictは最小NPZ互換列。市場原本や保存金融値は使わない。
    """
    return dict(raw_seq=np.arange(5,dtype=np.int64),execution_to_raw_index=np.arange(5,dtype=np.int64),price_time_s=np.array([0.,0.,2.,3.,4.]),
        volume_time_s=np.array([0.,0.,2.,3.,4.]),last=np.array([100.,101.,100.,100.,101.]),
        bid=np.array([100.,100.,99.,99.,100.]),ask=np.array([101.,101.,100.,100.,101.]),
        volume=np.array([10.,11.,12.,12.,13.]),volume_delta_known=np.array([False,True,True,True,True]),
        volume_delta_usable=np.array([False,True,True,True,True]),volume_delta_observed=np.array([np.nan,1.,1.,0.,1.]),
        volume_delta=np.array([np.nan,1.,1.,0.,1.]),price_reset_reason=np.array([1,0,0,0,0],np.uint16),
        lp_reset_reason=np.array([1,0,0,0,0],np.uint16),volume_reset_reason=np.array([1,0,0,0,0],np.uint16))


def main() -> None:
    """
    機能: seq/差不明/代理/同時計/接頭の意味を独立の期待値で検査する。
    引数: なし。
    返り値: None。全検査の証跡を所有域へ保存し、金融は実行しない。
    """
    raw=fixture();checks=[]
    buy=measure.observe(raw,1,0,1,1.)
    assert buy['volume_increased'] and not buy['volume_clock_changed'] and not buy['price_clock_changed']
    assert buy['last_moved_in_rebound_direction'] and buy['aggressor_proxy_side']==1
    checks.append('出来高/価格時計同値でも実値増を観測し、時計停滞を取引なしへ置換しない')
    sell=measure.observe(raw,2,1,-1,1.);assert sell['aggressor_proxy_side']==-1 and sell['last_moved_in_rebound_direction']
    checks.append('出来高増とLast対直前BBOの買売鏡像を代理に留める')
    zero=measure.observe(raw,3,2,1,1.);assert zero['volume_delta_usable'] and not zero['volume_increased'] and zero['group']=='既知の出来高差0'
    checks.append('既知出来高差0と不明を区別')
    same=deepcopy(raw);same['last'][1]=100.
    value=measure.observe(same,1,0,1,1.);assert value['volume_increased'] and not value['last_changed'] and value['group']=='出来高増・現在値が同価格'
    checks.append('同価格約定に相当し得る出来高増を価格変化条件へ誤変換しない')
    missing=deepcopy(raw);missing['last'][1]=np.nan
    value=measure.observe(missing,1,0,1,1.);assert value['current']['last'] is None and not value['aggressor_proxy_known']
    checks.append('原Last不明をBBO中値で救済しない')
    gap=deepcopy(raw);gap['raw_seq'][1:]+=1;gap['volume_delta_known'][1]=gap['volume_delta_usable'][1]=False
    value=measure.observe(gap,1,0,1,1.);assert not value['seq_continuous'] and not value['volume_value_pair_known'] and value['volume_value_delta'] is None
    checks.append('原seq断裂をまたぐ出来高差は不明')
    reset=deepcopy(raw);reset['volume'][1]=1.;reset['volume_delta_known'][1]=reset['volume_delta_usable'][1]=False;reset['volume_reset_reason'][1]=32
    value=measure.observe(reset,1,0,1,1.);assert not value['volume_value_pair_known'] and not value['volume_increased']
    checks.append('累計resetの負差を売りや出来高0へ置換しない')
    unavailable=deepcopy(raw);unavailable['volume_time_s'][1]=np.nan;unavailable['volume_delta_known'][1]=unavailable['volume_delta_usable'][1]=False
    value=measure.observe(unavailable,1,0,1,1.);assert value['volume_value_pair_known'] and not value['volume_delta_known'] and not value['volume_increased']
    checks.append('量の生差と時計付きusable資格は別記し、時計不明を肯定しない')
    first=measure.observe(raw,0,-1,1,1.);assert not first['seq_continuous'] and not first['last_pair_known']
    checks.append('最初原行に架空の直前行を作らない')
    future=deepcopy(raw)
    for name in ('last','volume','bid','ask','price_time_s','volume_time_s'):future[name][2:]=999.
    assert buy==measure.observe(future,1,0,1,1.)
    prefix={k:v[:2] for k,v in raw.items()};assert buy==measure.observe(prefix,1,0,1,1.)
    checks.append('当時原行以下だけを読み、未来改変及び実prefixで同じ観測')
    opposed=measure.observe(raw,2,1,1,1.);assert opposed['group']=='出来高増・現在値が逆方向へ変化'
    checks.append('反発BBO方向とLast変化方向の不一致を隠さない')
    stats=measure.counts([buy,sell,zero]);assert stats['判断候補数']==3 and stats['件数']['volume_increased']==2
    assert measure.counts([])['割合']['volume_increased'] is None
    checks.append('件数/候補分母の割合であり、無発火を勝ちに含めない')
    record=dict(seq=raw['raw_seq'],time_s=raw['price_time_s'],bid=raw['bid'],ask=raw['ask'],tick=1.,limit=1000.)
    normal=dict(quiet=np.zeros(5,bool),quiet_start_s=np.full(5,np.nan),range_pending_trend=np.zeros(5,bool))
    candidate=dict(row=0,side=1,planned_entry=101.,stop_price=90.)
    waited=measure.pending_observation(raw,record,normal,np.ones(5,bool),candidate)
    assert waited['終点種別']=='最初BBO到達' and waited['終点normal_row']==1 and not waited['終点より前のLast一呼値通過と出来高増']
    checks.append('公開当行の仮想到達を除外し、最初の次BBO到達を観測')
    altered=deepcopy(raw);altered['last'][1]=99.;record2=deepcopy(record);record2['ask']=np.array([103.,103.,101.,102.,102.])
    value=measure.pending_observation(altered,record2,normal,np.ones(5,bool),candidate)
    assert value['終点normal_row']==2 and value['最初の通過原行']['row']==1
    checks.append('BBO到達前のLast通過と正出来高増を原seqで区別し、同原行へ移動しない')
    same_cancel=deepcopy(normal);same_cancel['range_pending_trend'][1]=True
    value=measure.pending_observation(raw,record,same_cancel,np.ones(5,bool),candidate)
    assert value['終点種別']=='最初BBO到達'
    quiet=deepcopy(normal);quiet['quiet'][1]=True
    value=measure.pending_observation(raw,record,quiet,np.ones(5,bool),candidate)
    assert value['終点種別']=='元の静観又は新規期限'
    checks.append('既到達BBO優先と、予定静観取消先行の順序を観測区間へ反映')
    proof=dict(全合格=True,検査数=len(checks),検査=checks,source_SHA256={str(p.relative_to(measure.ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),measure.HERE/'measure.py')},
        大型保存入力読取=0,市場原本読取=0,金融再生=0,金融結果読取=0,現在API=0)
    measure.write('原値更新と出来高及び接頭の人工検査.json',proof)
    print(json.dumps(dict(全合格=True,検査数=len(checks)),ensure_ascii=False))


if __name__=='__main__':main()
