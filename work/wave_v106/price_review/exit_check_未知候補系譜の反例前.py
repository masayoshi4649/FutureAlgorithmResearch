"""途中全normal票と実残玉の追加退出を金融前の独立人工だけで確認する。"""

from copy import deepcopy
from pathlib import Path
import json
import sys

import numpy as np

from range_engine_check import load,digest
from trade_check import fixture_raw,oracle
from budget_check import fixture
from e01_trade_finance_audit import inspect_orders
import range_finance_audit as A


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_trade_exit'


def main() -> None:
    """
    機能: 固定sourceの全normalベクトル票・実方向の真偽・途中予約の因果を独立検算する。
    引数: なし。金融結果/現Night/原NPZ/実packetは読まない。
    返り値: Noneは金融前人工証跡。正式全normal票の全実行同値を主張しない。
    """
    target=HERE/'exit_全normal票と実残玉早期退出の独立人工.json';assert not target.exists()
    before={str(p.relative_to(ROOT)):digest(p) for p in SOURCE.glob('*.py')}
    V=load('独立途中票votes',SOURCE/'votes.py');F=load('独立途中票normal',SOURCE/'features.py');D=load('独立途中票daily',SOURCE/'daily.py')
    old=sys.modules.get('daily');sys.modules['daily']=D
    try:P=load('独立途中票policy',SOURCE/'policy.py')
    finally:
        if old is None:sys.modules.pop('daily',None)
        else:sys.modules['daily']=old
    checks=0;raw=fixture_raw()
    for mirror in (False,True):
        for kind in ('none','withinreset','outsidegap','withingap','reverse','nan','allnan','inside','lastnan','priorasknan','late_sameclock'):
            value=deepcopy(raw)
            if mirror:value['bid'],value['ask'],value['last']=200-raw['ask'],200-raw['bid'],200-raw['last']
            if kind=='withinreset':value['volume_delta_usable'][4]=False;value['volume_reset_reason'][4]=32
            if kind=='outsidegap':value['raw_seq'][2:]+=1
            if kind=='withingap':value['raw_seq'][5:]+=1
            if kind=='reverse':value['price_time_s'][5]=19
            if kind=='nan':value['price_time_s'][5]=np.nan
            if kind=='allnan':value['price_time_s'][:]=np.nan
            if kind=='inside':value['last'][4]=100.5 if not mirror else 99.5
            if kind=='lastnan':value['last'][4]=np.nan
            if kind=='priorasknan':value['ask'][3]=np.nan
            if kind=='late_sameclock':value['price_time_s'][6]=20;value['last'][6]=101 if not mirror else 99;value['volume_delta'][6]=1
            ctx=V.context(value);mapping=np.arange(len(value['raw_seq']),dtype=np.int64)
            for window in (10,30,60):
                vector=F.all_normal(value,ctx,mapping,window)
                for row in mapping:
                    expected=oracle(value,int(row),window,1)
                    assert vector['known'][row]==expected['known'] and vector['reason'][row]==expected['reason']
                    assert vector['up_votes'][row]==expected['up'] and vector['down_votes'][row]==expected['down'];checks+=4
                    short={k:v[:row+1] for k,v in value.items()};v2=F.all_normal(short,V.context(short),np.arange(row+1,dtype=np.int64),window)
                    for field in vector:np.testing.assert_array_equal(vector[field][:row+1],v2[field]);checks+=1
    # ----------------------------------------
    # 指標を実残玉方向へ掛ける真偽。flat・未知・2票未満を方向変更と読まない。
    for symbol in ('TOPIX','NK225'):
        unit=D.TICK[symbol]*D.QUANTITY[symbol]*D.VALUE[symbol]
        for side in (-1,0,1):
            for known in (False,True):
                for total in (0,1,2,4):
                    for balance in (-1.,-.25,-.249,0.,.249,.25,1.):
                        for loss in (-8.,-4.,-3.999,0.,1.):
                            base=dict(long_qty=np.array([D.QUANTITY[symbol] if side>0 else 0]),short_qty=np.array([D.QUANTITY[symbol] if side<0 else 0]),liquidation_yen=np.array([loss*unit]))
                            observed=dict(known=np.array([known]),up_votes=np.array([total],np.int32),down_votes=np.array([0],np.int32),balance=np.array([balance]))
                            expected=side!=0 and known and total>=2 and side*balance<=-.25 and loss<=-4
                            assert P.early_mask(base,observed,symbol)[0]==expected;checks+=1
    # ----------------------------------------
    # 当時逆票で判断した後の票変化は取消へ使わず、次正常気配の利益/損失をそのまま残す。
    cases=[]
    for symbol in ('TOPIX','NK225'):
        tick=D.TICK[symbol];unit=tick*D.QUANTITY[symbol]*D.VALUE[symbol]
        for side in (-1,1):
            for missing_next in (False,True):
                quotes,orders,uids=fixture(symbol,side,1,False);n=len(quotes['bid']);opening=4000 if symbol=='TOPIX' else 68000
                if side>0:quotes['bid'][2:4]=opening-3*tick;quotes['ask'][2:4]=quotes['bid'][2:4]+tick
                else:quotes['ask'][2:4]=opening+3*tick;quotes['bid'][2:4]=quotes['ask'][2:4]-tick
                quotes['quote_valid'][3]=not missing_next;base=D.reconstruct(('人工',symbol),orders,uids,quotes)
                balance=np.ones(n)*side;balance[2]=-side
                observed=dict(known=np.ones(n,bool),up_votes=np.ones(n,np.int32)*2,down_votes=np.ones(n,np.int32)*2,balance=balance)
                c=dict(profit_ticks=1,loss_ticks=8,early_loss_ticks=4);out=P.apply_policy(base,quotes,observed,c)
                assert out['control']['種別']=='逆票かつ4呼値損失' and out['control']['判断行']==2 and out['control']['返済行']==(4 if missing_next else 3)
                assert out['orders'][-1,6]==96 and out['exit_target_uids'][-1]==21
                inspect_orders(out,quotes,symbol);assert not np.any(out['orders'][(out['orders'][:,0]>2)&(out['orders'][:,7]==1)])
                cases.append(dict(symbol=symbol,side=side,次気配不正=missing_next,判断=2,返済=out['control']['返済行'],収支=out['summary']['収支']));checks+=4
    assert digest(SOURCE/'votes.py')==digest(ROOT/'work/wave_v106/trade_gate/votes.py')
    assert digest(SOURCE/'daily.py')==digest(ROOT/'work/wave_v106/e01_daily/core.py')
    assert before=={str(p.relative_to(ROOT)):digest(p) for p in SOURCE.glob('*.py')}
    proof=dict(全合格=True,scope='全normal票ベクトル対独立逐次oracleと途中退出の金融前人工。正式入力/新金融/結果未読。',検査数=checks,追加会計検査数=sum(A.COUNT.values()),人工退出口座=len(cases),人工=cases,source_SHA256=before,source開始終端一致=True,レビューsource_SHA256=digest(Path(__file__)),新金融=0,正式入力=0,NPZ=0,現NightAPI=0,留意点=['全normal途中票を改めて測り、入口票dictionaryを途中へ延長しない。票方向は当時実残玉sideを掛ける。','反対票だけでは退出せずfee清算<=−4初回呼値も必要。利益1/hard8の先着が優先。','判断後に票が戻ったり次quoteが利益になっても、既返済判断を取消したり判断時点を書き換えない。','窓はCurrentPriceTime代理、受信時刻・真の攻撃方向/量ではない。原seq以下の同clock後半だけを使う。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print('途中退出の独立人工合格',checks,digest(target))


if __name__=='__main__':main()
