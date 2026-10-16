"""持続指値への限定変更を人工原板で独立監査する。"""
import importlib.util
import sys
import numpy as np
from context import WORK, digest, save, record, arguments, cash_oracle, reservation_oracle, engine
from prefix import compare_prefix

spec=importlib.util.spec_from_file_location('orders83_audit_persistent',WORK/'persistent_engine.py')
persistent=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=persistent
spec.loader.exec_module(persistent)


def inspect(r: tuple, family: int, variant: int, width=1, symbol='TOPIX') -> tuple:
    """機能: 合成経路の全玉会計と予約を独立照合する。

    引数: r(tuple)、family/variant/width(int)、symbol(str)。返り値: 出力tuple。
    """
    args=arguments(r,family,width,variant,symbol)
    out=persistent.run(*args)
    cash_oracle(args,out,symbol);reservation_oracle(args,out)
    return out


def main() -> None:
    """機能: 指値保持の人工境界・全家族差分・未来切断を検査し証跡を保存する。

    引数: なし。返り値: なし(None)。
    """
    results={};cases=[]
    r=record([0,1,2,3,4,180,240,300],[100,98,98,98,104,104,104,104],
        [99.5,98,98,97,103.5,103.5,103.5,103.5],[100.5,98.5,98.5,97.5,104.5,104.5,104.5,104.5])
    out=inspect(r,6,2,2);cases.append((r,6,2,2))
    assert out[0][0,0]==3 and out[0][0,5]==98 and out[0][0,1]==1
    assert out[0][1,0]==4 and out[0][1,7]==2
    assert not np.any((out[4][:,3]==2)&(out[4][:,0]<3))
    results['同値待機後に気配のみ改善']={'新規判断行':1,'実約定行':3,'約定価格':98,'当該買気配':97.5,'子注文発動行':4}
    r=record([0,1,179,180,240,300],[100,98,98,98,98,98],
        [99.5,98,98,97,97,97],[100.5,98.5,98.5,97.5,97.5,97.5])
    out=inspect(r,6,3,2);cases.append((r,6,3,2))
    assert len(out[0])==0 and out[3][8]==1 and out[4][-1,3]==6 and out[4][-1,0]==3
    assert np.all(out[3][4:8]==0)
    results['新規期限と実行可能気配が同時']={'取消行':3,'注文数':0,'取消数':1}
    r=record([0,1,2,3,179,180,240,300],[100,96,78,96,96,96,96,96],
        [99.5,98,98,90,95.5,95.5,95.5,95.5],[100.5,98.5,98.5,90.5,96.5,96.5,96.5,96.5])
    out=inspect(r,7,3);cases.append((r,7,3,1))
    pending=out[4][(out[4][:,0]==1)&(out[4][:,3]==1),1].astype(int)
    cancelled=out[4][(out[4][:,0]==2)&(out[4][:,3]==6),1].astype(int)
    assert len(pending)==4 and len(cancelled)==3
    assert not np.isin(out[0][:,2],cancelled).any()
    assert (out[0][:,7]==5).any() and np.all(out[3][4:8]==0)
    results['全玉停止と待機取消']={'待機を含む新規予約':4,'停止時取消':3,'取消玉の後日約定':0}
    # ----------------------------------------
    times=np.r_[np.arange(170),180,240,300].astype(float)
    prices=np.r_[100+12*np.sin(np.arange(170)/4),100,100,100]
    r=record(times,prices)
    identical=0;checked=0
    for family in range(12):
        for variant in range(4):
            for symbol in ['TOPIX','NK225']:
                out=inspect(r,family,variant,2,symbol);checked+=1
                if family not in [6,7]:
                    old=engine.run(*arguments(r,family,2,variant,symbol))
                    for a,b in zip(out,old):np.testing.assert_array_equal(a,b)
                    identical+=1
    # ----------------------------------------
    comparisons=0;pending_cuts=0
    for r,f,v,w in cases:
        full=persistent.run(*arguments(r,f,w,v))
        for cut in range(1,len(r[0])):
            sliced=tuple(x[:cut].copy() if j<8 else x for j,x in enumerate(r))
            short=persistent.run(*arguments(sliced,f,w,v))
            compare_prefix(full,short,cut,r[0][cut-1]);comparisons+=1
            pending_cuts+=int(short[3][6]>0)
    result={'合格':True,'対象エンジンSHA256':digest(WORK/'persistent_engine.py'),
        '具体境界':results,'全家族商品変数ケース':checked,'指値以外の旧エンジン完全一致':identical,
        '人工未来切断':comparisons,'未約定予約を含む切断':pending_cuts,
        '解釈':'同一指値の保持と元指値約定の追加対照。取引所の待ち順位、部分約定、実受信時刻は証明しない。'}
    save('持続指値の人工境界監査.json',result);print(result)


if __name__=='__main__':main()
