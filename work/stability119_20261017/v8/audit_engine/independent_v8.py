"""独立した人工二脚で固定準備・別clock二確認・保守的取消を確認する。"""

import ast
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
V8=HERE.parent
ROOT=V8.parents[2]


def module(path: Path,name: str) -> object:
    """
    機能: 閉鎖された数値SOURCEだけを一意名で接続する。
    引数: path(Path)、name(str)はSOURCEとmodule名。
    返り値: objectは実行入口を起動しないmodule。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def main() -> None:
    """
    機能: v5不変会計に対しv8固有の入口と出口を少数の反例で確認する。
    引数: なし。
    返り値: None。独立人工証跡を保存し、市場・cache・正式金融・登録は使用しない。
    """
    source=V8/'engine_v8.py';start_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    assert start_sha=='499d00b4fd88418ee1e3a6894d64eb31fe95b25479403e8f9bb106a51d07b1fc'
    engine=module(source,'engine_v8')
    checks=Counter()
    def check(value: bool,label: str) -> None:
        """
        機能: 独立した期待を意味付きで検査する。
        引数: value(bool)、label(str)は判定と確認内容。
        返り値: None。不一致時は実市場へ進めず停止する。
        """
        assert value,label
        checks[label]+=1

    def case(path: list, mode: int=0, nk_only: tuple=(), top_end: float=math.inf,
             widths: dict|None=None, scales: dict|None=None, cut: float=math.inf,
             duplicate: tuple|None=None, clocks: tuple=(120.,180.,240.), python: bool=False) -> tuple:
        """
        機能: 独立に選んだ残差経路を二市場イベントに変換して核心へ渡す。
        引数: path(list[tuple])、mode(int)、各変更指定は人工観測と反証条件。
        返り値: tupleは保存配列群。数量とモデルは未来値で補わない。
        """
        records=[]
        for leg in (0,1):
            values=[]
            for time,delta in path:
                if time>cut or (leg==1 and (time in nk_only or time>top_end)):continue
                common=(scales or {}).get(time,1.)
                price=(100000.*math.exp(delta) if leg==0 else 1000.)*common
                spread=(widths or {}).get(time,(10.,.1))[leg]
                values.append((time,price,spread))
                if duplicate is not None and leg==0 and time==duplicate[0]:
                    values.append((time,100000.*math.exp(duplicate[1])*common,spread))
            tt=np.asarray([v[0] for v in values],float);last=np.asarray([v[1] for v in values],float);width=np.asarray([v[2] for v in values],float)
            records.append((np.arange(len(tt),dtype=np.int64),tt,last-width/2,last+width/2,last))
        cc=np.asarray([t for t in clocks if t<=cut],float)
        history=np.tile([1.,1.,math.log(100.),.001],(len(cc),1))
        times=np.r_[records[0][1],records[1][1],cc]
        kinds=np.r_[np.zeros(len(records[0][1]),np.int8),np.ones(len(records[1][1]),np.int8),np.full(len(cc),2,np.int8)]
        indexes=np.r_[np.arange(len(records[0][1])),np.arange(len(records[1][1])),np.arange(len(cc))].astype(np.int64)
        rows=np.r_[records[0][0],records[1][0],np.zeros(len(cc),np.int64)]
        order=np.lexsort((rows,kinds,times))
        fn=engine.replay.py_func if python else engine.replay
        return fn(times[order],kinds[order],indexes[order],cc,history,*records[0],*records[1],800.,900.,mode)

    path=[(120.,.003),(121.,.0023),(122.,.0022),(123.,.0021),(124.,.0015),(125.,.0009),(126.,.0015),(127.,.0015),(130.,-.0001),(131.,-.0001)]
    for sign in (1,-1):
        directed=[(t,sign*d) for t,d in path]
        for mode in (0,1):
            result=case(directed,mode)
            orders,parents,_,_,preps=result[:5]
            check(len(orders)==4 and len(parents)==1 and parents[0,1]==1.,'両方向二退出の実新規返済')
            check(np.all(orders[:2,5]==122.) and np.all(orders[:2,6]==123.),'別二clock確認の後strict次clockで建てる')
            check(preps[0,8]==121. and preps[0,9]==122. and parents[0,2]==-sign,'確認clockと逆方向二脚の系譜')
            check(parents[0,5]==(1. if mode==0 else 6.) and parents[0,4]==(130. if mode==0 else 126.),'center又は一σ改善後半σ追尾で退出')
            expected_fee=2*(math.floor(preps[0,15]*11)+math.floor(preps[0,16]*41.8))
            expected_budget=(abs(preps[0,7])-abs(preps[0,11]))*preps[0,15]*10*preps[0,17]+expected_fee
            check(math.isclose(parents[0,10],expected_budget,abs_tol=1e-6),'固定撤回幅元本と往復料の予算')
            gross=np.zeros(2);fees=np.zeros(2)
            for leg in (0,1):
                own=orders[orders[:,1]==leg]
                gross[leg]=own[0,3]*(own[1,8]-own[0,8])*own[0,4]*(10 if leg==0 else 1000)
                fees[leg]=sum(math.floor(v[4]*(11 if leg==0 else 41.8)+1e-9) for v in own)
            check(np.allclose(parents[0,22:24],gross) and np.allclose(parents[0,24:26],fees) and math.isclose(parents[0,28],sum(gross-fees),abs_tol=1e-6),'全注文から独立計算した二脚粗損益と費用')
            check(np.all(orders[:,6]>orders[:,5]),'新規と返済の同clock約定禁止')
    for replacement in (.0028,.0035):
        high=max(.003,replacement)
        result=case([(120.,.003),(121.,.0023),(122.,replacement),(123.,high-.0007),(124.,high-.0008),(125.,high-.0009)])
        check(result[4][0,8]==123. and result[4][0,9]==124. and result[0][0,5]==124.,'閾値割れ又は極値更新で古い一確認を破棄')
    result=case([(120.,.003),(121.,.0023),(127.,.0023),(128.,.0023),(129.,.0022),(130.,.0021)],nk_only=(127.,))
    check(result[4][0,8]==128. and result[4][0,9]==129.,'相手気配が五秒超なら確認をreset')
    result=case([(120.,.003),(121.,.0023),(122.,.0023),(123.,.0022),(124.,.0021)],duplicate=(121.,.0029))
    check(result[4][0,8]==122. and result[4][0,9]==123.,'同clock先行行だけの戻りを確認に数えない')
    result=case([(120.,.003),(121.,.0023),(122.,.0022),(123.,.0021),(124.,.0021)],scales={124.:1.1})
    check(len(result[0])==2 and result[1][0,1]==0 and result[1][0,5]==0,'共同同clockの共通上昇を偽の撤回へ変えない')
    result=case([(120.,.003),(121.,-.0001),(122.,-.0001)])
    check(len(result[0])==0 and result[4][0,19]==2.,'center帰還は未予約準備を取消')
    result=case(path,cut=121.)
    check(len(result[0])==0 and len(result[1])==0,'一確認とEOFだけで実取引を作らない')
    result=case(path,cut=123.)
    check(result[1][0,1]==0 and np.all(np.isnan(result[1][0,16:18])),'EOF保有を架空返済へ変えない')
    baseline=case(path,cut=123.)
    for future in (.05,-.05):
        changed=case(path[:4]+[(t,future) for t,_ in path[4:]])
        check(np.array_equal(baseline[0],changed[0][changed[0][:,6]<=123.],equal_nan=True),'未来置換で完成clockの過去注文不変')
        check(np.array_equal(baseline[4][:,:19],changed[4][:1,:19],equal_nan=True),'未来置換で予約モデル極値数量を不変')
    result=case(path,scales={123.:1.5})
    check(np.array_equal(result[0][:2,4],baseline[0][:2,4]),'予約後価格で整数数量を選び直さない')
    wide={time:(500.,20.) for time,_ in path if time>=121}
    result=case(path,widths=wide)
    check(len(result[0])==0,'中心予定益が三倍費用未満なら予約しない')
    result=case([(120.,.003),(121.,.0023),(122.,.0022),(123.,.0021),(182.,.0021),(183.,.0021)],top_end=122.)
    check(result[1][0,29]==1. and result[1][0,5]==4. and result[-1][2]==1 and np.all(result[-1][4:6]==0),'六十秒取消優先と孤立脚の後clock返済')
    result=case([(120.,.003),(121.,.0023),(122.,.0022),(123.,.0021),(124.,.0031),(125.,.0031),(180.,.003),(190.,-.0001),(240.,.003),(241.,.0023),(242.,.0022),(243.,.0021)])
    check(len(result[4])==2 and result[4][1,1]==240.,'実返済だけでは再準備せずcenter帰還後だけ再準備')
    # ----------------------------------------
    # 共通会計は同bytes旧源のASTを比較し、初期化やSOURCEの逸脱を検知する。
    legacy=V8/'legacy_engine_v5.py'
    check(legacy.exists(),'旧v5同bytes対照SOURCEの存在')
    old_tree=ast.parse(legacy.read_text(encoding='utf-8'));new_tree=ast.parse(source.read_text(encoding='utf-8'))
    old_f={v.name:ast.dump(v,include_attributes=False) for v in old_tree.body if isinstance(v,ast.FunctionDef)}
    new_f={v.name:ast.dump(v,include_attributes=False) for v in new_tree.body if isinstance(v,ast.FunctionDef)}
    for name in ('_quotes','model_history','choose_quantities','_mark','_parent'):check(old_f[name]==new_f[name],'基礎モデル整数会計AST不変:'+name)
    check(hashlib.sha256(source.read_bytes()).hexdigest()==start_sha,'核心SOURCE開始終端不変')
    proof={'passed':True,'economic_source_SHA256':start_sha,'checks':dict(checks),'total_checks':sum(checks.values()),'market_reads':0,'cache_reads':0,'formal_financial_replay':0,'registry_changes':0,'source_changes':0,'留保':'人工の会計と因果性の確認であり、実データでの有効性標本は増えていない。'}
    target=HERE/'固定準備と二確認reset及び共同時計の独立人工.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'passed':True,'checks':sum(checks.values()),'SHA256':hashlib.sha256(target.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=='__main__':main()
