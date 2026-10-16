"""最初の単一玉の常設指値・次気配返済・予約優先と費用を人工だけで確認する。"""

from copy import deepcopy
from decimal import Decimal
import json
import numpy as np
import common
import policy


def fixture(symbol: str, side: int=1) -> tuple[dict,dict]:
    """
    機能: 正常な人工気配と一つの実新規をラージ板の観測呼値で作成する。
    引数: symbol(str)、side(int)は商品と新規方向。
    返り値: tuple[dict,dict]は口座と最初entry。実入力を読まない。
    """
    n=9;tick=policy.TICK[symbol];p=4000. if symbol=='TOPIX' else 66000.
    b=np.full(n,p);a=b+tick
    q=dict(bid=b,ask=a,quote_valid=np.ones(n,bool),seq=np.arange(n,dtype=np.int64),time_s=np.arange(n,dtype=float))
    account=dict(session='人工',symbol=symbol,quotes=q,record=dict(limit=8.,tick=tick),
        quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool))
    E=q['ask' if side>0 else 'bid'][1]
    entry=dict(order=np.array([1,0,7,side,policy.QUANTITY[symbol],E,90,1.]),uid=71)
    return account,entry


def set_liquidation(account: dict, row: int, E: float, side: int, steps: float) -> None:
    """
    機能: 指定行の清算気配を建値から方向付き呼値だけ動かす。
    引数: account(dict)、row/side(int)、E/steps(float)は人工口座と変更量。
    返り値: None。両気配の正常spreadを保持する。
    """
    q=account['quotes'];tick=policy.TICK[account['symbol']];P=E+side*steps*tick
    q['bid'][row]=P if side>0 else P-tick;q['ask'][row]=P+tick if side>0 else P


def main() -> None:
    """
    機能: 買売・二商品・二方式・停止幅の経済と予約/未来接頭を人工で検査する。
    引数: なし。
    返り値: None。私有人工証跡のみ保存し、既知金融やAPIへ接続しない。
    """
    checks=[];assert len(policy.configs())==12
    for symbol in policy.QUANTITY:
        for side in (1,-1):
            for config in [c for c in policy.configs() if c['mode']=='CONFIRM']:
                a,e=fixture(symbol,side);E=e['order'][5];set_liquidation(a,3,E,side,1);set_liquidation(a,4,E,side,0)
                r=policy.play(a,e,config);rest=config['method']=='RESTING';expected_row=3 if rest else 4
                assert r['control']['返済行']==expected_row and r['orders'][-1,5]==E+(side*policy.TICK[symbol] if rest else 0.)
                net=Decimal(side)*Decimal(policy.QUANTITY[symbol])*(Decimal(str(r['orders'][-1,5]))-Decimal(str(E)))*Decimal(str(policy.VALUE[symbol]))-2*policy.fee(policy.QUANTITY[symbol],symbol)
                assert r['summary']['収支']==float(net) and r['summary']['費用']==2*policy.fee(policy.QUANTITY[symbol],symbol)
                assert r['orders'][-1,0]>r['orders'][0,0] and np.all(r['long_qty']<=policy.CAP[symbol]) and np.all(r['short_qty']<=policy.CAP[symbol])
                checks.append(symbol+str(side)+str(config['stop_ticks'])+config['method']+' 同一接触で常設固定lineと次気配実BBO・Decimal料を区別')
                changed=deepcopy(a);changed['quotes']['bid'][5:]+=100*policy.TICK[symbol];changed['quotes']['ask'][5:]+=100*policy.TICK[symbol]
                future=policy.play(changed,e,config);np.testing.assert_array_equal(r['orders'],future['orders'])
                for name in ('equity_yen','liquidation_yen','long_qty','short_qty'):np.testing.assert_array_equal(r[name][:5],future[name][:5])
                checks.append('返済後未来価格改変で過去注文と曲線を変更しない')
                # ----------------------------------------
                # 損切り予約の次行で利益へ回復しても、予約を常設利確へ置き換えない。
                a,e=fixture(symbol,side);E=e['order'][5]
                set_liquidation(a,2,E,side,-config['stop_ticks']);set_liquidation(a,3,E,side,2)
                r=policy.play(a,e,config);assert r['control']['種別']=='損切り' and r['control']['判断行']==2 and r['control']['返済行']==3
                assert r['orders'][-1,5]==E+side*2*policy.TICK[symbol]
                checks.append('損切りlatched後の利益接触で予約理由/価格モデルを遡及変更しない')
                a['quotes']['quote_valid'][3]=False;r=policy.play(a,e,config)
                assert r['control']['返済行']==4;checks.append('不正quoteを飛ばして最初の次正常へ返済')
                a,e=fixture(symbol,side);E=e['order'][5];set_liquidation(a,3,E,side,2);a['quiet'][3]=True
                r=policy.play(a,e,config);assert r['control']['種別']=='既知quiet' and r['control']['返済行']==3
                checks.append('既知quietの返済が同行利確接触より優先')
                a['quotes']['quote_valid'][3]=False;a['quiet'][4]=False;r=policy.play(a,e,config)
                assert r['control']['種別']=='既知quiet' and r['control']['返済行']==4
                checks.append('quiet中に正常quoteがなくてもtimer予約を後で維持')
                a,e=fixture(symbol,side);E=e['order'][5]
                set_liquidation(a,2,E,side,-config['stop_ticks']);a['quotes']['quote_valid'][3]=False;a['quiet'][3]=True
                r=policy.play(a,e,config);assert r['control']['元観測予約判断行']==2 and r['control']['timer開始行']==3
                assert r['control']['種別']=='既知quiet' and r['control']['判断行']==2 and r['control']['返済行']==4
                checks.append('損切り予約後quiet介入を旧判断とtimer由来へ別保存')
                a,e=fixture(symbol,side);E=e['order'][5];set_liquidation(a,1,E,side,-config['stop_ticks'])
                e['order'][5]=a['quotes']['ask' if side>0 else 'bid'][1]
                # 広spreadを新規fill行で作り、反対清算が停止線を破る。
                if side>0:a['quotes']['bid'][1]=e['order'][5]-(config['stop_ticks']+1)*policy.TICK[symbol]
                else:a['quotes']['ask'][1]=e['order'][5]+(config['stop_ticks']+1)*policy.TICK[symbol]
                r=policy.play(a,e,config);assert r['control']['判断行']==1 and r['control']['返済行']==2 and r['control']['種別']=='損切り'
                checks.append('新規fill行の支持破れを当行判断・次正常返済。同row返済なし')
                a,e=fixture(symbol,side);short=deepcopy(a)
                for k in short['quotes']:short['quotes'][k]=short['quotes'][k][:3]
                short['quiet']=short['quiet'][:3];short['quiet_force']=short['quiet_force'][:3]
                r=policy.play(short,e,config,False);assert len(r['orders'])==1 and not r['parent']
                assert r['long_qty'][-1]+r['short_qty'][-1]==policy.QUANTITY[symbol]
                try:policy.play(short,e,config,True)
                except AssertionError:pass
                else:raise AssertionError('切断入力を完成へ誤認')
                checks.append('finishFalse未返済保持・finishTrue端点不足拒否')
    a,e=fixture('TOPIX');r=policy.play(a,None,policy.configs()[0]);assert not r['parent'] and r['summary']['親数']==0
    checks.append('元入口なしを無取引として保持し勝ちへ含めない')
    common.write(common.HERE/'常設利確と次気配返済の人工検査.json',dict(全合格=True,検査数=len(checks),検査=checks,
        source_SHA256=common.source_hashes(),実input読取=0,元GU読取=0,新金融=0,原NPZ=0,API=0,
        限界='常設line接触全量は人工モデルである。実native板順位を確認していない。'))
    print(json.dumps(dict(全合格=True,検査数=len(checks)),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
