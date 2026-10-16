"""価格だけを読む注文手法の人工途中切断と未来改変を全家族で確認する。"""

from context import *


def known_events(events: np.ndarray, cut: int, stamp: float) -> np.ndarray:
    """機能: 実処理行と予定発火時計で、未発生イベントを除外する。

    引数: events(ndarray)、cut(int)、stamp(float)。返り値: 過去イベント(ndarray)。
    """
    return events[(events[:,0]<cut)&(events[:,6]<=stamp)]


def compare_prefix(full: tuple, prefix: tuple, cut: int, stamp: float) -> int:
    """機能: 約定・決済・全玉時価・予約を既知部分だけで照合する。

    引数: full/prefix(tuple)、cut(int)、stamp(float)。返り値: 比較配列数(int)。
    """
    np.testing.assert_array_equal(prefix[0],full[0][full[0][:,0]<cut])
    np.testing.assert_array_equal(prefix[1],full[1][full[1][:,2]<cut])
    np.testing.assert_array_equal(prefix[2],full[2][:cut])
    np.testing.assert_array_equal(prefix[4],known_events(full[4],cut,stamp))
    return 4


def main() -> None:
    """機能: 未来価格・気配の改変と完全切断で、過去注文を不変確認する。

    引数: なし。返り値: なし(None)。原本損益を調べる前の人工検査である。
    """
    times=np.repeat(np.arange(151,dtype=float)*2.,2)
    prices=500+8*np.sin(np.arange(len(times))/7.)
    prices[70:73]-=20;prices[180:183]+=20
    r=record(times,prices)
    counts=dict(人工経路数=0,切断地点数=0,比較配列数=0,保有中切断=0,両建て中切断=0,予約中切断=0)
    for family in range(12):
        for variant in [0,3]:
            args=arguments(r,family,variant=variant)
            full=engine.run.py_func(*args)
            locations={1,2,3,71,101,181,241,len(times)-1}
            for o in full[0][:4]:locations.update([int(o[0]),int(o[0])+1])
            for e in full[4][:4]:locations.update([int(e[0])+1])
            for cut in sorted(i for i in locations if 0<i<len(times)):
                shortened=tuple(v[:cut] if i<8 else v for i,v in enumerate(r))
                prefix=engine.run.py_func(*arguments(shortened,family,variant=variant))
                counts['比較配列数']+=compare_prefix(full,prefix,cut,times[cut-1])
                future=list(r)
                for column in [1,2,3]:
                    future[column]=r[column].copy();future[column][cut:]+=300.
                altered=engine.run.py_func(*arguments(tuple(future),family,variant=variant))
                counts['比較配列数']+=compare_prefix(altered,prefix,cut,times[cut-1])
                counts['切断地点数']+=1
                counts['保有中切断']+=int(prefix[3][4]+prefix[3][5]>0)
                counts['両建て中切断']+=int(prefix[3][4]>0 and prefix[3][5]>0)
                counts['予約中切断']+=int(prefix[3][6]+prefix[3][7]>0)
            counts['人工経路数']+=1
    result=dict(合格=True,**counts,主遅延秒=0,エンジンSHA256=digest(WORK/'engine.py'),
        範囲='各家族V0/V3。新サイクル・利益脚再建・親子・同時計後続行を含む人工資料。実データ未来不変は別途検証。')
    save('全家族人工未来切断監査.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
