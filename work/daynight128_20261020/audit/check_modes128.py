"""追加した日中出口と夜間全状態遷移を純人工で検査する。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from check_engines128 import WORK, ROOT, day_fixture, night_fixture, check_night_account, load

HERE = Path(__file__).resolve().parent


def run():
    """
    機能: 状態分岐を人工経路で発生させ期待する注文順を確認する。
    引数: なし。
    返り値: None。市場素材・保存金融成績は参照しない。
    """
    suffix = sys.argv[1] if len(sys.argv)>1 else "初回"
    sources = [WORK/"day_core128.py",WORK/"night128.py",WORK/"bbo_order_kernel126.py"]
    before = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    day=load(WORK/"day_core128.py","audit128_daymodes").simulate.py_func
    night=load(WORK/"night128.py","audit128_nightmodes").simulate.py_func
    checks=[]

    def check(name, action):
        """
        機能: 人工検査を実行し結果を記録する。
        引数: name(str)、action(callable)。
        返り値: None。
        """
        try:
            action()
            checks.append(dict(確認=name,合格=True))
        except Exception as exc:
            checks.append(dict(確認=name,合格=False,内容=f"{type(exc).__name__}: {exc}"))

    def contraction():
        """
        機能: ATR収縮後の回復でも損失幅を広げないことを確認する。
        引数: なし。
        返り値: None。
        """
        args,extra=day_fixture([100,100,100,99.5,98.5,98,100,101,102])
        atr,hist,_=extra
        atr[3]=2.
        original=day(*args,atr,hist,0)
        actual=day(*args,atr,hist,1)
        assert original[0][-1,0]==8.
        assert actual[0][-1,0]==5. and actual[0][-1,1]==4. and actual[0][-1,6]==32.
    check("日中ATR収縮は回復後も緩めない",contraction)

    def floor():
        """
        機能: 0.5R順行後の中期失敗時だけ利益保護を上げることを確認する。
        引数: なし。
        返り値: None。
        """
        args,extra=day_fixture([100,100,100,104,103,102,103,104,105])
        atr,hist,_=extra
        hist[4:,1]=104.
        hist[4:,10]=-1.
        actual=day(*args,atr,hist,2)
        assert actual[0][-1,0]==6. and actual[0][-1,1]==5. and actual[0][-1,6]==70.
        hist[4:,10]=1.
        control=day(*args,atr,hist,2)
        assert control[0][-1,0]==8.
    check("日中中期失敗時のみ小利益床",floor)

    paths={
        1:[98,100,100.5,103.5,106.5,104.5,104.5,104.5,104.5],
        2:[110.5,112,112.5,117.5,114.5,113.5,113.5,113.5,113.5],
        3:[108,110,107,108,108.5,114.5,111.5,110.5,110.5,110.5],
    }
    for mode,selected,us_open,efficiency in (
        (1,1,1.e9,.2),(2,2,1.e9,.5),(3,3,1.e9,.5),
        (4,1,1.e9,.2),(4,2,-5000.,.5),
        (5,1,1.e9,.2),(5,3,-5000.,.5),
        (6,1,1.e9,.2),(6,2,1.e9,.5),
    ):
        for reflected in (False,True):
            def active(mode=mode,selected=selected,us_open=us_open,efficiency=efficiency,reflected=reflected):
                """
                機能: 各モードの入口と出口を買売対称の経路で確認する。
                引数: mode/selected(int)、us_open/efficiency(float)、reflected(bool)。
                返り値: None。
                """
                args=list(night_fixture(paths[selected],reflected=reflected,us_open=us_open))
                args[6][:,5]=efficiency
                args[-1][0]=mode
                actual=night(*args)
                check_night_account(args,actual)
                assert len(actual[1])==1
                assert actual[1][0,13]==selected
                expected={1:([2.,5.],71.),2:([2.,5.],70.),3:([4.,7.],70.)}
                fills,reason=expected[selected]
                assert actual[0][:,0].tolist()==fills,actual[0]
                assert actual[1][0,12]==reason,actual[1]
            check(f"夜mode{mode}実状態{selected}_米開始{us_open}_反射{reflected}",active)

    def neutral():
        """
        機能: 効率が中間帯のとき回帰も追従も強制しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=list(night_fixture(paths[2]))
        args[6][:,5]=.4
        args[-1][0]=6.
        assert len(night(*args)[0])==0
    check("夜効率中間帯は未知選択",neutral)

    def quiet_pending():
        """
        機能: 既知の米国静観開始で未約定新規を取り消すことを確認する。
        引数: なし。
        返り値: None。
        """
        args=night_fixture(paths[1],us_open=1020.)
        assert len(night(*args)[0])==0
    check("夜静観開始で待機新規取消",quiet_pending)

    def phase():
        """
        機能: 米開始後限定の設定が開始前に建てないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=list(night_fixture(paths[2]))
        args[6][:,5]=.5
        args[-1][0]=2.
        args[-1][4]=1.
        assert len(night(*args)[0])==0
    check("夜米開始後限定を入口前に適用",phase)

    def unknown():
        """
        機能: 入口の必須相手短期列が未知のとき約定しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=list(night_fixture(paths[1]))
        args[7][:,6]=np.nan
        assert len(night(*args)[0])==0
    check("夜current_knownだけで未知短期票を許可しない",unknown)

    def insufficient_room():
        """
        機能: 回帰余地が初期幅未満なら帯内に戻っても建てないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=night_fixture([98,102,102,102,102,102,102,102,102])
        assert len(night(*args)[0])==0
    check("夜回帰までの残余地が不足なら見送り",insufficient_room)

    def already_center():
        """
        機能: 中心到達後の回帰新規を発行しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=night_fixture([98,106,106,106,106,106,106,106,106])
        assert len(night(*args)[0])==0
    check("夜中心到達済み回帰を新規にしない",already_center)

    def no_retroactive():
        """
        機能: 次行の不利な気配を見て成立済み新規を遡及取消しないことを確認する。
        引数: なし。
        返り値: None。
        """
        args=list(night_fixture(paths[1]))
        args[3][2]=120.
        result=night(*args)
        assert result[0][0,0]==2. and result[0][0,5]==120.
        check_night_account(args,result)
    check("夜発注後の不利約定を削除しない",no_retroactive)

    def trailing_does_not_widen():
        """
        機能: 初期幅固定と高値からの追尾で利益を残すことを確認する。
        引数: なし。
        返り値: None。
        """
        args=list(night_fixture(paths[2]))
        args[6][:,5]=.5
        args[-1][0]=2.
        args[5][3:]=1000.
        result=night(*args)
        assert result[1][0,11]==4. and result[0][-1,0]==5.
    check("夜保有後ATR急増でも初期幅固定",trailing_does_not_widen)

    def future_invariant():
        """
        機能: 将来価格・気配・資料を変更しても過去注文が不変であることを確認する。
        引数: なし。
        返り値: None。
        """
        args=list(night_fixture(paths[3]))
        args[-1][0]=3.
        a=night(*args)
        for index in (1,2,3):
            args[index]=args[index].copy()
            args[index][6:]+=30.
        args[6]=args[6].copy()
        args[6][6:,:]=np.nan
        b=night(*args)
        np.testing.assert_array_equal(a[0][a[0][:,0]<6.],b[0][b[0][:,0]<6.])
        np.testing.assert_array_equal(a[2][:6],b[2][:6])
    check("夜未来改変で既知注文と時価不変",future_invariant)

    for p in sources:
        assert before[str(p.relative_to(ROOT))]==hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(全合格=all(v["合格"] for v in checks),確認数=len(checks),確認=checks,
                数値源SHA256=before,新金融=0,市場素材読取=0)
    path=HERE/f"昼新出口と夜全モードの人工監査_{suffix}.json"
    assert not path.exists()
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    run()
