"""カバー保持・飽和救済・上下個別回転を、実市場無しの独立会計で監査する。"""

from collections import Counter
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

import fixtures120e as fixtures
import saved_accounting120 as core


HERE=Path(__file__).resolve().parent
OWNER=HERE.parent
SOURCE=OWNER/'recovery_e'/'engine120e.py'
EXPECTED='5fcecd4aa8061ce4be46291e90bfd7d912b11dbd0c1f7f7e3e535b34f346830a'
OUT=HERE/'カバー保持救済と上下回転の独立人工'
CHECKS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 独立人工の意味別期待を確認し不一致で停止する。
    引数: value(bool)、label(str)は判定と内容。
    返り値: None。
    """
    assert bool(value),label
    CHECKS[label]+=1


def load(name: str,path: Path):
    """
    機能: 所有者が閉じた源だけを固有module名で読み込む。
    引数: name(str)、path(Path)はmodule名とsource。
    返り値: module。市場・金融保存値・登録台帳を読まない。
    """
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod


def normal(args: tuple) -> tuple[dict,int]:
    """
    機能: eのLastを含む正常観測資格だけを独立に作る。
    引数: args(tuple)は原row、時計、Last、気配、固定契約。
    返り値: tuple[dict,int]は正常観測と棄却数。未知価格を補完しない。
    """
    rows,times,last,bid,ask,*_=args;start,end=args[12],args[15]
    mask=np.isfinite(times)&(times>=start)&(times<=end)&np.isfinite(last)&(last>0)&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(bid<=ask)
    indices=np.flatnonzero(mask);accepted=np.zeros(len(rows),bool)
    if len(indices):accepted[indices]=times[indices]>=np.r_[-math.inf,np.maximum.accumulate(times[indices])[:-1]]
    return {k:v[accepted] for k,v in zip(('row','time','last','bid','ask'),args[:5])},int(len(rows)-sum(accepted))


def account(args: tuple,answer: tuple) -> dict:
    """
    機能: eの両建てを明示し、既凍結の全在庫算術で注文・玉・時価を照合する。
    引数: args(tuple)、answer(tuple)は人工観測とe出力。
    返り値: dictは全正常原rowの独立現金・組baseline・全玉評価。戦略エンジンは再生しない。
    """
    q,rejected=normal(args);o,l,c,s=answer;fee=math.floor(args[7]+1e-9);mult=args[6]
    row=dict(zip(E.SUMMARY_COLUMNS,s.tolist()));check(row['clock_rejected']==rejected,'有限LastとBBOと時計の棄却数')
    row['clock_rejected']=0
    row.update(realized_net=row['profit']-row['loss'],forced_loss=float(np.sum(np.maximum(-l[l[:,14]==9,13],0))),forced_profit=float(np.sum(np.maximum(l[l[:,14]==9,13],0))),trail_net=float(np.sum(l[l[:,14]==1,13])),long_net=float(np.sum(l[l[:,1]==1,13])),short_net=float(np.sum(l[l[:,1]==-1,13])))
    setting=dict(cap=args[5],multiplier=mult,fee=args[7],observed_tick=args[8],session_start=args[12],entry_end=args[13],close_time=args[14],session_end=args[15])
    # eのmode1/2は旧NET/FLIPではない。両建ての会計種別を別番号で明示する。
    core.audit_account(q,o,l,c,row,setting,dict(mode=12+args[10],fraction=args[9],trail=args[11]))
    state={};cash=0.;realized=0.;ptr=0;baseline=0.;basket_peak=0.;previous_count=0;snapshots={}
    for i,raw in enumerate(q['row']):
        before=cash
        while ptr<len(o) and o[ptr,4]==raw:
            order=o[ptr];uid=int(order[0]);side=int(order[2])
            if order[1]==1:
                state[uid]=dict(side=side,entry=order[7],rung=int(order[10]),entry_row=int(raw),order=order.copy());cash-=fee
            else:
                item=state.pop(uid);gross=item['side']*(order[7]-item['entry'])*mult;cash+=gross-fee;realized+=gross-2*fee
            ptr+=1
        if previous_count==0 and state:baseline=before;basket_peak=0.
        liquid={uid:item['side']*((q['bid'][i] if item['side']==1 else q['ask'][i])-item['entry'])*mult-2*fee for uid,item in state.items()}
        equity=cash+sum(v+fee for v in liquid.values());basket=equity-baseline
        if state:basket_peak=max(basket_peak,basket)
        snapshots[int(raw)]=dict(cash=cash,realized=realized,equity=equity,basket=basket,baseline=baseline,peak=basket_peak,liquid=liquid,held={uid:dict(item) for uid,item in state.items()})
        previous_count=len(state)
    check(ptr==len(o),'所有注文を正常行で全処理')
    entry=o[o[:,1]==1];exits=o[o[:,1]==2]
    di=core.positions(q['row'],entry[:,3],'e新規判断原row');fi=core.positions(q['row'],entry[:,4],'e新規約定原row')
    check(np.all(entry[:,2]*(q['last'][di]-entry[:,17])>=-1e-6),'e新規判断Lastは方向別追尾線へ到達')
    check(np.all(di>0) and np.all(entry[:,2]*(q['last'][di]-q['last'][di-1])>0),'e新規は正常Lastの当時方向変化と一致')
    check(np.all(entry[:,2]*(entry[:,7]-np.where(entry[:,2]>0,q['ask'][di],q['bid'][di]))<=args[8]+1e-6),'e新規は判断BBOから一観測tick以内')
    check(np.all(q['ask'][di]-q['bid'][di]<=s[16]+1e-6) and np.all(q['ask'][fi]-q['bid'][fi]<=s[16]+1e-6),'e判断と最初fillのspread資格')
    if args[10] in (0,1):check(not np.any(exits[:,9]==1),'KEEPとRESCUEは勝玉の個別利確をしない')
    if args[10]==0:check(np.all(np.isin(exits[:,9],(9,10))),'KEEPは全組追尾又は場末だけ返済')
    if args[10]==2:check(np.all(np.isin(exits[:,9],(1,9))),'ROTATEに組追尾又はRESCUEを混ぜない')
    for order in exits:
        raw=int(order[3]);uid=int(order[0]);reason=int(order[9]);frame=snapshots[raw]
        check(uid in frame['held'],'返済判断時に対象UIDを実保有')
        if reason==10:
            check(frame['basket']>0 and frame['peak']>=(args[11]+1)*s[16]*mult and frame['peak']-frame['basket']>=args[11]*s[16]*mult-1e-6,'組追尾は初回fee前baselineと途中実損を含む純益')
            ids=set(exits[exits[:,3]==raw,0].astype(int));check(set(frame['held'])==ids,'組追尾は全実玉を同じ判断原rowで返済予約')
        if reason==1:
            held=frame['held'][uid];en=int(np.searchsorted(q['row'],held['entry_row']));stop=int(np.searchsorted(q['row'],raw));side=held['side']
            values=side*((q['bid'][en:stop+1] if side==1 else q['ask'][en:stop+1])-held['entry'])*mult-2*fee
            check(max(values)>0 and values[-1]>0 and max(values)-values[-1]>=args[11]*s[16]*mult-1e-6,'ROTATEは正peakから戻り現在純益も正の玉だけ返済判断')
        if reason==11:
            check(args[10]==1 and sum(v['side']==1 for v in frame['held'].values())==args[5] and sum(v['side']==-1 for v in frame['held'].values())==args[5],'RESCUEは両側実cap飽和時だけ')
            item=frame['held'][uid];own=[frame['liquid'][key] for key,value in frame['held'].items() if value['side']==item['side']]
            check(frame['liquid'][uid]<0 and frame['liquid'][uid]==min(own),'RESCUE対象は反対方向の最悪負け一枚')
            check(len(exits[(exits[:,3]==raw)&(exits[:,9]==11)])==1,'RESCUE一判断で一枚だけ返済')
    return snapshots


def run(args: tuple) -> tuple:
    """
    機能: 全配列のPython/JIT一致と独立算術を同じ人工で照合する。
    引数: args(tuple)は市場無関係の観測と固定契約。
    返り値: tupleは高速版の出力。
    """
    answer=E.replay(*args);plain=E.replay.py_func(*args)
    for a,b,name in zip(answer,plain,('注文','玉','曲線','集計')):check(a.shape==b.shape and np.array_equal(a,b,equal_nan=True),'eのPythonとJITの'+name+'完全同値')
    account(args,answer)
    return answer


def main() -> None:
    """
    機能: 初回一枚・カバー保持・部分実損・個別回転・具体入口例・EOF・未来不変を人工で確認する。
    引数: なし。
    返り値: None。新規市場・金融結果は読まず源修正も行わない。
    """
    global E
    original=SOURCE.read_bytes();check(hashlib.sha256(original).hexdigest()==EXPECTED,'e修正源開始SHA')
    os.environ.pop('NUMBA_BOUNDSCHECK',None);E=load('audit120e_closed_engine',SOURCE)
    # ----------------------------------------
    # 旧初回break反例は全空き極値の先行観測で修正される。
    args=fixtures.material([100,103,103,103,103,103,103,103,103,103],0,last=[100,103,101,99,99,99,99,99,99,99],entry_end=6,close=8)
    boundary=run(args);be=boundary[0][boundary[0][:,1]==1]
    check(np.any((be[:,2]==-1)&(be[:,3]==3)&(be[:,17]==100)),'初回買い発火行の高値103も売り側で観測済み')
    for mode in range(3):
        value=run(fixtures.first_phase_only_one(mode));entry=value[0][value[0][:,1]==1]
        check(sum(entry[:,3]==1)==1 and sum(entry[:,4]==2)==1,'多数段階飛びでも初回予約と初回fillは一枚')
        check(sum(entry[:,4]==3)>1,'初回fill後は両方向段階追加の余地を残す')
    # ----------------------------------------
    # 小さな純益peakはROTATEだけが個別追尾し、KEEP/RESCUEは組起動線まで保持する。
    profits=[]
    for mode in range(3):
        answer=run(fixtures.positive_peak_below_old_activation(mode));orders=answer[0];one=orders[(orders[:,1]==2)&(orders[:,9]==1)]
        if mode==2:check(len(one)==1 and one[0,3]==4 and one[0,16]==418,'ROTATEはpeak1418から418へ戻れば旧2000起動線なしで個別返済')
        else:check(not len(one) and np.all(orders[orders[:,1]==2,9]==9),'KEEPとRESCUEはこの小幅純益を個別に外さない')
        profits.append(dict(mode=mode,individual_closes=len(one),net=float(answer[3][0])))
    # ----------------------------------------
    # 飽和時に負け一枚を返しても、その確定損失を組開始cashから取り除かない。
    for mode in (0,1):
        args=fixtures.rescue_realized_loss_is_not_erased(mode);answer=run(args);snap=account(args,answer);o=answer[0]
        rescue=o[(o[:,1]==2)&(o[:,9]==11)]
        if mode==0:check(not len(rescue),'KEEPは両側飽和を保持する')
        else:
            check(len(rescue)==1 and rescue[0,3]==6 and rescue[0,4]==7 and rescue[0,16]==-12,'RESCUEはLast三単位反発で逆側最悪一枚を次BBO返済')
            check(snap[7]['realized']==-12 and sum(snap[7]['liquid'].values())==6 and snap[7]['basket']==-6,'実現損十二と残玉純益六を同じ組に保持')
            check(snap[8]['basket']==-7 and not np.any(o[(o[:,1]==2),9]==10),'残玉だけの純益回収を全組利益と誤認しない')
            check(sum(v['side']==1 for v in snap[7]['held'].values())==1 and sum(v['side']==-1 for v in snap[7]['held'].values())==0,'飽和削減後は実約定で差分一枚を作る')
    # ----------------------------------------
    # ユーザー指定の3993/3994と3993/3984、および鏡像を判断線として直接確認する。
    concrete=[]
    paths=([4000,3990,3990,3993,3993,3994,3994,3994,3994,3994],
           [4000,3990,3990,3993,3993,3980,3980,3984,3984,3984,3984,3984])
    for case,path in enumerate(paths):
        for side in (1,-1):
            x=np.asarray(path,float);x=x if side==1 else 8000-x
            args=fixtures.material(x,2,cap=3,half=.25,multiplier=1000.,fee=41.8,tick=.5,fraction=.00025)
            answer=run(args);entry=answer[0][(answer[0][:,1]==1)&(answer[0][:,2]==side)];expected=[3993,3994 if case==0 else 3984];expected=expected if side==1 else [8000-v for v in expected]
            chosen=[]
            for rung,goal in enumerate(expected):
                found=entry[entry[:,10]==rung];check(len(found)==1 and found[0,17]==goal,'具体入口例は各未約定側rungのLast極値から指定線で発火')
                chosen.append(found[0]);check(found[0,7]==goal+side*.25,'具体入口の実約定はtriggerlineではなく後続ask又はbid')
            first_lot=answer[1][answer[1][:,0]==chosen[0][0]][0]
            check(first_lot[6]==chosen[0][7],'新安値又は高値で既保有玉の実建値を移動しない')
            concrete.append(dict(path=case,side=side,trigger_lines=expected,fill_prices=[float(v[7]) for v in chosen]))
    # ----------------------------------------
    # 多数cap・実料金・同clock・全正常行時価・EOF保有を会計から確認する。
    rng=np.random.default_rng(12017)
    for mode in range(3):
        for cap in (1,2,10,20):
            x=65000+np.cumsum(rng.integers(-3,4,150))*10
            args=(np.arange(len(x),dtype=np.int64),np.floor(np.arange(len(x))/2.),x.astype(float),x-5.,x+5.,cap,10.,11.,10.,.000125,mode,1.,0.,65.,70.,80.)
            answer=run(args);check(answer[3][8]==0,'十分な場末後気配があれば全玉実返済')
    eof_args=list(fixtures.positive_peak_below_old_activation(0));eof_args[:5]=[v[:4] for v in eof_args[:5]]
    eof=run(tuple(eof_args));check(eof[3][8]>0 and not np.any(eof[0][eof[0][:,1]==2,9]==9),'EOF含損又は含益を架空の場末返済へ変えない')
    bad=list(fixtures.positive_peak_below_old_activation(2));bad[2]=bad[2].copy();bad[1]=bad[1].copy();bad[2][2]=np.nan;bad[1][2]=1000.
    invalid=run(tuple(bad));check(invalid[3][15]==1 and not np.any(invalid[0][:,4]==2),'未知Lastの未来時計が高水位を汚染せず次正常rowで処理する')
    # ----------------------------------------
    # Last/BBO未来の変更で、既観測済みの注文・玉・公開資産を変えない。
    for mode in range(3):
        x=(65000+np.cumsum(rng.integers(-3,4,160))*10).astype(float)
        args=(np.arange(len(x),dtype=np.int64),np.arange(len(x),dtype=float),x,x-5,x+5,10,10.,11.,10.,.000125,mode,1.,0.,150.,155.,161.)
        prefix=list(args);prefix[:5]=[v[:60] for v in args[:5]];short=run(tuple(prefix))
        changed=list(args);future=x.copy();future[60:]=x[59]+np.arange(len(x)-60)*30;changed[2:5]=[future,future-5,future+5];full=run(tuple(changed))
        for a,b in ((short[0],full[0][full[0][:,4]<=59]),(short[1],full[1][full[1][:,8]<=59])):check(a.shape==b.shape and np.array_equal(a,b,equal_nan=True),'e未来置換で前半全注文と完結玉不変')
        for point in short[2][:-1]:check(np.array_equal(point,full[2][full[2][:,0]==point[0]][0],equal_nan=True),'e未来置換で前半全残玉資産不変')
    sys.path.insert(0,str(OWNER));catalog=load('audit120e_catalog',OWNER/'recovery_e'/'catalog120e.py');specs=catalog.specifications()
    check(len(specs)==18 and len({s['id'] for s in specs})==18 and {s['mode'] for s in specs}=={0,1,2},'e三管理三幅二追尾の十八条件')
    check(SOURCE.read_bytes()==original,'e源終端SHA不変')
    proof=dict(passed=True,engine_sha256=EXPECTED,audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),fixtures_source_sha256=hashlib.sha256(Path(fixtures.__file__).read_bytes()).hexdigest(),accounting_source_sha256=hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),checks=dict(CHECKS),accounting_checks=dict(core.CHECKS),small_peak_cases=profits,concrete_entries=concrete,original_market_reads=0,NPZ_reads=0,result_reads=0,financial_replay=0,registry_changes=0,source_changes=0,留保='人工・源・算術の確認で収益優位の証明ではない。KEEP/RESCUEとROTATEは出口の異なる対照。全残玉の返済側BBOと費用を評価し、RESCUE途中実損やEOFを隠さない。')
    core.save(OUT/'カバー保持飽和救済と上下個別回転の独立人工.json',proof)
    print(json.dumps(dict(passed=True,engine_sha256=EXPECTED,checks=sum(CHECKS.values()),accounting_checks=sum(core.CHECKS.values())),ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        target=OUT/'人工False.json'
        if not target.exists():core.save(target,dict(passed=False,error_type=type(exc).__name__,error=str(exc),engine_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),checks=dict(CHECKS),accounting_checks=dict(core.CHECKS),market_reads=0,NPZ_reads=0,financial_replay=0))
        raise
