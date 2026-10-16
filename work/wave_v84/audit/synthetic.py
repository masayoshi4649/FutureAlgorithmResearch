"""逆指値新規と即ドテンの境界を人工原板と独立台帳で検証する。"""
from context import *


def execute(r: tuple, family: int, variant=1, width=2, symbol='TOPIX') -> tuple:
    """機能: 指定した人工経路を再生し、現金と予約を独立照合する。

    引数: r(tuple)、family/variant/width(int)、symbol(str)。返り値: 出力tuple。
    """
    args=arguments(r,family,width,variant,symbol)
    out=load_engine().run(*args)
    cash_oracle(args,out,symbol);reservation_oracle(args,out)
    assert out[3][11]<=args[4]
    for row in np.unique(out[0][:,0]):
        openings=out[0][(out[0][:,0]==row)&(out[0][:,6]==1)]
        assert len(openings)<=1
    return out


def main() -> None:
    """機能: 6家族全幅変数・商品と具体的な因果境界を検査する。

    引数: なし。返り値: なし(None)。原本損益の表示や選定はしない。
    """
    results={};checks=orders=trades=0
    # ----------------------------------------
    r=record([0,1,2,3,4,5,180,240,300],[100,102,106,104,102,100,100,100,100])
    out=execute(r,3)
    same=out[0][out[0][:,0]==3]
    assert len(same)==2 and list(same[:,6])==[0,1] and list(same[:,3])==[-1,-1]
    assert same[:,8].sum()==836 and np.all(same[:,5]==103.5)
    assert len(out[0][(out[0][:,0]==3)&(out[0][:,6]==1)])==1
    results['返済後の即ドテン']={'反転行':3,'同じ売気配':103.5,'返済と新規の料金計':836,'最大総玉':out[3][11]}
    wait=execute(r,4)
    assert not np.any((wait[0][:,0]==3)&(wait[0][:,6]==1))
    assert np.any((wait[0][:,0]==4)&(wait[0][:,6]==1)&(wait[0][:,7]==22)&(wait[0][:,3]==-1))
    results['反対へ追加1段']={'返済行':3,'反転新規行':4,'返済時現在値':104,'反転新規条件価格':102}
    # ----------------------------------------
    r=record([0,1,2,3,4,5,6,180,240,300],[100,102,106,104,106,104,102,102,102,102])
    out=execute(r,4)
    assert not np.any((out[0][:,0]==4)&(out[0][:,6]==1))
    entered=out[0][(out[0][:,6]==1)&(out[0][:,0]>3)][0]
    assert entered[0]==5 and entered[7]==20 and entered[3]==-1
    results['元方向1段で意図解除']={'解除行':4,'新基準':106,'通常入口再開行':5,'新規理由':20}
    # ----------------------------------------
    r=record([0,1,2,3,4,180,240,300],[100,102,104,102,100,100,100,100])
    out=execute(r,5)
    assert out[1][0,10]<0 and not np.any((out[0][:,0]==3)&(out[0][:,6]==1))
    rprofit=record([0,1,2,3,180,240,300],[100,102,106,104,104,104,104])
    profit=execute(rprofit,5)
    assert profit[1][0,10]>0 and np.any((profit[0][:,0]==3)&(profit[0][:,7]==21))
    results['利益返済限定']={'赤字時即反転なし':True,'料金後黒字時だけ即反転':True}
    # ----------------------------------------
    r=record([0,1,2,3,4,5,180,240,300],[100,102,106,104,100,100,100,100,100],
        [99.5,101.5,105.5,np.nan,np.nan,99.5,99.5,99.5,99.5],
        [100.5,102.5,106.5,np.nan,np.nan,100.5,100.5,100.5,100.5])
    out=execute(r,3)
    assert not np.any((out[0][:,0]>=3)&(out[0][:,0]<5))
    filled=out[0][out[0][:,0]==5]
    assert list(filled[:,6])==[0,1] and filled[0,1]==3 and filled[1,1]==5
    results['返済気配欠測中']={'反対新規の先行なし':True,'返済実約定後の行':5,'最大総玉':out[3][11]}
    # ----------------------------------------
    r=record([0,1,2,180,240,300],[100,102,106,104,104,104])
    out=execute(r,3)
    assert np.all(out[0][out[0][:,6]==1,9]<180) and out[3][4:8].sum()==0
    results['新規停止後のドテン禁止']={'返済だけ':True,'残玉':0}
    r=record([0,1,2,3,4,240,300],[100,102,np.nan,np.nan,102,102,102],
        [99.5,99,99,99,99,99,99],[100.5,105,105,105,105,105,105])
    out=execute(r,3)
    assert out[0][0,0]==1 and out[0][1,0]==4 and out[0][1,7]==1
    assert out[3][11]==10
    results['欠測後の初回監視']={'子条件の初回有効行':4,'同一行反転は一度':True}
    # ----------------------------------------
    r=record([0,1,179,181,260,300],[100,102,102,102,102,102],
        [99.5,np.nan,np.nan,np.nan,101.5,101.5],
        [100.5,np.nan,np.nan,np.nan,102.5,102.5])
    out=execute(r,3)
    assert list(out[0][:,0])==[4,4] and list(out[0][:,6])==[1,0] and out[0][-1,7]==6
    assert not out[3][4:8].any()
    results['場末後の保留新規約定']={'同じ行で直ちに全返済':True,'追加反転なし':True}
    # ----------------------------------------
    times=np.repeat(np.arange(151,dtype=float)*2.,2)
    prices=500+90*np.sin(np.arange(len(times))/7.)
    prices[70:73]-=80;prices[180:183]+=80
    r=record(times,prices)
    for family in range(6):
        for width in [2,4,8,16,32,64]:
            for variant in range(3):
                for symbol in ['TOPIX','NK225']:
                    out=execute(r,family,variant,width,symbol);checks+=1
                    orders+=len(out[0]);trades+=len(out[1])
                    assert out[3][4:8].sum()==0
    result=dict(合格=True,全幅家族商品ケース=checks,注文数=orders,決済数=trades,具体境界=results,
        エンジンSHA256=digest(WORK/'engine.py'),旧約定共通関数SHA256=digest(WORK.parent/'wave_v83/engine.py'))
    save('ドテン人工境界と独立会計.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
