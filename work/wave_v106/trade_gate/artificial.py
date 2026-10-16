"""自己取引更新代理の時計、分母、三scopeを純人工だけで確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

import common
import policy
import votes


def fixture() -> dict:
    """
    機能: 同clock後半に複数取引更新代理がある8原行を人工生成する。
    引数: なし。
    返り値: dictは最小保存NPZ互換。市場原本や金融結果を使わない。
    """
    return dict(raw_seq=np.arange(8,dtype=np.int64),price_time_s=np.array([0.,1.,5.,10.,10.,10.,12.,40.]),
        bid=np.full(8,100.),ask=np.full(8,101.),last=np.array([100.,100.,100.,100.,101.,101.,101.,99.]),
        volume=np.array([0.,0.,0.,0.,1.,2.,2.,3.]),volume_time_s=np.array([0.,1.,5.,10.,10.,10.,12.,40.]),
        volume_delta=np.array([np.nan,0.,0.,0.,1.,1.,0.,1.]),volume_delta_usable=np.array([False,True,True,True,True,True,True,True]),
        volume_reset_reason=np.array([1,0,0,0,0,0,0,0],np.uint16),price_reset_reason=np.array([1,0,0,0,0,0,0,0],np.uint16))


def main() -> None:
    """
    機能: 1更新1票、同clock接頭、欠測拒否と元入口契約を人工境界で検査する。
    引数: なし。
    返り値: None。証跡のみ保存し、新金融/大型入力/APIは実行しない。
    """
    raw=fixture();checks=[];ctx=votes.context(raw)
    value=votes.measure(raw,ctx,6,10,1)
    assert value['known'] and value['accepted'] and value['up_votes']==2 and value['direction_votes']==2 and value['balance']==1.
    checks.append('正出来高増の原Last対直前BBOを2買票として方向確認')
    same=deepcopy(raw);same['volume_delta'][4:6]=[100.,1.]
    assert votes.measure(same,votes.context(same),6,10,1)==value
    checks.append('100枚増も1枚増も1観測1票、増加量を同側へ配賦しない')
    earlier=votes.measure(raw,ctx,4,10,1)
    assert earlier['known'] and not earlier['accepted'] and earlier['direction_votes']==1
    assert votes.measure(raw,ctx,5,10,1)['accepted']
    checks.append('sameclock未来後半の2票目を最初候補へ戻さない')
    prefix={k:v[:7] for k,v in raw.items()}
    assert value==votes.measure(prefix,votes.context(prefix),6,10,1)
    changed=deepcopy(raw)
    for key in ('price_time_s','last','bid','ask','volume','volume_delta'):changed[key][7]=10000.
    assert value==votes.measure(changed,votes.context(changed),6,10,1)
    checks.append('実prefixと未来数値改変で候補当時値完全一致')
    inside=deepcopy(raw);inside['last'][4]=100.5
    result=votes.measure(inside,votes.context(inside),6,10,1)
    assert result['known'] and result['direction_votes']==1 and result['inside_price_rows']==1 and not result['accepted']
    checks.append('直前bid/ask内側Lastは方向票0で、支持へ救済しない')
    zero=deepcopy(raw);zero['volume_delta'][4:6]=0.
    result=votes.measure(zero,votes.context(zero),6,10,1)
    assert result['known'] and result['direction_votes']==0 and result['balance'] is None and not result['accepted']
    checks.append('既知0出来高は票0、無活動を支持としない')
    gap=deepcopy(raw);gap['raw_seq'][5:]+=1
    result=votes.measure(gap,votes.context(gap),6,10,1);assert not result['known'] and result['reason']&4
    checks.append('原seq断裂を含む窓は未知')
    reverse=deepcopy(raw);reverse['price_time_s'][5]=9.
    result=votes.measure(reverse,votes.context(reverse),6,10,1);assert not result['known'] and result['reason']&4
    checks.append('価格代理時計highwater逆行を含む窓は未知')
    missing=deepcopy(raw);missing['price_time_s'][4]=np.nan
    result=votes.measure(missing,votes.context(missing),6,10,1);assert not result['known'] and result['reason']&4
    checks.append('価格時計欠測の次行を連続と誤認しない')
    volume_unknown=deepcopy(raw);volume_unknown['volume_delta_usable'][4]=False
    result=votes.measure(volume_unknown,votes.context(volume_unknown),6,10,1);assert not result['known'] and result['reason']&8
    reset=deepcopy(raw);reset['volume_reset_reason'][4]=32
    result=votes.measure(reset,votes.context(reset),6,10,1);assert not result['known'] and result['reason']&8
    checks.append('usable不能又は累計resetを0へ補完しない')
    last_missing=deepcopy(raw);last_missing['last'][4]=np.nan
    result=votes.measure(last_missing,votes.context(last_missing),6,10,1);assert not result['known'] and result['reason']&16
    quote_missing=deepcopy(raw);quote_missing['ask'][3]=np.nan
    result=votes.measure(quote_missing,votes.context(quote_missing),6,10,1);assert not result['known'] and result['reason']&16
    checks.append('正増行のLast又は直前BBO欠測を攻撃方向へ補完しない')
    assert votes.measure(raw,ctx,6,30,1)['reason']&1
    checks.append('W秒前以前の観測開始がなければ窓は未知')
    lower=deepcopy(raw);lower['price_time_s'][2:]=[2.,10.,10.,10.,12.,40.];lower['volume_delta'][2]=1.;lower['last'][2]=99.
    result=votes.measure(lower,votes.context(lower),6,10,1);assert result['up_votes']==2 and result['down_votes']==0
    checks.append('厳密な下端(cTime−W,cTime]で境界clockの票を除外')
    reflected=deepcopy(raw)
    reflected['bid']=200.-raw['ask'];reflected['ask']=200.-raw['bid'];reflected['last']=200.-raw['last']
    result=votes.measure(reflected,votes.context(reflected),6,10,-1)
    assert result['known'] and result['accepted'] and result['down_votes']==2 and result['balance']==1.
    checks.append('買売鏡像で釣合いと採否が一致')
    sameclock=deepcopy(raw);sameclock['volume_time_s'][4:6]=[10.,10.]
    assert votes.measure(sameclock,votes.context(sameclock),6,10,1)['accepted']
    checks.append('出来高時計同値でも保存正増を捨てない')
    counts=policy.configs();assert len(counts)==36 and len({c['id'] for c in counts})==36
    checks.append('3窓2margin2新規3scopeの36条件を固定')
    normal=dict(event=np.array([1,0,-1],np.int8),entry_families=np.array([1,0,2],np.int8))
    row_features={0:dict(known=False,reason=8,accepted=False,direction_votes=None),2:dict(known=False,reason=4,accepted=False,direction_votes=None)}
    R,_=votes.entry_filter(normal,row_features,'R');C,_=votes.entry_filter(normal,row_features,'C');B,_=votes.entry_filter(normal,row_features,'BOTH')
    assert R.tolist()==[True,True,False] and C.tolist()==[False,True,True] and B.tolist()==[False,True,False]
    assert normal['event'].tolist()==[1,0,-1]
    checks.append('R/C/BOTH対象だけ拒否、元eventと非対象及び非候補行を変更しない')
    features={0:dict(known=True,reason=0,accepted=True,direction_votes=2),2:dict(known=True,reason=0,accepted=True,direction_votes=2)}
    for scope in ('R','C','BOTH'):
        mask,reasons=votes.entry_filter(normal,features,scope);assert mask.all() and not reasons.any()
    checks.append('全肯定maskは元入口同値で、pending/出口用の追加列を作らない')
    import prepare
    clones=prepare.clone_checks();assert len(clones)==6
    checks.append('金融/価格反発/選択6source複製は旧source完全同bytes')
    result=dict(全合格=True,検査数=len(checks),検査=checks,source_SHA256=prepare.sources(),exact_math=clones,
        金融再生=0,市場原本読取=0,大型入力読取=0,金融結果読取=0,現在snapshot読取=0,API取得=0)
    common.write(common.HERE/'取引更新方向票とscope及び接頭の人工検査.json',result)
    print(json.dumps(dict(全合格=True,検査数=len(checks)),ensure_ascii=False))


if __name__=='__main__':main()
