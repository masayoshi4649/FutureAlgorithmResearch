"""方向別の最初の候補価格を保持する入口の状態管理を独立人工で検査する。"""

from copy import deepcopy
import json
from pathlib import Path
import time
import numpy as np

from check_exit130 import account, load
from audit_saved_round1_130 import read, reference, sha
from budget_connection130 import connection

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def fixture(prices=None, reflected=False, quantity=5, retest=0):
    """
    機能: 境界100・幅4・60秒刻みの架空入口と活動資料を作る。
    引数: prices(list又はNone)、reflected(bool)、quantity/retest(int)は人工条件。
    返り値: tuple[list,ndarray]は16引数と活動。実市場資料は含まない。
    """
    values = np.array(prices or [100.5,101.5,102.,102.5,101.25,101.5,101.5,101.5,101.5,101.5],float)
    n = len(values)
    times = np.arange(n,dtype=float)*60.
    h = np.zeros((n,15))
    h[:,[0,1,2,3,4,8]] = [95.,95.,4.,100.,90.,95.]
    h[:,5] = .5
    h[:,[6,7,10,11,13]] = 1.
    market = np.ones((n,12))
    market[:,0] = values
    market[:,1] = 200.
    market[:,2:4] = 4.
    market[:,4:8] = .2
    market[:,8:11] = times[:,None]-1.
    activity = np.tile([1.,10.,-5.,1.],(n,1))
    bid,ask = values-.25,values+.25
    if reflected:
        values = 200.-values
        bid,ask = 200.-ask,200.-bid
        high = h[:,3].copy()
        h[:,3],h[:,4] = 200.-h[:,4],200.-high
        h[:,[0,1,8]] = 200.-h[:,[0,1,8]]
        h[:,[6,7,10,11,13]] *= -1.
        market[:,0] = values
        market[:,4:8] *= -1.
        activity[:,[0,2]] *= -1.
    params = np.array([2.,1.,1.,.75,0.,0.,.25,900.,.35,.25,6. if retest else 3.,2.,0.,1e9])
    args = [times,values,bid,ask,np.ones(n,bool),np.full(n,4.),h,market,0.,times[-2],1e9,.5,
            quantity,1000. if quantity == 5 else 10.,418 if quantity == 5 else 110,params]
    return args,activity


def main():
    """
    機能: 旧互換・価格基準の固定と解除・方向対称・未来不使用・実runner接続を確認する。
    引数: なし。
    返り値: None。指紋付き人工証拠を保存し、金融再生は行わない。
    """
    core = load(WORK/"night_budget130.py","予算核130独立")
    old = load(WORK/"night_activity130.py","予算旧核130独立")
    runner = load(WORK/"run_budget130.py","予算接続130独立")
    configs = read(WORK/"第四巡条件.json")
    reason_path = WORK/"第四巡の変更根拠_確定.json"
    reason = read(reason_path)
    paths = [ROOT/path for path in runner.sources()]
    paths += [Path(__file__),HERE/"budget_connection130.py",HERE/"check_activity_entry130.py",
              HERE/"check_exit130.py",WORK/"night_activity130.py",WORK/"第四巡条件.json",reason_path,
              ROOT/reason["diagnosis"]["path"]]
    before = {str(p.relative_to(ROOT)):sha(p) for p in paths}
    tests=[]

    def check(label,action):
        """
        機能: 一項目の成功又は失敗を記録する。
        引数: label(str)、action(callable)は検査名と処理。
        返り値: None。
        """
        try:
            action()
            tests.append(dict(確認=label,合格=True))
        except Exception as exc:
            tests.append(dict(確認=label,合格=False,詳細=f"{type(exc).__name__}: {exc}"))

    def simulate(args,data,budget=1,activity=1,retest=0,style=0,compiled=False):
        """
        機能: 人工資料を対象核に渡し、会計も独立照合する。
        引数: args(list)、data(ndarray又はNone)、budget/activity/retest/style(int)、compiled(bool)。
        返り値: tupleは注文・取引・全行時価。
        """
        fn=core.simulate if compiled else core.simulate.py_func
        result=fn(*args,retest,style,data,activity,budget)
        account(args,result)
        return result

    def same(left,right):
        """
        機能: 出力三配列の厳密同値を確認する。
        引数: left/right(tuple[ndarray,...])は比較対象。
        返り値: None。
        """
        for a,b in zip(left,right):
            np.testing.assert_array_equal(a,b)

    for reflected in (False,True):
        for quantity in (5,10):
            for retest in (0,1):
                for style in range(4):
                    def compatible(reflected=reflected,quantity=quantity,retest=retest,style=style):
                        """
                        機能: budget0で活動入口の全出力が旧核と一致するか調べる。
                        引数: reflected(bool)、quantity/retest/style(int)は検査条件。
                        返り値: None。
                        """
                        prices=[101.,104.,100.8,102.,102.,106.,103.,99.,99.,99.] if retest else None
                        args,data=fixture(prices,reflected,quantity,retest)
                        data[1,3]=0.
                        for mode in (0,1):
                            item=data if mode else None
                            previous=old.simulate.py_func(*args,retest,style,item,mode)
                            same(previous,simulate(args,item,0,mode,retest,style))
                    check(f"旧全互換 反転{reflected} 枚数{quantity} 再試験{retest} 出口{style}",compatible)

        def reject_worse(reflected=reflected):
            """
            機能: 初回見送り後の不利候補を捨て、同値へ戻った候補だけ許す。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args,data=fixture(reflected=reflected)
            data[1,3]=0.
            prior=simulate(args,data,0)
            current=simulate(args,data)
            assert tuple(prior[0][0,:2])==(4,3)
            assert tuple(current[0][0,:2])==(6,5)
        check(f"不利を拒否し等値を許可 反転{reflected}",reject_worse)

        def retest_reset(reflected=reflected):
            """
            機能: 再試験入口でも不利候補を破棄し、進行・戻り・再進行を最初から行う。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args,data=fixture([101.,104.,100.8,102.,102.,104.,100.8,102.5,
                               102.,104.,100.8,102.,102.,102.,102.,102.],reflected,retest=1)
            data[3,3]=0.
            result=simulate(args,data,retest=1)
            assert tuple(result[0][0,:2])==(12,11)
        check(f"再試験入口も不利破棄後全段階からやり直す 反転{reflected}",retest_reset)

        def never_update(reflected=reflected):
            """
            機能: 後続の不利候補又は有利だが不適格な候補で基準価格を更新しない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args,data=fixture([100.5,101.5,102.,102.5,101.75,102.,101.25,101.5,101.5,101.5,101.5,101.5],
                              reflected)
            data[1,3]=data[3,3]=0.
            result=simulate(args,data)
            assert tuple(result[0][0,:2])==(8,7)
            args,data=fixture([100.5,101.5,100.5,101.,101.25,101.5,101.5,101.5,101.5,101.5],reflected)
            data[1,3]=data[3,3]=0.
            assert tuple(simulate(args,data)[0][0,:2])==(6,5)
        check(f"最初の価格を不利にも有利にも更新しない 反転{reflected}",never_update)

        for breach,expected in ((99.,True),(99.001,False),(np.nan,False)):
            def boundary(reflected=reflected,breach=breach,expected=expected):
                """
                機能: 初回の境界0.25R破綻は異常気配・相手欠測でも有限自己価格だけで解除する。
                引数: reflected/expected(bool)、breach(float)は検査条件。
                返り値: None。
                """
                args,data=fixture([100.5,101.5,102.,102.5,breach,102.,103.,103.,103.,103.,103.,103.],reflected)
                data[1,3]=0.
                args[4][4]=False
                args[7][4]=np.nan
                result=simulate(args,data)
                entries=result[0][result[0][:,7]==1]
                assert bool(len(entries))==expected
                if expected:
                    assert tuple(entries[0,:2])==(7,6)
            check(f"境界解除 等号含む値{breach} 反転{reflected}",boundary)

        def fixed_width(reflected=reflected):
            """
            機能: 後のATR拡大で初回の解除境界を拡大しない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args,data=fixture([100.5,101.5,102.,102.5,98.5,102.,103.,103.,103.,103.,103.,103.],reflected)
            data[1,3]=0.
            args[5][2:]=8.
            args[4][4]=False
            result=simulate(args,data)
            assert tuple(result[0][0,:2])==(7,6)
        check(f"解除は最初の固定R 反転{reflected}",fixed_width)

        def accepted_keeps_budget(reflected=reflected):
            """
            機能: 許可した新規とその返済でも、価格予算を消さず後続の追いを防ぐ。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args,data=fixture([100.5,101.5,101.5,101.5,101.5,107.,104.,104.,104.,104.,104.,104.,104.,104.],
                              reflected)
            data[1,3]=0.
            result=simulate(args,data)
            assert len(result[0][result[0][:,7]==1])==1
            previous=simulate(args,data,0)
            assert len(previous[0][previous[0][:,7]==1])>1
        check(f"新規成立・返済で基準を解除しない 反転{reflected}",accepted_keeps_budget)

        def pending(reflected=reflected):
            """
            機能: 判定後の不利約定や境界破綻を見て、新規予約を取り消さない。
            引数: reflected(bool)は方向。
            返り値: None。
            """
            args,data=fixture([100.5,101.5,101.5,101.5,99.,105.,105.,105.,105.,105.],reflected)
            data[1,3]=0.
            args[4][4]=False
            data[4:]=np.nan
            result=simulate(args,data)
            assert tuple(result[0][0,:2])==(5,3)
            assert result[0][0,5]==(args[2] if reflected else args[3])[5]
        check(f"境界解除後も既発注は次正常不利気配で実行 反転{reflected}",pending)

    def independent_sides():
        """
        機能: 買い予算と売り予算を混ぜず別々に保持する。
        引数: なし。
        返り値: None。
        """
        args,data=fixture([100.5,101.5,104.,103.,102.,102.,101.25,101.5,101.5,101.5,101.5,101.5])
        data[1,3]=data[3,3]=0.
        args[6][2:4,3]=110.
        args[6][2:4,4]=105.
        for column in (6,7,10,11,13):
            args[6][2:4,column]=-1.
        args[7][2:4,4:8]=-.2
        data[2:4,0]*=-1.
        data[2:4,2]*=-1.
        result=simulate(args,data)
        assert tuple(result[0][0,:2])==(8,7) and result[0][0,3]==1.
    check("買いと売りの予算を独立保存",independent_sides)

    def unqualified_does_not_record():
        """
        機能: 旧発注資格のない原行を初回見送り価格として採用しない。
        引数: なし。
        返り値: None。
        """
        args,data=fixture([100.5,101.5,102.,102.,102.,102.,102.,102.,102.,102.])
        args[7][1,4]=0.
        data[1,3]=0.
        result=simulate(args,data)
        assert tuple(result[0][0,:2])==(3,2)
    check("旧資格のない活動不適格は予算を作らない",unqualified_does_not_record)

    def quiet_resets():
        """
        機能: 自己価格が未知でも禁止時間は保存予算を解除する。
        引数: なし。
        返り値: None。
        """
        args,data=fixture([100.5,101.5,102.,102.5,np.nan,102.,103.,103.,103.,103.,103.,103.])
        data[1,3]=0.
        args[10]=args[0][4]
        args[15][7]=30.
        args[0][5:]=1640.+np.arange(len(args[0])-5)*60.
        args[9]=args[0][-2]
        result=simulate(args,data)
        assert tuple(result[0][0,:2])==(7,6)
    check("禁止時間で自己価格未知でも予算解除",quiet_resets)

    for boundary_kind in ("禁止時間","場末"):
        def pending_exception(boundary_kind=boundary_kind):
            """
            機能: 禁止時間又は場末の未約定新規取消という旧例外を保つ。
            引数: boundary_kind(str)は確認する旧例外。
            返り値: None。
            """
            args,data=fixture([100.5,101.5,101.5,101.5,101.5,101.5,101.5,101.5,101.5,101.5])
            data[1,3]=0.
            if boundary_kind=="禁止時間":
                args[10]=args[0][4]
                args[15][7]=30.
            else:
                args[9]=args[0][4]
            result=simulate(args,data)
            assert len(result[0])==0
            same(result,simulate(args,data,0))
        check(boundary_kind+"の未約定新規取消は旧仕様互換",pending_exception)

    def future_and_jit():
        """
        機能: 将来毒化の過去不変と、新旧モードのJIT一致を確認する。
        引数: なし。
        返り値: None。
        """
        args,data=fixture()
        data[1,3]=0.
        result=simulate(args,data)
        changed,poison=deepcopy(args),data.copy()
        cut=5
        for column in (1,2,3):
            changed[column][cut:]+=50.
        poison[cut:]=np.nan
        modified=simulate(changed,poison)
        np.testing.assert_array_equal(result[2][:cut],modified[2][:cut])
        np.testing.assert_array_equal(result[0][result[0][:,0]<cut],modified[0][modified[0][:,0]<cut])
        same(result,simulate(args,data,compiled=True))
        same(simulate(args,None,0,0),simulate(args,None,0,0,compiled=True))
        mirror,mirror_activity=fixture(reflected=True)
        mirror_activity[1,3]=0.
        reflected=simulate(mirror,mirror_activity)
        np.testing.assert_array_equal(result[0][:,3],-reflected[0][:,3])
        np.testing.assert_array_equal(result[2][:,[0,2,3]],reflected[2][:,[0,2,3]])
    check("未来毒・JIT・上下対称",future_and_jit)

    def fixed_configs():
        """
        機能: 第四巡が第二巡に予算だけを追加し、凍結根拠を参照するか確認する。
        引数: なし。
        返り値: None。
        """
        originals=read(WORK/"第二巡条件.json")
        for original,current in zip(originals,configs):
            for key in (*runner.PARAMETERS,"retest_mode","exit_style","activity_mode","price_source","peer_delay"):
                assert original[key]==current[key]
            assert current["budget_mode"]==1
        assert [c["id"] for c in configs]==["W11","W12"]
        assert sha(ROOT/reason["diagnosis"]["path"])==reason["diagnosis"]["sha256"]
        assert "execution_clarification" in reason
    check("固定条件と旧禁止時間例外の明示",fixed_configs)
    check("実runner四商品条件を21引数・原行・活動付きで接続",lambda:connection(runner,configs))
    after={str(p.relative_to(ROOT)):sha(p) for p in paths}
    assert before==after
    passed=all(t["合格"] for t in tests)
    target=HERE/f"候補価格予算の独立人工と接続_{time.time_ns()}.json"
    target.write_text(json.dumps(dict(passed=passed,checks=len(tests),tests=tests,sources=after,
        financial_replays=0,real_market_data_reads=0,API=0),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(passed=passed,path=str(target),checks=len(tests),
                         failures=[t for t in tests if not t["合格"]]),ensure_ascii=False),flush=True)
    if not passed:
        raise SystemExit(1)


if __name__=="__main__":
    main()
