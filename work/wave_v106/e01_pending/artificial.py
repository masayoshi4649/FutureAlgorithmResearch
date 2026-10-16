"""待機取消の同行順序・永久性・元E01/P1L8接続を純人工で確認する。"""

import ast

import numpy as np

import common
import engine
import order_kernel
import prices


daily=common.module('106既P1L8の不変UID会計',common.ROOT/'work/wave_v106/e01_daily/core.py')


def fixture() -> tuple:
    """
    機能: 待機指値・部分返済・不正気配・後続紙上親のある私有素材を作る。
    引数: なし。
    返り値: tupleは元engineと同じ13引数。実市場・将来利益を使わない。
    """
    n=12;times=np.arange(n,dtype=float);last=np.full(n,100.);bid=np.full(n,99.5);ask=np.full(n,100.)
    bid[3]=97.5;ask[3]=98.;bid[4]=101.5;ask[4]=102.;bid[9]=102.;ask[9]=102.5
    qok=np.ones(n,bool);qok[5]=False
    feed=np.array([[1,0,0,1,5,100.,1,1,0,10.], [4,3,0,-1,2,100.,2,0,0,10.],
        [6,5,0,-1,3,100.,2,0,0,10.], [8,7,1,-1,5,100.,1,1,0,10.],
        [10,9,1,1,5,100.,2,0,0,10.]],float)
    return times,last,bid,ask,qok,feed,np.zeros(n,bool),np.zeros(n,bool),20.,10,.5,.2,False


def original() -> object:
    """
    機能: 不変旧engineのsimulate本体だけをASTで接続する。
    引数: なし。
    返り値: objectはPython関数。旧moduleのimport/cache/mainは実行しない。
    """
    tree=ast.parse((common.REFERENCE/'engine.py').read_text(encoding='utf8'))
    fn=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='simulate')
    fn.decorator_list=[];namespace=dict(np=np,execute=order_kernel.execute.py_func)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(common.REFERENCE/'engine.py'),'exec'),namespace)
    return namespace['simulate']


def equal(a: tuple, b: tuple) -> None:
    """
    機能: 旧注文・玉・全行・親・UID・公開証跡を全列同値で確認する。
    引数: a/b(tuple)は同じ人工素材のengine出力。
    返り値: None。不一致は停止する。
    """
    assert len(a)==len(b)==9
    for x,y in zip(a,b):
        np.testing.assert_array_equal(x,y)


def run() -> None:
    """
    機能: 取消後復活なし、同行fill優先、unknown保留、元経済接続を人工検査する。
    引数: なし。
    返り値: None。全市場の金融を実行せず新人工証跡を保存する。
    """
    args=fixture();n=len(args[0]);unknown=np.full(n,3,np.int8);old=original()(*args);checks=[]
    base=engine.simulate.py_func(*args,unknown,unknown,0);equal(base,old)
    checks.append('追加取消を無効にすると元E01の9出力が完全一致')
    own=unknown.copy();peer=unknown.copy();own[2]=peer[2]=-1
    cancelled=engine.simulate.py_func(*args,own,peer,2)
    assert not np.any(cancelled[0][:,2]==0) and np.any(cancelled[0][:,2]==1)
    proof=cancelled[8];assert len(proof[(proof[:,1]==5)&(proof[:,2]==0)])==1
    assert cancelled[7][3,6]==1 and cancelled[7][3,7]==0
    checks.append('到達前pair逆行で永久取消、後で到達しても復活せず次紙上親は処理')
    own=unknown.copy();peer=unknown.copy();own[3]=peer[3]=-1
    same=engine.simulate.py_func(*args,own,peer,2);equal(same,old)
    checks.append('既有効指値の到達と逆行が同rowならfill優先、約定を遡及消去しない')
    own=unknown.copy();own[2]=-1
    equal(engine.simulate.py_func(*args,own,unknown,2),old)
    checks.append('自己一時逆行だけ、相手UNKNOWNは取消しない')
    peer=unknown.copy();peer[2]=-1
    alone=engine.simulate.py_func(*args,unknown,peer,1)
    assert not np.any(alone[0][:,2]==0)
    equal(engine.simulate.py_func(*args,unknown,peer,2),old)
    checks.append('相手のみ逆行条件と両市場逆行条件を区別')
    quiet_args=list(args);quiet_args[6]=quiet_args[6].copy();quiet_args[6][2]=True
    quiet=engine.simulate.py_func(*quiet_args,unknown,unknown,0);quiet_old=original()(*quiet_args)
    equal(quiet,quiet_old);assert np.any(quiet[8][:,1]==4)
    checks.append('元U休止・未約定永久取消・予約返済の数学が同値')
    q=dict(bid=args[2],ask=args[3],quote_valid=args[4],seq=np.arange(n,dtype=np.int64),time_s=args[0])
    one=daily.reconstruct(('人工','TOPIX'),base[0],base[5],q)
    before=daily.reconstruct(('人工','TOPIX'),old[0],old[5],q)
    stop=daily.apply_policy(one,q,dict(profit_ticks=1,loss_ticks=8))
    stop_old=daily.apply_policy(before,q,dict(profit_ticks=1,loss_ticks=8))
    np.testing.assert_array_equal(stop['orders'],stop_old['orders']);assert stop['control']==stop_old['control']
    checks.append('元E01同値接頭へP1L8を接続すると既P1L8注文と判断が一致')
    future=list(args);future[2]=future[2].copy();future[3]=future[3].copy()
    future[2][3:8]+=100.;future[3][3:8]+=100.
    own=unknown.copy();peer=unknown.copy();own[2]=peer[2]=-1
    later=engine.simulate.py_func(*future,own,peer,2)
    np.testing.assert_array_equal(later[8][(later[8][:,1]==5)&(later[8][:,2]==0)],
        cancelled[8][(cancelled[8][:,1]==5)&(cancelled[8][:,2]==0)])
    checks.append('取消後のfuture価格変化は当時取消判断へ影響しない')
    # ----------------------------------------
    times=np.array([0.,0.,0.,0.,20.,30.]);bid=np.array([100.,101.,102.,101.,103.,104.]);raw=dict(
        raw_seq=np.arange(6,dtype=np.int64),price_time_s=times,bid=bid,ask=bid+1.,bbo_valid=np.ones(6,bool),
        qualified=np.ones(6,bool),price_reset_reason=np.zeros(6,np.uint16))
    public=dict(rows=np.array([0,4,5],np.int64),raw_seq=np.array([0,4,5],np.int64),times=np.array([0.,20.,30.]))
    policy=dict(max_public_gap_seconds=15.,baseline_extra_age_seconds=15.,spread_max_ticks=2.,spread_increment_ticks=1.)
    corrected=prices.windows(raw,public,1.,policy);strict=prices.legacy.public_windows(raw,public,1.,policy)
    assert strict['windows']['30']['unknown_reason'][-1]==32
    assert corrected['windows']['30']['unknown_reason'][-1]==0
    assert corrected['windows']['30']['direction_t1'][-1]==1
    checks.append('全quote正常のpriceclock gapだけを欠測扱いから除く、基準とBBOは不変')
    bad={k:v.copy() for k,v in raw.items()};bad['price_reset_reason'][2]=8
    preserved=prices.windows(bad,public,1.,policy)
    assert preserved['windows']['30']['unknown_reason'][-1]&16
    checks.append('原clock reset・原seq/BBO不正はpricegap訂正後もUNKNOWN')
    both=prices.project(raw,corrected,np.array([30.]),None,10,True,np.array([True]))
    assert both['public_index'][0]==1 and both['age_seconds'][0]==10.
    checks.append('相手同時計を禁止、fresh<=15秒とfirst公表を保持')
    jit=engine.simulate(*args,own,peer,2);equal(jit,cancelled)
    checks.append('Python/JITの取消と全経済配列が同値、JITは所有域のみ')
    common.write(common.HERE/'待機指値取消と元注文接続の人工検査.json',dict(全合格=True,
        検査数=len(checks),検査=checks,実装SHA256=common.source_hashes(),正式金融=0,原板=0,API=0))
    print('待機取消の人工'+str(len(checks))+'項目合格。正式金融0',flush=True)


if __name__=='__main__':
    run()
