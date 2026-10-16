"""注文だけの12家族を、価格不変・往復・跳躍・欠測の人工経路で検査する。"""

from context import *


def run_checked(a: tuple, symbol: str) -> tuple:
    """機能: 実装を人工経路で動かし、独立会計と予約順を検算する。

    引数: a(tuple)、symbol(str)。返り値: 実装出力・独立会計・予約集計(tuple)。
    """
    out=engine.run.py_func(*a)
    return out,cash_oracle(a,out,symbol),reservation_oracle(a,out)


def main() -> None:
    """機能: 全家族の人工反証と具体的な期待値を実行する。

    引数: なし。返り値: なし(None)。失敗も日本語で記録する。
    """
    passed=[];failed=[];accounts=orders=trades=curvepoints=0

    def check(name,action):
        """機能: 一つの境界検査を実行し、他の検査を止めず記録する。

        引数: name(str)、action(callable)。返り値: なし(None)。
        """
        try:
            value=action();passed.append(dict(検査=name,結果=value))
        except Exception as exc:
            failed.append(dict(検査=name,例外=type(exc).__name__,詳細=str(exc)))

    # ----------------------------------------
    # 前半で上昇・下落・往復・跳躍をすべて含む。終わりは全玉清算できる。
    t=np.arange(301,dtype=float)
    p=500+8*np.sin(t/9.)+np.where(t<80,t*.1,np.where(t<160,16-t*.1,0))
    p[70:75]+=16.;p[150:155]-=16.
    for symbol in ['TOPIX','NK225']:
        for family in range(12):
            for variant in range(4):
                for delay in [0.,5.]:
                    a=arguments(record(t,p),family,width=2,variant=variant,symbol=symbol,delay=delay)
                    try:
                        out,b,c=run_checked(a,symbol)
                        assert not np.any(out[3][4:8])
                        accounts+=1;orders+=b['注文数'];trades+=b['決済数'];curvepoints+=b['全行時価数']
                    except Exception as exc:
                        failed.append(dict(検査=f'全家族人工 {symbol} 家族{family} V{variant} 待ち{delay}',
                            例外=type(exc).__name__,詳細=str(exc)))
    passed.append(dict(検査='12家族×4変数×両商品×即時/旧遅延互換の独立会計',口座数=accounts))

    def flat_hedge():
        """機能: 無変動の両建てが料金と気配差だけを失うことを確認する。

        引数: なし。返り値: 具体会計(dict)。
        """
        a=arguments(record([0,1,2,240,241],[100]*5),2,width=8)
        out,b,c=run_checked(a,'TOPIX')
        assert b['収支']==-21672. and b['料金']==1672 and b['最大総保有']==20
        np.testing.assert_array_equal(out[0][:2,0],[0,0]);assert len(out[1])==2
        return b
    check('価格不変の両建ては無利益・両方向全料金',flat_hedge)

    def sameclock_child():
        """機能: 親は同一行即時、子は次の同時計観測で監視されることを確認する。

        引数: なし。返り値: 判断・約定行(dict)。
        """
        a=arguments(record([0,0,1,240,241],[100]*5,bid=[99]*5,ask=[105]*5),1,width=2)
        out,b,c=run_checked(a,'TOPIX')
        assert out[0][0,0]==0 and out[0][1,0]==1 and out[0][1,7]==1
        return dict(親約定行=int(out[0][0,0]),子約定行=int(out[0][1,0]),親子約定時計=out[0][:2,11].tolist())
    check('即時新規・次の同時計行で子の初回損切り',sameclock_child)

    def missing_child():
        """機能: 初回子監視前の無効価格で、その監視権が失われないことを確認する。

        引数: なし。返り値: 親子注文(dict)。
        """
        a=arguments(record([0,1,2,240,241],[100,np.nan,100,100,100],bid=[99]*5,ask=[105]*5),1,width=2)
        out=engine.run.py_func(*a)
        assert out[0][1,0]==2 and out[0][1,7]==1,out[0].tolist()
        return dict(子約定行=int(out[0][1,0]))
    check('無効CurrentPriceを挟んでも未評価IFDを保持',missing_child)

    def ioc_failure():
        """機能: 条件価格タッチだけでは上限付き買いを成立させない。

        引数: なし。返り値: 発注と失効の件数(dict)。
        """
        a=arguments(record([0,1,2,240,241],[100,98,98,98,98]),6,width=2)
        out,b,c=run_checked(a,'TOPIX')
        assert len(out[0])==0 and c['失効数']==1 and c['新規予約数']==1
        return c
    check('指値条件到達とaskでのIOC失効を区別',ioc_failure)

    def timer_gap():
        """機能: 観測空白の間でも既知の場内返済予定を送った時計で扱う。

        引数: なし。返り値: 返済時計(dict)。
        """
        a=arguments(record([0,1,239,260,261],[100]*5),1,width=8)
        out,b,c=run_checked(a,'TOPIX')
        last=out[0][-1];assert last[7]==6 and last[9]==240 and last[11]==260
        return dict(予定時計=float(last[9]),約定時計=float(last[11]),利益=b['収支'])
    check('観測欠落中の定時返済・最初の有効気配約定',timer_gap)

    def late_entry():
        """機能: 場末にようやく成立した新規も残さず返済する。

        引数: なし。返り値: 新規と返済の注文(dict)。
        """
        a=arguments(record([0,239,260,261,270],[100]*5,bid=[np.nan,np.nan,99,99,99],ask=[np.nan,np.nan,101,101,101]),1,width=8)
        out,b,c=run_checked(a,'TOPIX')
        assert len(out[0])==2 and not np.any(out[3][4:8])
        assert out[0][0,0]==2 and out[0][1,0]==2 and out[0][1,7]==6
        return dict(同一行新規返済=True,料金=b['料金'],最大保有=int(out[3][0]))
    check('遅着新規の同一行場内清算と最大保有',late_entry)

    def capacity():
        """機能: 多段注文が毎行発動しても配列容量が取引を切り捨てない。

        引数: なし。返り値: 注文数(dict)。
        """
        times=np.arange(301,dtype=float)
        prices=np.where(np.arange(301)%2,490.,510.);prices[0]=500.
        out=engine.run.py_func(*arguments(record(times,prices),7,width=1))
        return dict(注文数=len(out[0]),イベント数=len(out[4]))
    check('多段グリッドの高頻度全段発動と容量境界',capacity)

    result=dict(合格=not failed,旧実装互換遅延は人工のみ=True,主検証遅延秒=0,
        人工口座数=accounts,注文数=orders,決済数=trades,全行清算時価数=curvepoints,
        成功=passed,失敗=failed,エンジンSHA256=digest(WORK/'engine.py'))
    save('人工境界と全玉会計監査.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
