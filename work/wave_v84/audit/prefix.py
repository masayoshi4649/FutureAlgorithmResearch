"""即ドテン・反転確認待ちを含む既知部分の因果不変を検証する。"""
from context import *


def compare_prefix(full: tuple, prefix: tuple, cut: int, stamp: float) -> int:
    """機能: 実発生時刻までの約定・決済・時価・予約を照合する。

    引数: full/prefix(tuple)、cut(int)、stamp(float)。返り値: 比較配列数(int)。
    """
    np.testing.assert_array_equal(prefix[0],full[0][full[0][:,0]<cut])
    np.testing.assert_array_equal(prefix[1],full[1][full[1][:,2]<cut])
    np.testing.assert_array_equal(prefix[2],full[2][:cut])
    prior=full[4][(full[4][:,0]<cut)&(full[4][:,6]<=stamp)]
    np.testing.assert_array_equal(prefix[4],prior)
    return 4


def main() -> None:
    """機能: 全家族で未来の完全切断と値の改変が過去を変えないか確認する。

    引数: なし。返り値: なし(None)。
    """
    engine=load_engine()
    times=np.repeat(np.arange(151,dtype=float)*2.,2)
    prices=500+90*np.sin(np.arange(len(times))/7.)
    prices[70:73]-=80;prices[180:183]+=80
    regular=record(times,prices)
    missing=record([0,1,2,3,4,5,6,179,181,260,300],[100,102,106,104,np.nan,100,98,98,98,98,98],
        [99.5,101.5,105.5,np.nan,np.nan,99.5,97.5,97.5,97.5,97.5,97.5],
        [100.5,102.5,106.5,np.nan,np.nan,100.5,98.5,98.5,98.5,98.5,98.5])
    counts=dict(人工経路数=0,切断地点数=0,比較配列数=0,保有中切断=0,予約中切断=0)
    for r in [regular,missing]:
        for family in range(6):
            for width in ([2,8,64] if r is regular else [2]):
                for variant in ([0,1,2] if r is regular else [1]):
                    full=engine.run(*arguments(r,family,width,variant))
                    locations={1,2,3,len(r[0])//3,len(r[0])*2//3,len(r[0])-1}
                    if r is missing:locations.update(range(1,len(r[0])))
                    for o in np.r_[full[0][:5],full[0][-2:]]:locations.update([int(o[0]),int(o[0])+1])
                    for cut in sorted(i for i in locations if 0<i<len(r[0])):
                        shortened=tuple(v[:cut] if i<8 else v for i,v in enumerate(r))
                        before=engine.run(*arguments(shortened,family,width,variant))
                        counts['比較配列数']+=compare_prefix(full,before,cut,r[0][cut-1])
                        future=list(r)
                        for column in [1,2,3]:
                            future[column]=r[column].copy();future[column][cut:]+=300.
                        changed=engine.run(*arguments(tuple(future),family,width,variant))
                        counts['比較配列数']+=compare_prefix(changed,before,cut,r[0][cut-1])
                        counts['切断地点数']+=1
                        counts['保有中切断']+=int(before[3][4]+before[3][5]>0)
                        counts['予約中切断']+=int(before[3][6]+before[3][7]>0)
                    counts['人工経路数']+=1
    result=dict(合格=True,**counts,エンジンSHA256=digest(WORK/'engine.py'),
        制約='保存順と現在値時計に対する因果性。実際の受信時計や取引所処理は証明しない。')
    save('全家族人工未来切断監査.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
