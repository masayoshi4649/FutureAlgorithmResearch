"""動的数量と部分返済を、旧同値とDecimal実料で人工検査する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib

import numpy as np
from numba.core.registry import CPUDispatcher

import common
import catalog
import daily
import engine
import interface
import baseline
import order_kernel
import policy
import runner
import storage


def fixture(symbol: str, side: int=1, atr: float|None=None) -> dict:
    """
    機能: 仮想部分返済2→1→残の割合と、後続の新規を持つ人工気配を作る。
    引数: symbol(str)、side(int)、atr(float|None) は商品・方向・公開ATR。
    返り値: dict は人工専用口座。実入力は使用しない。
    """
    tick=daily.TICK[symbol];qty=catalog.QUANTITY[symbol];n=18;base=4000. if symbol=='TOPIX' else 65000.
    bid=np.full(n,base);ask=bid+tick;p=ask.copy();times=np.arange(n,dtype=float)
    first=2 if symbol=='TOPIX' else 4;second=1 if symbol=='TOPIX' else 2
    a=1. if symbol=='TOPIX' else 50.
    if atr is not None:a=atr
    feed=np.array([[1,0,0,1,qty,p[1],0,1,0,a],
        [4,0,0,-1,first,p[4],0,0,0,0],[6,0,0,-1,second,p[6],0,0,0,0],
        [8,0,0,-1,qty-first-second,p[8],0,0,0,0],
        [10,0,1,1,qty,p[10],0,1,0,a],[14,0,1,-1,qty,p[14],0,0,0,0]],float)
    if side<0:
        center=2*base+tick;p=center-p;bid,ask=center-ask,center-bid;feed[:,3]*=-1;feed[:,5]=center-feed[:,5]
    quotes=dict(seq=np.arange(n,dtype=np.int64),time_s=times,bid=bid,ask=ask,quote_valid=np.ones(n,bool))
    record=dict(seq=quotes['seq'],time_s=times,price=p,start=0.,end=17.,limit=17.,tick=tick)
    features={int(o[0]):dict(known=True,reason=0,direction_votes=2,balance=1.,accepted=True) for o in feed[feed[:,7]==1]}
    return dict(symbol=symbol,record=record,quotes=quotes,feed=feed,quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),
        trade_features={'60':features})


def old(a: dict, c: dict, python: bool=False) -> tuple:
    """
    機能: 同bytes私有旧engineを使い、旧9配列の数値対照だけを返す。
    引数: a/c(dict)、python(bool) は人工口座・条件・Pythonか。
    返り値: tuple は旧9配列。旧moduleや旧JITは読まない。
    """
    r,q=a['record'],a['quotes'];mask,_=policy.mask(a['feed'],len(r['price']),a['trade_features']['60'],c['mode'])
    fn=baseline.simulate.py_func if python else baseline.simulate
    return fn(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],a['quiet'],a['quiet_force'],
        r['limit'],catalog.CAP[a['symbol']],r['tick'],0.,True,mask)


def assert_equal(a: tuple, b: tuple, count: int=9) -> None:
    """
    機能: 数値対照の対象配列を全要素exactに照合する。
    引数: a/b(tuple)、count(int) は比較出力と対象数。
    返り値: None。NaNの同位置を含むexact配列比較で不一致を拒否する。
    """
    for i in range(count):np.testing.assert_array_equal(a[i],b[i])


def prefix(a: dict, cut: int) -> dict:
    """
    機能: 未完成場の実観測接頭だけを人工的に切り出す。
    引数: a(dict)、cut(int) は人工口座と行端点。
    返り値: dict は未来limitを保持した未返済接頭。終端を人工清算しない。
    """
    r=dict(a['record']);q=dict(a['quotes'])
    for d in (r,q):
        for k,v in tuple(d.items()):
            if isinstance(v,np.ndarray):d[k]=v[:cut].copy()
    feed=a['feed'][a['feed'][:,0]<cut].copy()
    return dict(a,record=r,quotes=q,feed=feed,quiet=a['quiet'][:cut].copy(),quiet_force=a['quiet_force'][:cut].copy(),
        trade_features={'60':{row:v for row,v in a['trade_features']['60'].items() if row<cut}})


def independent_fees(values: tuple, symbol: str) -> None:
    """
    機能: Decimal注文別料を自前集計し、engineの実支払曲線へ照合する。
    引数: values(tuple)、symbol(str) は人工実注文と商品。
    返り値: None。旧会計の自己一致だけに依存せず料額を検査する。
    """
    fee=Decimal('41.8' if symbol=='TOPIX' else '11');paid=np.zeros(len(values[10]))
    for o in values[0]:paid[int(o[0])]+=int((Decimal(int(o[4]))*fee).to_integral_value(rounding=ROUND_FLOOR))
    np.testing.assert_array_equal(np.cumsum(paid),values[10][:,0])


def driver_connection() -> list[str]:
    """
    機能: 数量差の五寄与、親内玉相殺、副集計及び疎保存を人工で接続する。
    引数: なし。実入力cacheや保存金融の台帳は読まない。
    返り値: list[str] は確認した接続範囲の日本語説明。
    """
    checks=[]
    before=dict(parent=[{'親':0,'収支':-100.},{'親':1,'収支':50.},{'親':2,'収支':200.}],summary={'収支':150.})
    after=dict(parent=[{'親':2,'収支':100.},{'親':3,'収支':-10.}],summary={'収支':90.})
    change=storage.delta(before,after)
    assert change=={'収支変化':-60.,'避けた基準損失':100.,'失った基準利益':50.,
        '共通入口の数量/出口差':-100.,'新たな入口の収支':-10.}
    checks.append('数量が違う同paper親を共通寄与とし、入口削除・新参加との五寄与等式を保持')
    for symbol in catalog.QUANTITY:
        for side in (1,-1):
            a=fixture(symbol,side);c=catalog.configs()[0];tick=daily.TICK[symbol]
            if side>0:
                a['quotes']['bid'][5]=a['quotes']['ask'][2]+tick
                a['quotes']['ask'][5]=a['quotes']['bid'][5]+tick
            else:
                a['quotes']['ask'][5]=a['quotes']['bid'][2]-tick
                a['quotes']['bid'][5]=a['quotes']['ask'][5]-tick
            values=interface.execute(a,c,python=True)
            value=interface.account_output('人工',a,c,values)
            legs=value['actual_legs'];totals=value['actual_leg_totals']
            assert any(p['収支']>0 for p in legs) and any(p['収支']<0 for p in legs)
            assert totals['profit']==sum(p['収支'] for p in legs if p['収支']>0)
            assert totals['loss']==sum(-p['収支'] for p in legs if p['収支']<0)
            assert np.isclose(totals['net'],value['summary']['収支'],atol=1e-5,rtol=0.)
            assert totals['profit_share']!=value['summary']['利益割合']
            saved=storage.stored(value,len(a['record']['price']))
            assert saved['schema_version']==2
            for name in ('equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty',
                         'execution_states','gate_accepted','gate_reasons','sizing_fee_curve'):
                encoded=saved[name];assert encoded['length']==len(a['record']['price'])
                locations=np.searchsorted(encoded['rows'],np.arange(encoded['length']),side='right')-1
                np.testing.assert_array_equal(encoded['values'][locations],value[name])
            checks.append(symbol+str(side)+':親内の正負実玉を別定義で集計し、政策会計とGU診断の全行疎保存がexact')
    sessions=['人工'+str(i) for i in range(33)]
    rows=[dict(session=s,symbol=symbol) for s in sessions for symbol in catalog.QUANTITY]
    refs=[dict(**r,path='人工専用',SHA256='人工専用') for r in rows]
    small=dict(results={'人工条件':dict(rows=rows,ledgers=refs,symbols={})})
    linked=runner.item(small,'人工条件')
    assert len(linked['ledgers'])==66 and set(linked['ledgers'])=={r['session']+'|'+r['symbol'] for r in rows}
    assert len(runner.cloned())==5
    checks.append('driverの66場商品引用と、影・UID・料・公開gate・旧執行の同bytesコピーを検査')
    return checks


# ----------------------------------------
def run(proof_name: str='予定リスク数量と累積部分返済及び旧同値の人工検査_v2.json') -> None:
    """
    機能: 旧同値・実部分率・予約・数量固定・料金・接頭未来を人工で検査する。
    引数: proof_name(str) は新しい人工証跡名。既証跡を上書きしない。
    返り値: None。新金融は実行せず、所有証跡へsource束縛で保存する。
    """
    source_before=common.sources();checks=[];comparisons=0
    configs=catalog.configs();assert len(configs)==4
    for s in catalog.QUANTITY:
        for side in (1,-1):
            for c in configs:
                a=fixture(s,side);off=interface.execute(a,c,sizing_enabled=False);legacy=old(a,c)
                assert_equal(off,legacy);comparisons+=9;checks.append(s+str(side)+c['id']+':部品OFF旧9配列exact')
                tiny=fixture(s,side,atr=.001)
                # 全量対照では最初の親を値幅0で完結し、次親にも全量を払える余力を残す。
                # 通常fixtureのspread負けで次qが縮むことは別の検査で確認する。
                for fill in (5,7,9):
                    if side>0:
                        tiny['quotes']['bid'][fill]=tiny['quotes']['ask'][2]
                        tiny['quotes']['ask'][fill]=tiny['quotes']['bid'][fill]+daily.TICK[s]
                    else:
                        tiny['quotes']['ask'][fill]=tiny['quotes']['bid'][2]
                        tiny['quotes']['bid'][fill]=tiny['quotes']['ask'][fill]-daily.TICK[s]
                actual=interface.execute(tiny,c);legacy=old(tiny,c)
                # 全量の後親も許せるよう同額で閉じ、料だけ負担する幅にする。
                assert np.all(actual[9][:,4]==catalog.QUANTITY[s])
                assert_equal(actual,legacy);comparisons+=9;checks.append(s+str(side)+c['id']+':全base数量旧9配列exact')
            for requested,a_value in ((1,3. if s=='TOPIX' else 100.),(2,1.5 if s=='TOPIX' else 70.),(3,1. if s=='TOPIX' else 50.)):
                a=fixture(s,side,a_value);c=configs[0]
                values=interface.execute(a,c);python=interface.execute(a,c,python=True)
                assert_equal(values,python,11);comparisons+=11
                first=values[0][values[0][:,2]==0];assert int(first[0,4])==requested
                original=catalog.QUANTITY[s];cum1=2 if s=='TOPIX' else 4;cum2=3 if s=='TOPIX' else 6
                desired=[requested*cum1//original,requested*cum2//original];expected=[desired[0],desired[1]-desired[0],requested-desired[1]]
                assert [int(o[4]) for o in first if not o[7]]==[q for q in expected if q]
                independent_fees(values,s)
                for case in configs:interface.account_output('人工',a,case,values)
                checks.append(s+str(side)+':実Q'+str(requested)+'の累積部分率・次quote・Decimal料・全UID会計')
                if s=='TOPIX' and requested==3:assert values[10][9,0]==249
                if requested==3:assert values[9][1,4]<requested,'前親lossと実料で次の数量余力は縮む'
                for cut in (2,3,5,7,9,11,15):
                    short=interface.execute(prefix(a,cut),c,python=True)
                    np.testing.assert_array_equal(short[0],values[0][values[0][:,0]<cut])
                    np.testing.assert_array_equal(short[2],values[2][:cut]);np.testing.assert_array_equal(short[7],values[7][:cut]);np.testing.assert_array_equal(short[10],values[10][:cut])
                    np.testing.assert_array_equal(short[9],values[9][values[9][:,0]<cut])
                    if cut==3:assert short[7][-1,3]+short[7][-1,4]==requested,'未返済接頭を場末清算しない'
                    altered=fixture(s,side,a_value)
                    altered['quotes']['bid'][cut:]+=10*daily.TICK[s];altered['quotes']['ask'][cut:]+=10*daily.TICK[s]
                    altered['quotes']['quote_valid'][cut:]=False
                    future=interface.execute(prefix(altered,cut),c,python=True);assert_equal(short,future,11);comparisons+=11
                checks.append(s+str(side)+':Q'+str(requested)+'の七接頭と未来quote資格変更不変')
            a=fixture(s,side);c=configs[0];a['quotes']['quote_valid'][1]=False
            values=interface.execute(a,c,python=True);assert values[9][0,13]==96 and not np.any(values[0][values[0][:,2]==0,7])
            checks.append(s+str(side)+':公開当行quote未知は同親を将来救済しない')
            a=fixture(s,side,atr=1000.);values=interface.execute(a,c,python=True)
            assert values[9][0,13]==97 and values[9][0,4]==0 and len(values[0])==0
            checks.append(s+str(side)+':既知q0と未知を分離し全影feed継続')
            a=fixture(s,side);a['quotes']['quote_valid'][5:12]=False;values=interface.execute(a,c,python=True)
            assert not np.any(values[0][values[0][:,2]==1,7]);assert values[8][values[8][:,1]==1][-1,17]==94
            assert sum(o[4] for o in values[0] if not o[7])==3
            checks.append(s+str(side)+':複数exit予約を二重返済せず後親busy拒否')
            a=fixture(s,side);a['quotes']['bid'][2]+=20*daily.TICK[s];a['quotes']['ask'][2]+=20*daily.TICK[s]
            values=interface.execute(a,c,python=True);assert values[0][0,4]==values[9][0,4]==3
            checks.append(s+str(side)+':次quote悪化後も公開時実枚数を後から変更しない')
            a=fixture(s,side);a['quiet'][2:4]=True;values=interface.execute(a,c,python=True)
            assert not np.any(values[0][values[0][:,2]==0,7]);checks.append(s+str(side)+':既知静観が新規fillに優先')
            a=fixture(s,side);a['record']['limit']=2.;values=interface.execute(a,c,python=True)
            assert len(values[0])==0;checks.append(s+str(side)+':既知期限が新規fillに優先')
    checks.extend(driver_connection())
    locators={}
    for module in (engine,baseline,order_kernel):
        for name,value in vars(module).items():
            if isinstance(value,CPUDispatcher):
                path=value._cache._impl._locator._cache_path;assert str(common.HERE/'jit') in path
                locators[module.__name__+'.'+name]=path
    assert source_before==common.sources()
    common.write(common.HERE/proof_name,dict(全合格=True,
        確認観点=checks,観点数=len(checks),全配列照合数=comparisons,source_SHA256=source_before,
        JIT所有域=locators,母条件数=2,利益目標数=2,予定GU=132,予定政策会計=264,
        実入力読取=0,元paper再計算=0,正式金融=0,API=0))
    print('数量・累積部分・旧同値人工合格 '+str(len(checks))+'観点/'+str(comparisons)+'配列照合',flush=True)


if __name__=='__main__':run()
