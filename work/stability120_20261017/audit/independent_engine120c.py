"""追加信用・片側・新規価格限定・気配差制限を市場無しで敵対的に確認する。"""

from collections import Counter
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

import saved_accounting120 as accounting


HERE=Path(__file__).resolve().parent
OWNER=HERE.parent
SOURCE=OWNER/'recovery_c'/'engine120c.py'
EXPECTED='4433551d814aa39c7305d9de9ba15ded4bd0d656241dd9dd0e417b8bac45b7d4'
OLD=OWNER/'recovery_b'/'engine120b.py'
OUT=HERE/'新四管理の信用予約と最初次気配の独立人工'
CHECKS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 意味のある独立期待に不一致があれば停止する。
    引数: value(bool)、label(str)は条件と内容。
    返り値: None。
    """
    assert bool(value),label
    CHECKS[label]+=1


def load(name: str,path: Path):
    """
    機能: 源を独立module名で読み込み人工だけを実行可能にする。
    引数: name(str)、path(Path)は固有名と実装source。
    返り値: module。市場・保存金融結果を読まない。
    """
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod


def material(mid: object,mode: int,cap: int=3,half: object=.5,trail: float=100.,entry_end: float|None=None,close: float|None=None) -> tuple:
    """
    機能: 一単位・ゼロ切捨て料金の意味分離用人工BBOを作る。
    引数: mid/half(object)、mode/cap(int)、trail/entry_end/close(float|None)。
    返り値: tupleはreplay引数。約定の先読みや有利な待ちを加えない。
    """
    x=np.asarray(mid,float);n=len(x);h=np.full(n,half) if np.ndim(half)==0 else np.asarray(half,float)
    stop=float(n-3) if close is None else close;deadline=stop-2 if entry_end is None else entry_end
    return (np.arange(n,dtype=np.int64),np.arange(n,dtype=float),x,x-h,x+h,cap,1.,0.,1.,.01,mode,trail,0.,deadline,stop,float(n+1))


def same(actual: tuple,expected: tuple,label: str) -> None:
    """
    機能: 計算処理間の全注文・玉・曲線・summaryを完全一致で照合する。
    引数: actual/expected(tuple)、label(str)は人工出力と比較の意味。
    返り値: None。
    """
    for a,b,name in zip(actual,expected,('注文','玉','曲線','集計')):
        check(a.shape==b.shape and np.array_equal(a,b,equal_nan=True),label+'の'+name+'完全同値')


def account(args: tuple,answer: tuple) -> dict:
    """
    機能: 既凍結の保存台帳算術へ人工出力を接続する。
    引数: args(tuple)、answer(tuple)は人工観測と実装出力。
    返り値: dictは独立数量会計。戦略本体は再生しない。
    """
    rr,tt,last,bid,ask,cap,mult,fee,tick,fraction,mode,trail,start,entry_end,close,end=args
    o,l,c,s=answer;row=dict(zip(E.SUMMARY_COLUMNS,s.tolist()))
    row.update(realized_net=row['profit']-row['loss'],forced_loss=float(np.sum(np.maximum(-l[l[:,14]==9,13],0))),forced_profit=float(np.sum(np.maximum(l[l[:,14]==9,13],0))),trail_net=float(np.sum(l[l[:,14]==1,13])),long_net=float(np.sum(l[l[:,1]==1,13])),short_net=float(np.sum(l[l[:,1]==-1,13])))
    setting=dict(cap=cap,multiplier=mult,fee=fee,observed_tick=tick,session_start=start,entry_end=entry_end,close_time=close,session_end=end)
    return accounting.audit_account(dict(row=rr,time=tt,last=last,bid=bid,ask=ask),o,l,c,row,setting,dict(mode=mode,fraction=fraction,trail=trail))


def features(args: tuple,answer: tuple) -> None:
    """
    機能: 保存実新規から、当時の全同方向清算純益と同原row追加数を独立照合する。
    引数: args(tuple)、answer(tuple)は人工BBOと注文・玉。
    返り値: None。永久予約とは解釈せず当原rowのpending追加信用を検査する。
    """
    rr,tt,last,bid,ask,cap,mult,fee,tick,frac,mode,trail,*_=args
    o,l,c,s=answer;en=o[o[:,1]==1];ex={int(v[0]):v for v in o[o[:,1]==2]};fee_one=math.floor(fee+1e-9);step=s[16]
    for raw in np.unique(en[:,3]):
        di=int(np.flatnonzero(rr==raw)[0])
        for side in (1,-1):
            group=en[(en[:,3]==raw)&(en[:,2]==side)]
            if not len(group):continue
            held=[v for v in en if v[4]<=raw and (int(v[0]) not in ex or ex[int(v[0])][4]>raw)]
            own=[v for v in held if v[2]==side]
            check(not any(int(v[0]) in ex and ex[int(v[0])][3]<=raw for v in own),'同方向返済予約中は追加しない')
            if not own:check(len(group)==1,'各方向の初回は一枚だけ')
            else:
                pure=sum(side*((bid[di] if side==1 else ask[di])-v[7])*mult-2*fee_one for v in own)
                check(pure+1e-8>=3*step*mult*len(group),'同raw追加はpending分を一回ずつ純益から予約')
            if mode>=9:
                check(not any(v[2]==-side for v in held),'片方向型は対向保有中の新規判断無し')
                check(not any(v[2]==-side and v[3]<=raw<v[4] for v in en),'片方向型は対向新規予約中の新規判断無し')
            if mode>=10:
                actual=group[:,7];basis=ask[di] if side==1 else bid[di]
                check(np.all(side*(actual-basis)<=tick+1e-8),'新規実fillは判断気配から観測一tick以内')
            if mode==11:
                check(ask[di]-bid[di]<=step+1e-8,'COST判断時spread資格')
                check(np.all(group[:,15]-group[:,14]<=step+1e-8),'COST最初fillのspread資格')


def run(args: tuple) -> tuple:
    """
    機能: 人工のPython/JIT同値と独立全在庫会計をまとめて照合する。
    引数: args(tuple)は市場無関係の合成観測。
    返り値: tupleはJITの出力。
    """
    result=E.replay(*args);same(result,E.replay.py_func(*args),'新管理JITとPython')
    account(args,result)
    if args[10]>=8:features(args,result)
    return result


def main() -> None:
    """
    機能: 旧八管理同値、新四管理の信用・片側・FAK・spread・gap・未来不変を人工だけで調べる。
    引数: なし。
    返り値: None。源を変更せず成功又はFalseを自所有領域へ保存する。
    """
    global E
    original=SOURCE.read_bytes();check(hashlib.sha256(original).hexdigest()==EXPECTED,'新源開始SHA')
    os.environ.pop('NUMBA_BOUNDSCHECK',None)
    E=load('audit120c_closed_engine',SOURCE);old=load('audit120c_old120b_engine',OLD)
    rng=np.random.default_rng(20261017);path=(65000+np.cumsum(rng.integers(-4,5,250))*10).astype(float)
    legacy=[]
    for cap in (2,20):
        for mode in range(8):
            args=(np.arange(len(path),dtype=np.int64),np.arange(len(path),dtype=float),path,path-10,path+10,cap,10.,11.,10.,.000125,mode,1.,0.,240.,245.,251.)
            answer=E.replay(*args);same(answer,old.replay(*args),'旧八管理の合成出力')
            legacy.append(dict(cap=cap,mode=mode,entries=int(answer[3][13])))
    # ----------------------------------------
    # 多段同時到達でも初回一枚、その後の同raw追加は純益三単位ずつを重複使用しない。
    credit=material([100,103,104,140,141,141,141,141,141,141,141,141],8,cap=20,entry_end=5,close=8)
    value=run(credit);entry=value[0][value[0][:,1]==1]
    first=entry[entry[:,3]==1];adds=entry[entry[:,3]==3]
    check(len(first)==1 and len(adds)==11,'初回一枚から純益三十五星分で追加十一枚だけ')
    # ----------------------------------------
    # 方向合計停止は全玉を次BBOで返し、予定三単位を値飛びで超える損失も残す。
    stop_path=[100,103,104,106,108,109,110,109,107,90,90,90,90,90,90]
    cases=[]
    for mode in (8,9,10,11):
        # 価格限定は一tick以内の動きで予約を通過させてから反転させる。
        rich=np.r_[np.arange(100.,116.),np.arange(114.,109.,-1.),90.,90.,90.,90.,90.,90.]
        args=material(rich,mode,cap=4,entry_end=18,close=23)
        result=run(args);stops=result[1][result[1][:,14]==8]
        check(len(stops)>0 and np.min(stops[:,13])<-3,'方向停止でも次BBOのgap超過を隠さない')
        check(result[3][13]>1,'全新modeで実追加が発火')
        cases.append(dict(mode=mode,entries=int(result[3][13]),stop_lots=len(stops),min_stop=float(np.min(stops[:,13]))))
    # ----------------------------------------
    # 全方向玉の実返済直後は、空き枠に残った旧安値から即再入しない。
    reset_args=material([100,103,104,100,110,111,112,113,114,114,114,114,114],8,cap=3,entry_end=10,close=11)
    reset=run(reset_args);entries=reset[0][reset[0][:,1]==1]
    check(np.any((reset[1][:,14]==8)&(reset[1][:,8]==4)),'停止判断後の反対gapで実返済が完了')
    check(not np.any((entries[:,2]==1)&(entries[:,3]==4)),'全返済行では全空き枠極値を現在へ戻す')
    check(np.any((entries[:,2]==1)&(entries[:,3]==7)),'新しい三単位反発は再準備後に許す')
    # ----------------------------------------
    # 新規限定は最初の次正常気配だけを使い、不達後に有利な後続価格を待たない。
    for side in (1,-1):
        raw=np.array([100,100,103,104.5,103.5,103.5,103.5,103.5,103.5,103.5,103.5,103.5])
        mid=raw if side==1 else 200-raw
        baseline=run(material(mid,9,cap=1,entry_end=7,close=9))
        limited=run(material(mid,10,cap=1,entry_end=7,close=9))
        check(np.any((baseline[0][:,1]==1)&(baseline[0][:,2]==side)),'FAK対照の無制限新規は最初次rowで発火')
        check(not np.any((limited[0][:,1]==1)&(limited[0][:,2]==side)) and limited[3][14]>0,'FAK不達はその場で失効し後から復活しない')
        edge=raw.copy();edge[3:]=104.;edge=edge if side==1 else 200-edge
        boundary=run(material(edge,10,cap=1,entry_end=7,close=9))
        check(np.any((boundary[0][:,1]==1)&(boundary[0][:,2]==side)),'FAK一tick丁度は買売対称に約定')
    # ----------------------------------------
    # 広い気配は新規極値を作らず、最初fillで拡幅しても新規を取消す。返済は妨げない。
    mid=np.array([100,100,80,83,84,84,84,84,84,84,84,84.]);half=np.full(len(mid),.5);half[2]=1.
    limited=run(material(mid,10,half=half,entry_end=7,close=9));cost=run(material(mid,11,half=half,entry_end=7,close=9))
    check(np.any(limited[0][:,1]==1) and not np.any(cost[0][:,1]==1),'広気配だけの安値をCOSTは入口極値へ採用しない')
    mid=np.array([100,100,103,103.25,103.25,103.25,103.25,103.25,103.25,103.25,103.25,103.25]);half=np.full(len(mid),.25);half[3]=1.
    limited=run(material(mid,10,half=half,entry_end=7,close=9));cost=run(material(mid,11,half=half,entry_end=7,close=9))
    check(np.any(limited[0][:,1]==1) and not np.any(cost[0][:,1]==1),'価格内でも最初fillが広気配ならCOSTは失効')
    wide_mid=[100,100,103,104,105,105,105,105,105];wide_half=[.25,.25,.25,.25,.25,2.,2.,2.,2.]
    wide_exit=run(material(wide_mid,11,cap=1,half=wide_half,entry_end=4,close=5))
    check(np.any((wide_exit[0][:,1]==2)&(wide_exit[0][:,15]-wide_exit[0][:,14]>wide_exit[3][16])),'広気配でも既存玉の場末返済を止めない')
    # ----------------------------------------
    # 実商品料金・枚数上限で全新modeをPythonと照合し、未来だけを書き換えても過去は不変。
    for mode in (8,9,10,11):
        for cap,mult,fee,tick,base,half in ((10,1000.,41.8,.5,4000.,.25),(20,10.,11.,10.,65000.,5.)):
            x=base+np.cumsum(rng.integers(-4,5,180))*tick
            args=(np.arange(len(x),dtype=np.int64),np.arange(len(x),dtype=float),x,x-half,x+half,cap,mult,fee,tick,.000125,mode,1.,0.,170.,175.,181.)
            result=run(args)
            prefix=list(args);prefix[:5]=[v[:70] for v in args[:5]];short=run(tuple(prefix))
            changed=list(args);replacement=x.copy();replacement[70:]=replacement[69]+np.arange(len(x)-70)*tick*3
            changed[2:5]=[replacement,replacement-half,replacement+half];full=run(tuple(changed))
            same((short[0],short[1]),(full[0][full[0][:,4]<=69],full[1][full[1][:,8]<=69]),'未来置換の前半注文と玉')
            for point in short[2][:-1]:
                target=full[2][full[2][:,0]==point[0]][0]
                check(np.array_equal(point,target,equal_nan=True),'未来置換でも前半全在庫時価不変')
    check(SOURCE.read_bytes()==original,'新源終端SHA不変')
    proof=dict(passed=True,engine_sha256=EXPECTED,audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),accounting_source_sha256=hashlib.sha256(Path(accounting.__file__).read_bytes()).hexdigest(),checks=dict(CHECKS),accounting_checks=dict(accounting.CHECKS),legacy_cases=legacy,new_cases=cases,original_market_reads=0,NPZ_reads=0,result_reads=0,financial_replay=0,registry_changes=0,source_changes=0,留保='信用は同原rowのpending追加を重複消費しない条件。既約定分の三単位を永久確保する制度ではない。固定損失停止は判断線であり次BBOの約定損失を保証しない。旧八管理は人工同値だけを照合し旧実測再生は零。')
    accounting.save(OUT/'新四管理の信用予約と最初次気配の独立人工.json',proof)
    print(json.dumps(dict(passed=True,engine_sha256=EXPECTED,checks=sum(CHECKS.values()),accounting_checks=sum(accounting.CHECKS.values())),ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        OUT.mkdir(parents=True,exist_ok=True);target=OUT/'人工False.json'
        if not target.exists():accounting.save(target,dict(passed=False,error_type=type(exc).__name__,error=str(exc),engine_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),checks=dict(CHECKS),accounting_checks=dict(accounting.CHECKS),market_reads=0,NPZ_reads=0,financial_replay=0))
        raise
