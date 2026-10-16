"""複数親・両建て・数量料・停止遅れを、小人工の独立期待値で確認する。"""

from copy import deepcopy
import json
from pathlib import Path
import traceback
import time

import numpy as np

import common
import catalog
import control
import join
import prepare

HERE=Path(__file__).resolve().parent
ENGINE=common.module('106配分人工の現不変interface',common.WAVE/'engine/interface.py')
OLD_ACCOUNTING=common.module('106配分人工の不変会計',common.ROOT/'work/wave_v102/accounting.py')
CHECKS={}


def check(label: str, condition: bool) -> None:
    """
    機能: 独立した人工期待値と件数を記録する。
    引数: label(str)、condition(bool)は検査名と期待値。
    返り値: None。不一致をFalseのまま保持する。
    """
    assert condition,label;CHECKS[label]=CHECKS.get(label,0)+1


def fixture(symbol: str, side: int=1) -> tuple[dict,dict]:
    """
    機能: 入口・初期支持・次正常気配が明示された小人工を作る。
    引数: symbol(str)、side(int)は商品と方向。
    返り値: tuple[dict,dict]はpreparedと同原行normal入口。正式入力を読まない。
    """
    opening,tick=(4000.,.5) if symbol=='TOPIX' else (50000.,10.)
    n=1005;seq=np.arange(n,dtype=np.int64)+1000;times=np.arange(n,dtype=float)
    bid=np.full(n,opening);ask=bid+tick
    record=dict(symbol=symbol,session='人工',time_s=times,seq=seq,bid=bid,ask=ask,price=(bid+ask)/2,
        quote_valid=np.ones(n,bool),price_valid=np.ones(n,bool),tick=tick,start=0.,limit=1000.,end=1005.,人工素材=True)
    prepared=dict(record=record,reference_open=opening,signal={'trend_width':100*tick})
    case=dict(entry_id='C_OWN',event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),
        entry_quality=np.ones(n,bool),entry_reset=np.zeros(n,bool),execution_to_raw_index=np.arange(n,dtype=np.int64),decisions=[])
    event(prepared,case,330,side,opening if side==1 else opening+tick)
    return prepared,case


def event(prepared: dict, case: dict, row: int, side: int, support: float) -> None:
    """
    機能: 同一原行の候補根拠を人工素材へ追加する。
    引数: prepared/case(dict)、row/side(int)、support(float)。
    返り値: None。当時より後のanchorを作らない。
    """
    seq=int(prepared['record']['seq'][row]);case['event'][row]=side;case['support_price'][row]=support
    case['decisions'].append(dict(row=row,normal_row=row,raw_row=row,raw_seq=seq,side=side,support_price=support,
        selected_support_roots=[dict(family=case['entry_id'][0],anchor_raw_seq=seq-1,support_price=support)]))
    case['decisions'].sort(key=lambda d:d['row'])


def quote(prepared: dict, begin: int, bid: float) -> None:
    """
    機能: 人工の後続気配を同spreadへ置く。
    引数: prepared(dict)、begin(int)、bid(float)は開始行と価格。
    返り値: None。原seqと時計は変更しない。
    """
    r=prepared['record'];r['bid'][begin:]=bid;r['ask'][begin:]=bid+r['tick'];r['price'][begin:]=bid+r['tick']/2


def run_leg(prepared: dict, case: dict, quantity: int, finish: bool=True) -> dict:
    """
    機能: 不変106B4を人工だけへ実量接続する。
    引数: prepared/case(dict)、quantity(int)、finish(bool)。
    返り値: dictはPython本体の物理出力。
    """
    cfg=dict(catalog.catalog()[0],id='人工B4')
    return ENGINE.play(prepared,case,cfg,quantity=quantity,finish=finish,python=True)


def main() -> None:
    """
    機能: 目標、損失、両建て、未約定取消、数量料、接頭因果を人工検算する。
    引数: なし。
    返り値: None。全33の新金融は実行しない。
    """
    target=HERE/'複数親の場内停止と固定配分の人工検査.json';assert not target.exists()
    paths=[HERE/f for f in ('common.py','catalog.py','prepare.py','join.py','control.py','artificial.py')]
    start={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}
    for symbol in ('TOPIX','NK225'):
        cap,m=(10,1000.) if symbol=='TOPIX' else (20,10.)
        for allocation in ((cap//2,cap//2),(cap*4//5,cap//5)):
            for side in (1,-1):
                p,c=fixture(symbol,side);r=deepcopy(c);r['entry_id']='R_OWN'
                tick=p['record']['tick'];opening=p['reference_open']
                quote(p,340,opening+side*10*tick)
                quote(p,341,opening-side*2*tick)
                legs={'C':run_leg(p,c,allocation[0]),'R':run_leg(p,r,allocation[1])}
                baseline=join.join_portfolio_outputs(legs,allocation,symbol);baseline['initial_width']=legs['C']['initial_width']
                out=control.simulate(p['record'],baseline,cap*tick*m,None)
                check('二親は合算目標の最初row後の次quote返済',out['decision_row']==340 and out['fill_row']==341 and len(out['trades'])==2)
                check('次quote悪化で目標利益を保証しない',out['trades'][:,11].sum()<0)
                check('注文UIDと親namespaceの衝突なし',len(set(out['orders'][:,16]))==len(out['orders']) and len(set(out['trades'][:,0]))==2)
                OLD_ACCOUNTING.account(('人工',symbol),out)
                expected_curve,trace=control.economic_path(p['record'],out['orders'])
                np.testing.assert_allclose(expected_curve,out['curve'],atol=1e-5,rtol=0)
                check('現金・方向別枚数・注文料一致',True)
                check('同方向最大は総cap、最後flat',out['target_trace'][:,:4].max()==cap and not out['target_trace'][-1].any())
                check('腿ごとのfee floorを足す',out['orders'][:,9].sum()==2*sum(np.floor(q*(41.8 if symbol=='TOPIX' else 11)+1e-8) for q in allocation))
                check('TOP5枚片道209円',symbol!='TOPIX' or allocation!=(5,5) or np.all(out['orders'][:,9]==209))
                same=control.simulate(p['record'],baseline,None,None)
                for field in ('orders','trades','curve','target_trace'):np.testing.assert_array_equal(same[field],baseline[field])
                check('全目標offは無目標基準exact同値',True)
                # ----------------------------------------
                # 判断後の不正気配は約定せず、予約済全親はquality悪化でも取り消さない。
                bad=deepcopy(p);bad['record']['quote_valid'][341:344]=False
                c2=deepcopy(c);r2=deepcopy(r);c2['entry_quality'][340:]=False;r2['entry_quality'][340:]=False
                bs=join.join_portfolio_outputs({'C':run_leg(bad,c2,allocation[0]),'R':run_leg(bad,r2,allocation[1])},allocation,symbol)
                bs['initial_width']=baseline['initial_width'];blocked=control.simulate(bad['record'],bs,cap*tick*m,None)
                check('返済は不正quoteを越え次正常quote、入口資格悪化は無関係',blocked['decision_row']==340 and blocked['fill_row']==344)
                # ----------------------------------------
                # 保有中の接頭を直接再生し、完成結果の未来tradeを作らない。
                length=341;small=deepcopy(p);small['record']={k:v[:length].copy() if isinstance(v,np.ndarray) else v for k,v in p['record'].items()}
                cs={k:v[:length].copy() if isinstance(v,np.ndarray) else deepcopy(v) for k,v in c.items()}
                rs=dict(deepcopy(cs),entry_id='R_OWN')
                bs=join.join_portfolio_outputs({'C':run_leg(small,cs,allocation[0],False),'R':run_leg(small,rs,allocation[1],False)},allocation,symbol)
                bs['initial_width']=baseline['initial_width'];prefix=control.simulate(small['record'],bs,cap*tick*m,None,False)
                check('未返済接頭へ未来tradeなし',len(prefix['orders'])==2 and len(prefix['trades'])==0 and prefix['pending_liquidation'])
                np.testing.assert_allclose(prefix['curve'],out['curve'][:length],atol=1e-5,rtol=0)
                check('完成結果と保有接頭時価一致',True)
                future=deepcopy(p);quote(future,341,opening+side*1000*tick)
                altered=join.join_portfolio_outputs({'C':run_leg(future,c,allocation[0]),'R':run_leg(future,r,allocation[1])},allocation,symbol)
                alt=control.simulate(future['record'],altered,cap*tick*m,None)
                check('未来変更でも当時判断不変',alt['decision_row']==out['decision_row'])
                np.testing.assert_array_equal(alt['orders'][alt['orders'][:,0]<=340],out['orders'][out['orders'][:,0]<=340])
                # ----------------------------------------
                # C買/R売又は逆は相殺せず両建てfeeとspreadを全て負担する。
                hedged,cc=fixture(symbol,side);rr=deepcopy(cc);rr['entry_id']='R_OWN';rr['event']*=-1
                for d in rr['decisions']:
                    d['side']*=-1;d['support_price']=opening+(tick if -side==-1 else 0);d['selected_support_roots'][0]['support_price']=d['support_price']
                rr['support_price'][330]=rr['decisions'][0]['support_price']
                hedge=join.join_portfolio_outputs({'C':run_leg(hedged,cc,allocation[0]),'R':run_leg(hedged,rr,allocation[1])},allocation,symbol)
                hcurve,_=control.economic_path(hedged['record'],hedge['orders']);np.testing.assert_allclose(hcurve,hedge['curve'],atol=1e-4,rtol=0)
                stopped=control.simulate(hedged['record'],hedge,None,1.)
                check('両建て物理保有をnet相殺しない',np.any((hedge['target_trace'][:,0]>0)&(hedge['target_trace'][:,1]>0)) and len(stopped['trades'])==2)
                OLD_ACCOUNTING.account(('人工',symbol),stopped)
    # ----------------------------------------
    # 片方未約定のまま他方目標到達: 後の新規fillを取り除く。
    p,c=fixture('TOPIX');r=deepcopy(c);r['entry_id']='R_OWN';r['event'][:]=0;r['support_price'][:]=np.nan;r['decisions']=[]
    quote(p,340,4005.);event(p,r,340,1,4005.)
    legs={'C':run_leg(p,c,5),'R':run_leg(p,r,5)}
    bs=join.join_portfolio_outputs(legs,(5,5),'TOPIX');bs['initial_width']=legs['C']['initial_width']
    stopped=control.simulate(p['record'],bs,5000.,None)
    check('停止判断rowの未約定新規取消',stopped['cancelled_pending_entry']==5 and len(stopped['trades'])==1 and len(stopped['orders'])==2)
    OLD_ACCOUNTING.account(('人工','TOPIX'),stopped)
    # ----------------------------------------
    # 入力接続は記録・C入口の不一致を救済しない。
    old=dict(schema_version=1,session='人工',normal={s:{'record':p['record']} for s in ('TOPIX','NK225')},cases={})
    current=dict(schema_version=1,session='人工',prepared={s:p for s in ('TOPIX','NK225')},cases={})
    for e in ('C_OWN','C_N30','R_OWN'):
        value=dict(deepcopy(c),entry_id=e)
        old['cases'][e]={s:{'normal':value} for s in ('TOPIX','NK225')}
        if e!='R_OWN':current['cases'][e]={s:value for s in ('TOPIX','NK225')}
    prepare.connect(old,current);check('3入口と全正常原行の人工接続',True)
    bad=deepcopy(old);bad['normal']['TOPIX']['record']['seq'][2]+=1
    try:prepare.connect(bad,current)
    except AssertionError:check('正常原seq不一致を0や未来で救済しない',True)
    else:raise AssertionError('不一致を受理')
    check('39条件数と固定実量配分',len(catalog.catalog())==39)
    assert start=={p:common.digest(common.ROOT/p) for p in start}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=CHECKS,source_SHA256=start,
        開始終端source一致=True,新正式金融再生=0,正式input読取=0,原板読取=0,API取得=0))
    print(json.dumps({'全合格':True,'検査件数':CHECKS},ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        folder=HERE/('人工False_'+time.strftime('%Y%m%d_%H%M%S'));folder.mkdir()
        for name in ('artificial.py','control.py','join.py','prepare.py','common.py','catalog.py'):
            (folder/name).write_bytes((HERE/name).read_bytes())
        common.save(folder/'False.json',dict(全合格=False,例外=str(error),traceback=traceback.format_exc(),完了検査=CHECKS,新正式金融再生=0))
        raise
