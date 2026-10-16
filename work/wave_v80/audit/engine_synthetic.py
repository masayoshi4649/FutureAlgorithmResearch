"""遅延注文を人工経路で追い、実装と独立期待値を照合する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
sys.dont_write_bytecode=True
os.environ['NUMBA_CACHE_DIR']=str(HERE/'numba_cache')
spec=importlib.util.spec_from_file_location('wave80_engine_audit',WORK/'engine.py')
engine=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=engine
spec.loader.exec_module(engine)


def arguments(times, bids, asks=None, directions=None, **options) -> list:
    """機能: 人工時計と気配からエンジン入力を作る。

    引数: times/bids/asks/directions(list|None)、options(dict)。返り値: 引数列(list)。
    入口信号自体の妥当性ではなく、その後の注文状態遷移を分離検査する。
    """
    times=np.asarray(times,dtype=float);bids=np.asarray(bids,dtype=float)
    asks=bids+1. if asks is None else np.asarray(asks,dtype=float)
    grid=np.unique(times)
    mapped=np.searchsorted(grid,times,side='right')-1
    states=np.zeros(len(grid),dtype=np.int8)
    states[0]=1
    if directions is not None:
        states=np.asarray(directions,dtype=np.int8)
        assert len(states)==len(grid)
    quality=np.ones(len(times),dtype=np.bool_)
    reset=np.zeros(len(times),dtype=np.bool_)
    source=np.searchsorted(times,grid,side='left')-1
    refs=np.full(len(grid),100.)
    keys=dict(tick=1.,start=0.,limit=5000.,quantity=10,value=1000.,fee_unit=41.8,
        latency=5.,entry_mode=0,target_ticks=2.,stop_ticks=2.,hold_seconds=60.,trail_mode=0,cooldown=30.,repair_mode=0)
    keys.update(options)
    return [times,bids,asks,quality,reset,mapped,grid,states,source.copy(),source.copy(),refs,refs+1.,
        *[keys[k] for k in ('tick','start','limit','quantity','value','fee_unit','latency','entry_mode',
                           'target_ticks','stop_ticks','hold_seconds','trail_mode','cooldown','repair_mode')]]


def run(args: list) -> tuple:
    """機能: Python版の注文エンジンを人工入力で再生する。

    引数: args(list)。返り値: 注文・決済・時価・統計・イベント(tuple)。
    """
    return engine.simulate.py_func(*args)


def near(left, right, label: str) -> None:
    """機能: 価格と円額を厳しい数値許容差で比較する。

    引数: left/right(数値又は配列)、label(str)。返り値: なし(None)。
    """
    np.testing.assert_allclose(left,right,atol=1e-7,rtol=0,err_msg=label)


def same(left: tuple, right: tuple) -> None:
    """機能: 再生結果の全配列を完全照合する。

    引数: left/right(tuple)。返り値: なし(None)。
    """
    assert len(left)==len(right)
    for a,b in zip(left,right):
        np.testing.assert_array_equal(a,b)


def main() -> None:
    """機能: 遅延・指値・子注文・残玉・未来不変を人工経路で検査する。

    引数: なし。返り値: なし(None)。失敗した期待値も監査JSONへ残す。
    """
    results=[];prefix_count=0
    def check(name, action):
        """機能: 一つの独立期待値を実行し合否を保存する。

        引数: name(str)、action(callable)。返り値: なし(None)。
        """
        try:
            action();results.append(dict(検査=name,合格=True))
        except Exception as exc:
            results.append(dict(検査=name,合格=False,詳細=str(exc),型=type(exc).__name__))

    # ----------------------------------------
    # 成行の待機、鏡映、無効気配と返済遅れ。
    mainargs=arguments([60,64,65,66,70,71],[100,101,100,103,95,99])
    mainout=run(mainargs)
    def market5():
        """機能: 5秒待ちの新規と返済価格を検算する。

        引数: なし。返り値: なし(None)。
        """
        orders,trades,curve,stats,events=mainout
        assert orders.shape==(2,18) and trades.shape==(1,12)
        near(orders[:,[0,1,3,5,10,11,12]],[[2,0,1,101,60,65,65],[5,3,-1,99,66,71,71]],'5秒双方')
        near(trades[:,10],[-20836.],'遅延で利確判断後に赤字')
        near(curve[4],-60836.,'返済待ちの下落を残す')
        assert np.array_equal(stats[:3],[0,0,0])
    check('新規返済双方5秒と返済待ちの全損失',market5)
    def mirrored():
        """機能: 売買を鏡映した短期売買の損益対称性を検査する。

        引数: なし。返り値: なし(None)。
        """
        args=[a.copy() if isinstance(a,np.ndarray) else a for a in mainargs]
        args[1]=200-mainargs[2];args[2]=200-mainargs[1];args[7]*=-1
        out=run(args)
        near(out[1][:,10],mainout[1][:,10],'方向対称損益')
        near(out[2],mainout[2],'方向対称時価')
        near(out[0][:,3],-mainout[0][:,3],'方向対称注文')
    check('ロングとショートの鏡映対称',mirrored)
    def zero_same_clock():
        """機能: 0秒でも同時計の後行でしか約定しないことを検査する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,60,60,60],[100,100,103,102],latency=0.))
        near(out[0][:,[0,1,5]],[[1,0,101],[3,2,102]],'0秒次原本行')
        near(out[1][:,10],[9164.],'0秒料金')
    check('0秒遅延でも判断行約定なしと同時計順序',zero_same_clock)
    def one_second():
        """機能: 1秒の到達直前を使わないことを検査する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,60.9,61,62,62.9,63],[100,110,100,103,110,102],latency=1.))
        near(out[0][:,[0,1,5]],[[2,0,101],[5,3,102]],'1秒到達')
    check('1秒未満の良い気配を先取りしない',one_second)
    def invalid_fill():
        """機能: 無効気配の到達行で約定せず次の有効行を使う。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,66],[100,np.nan,102]))
        assert out[0].shape[0]==1 and out[0][0,0]==2
        near(out[0][0,5],103.,'無効気配飛ばし')
        assert out[3][0]==1 and out[3][2]==0
        near(out[2][-1],-10836.,'未返済玉時価')
    check('無効気配・未返済残玉・両道料金を時価へ含む',invalid_fill)
    def pending_exit():
        """機能: 返済未到達の終端で残玉と返済待ちを残す。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,66,70],[100,100,103,90]))
        assert out[0].shape[0]==1 and len(out[1])==0
        assert out[3][0]==1 and out[3][2]==1
        near(out[2][-1],-110836.,'終端返済待ち時価')
    check('返済待ちの終端を決済済み扱いにしない',pending_exit)

    # ----------------------------------------
    # 上限価格IOC近似と待機指値の約定・取消境界。
    def capped_reject():
        """機能: 到達時の価格上限超過が未約定になることを確認する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,66],[100,102,99],entry_mode=1))
        assert len(out[0])==0 and out[3][6]==1
        assert 21 in out[4][:,2]
        near(out[2],0.,'不成立なら料金なし')
    check('価格上限超過のIOC近似は追跡して後で約定しない',capped_reject)
    def capped_boundary():
        """機能: 指定した不利1呼値までを許す到達上限を確認する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65],[100,101],entry_mode=1))
        near(out[0][:,5],[102.],'価格上限等値')
    check('価格上限等値の到達だけを許す',capped_boundary)
    def passive_touch():
        """機能: touchだけで指値約定せず1呼値通過でのみ約定する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,66],[100,99,98],entry_mode=2))
        near(out[0][:,[0,5]],[[2,100.]],'通過後指値価格')
        near(out[2][-1],-20836.,'自己側指値の約定直後逆選択')
    check('待機指値はtouch不可・通過後も指値価格仮定',passive_touch)
    def cancel_pending_fill():
        """機能: 取消判断後到達前は指値が存続して約定する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,80,84],[100,100,100,98],entry_mode=2))
        near(out[0][:,[0,5]],[[3,100.]],'取消待ち約定')
        assert 22 in out[4][:,2] and 23 not in out[4][:,2]
    check('取消待ち5秒以内は指値約定リスクが残る',cancel_pending_fill)
    def cancel_exact():
        """機能: 取消到達同時計では取消を優先する固定規則を確認する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,80,85],[100,100,100,98],entry_mode=2))
        assert len(out[0])==0 and out[3][6]==1 and 23 in out[4][:,2]
    check('取消到達の同時計は取消優先',cancel_exact)
    def cancel_gap():
        """機能: TTLを無観測でも時刻通りに発火させた独立期待値を検査する。

        引数: なし。返り値: なし(None)。観測駆動方式ならこの期待値との差を明示する。
        """
        out=run(arguments([60,65,90],[100,100,98],entry_mode=2))
        assert len(out[0])==0, '80秒取消判断・85秒取消到達より後の90秒で指値が約定した'
    check('指値TTLは無観測時間をまたいでも予定時刻に取消',cancel_gap)

    # ----------------------------------------
    # 実約定後だけの保険、トレール、場内返済と容量保護。
    def parent_before_child():
        """機能: 約定前の極値を返済トレールへ流用しないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,62,65,66,67],[100,120,100,101,101],trail_mode=1))
        assert len(out[0])==1 and out[3][2]==0
        assert 24 not in out[4][:,2]
    check('親約定前の高値はトレールへ引き継がない',parent_before_child)
    def trailing():
        """機能: 順行後トレール発動にも返済遅延を適用する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,66,67,72],[100,100,104,103,101],trail_mode=1))
        near(out[0][:,[0,1,5,6]],[[1,0,101,10],[4,3,101,5]],'追跡返済にも遅延')
        near(out[1][:,10],[-836.],'小幅保護の料金後赤字')
    check('追跡返済も5秒後の気配で約定',trailing)
    def cutoff():
        """機能: 予定撤収を判断してから返済待ちを維持する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,139,140,145],[100]*5,limit=200.,hold_seconds=500.))
        near(out[0][:,[0,1,6,10,11]],[[1,0,10,60,65],[4,2,4,140,145]],'予定撤収')
    check('場内撤収にも判断と5秒後約定を分離',cutoff)
    def deadline_gap():
        """機能: 観測がなくても保有期限で返済送信し最初の到達後気配を使う。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,135],[100,100,99]))
        near(out[0][:,[0,1,6,10,11,12]],[[1,0,10,60,65,65],[2,1,3,125,130,135]],'保有期限と観測gap')
        near(out[1][:,10],[-20836.],'gap返済価格')
    check('無観測中の保有期限は次観測からさらに5秒待たない',deadline_gap)
    def opposite_exit():
        """機能: 反対信号の改修も到達前に返済しないことを確認する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65,66,70,71],[100,100,100,97,99],directions=[1,0,-1,0,0],repair_mode=2))
        near(out[0][:,[0,1,6,10,11]],[[1,0,10,60,65],[4,2,6,66,71]],'反対信号返済')
        near(out[2][3],-40836.,'反対判断後の待機損失')
    check('反対信号返済にも5秒待ち',opposite_exit)
    def do_not_chase():
        """機能: 改修1が判断時点の価格だけで入口を拒否する。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,65],[102,100],repair_mode=1))
        assert len(out[0])==0 and len(out[4])==0
        accepted=run(arguments([60,65],[101,100],repair_mode=1))
        assert len(accepted[0])==1
    check('追いかけ拒否は判断時だけで1呼値等値を許す',do_not_chase)
    def consecutive_pause():
        """機能: 2連敗が確定する前に休止せず確定後120秒だけ止める。

        引数: なし。返り値: なし(None)。
        """
        times=np.arange(60.,209.);bids=np.full(len(times),100.)
        bids[times>=66]=98.;bids[times>=82]=96.
        out=run(arguments(times,bids,directions=np.ones(len(times)),repair_mode=3,cooldown=5.))
        events=out[4];decisions=events[events[:,2]==20,3]
        near(decisions,[60.,76.,207.],'休止明け判断')
        pauses=events[events[:,2]==30]
        near(pauses[:,[3,6]],[[87.,207.]],'確定連敗から120秒')
        assert len(out[1])==2 and np.all(out[1][:,10]<0)
    check('2連敗の確定後120秒休止',consecutive_pause)
    def prefill_limit():
        """機能: 新規未到達の終端に待機状態を残す。

        引数: なし。返り値: なし(None)。
        """
        out=run(arguments([60,64],[100,100]))
        assert len(out[0])==0 and out[3][1]==1 and out[3][0]==0
        near(out[2],0.,'新規未約定は料金なし')
    check('未到達新規は未約定として記録',prefill_limit)
    def capacity_guard():
        """機能: 同時計の過剰回数は範囲外書込みより前に明示停止する。

        引数: なし。返り値: なし(None)。
        """
        n=1500;times=np.full(n,60.);bid=np.tile([100.,100.,98.],500)
        try:
            run(arguments(times,bid,directions=[1],latency=0.,cooldown=0.,stop_ticks=1.))
        except AssertionError:
            return
        raise AssertionError('想定以上の注文回数を容量ガードが拒否しなかった')
    check('同時計過剰売買は配列破壊前に拒否',capacity_guard)

    def timer_prefix():
        """機能: 最後既知行を参照するタイマー記録も論理時刻で未来と分離する。

        引数: なし。返り値: なし(None)。
        """
        for entrymode in [0,2]:
            args=arguments([60,65,79,80,84,85,124,125,129,130,135],
                [100]*11,entry_mode=entrymode)
            full=run(args)
            for cut in range(1,len(args[0])):
                sliced=[v[:cut] if i<=5 else v for i,v in enumerate(args)]
                part=run(sliced)
                events=full[4][(full[4][:,0]<cut)&(full[4][:,3]<=args[0][cut-1])]
                np.testing.assert_array_equal(part[4],events)
                np.testing.assert_array_equal(part[0],full[0][full[0][:,0]<cut])
                np.testing.assert_array_equal(part[2],full[2][:cut])
    check('タイマーイベントを原本行だけで過去に見せない',timer_prefix)

    # ----------------------------------------
    # 途中切断と未来変異。未約定待ち・建玉保有中も過去の注文と時価は不変。
    for entrymode in range(3):
        for latency in [0.,1.,5.]:
            times=np.arange(60.,110.)
            bids=np.repeat([100.,98.,105.,102.,96.,99.,103.,102.,100.,99.],5)
            args=arguments(times,bids,latency=latency,entry_mode=entrymode,trail_mode=1)
            full=run(args)
            for cut in [1,4,6,10,20,35,49]:
                prefix_count+=1
                def prefix_action(args=args,full=full,cut=cut):
                    """機能: 一地点より後を切断・改変しても過去記録が変わらないことを検査する。

                    引数: args(list)、full(tuple)、cut(int)。返り値: なし(None)。
                    """
                    sliced=[v[:cut] if i<=5 else v for i,v in enumerate(args)]
                    partial=run(sliced)
                    np.testing.assert_array_equal(partial[0],full[0][full[0][:,0]<cut])
                    np.testing.assert_array_equal(partial[1],full[1][full[1][:,2]<cut])
                    np.testing.assert_array_equal(partial[2],full[2][:cut])
                    np.testing.assert_array_equal(partial[4],full[4][full[4][:,0]<cut])
                    mutated=[v.copy() if isinstance(v,np.ndarray) else v for v in args]
                    mutated[1][cut:]+=500.;mutated[2][cut:]+=500.;mutated[7][cut:]*=-1
                    changed=run(mutated)
                    np.testing.assert_array_equal(changed[0][changed[0][:,0]<cut],partial[0])
                    np.testing.assert_array_equal(changed[1][changed[1][:,2]<cut],partial[1])
                    np.testing.assert_array_equal(changed[2][:cut],partial[2])
                    np.testing.assert_array_equal(changed[4][changed[4][:,0]<cut],partial[4])
                check(f'未来不変_方式{entrymode}_遅延{latency:g}_切断{cut}',prefix_action)
    check('Numba版とPython版の全配列一致',lambda:same(engine.simulate(*mainargs),mainout))
    result=dict(合格=all(r['合格'] for r in results),エンジンSHA256=hashlib.sha256((WORK/'engine.py').read_bytes()).hexdigest(),
        検査数=len(results),未来切断地点数=prefix_count,失敗=[r for r in results if not r['合格']],全検査=results)
    path=HERE/'遅延エンジンの人工境界と未来監査.json'
    path.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='全検査'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
