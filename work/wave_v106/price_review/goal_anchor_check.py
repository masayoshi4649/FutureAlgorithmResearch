"""最初の受理数量アンカーを独立人工と当時接頭で監査する。"""

from pathlib import Path
import hashlib
import json
import os
import sys

import numpy as np
import numba

from risk_sizing_oracle import fee, LOSS, VALUE


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_size_goal_anchor'
OLD=ROOT/'work/wave_v106/e01_risk_sizing'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE))
import common
os.environ['NUMBA_CACHE_DIR']=str(HERE/'goal_anchor_jit')
numba.config.CACHE_DIR=str(HERE/'goal_anchor_jit')
import catalog
import daily
import interface
import goal_policy
import fixed_goal_interface


def digest(path: Path) -> str:
    """
    機能: 小sourceと自所有小証跡の指紋を取得する。
    引数: path(Path)は小資料の位置。
    返り値: strはSHA256。正式結果・packet・ledgerは読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(symbol: str, side: int=1) -> dict:
    """
    機能: 三つの紙上親と異なる当時ATRを持つ人工だけを作る。
    引数: symbol(str)、side(int)は商品と方向。
    返り値: dictはq1からq2・q3へ変わる人工口座。市場資料を使わない。
    """
    n=20; full=catalog.QUANTITY[symbol]; tick=.5 if symbol=='TOPIX' else 10.
    b=100. if symbol=='TOPIX' else 1000.; bid=np.full(n,b); ask=bid+tick
    atrs=(3.,1.,.4) if symbol=='TOPIX' else (130.,70.,40.)
    rows=[]; bases={}
    for cid,(entry,exit,atr) in enumerate(zip((1,6,12),(3,10,16),atrs)):
        rows.extend([[entry,0,cid,side,full,b+tick/2,0,1,0,atr],[exit,0,cid,-side,full,b+tick/2,0,0,0,0]])
        bases[entry]=dict(known=True,reason=0,direction_votes=2,balance=1.)
    times=np.arange(n,dtype=float); seq=np.arange(900,900+n,dtype=np.int64)
    return dict(symbol=symbol,record=dict(time_s=times,seq=seq,price=(bid+ask)/2,tick=tick,limit=18.),
        quotes=dict(time_s=times,seq=seq,bid=bid,ask=ask,quote_valid=np.ones(n,bool)),feed=np.array(rows,float),
        quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),trade_features={'60':bases},paper_SHA256='独立人工')


def clone(a: dict) -> dict:
    """
    機能: 人工の配列と票を深い一段で複写し、反例変更を元へ混ぜない。
    引数: a(dict)は人工口座。
    返り値: dictは独立した人工。元データを編集しない。
    """
    return dict(a,record={k:v.copy() if isinstance(v,np.ndarray) else v for k,v in a['record'].items()},
        quotes={k:v.copy() for k,v in a['quotes'].items()},feed=a['feed'].copy(),quiet=a['quiet'].copy(),quiet_force=a['quiet_force'].copy(),
        trade_features={'60':{k:dict(v) for k,v in a['trade_features']['60'].items()}})


def prefix(a: dict, cut: int) -> dict:
    """
    機能: 受理前も含む当時行だけで人工口座を切る。
    引数: a(dict)、cut(int)は人工と排他的終点。
    返り値: dictは接頭。未返済を場末という理由で清算しない。
    """
    value=clone(a)
    for group in ('record','quotes'):
        value[group]={k:v[:cut] if isinstance(v,np.ndarray) else v for k,v in value[group].items()}
    value['feed']=value['feed'][value['feed'][:,0]<cut]; value['quiet']=value['quiet'][:cut]; value['quiet_force']=value['quiet_force'][:cut]
    value['record']['limit']=1000.; return value


def expected_anchor(a: dict, config: dict, values: tuple) -> dict:
    """
    機能: 元イベント順の最初の受理だけを整数金額から独立計算する。
    引数: a/config(dict)、values(tuple)は人工とengine出力。
    返り値: dictは成立・行・数量・円目標。実約定を選択基準へ変えない。
    """
    events=[e for e in values[9] if e[15]==1]
    if not events: return dict(成立=False,数量=None,利益目標円=None,受理行=None)
    first=events[0]; q=int(first[4]); unit=500 if a['symbol']=='TOPIX' else 100
    return dict(成立=True,数量=q,利益目標円=config['profit_ticks']*unit*q,受理行=int(first[0]))


def stream_stop(a: dict, config: dict, values: tuple, target: float|None) -> dict:
    """
    機能: 実注文接頭の支払・UID・当時清算から先着停止と次気配返済を独立求める。
    引数: a/config(dict)、values(tuple)、target(float|None)は人工と事前固定目標。
    返り値: dictは期待注文と停止情報。daily又は過去金融結果を使わない。
    """
    orders,uids=values[0],values[5]; symbol=a['symbol']; q=a['quotes']; cursor=0; held={}; cash=0.; paid=0
    if target is None:
        assert len(orders)==0
        return dict(orders=orders.copy(),uids=uids.copy(),targets=np.full(len(uids),-1,np.int64),発動=False)
    for row in range(len(q['bid'])):
        while cursor<len(orders) and orders[cursor,0]==row:
            order=orders[cursor]; side,quantity,new=map(int,(order[3],order[4],order[7])); cash-=side*quantity*order[5]; paid+=fee(quantity,symbol)
            if new: held[int(uids[cursor])]=dict(cid=int(order[2]),side=side,quantity=quantity)
            else:
                need=quantity
                for state in held.values():
                    if state['cid']==order[2] and state['side']==-side:
                        closed=min(need,state['quantity']); state['quantity']-=closed; need-=closed
                assert need==0
            cursor+=1
        if not (q['quote_valid'][row] and 0<q['bid'][row]<q['ask'][row]): continue
        mark=cash+sum(s['side']*s['quantity']*(q['bid'][row] if s['side']==1 else q['ask'][row]) for s in held.values())
        liquid=mark*VALUE[symbol]-paid-sum(fee(s['quantity'],symbol) for s in held.values() if s['quantity'])
        if liquid<target and liquid>-LOSS[symbol]: continue
        profit=liquid>=target; remaining={uid:s for uid,s in held.items() if s['quantity']}; fill=row
        expected=orders[:cursor].tolist(); expected_uids=uids[:cursor].tolist(); targets=[-1]*cursor
        if remaining:
            fill=next(i for i in range(row+1,len(q['bid'])) if q['quote_valid'][i] and 0<q['bid'][i]<q['ask'][i])
            for uid,state in remaining.items():
                side=-state['side']; price=q['ask'][fill] if side==1 else q['bid'][fill]
                expected.append([fill,row,state['cid'],side,state['quantity'],price,94 if profit else 95,0]); expected_uids.append(-1); targets.append(uid)
        return dict(orders=np.array(expected,float),uids=np.array(expected_uids,np.int64),targets=np.array(targets,np.int64),
            発動=True,判断行=row,返済行=fill,種別='利益目標' if profit else '損失予算')
    return dict(orders=orders.copy(),uids=uids.copy(),targets=np.full(len(uids),-1,np.int64),発動=False)


def check(a: dict, config: dict) -> tuple:
    """
    機能: 人工のアンカーと停止を独立基準へ照合する。
    引数: a/config(dict)は人工口座と固定条件。
    返り値: tupleはengine配列と実政策。正式金融を運転しない。
    """
    values=interface.execute(a,config,python=True); expected=expected_anchor(a,config,values)
    anchor=goal_policy.observe_anchor(a,config,values)
    for k,v in expected.items(): assert anchor[k]==v
    output=interface.account_output('人工',a,config,values); target=expected['利益目標円']
    assert output['goal_anchor']==anchor and output['control']['目標']==target and output['control']['損失予算']==LOSS[a['symbol']]
    stop=stream_stop(a,config,values,target)
    for field,key in (('orders','orders'),('order_uids','uids'),('exit_target_uids','targets')): np.testing.assert_array_equal(output[field],stop[key])
    assert output['control']['発動']==stop['発動']
    if stop['発動']:
        assert output['control']['判断行']==stop['判断行'] and output['control']['返済行']==stop['返済行'] and output['control']['種別']==stop['種別']
        assert stop['判断行']>=anchor['受理行']
    assert output['summary']['費用']==sum(fee(int(o[4]),a['symbol']) for o in output['orders'])
    assert output['long_qty'][-1]==output['short_qty'][-1]==0
    return values,output


def main() -> None:
    """
    機能: 最初受理・取消・拒否・全量旧同値・当時接頭・先着停止の独立人工を固定する。
    引数: なし。源範囲を先に束縛し、正式結果・packet・ledger・APIは読まない。
    返り値: Noneは自所有の独立証跡。不合格時はFalseを保持する。
    """
    names=('goal_policy.py','interface.py','catalog.py','engine.py','daily.py','order_kernel.py','policy.py','fixed_goal_interface.py','common.py')
    sources={str((SOURCE/n).relative_to(ROOT)).replace('\\','/'):digest(SOURCE/n) for n in names}
    scope=HERE/'goal_anchor_独立人工の源範囲事前固定.json'; target=HERE/'goal_anchor_最初受理と取消保持及び接頭停止の独立人工.json'
    assert not scope.exists() and not target.exists()
    scope.write_text(json.dumps(dict(source_SHA256=sources,正式結果=0,packet=0,ledger=0,API=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        clones={}
        for new,old in (('engine.py','engine.py'),('daily.py','daily.py'),('order_kernel.py','order_kernel.py'),('policy.py','policy.py'),('common.py','common.py'),('fixed_goal_interface.py','interface.py')):
            assert (SOURCE/new).read_bytes()==(OLD/old).read_bytes(); clones[new]=digest(OLD/old)
        rows=[]; cases=0; arrays=0; truths=0
        for config in catalog.configs():
            for symbol in ('TOPIX','NK225'):
                for side in (1,-1):
                    a=fixture(symbol,side); values,out=check(a,config); cases+=1
                    assert list(values[9][:,4])==[1,2,3] and out['goal_anchor']['数量']==1
                    assert out['control']['目標']==(500 if symbol=='TOPIX' else 100)*config['profit_ticks']
                    # 受理q1は将来未約定で取消されても固定。最初の実約定q2へ選び直さない。
                    cancel=clone(a); cancel['quiet'][2:5]=True
                    if symbol=='TOPIX': cancel['feed'][2,9]=1.5
                    v,result=check(cancel,config); cases+=1
                    assert v[9][0,15]==1 and result['goal_anchor']['数量']==1 and v[0][0,4]==2 and v[0][0,2]==1
                    rows.append(dict(id=config['id'],商品=symbol,方向=side,種類='受理後取消',アンカーq=1,初実約定q=2,目標=result['control']['目標']))
                    # q0、公開quote未知、母拒否、静観拒否は初回受理q2を選ぶ。
                    for label in ('q0','quote未知','母拒否','静観拒否'):
                        rejected=clone(a)
                        if symbol=='TOPIX': rejected['feed'][2,9]=1.5
                        if label=='q0': rejected['feed'][0,9]=10000.
                        elif label=='quote未知': rejected['quotes']['quote_valid'][1]=False
                        elif label=='母拒否': rejected['trade_features']['60'][1]['balance']=-1.
                        else: rejected['quiet'][1:5]=True
                        v,result=check(rejected,config); cases+=1
                        assert v[9][0,15]==0 and result['goal_anchor']['受理行']==6 and result['goal_anchor']['数量']==2
                    busy=clone(a); busy['feed'][1,0]=6
                    if symbol=='TOPIX': busy['feed'][2,9]=1.5
                    v,result=check(busy,config); cases+=1
                    assert v[9][1,4]>0 and v[9][1,15]==0 and result['goal_anchor']['数量']==1
                    # 全量アンカーなら新旧固定円の実政策は全配列・親・UID・料金で同値。
                    full=clone(a); full['feed'][0,9]=.01; v,result=check(full,config); cases+=1
                    assert result['goal_anchor']['数量']==catalog.QUANTITY[symbol]
                    prior=fixed_goal_interface.account_output('人工',full,config,v)
                    for field in ('orders','order_uids','exit_target_uids','order_fees','equity_yen','liquidation_yen','reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
                        np.testing.assert_array_equal(result[field],prior[field]); arrays+=1
                    for field in ('summary','parent','uid_accounts','actual_legs','actual_leg_totals','control'): assert result[field]==prior[field]
                    # 非受理は目標None。条件付き停止を0円目標として発動させない。
                    none=clone(a)
                    for base in none['trade_features']['60'].values(): base['balance']=-1.
                    v,result=check(none,config); cases+=1
                    assert not result['goal_anchor']['成立'] and result['control']['目標'] is None and not result['control']['発動'] and result['summary']['利益割合'] is None
                    expiry=clone(a); expiry['record']['limit']=1.; v,result=check(expiry,config); cases+=1
                    assert not result['goal_anchor']['成立'] and len(v[0])==0
                    # 先着利益は独立q1の金額。P1は行3、P2は行4で初到達する。
                    rise=clone(a); move=np.zeros(20); move[3]=side*(1.5 if symbol=='TOPIX' else 30.); move[4:]=side*(2. if symbol=='TOPIX' else 40.)
                    rise['quotes']['bid']+=move; rise['quotes']['ask']+=move; rise['record']['price']+=move
                    _,result=check(rise,config); cases+=1
                    assert result['control']['判断行']==(3 if config['profit_ticks']==1 else 4)
                    # 後続q・気配・票は既受理アンカーと既観測接頭を変更しない。
                    for cut in (1,2,3,6,8,12,17):
                        short=interface.execute(prefix(a,cut),config,python=True); anchor=goal_policy.observe_anchor(prefix(a,cut),config,short)
                        for index in (2,7,10): np.testing.assert_array_equal(short[index],values[index][:cut]); arrays+=1
                        np.testing.assert_array_equal(short[0],values[0][values[0][:,0]<cut]); arrays+=1
                        np.testing.assert_array_equal(short[9],values[9][values[9][:,0]<cut]); arrays+=1
                        if cut>1: assert anchor==out['goal_anchor']
                        else: assert not anchor['成立']
                        altered=clone(a); altered['quotes']['bid'][cut:]+=100.; altered['quotes']['ask'][cut:]+=100.
                        altered['record']['price'][cut:]+=100.
                        for base_row,base in altered['trade_features']['60'].items():
                            if base_row>=cut: base['balance']=-1.
                        future=interface.execute(prefix(altered,cut),config,python=True)
                        for observed,expected in zip(short,future): np.testing.assert_array_equal(observed,expected); arrays+=1
                    # source時計とqの独立真偽表は実fill無しで全受理組合せを確認する。
                    for first in (0,1):
                        for q1 in range(1,catalog.QUANTITY[symbol]+1):
                            for q2 in range(1,catalog.QUANTITY[symbol]+1):
                                events=np.zeros((2,16)); events[:,0]=(1,6); events[:,1]=(0,1); events[:,3]=catalog.QUANTITY[symbol]
                                events[:,4]=(q1,q2); events[:,14]=1; events[:,15]=(first,1)
                                synthetic=list(values); synthetic[0]=np.empty((0,8)); synthetic[9]=events
                                got=goal_policy.observe_anchor(a,config,tuple(synthetic)); expected_q=q1 if first else q2
                                assert got['数量']==expected_q and got['受理行']==(1 if first else 6)
                                assert got['利益目標円']==expected_q*(500 if symbol=='TOPIX' else 100)*config['profit_ticks']; truths+=1
        assert sources=={str((SOURCE/n).relative_to(ROOT)).replace('\\','/'):digest(SOURCE/n) for n in names}
        proof=dict(全合格=True,source_SHA256=sources,独立source_SHA256=digest(Path(__file__)),源範囲SHA256=digest(scope),
            同bytes複写=clones,人工条件数=cases,配列照合数=arrays,二受理真偽表数=truths,取消保持=rows,
            定義='最初actual_pending1の公開受理qに比例した目標を固定。最初の実約定qではない。',
            留保=['この比例変更は黒字平均も下げ得る。L2不変なので平均黒字補填を保証しない。',
                  '価格時計/原seqは元engineの契約で、受信時刻を新設していない。',
                  '政策会計は完結GUの当時停止へ写す。接頭の未返済を場末として清算しない。'],
            正式結果読取=0,packet=0,ledger=0,API=0,原板=0,NPZ=0,金融=0,旧source及び旧JIT変更=0)
        target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,条件=cases,配列=arrays,真偽表=truths,SHA256=digest(target)),ensure_ascii=False))
    except BaseException:
        import traceback
        failure=HERE/'goal_anchor_独立人工False.json'; assert not failure.exists()
        failure.write_text(json.dumps(dict(全合格=False,source_SHA256=sources,原因=traceback.format_exc(),正式結果=0,packet=0,ledger=0,API=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__': main()
