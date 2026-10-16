"""初回受理数量の損失線だけを独立人工・当時接頭・保存GU復元で確認する。"""

from pathlib import Path
import copy
import hashlib
import json
import os
import sys

import numpy as np
import numba

from risk_sizing_oracle import fee, LOSS, VALUE


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_size_loss_anchor'
OLD=ROOT/'work/wave_v106/e01_size_goal_anchor'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE))
import common
os.environ['NUMBA_CACHE_DIR']=str(HERE/'loss_anchor_jit')
numba.config.CACHE_DIR=str(HERE/'loss_anchor_jit')
import catalog
import daily
import interface
import goal_policy
import fixed_loss_policy
import fixed_goal_interface
import reuse
import storage


def digest(path: Path) -> str:
    """
    機能: 小source又は自所有証跡だけの指紋を取得する。
    引数: path(Path)は小資料の位置。
    返り値: strはSHA256。正式結果・packet・ledgerを読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(symbol: str, side: int=1) -> dict:
    """
    機能: 三紙上親の当時ATRを変え、実qが1・2・3へ変わる人工を作る。
    引数: symbol(str)、side(int)は商品と方向。
    返り値: dictは人工口座。実市場の保存資料を使わない。
    """
    n=20;full=catalog.QUANTITY[symbol];tick=.5 if symbol=='TOPIX' else 10.
    bid=np.full(n,100. if symbol=='TOPIX' else 1000.);ask=bid+tick
    atrs=(3.,1.,.4) if symbol=='TOPIX' else (130.,70.,40.)
    feed=[];bases={}
    for cid,(entry,end,atr) in enumerate(zip((1,6,12),(3,10,16),atrs)):
        feed.extend([[entry,0,cid,side,full,bid[entry]+tick/2,0,1,0,atr],
                     [end,0,cid,-side,full,bid[end]+tick/2,0,0,0,0]])
        bases[entry]=dict(known=True,reason=0,direction_votes=2,balance=1.)
    clock=np.arange(n,dtype=float);seq=np.arange(900,900+n,dtype=np.int64)
    return dict(symbol=symbol,record=dict(time_s=clock,seq=seq,price=(bid+ask)/2,tick=tick,limit=18.),
        quotes=dict(time_s=clock,seq=seq,bid=bid,ask=ask,quote_valid=np.ones(n,bool)),
        feed=np.asarray(feed,float),quiet=np.zeros(n,bool),quiet_force=np.zeros(n,bool),
        trade_features={'60':bases},paper_SHA256='独立人工')


def clone(account: dict) -> dict:
    """
    機能: 人工の気配・注文・票を複写して反例変更を元へ混ぜない。
    引数: account(dict)は人工口座。
    返り値: dictは変更可能な独立人工。実資料を編集しない。
    """
    return copy.deepcopy(account)


def prefix(account: dict, cut: int) -> dict:
    """
    機能: 未来期限を保ったまま、当時までの配列だけへ人工口座を切る。
    引数: account(dict)、cut(int)は人工と排他的終点。
    返り値: dictは接頭。未返済を短縮した場末として清算しない。
    """
    result=clone(account)
    for group in ('record','quotes'):
        result[group]={k:v[:cut] if isinstance(v,np.ndarray) else v for k,v in result[group].items()}
    result['feed']=result['feed'][result['feed'][:,0]<cut]
    result['quiet']=result['quiet'][:cut];result['quiet_force']=result['quiet_force'][:cut]
    result['record']['limit']=1000.
    return result


def expected_anchor(account: dict, config: dict, values: tuple) -> dict:
    """
    機能: イベント順の最初の受理qから、利益と損失の円線を整数で独立算出する。
    引数: account/config(dict)、values(tuple)は人工と11配列。
    返り値: dictは数量・受理行・両停止線。最初の実fillを選択基準へ変えない。
    """
    accepted=[e for e in values[9] if e[15]==1]
    if not accepted:return dict(成立=False,数量=None,受理行=None,利益目標円=None,損失停止線円=None)
    event=accepted[0];q=int(event[4]);profit_unit=500 if account['symbol']=='TOPIX' else 100
    loss_unit=1000 if account['symbol']=='TOPIX' else 200
    return dict(成立=True,数量=q,受理行=int(event[0]),利益目標円=profit_unit*config['profit_ticks']*q,
        損失停止線円=loss_unit*q)


def stream_stop(account: dict, values: tuple, profit: float|None, loss: float|None) -> dict:
    """
    機能: 実注文接頭の現金・UID・実料から先着停止と次正常気配の返済を独立計算する。
    引数: account(dict)、values(tuple)、profit/loss(float|None)は人工と事前線。
    返り値: dictは期待注文・UID・停止情報。daily停止処理又は正式損益を使わない。
    """
    orders,uids=values[0],values[5];symbol=account['symbol'];quotes=account['quotes']
    cash=0.;paid=0;held={};cursor=0
    if profit is None:
        assert loss is None and len(orders)==0
        return dict(orders=orders.copy(),uids=uids.copy(),targets=np.full(len(uids),-1,np.int64),発動=False)
    for row in range(len(quotes['bid'])):
        while cursor<len(orders) and int(orders[cursor,0])==row:
            order=orders[cursor];side,quantity,new=map(int,(order[3],order[4],order[7]))
            cash-=side*quantity*order[5];paid+=fee(quantity,symbol)
            if new:held[int(uids[cursor])]=dict(cid=int(order[2]),side=side,quantity=quantity)
            else:
                need=quantity
                for state in held.values():
                    if state['cid']==order[2] and state['side']==-side:
                        closed=min(need,state['quantity']);state['quantity']-=closed;need-=closed
                assert need==0
            cursor+=1
        if not (quotes['quote_valid'][row] and 0<quotes['bid'][row]<quotes['ask'][row]):continue
        mark=cash+sum(s['side']*s['quantity']*(quotes['bid'][row] if s['side']==1 else quotes['ask'][row]) for s in held.values())
        liquid=mark*VALUE[symbol]-paid-sum(fee(s['quantity'],symbol) for s in held.values() if s['quantity'])
        if liquid<profit and liquid>-loss:continue
        is_profit=liquid>=profit;remaining={uid:s for uid,s in held.items() if s['quantity']};fill=row
        expected=orders[:cursor].tolist();expected_uids=uids[:cursor].tolist();targets=[-1]*cursor
        if remaining:
            fill=next(i for i in range(row+1,len(quotes['bid'])) if quotes['quote_valid'][i] and 0<quotes['bid'][i]<quotes['ask'][i])
            for uid,state in remaining.items():
                side=-state['side'];price=quotes['ask'][fill] if side==1 else quotes['bid'][fill]
                expected.append([fill,row,state['cid'],side,state['quantity'],price,94 if is_profit else 95,0])
                expected_uids.append(-1);targets.append(uid)
        return dict(orders=np.asarray(expected,float),uids=np.asarray(expected_uids,np.int64),targets=np.asarray(targets,np.int64),
            発動=True,判断行=row,返済行=fill,種別='利益目標' if is_profit else '損失予算',判断清算円=liquid)
    return dict(orders=orders.copy(),uids=uids.copy(),targets=np.full(len(uids),-1,np.int64),発動=False)


def check(account: dict, config: dict) -> tuple:
    """
    機能: 独立の整数停止線・実料接頭計算へ新政策を照合する。
    引数: account/config(dict)は人工口座と固定条件。
    返り値: tupleは11GU配列と新政策。不変GUは人工に限って運転する。
    """
    values=interface.execute(account,config,python=True);expected=expected_anchor(account,config,values)
    anchor=goal_policy.observe_anchor(account,config,values)
    for field in ('成立','数量','受理行','利益目標円'):assert anchor[field]==expected[field]
    output=interface.account_output('人工',account,config,values)
    assert output['goal_anchor']==anchor and output['control']['目標']==expected['利益目標円']
    assert output['control']['損失予算']==expected['損失停止線円']
    assert output['loss_anchor']['新規数量選択予算円']==LOSS[account['symbol']]
    assert output['loss_anchor']['比例損失停止線円']==expected['損失停止線円']
    stop=stream_stop(account,values,expected['利益目標円'],expected['損失停止線円'])
    for field,key in (('orders','orders'),('order_uids','uids'),('exit_target_uids','targets')):
        np.testing.assert_array_equal(output[field],stop[key])
    assert output['control']['発動']==stop['発動']
    if stop['発動']:
        for field in ('判断行','返済行','種別'):assert output['control'][field]==stop[field]
        assert stop['判断行']>=anchor['受理行']
    assert output['summary']['費用']==sum(fee(int(o[4]),account['symbol']) for o in output['orders'])
    assert output['long_qty'][-1]==output['short_qty'][-1]==0
    return values,output


def old_output(account: dict, config: dict, values: tuple) -> dict:
    """
    機能: 自所有同bytes旧goal部品で、損失固定の人工対照だけを求める。
    引数: account/config(dict)、values(tuple)は人工と共通GU。
    返り値: dictは旧停止線の人工会計。旧金融又は旧moduleを運転しない。
    """
    base=daily.reconstruct(('人工',account['symbol']),values[0],values[5],account['quotes'])
    anchor=fixed_loss_policy.observe_anchor(account,config,values)
    return fixed_loss_policy.apply(base,account['quotes'],config,anchor)


def shift(account: dict, start: int, side: int, distance: float) -> None:
    """
    機能: 人工気配の指定行以後を指定方向へ平行移動する。
    引数: account(dict)、start/side(int)、distance(float)は人工と移動量。
    返り値: Noneは人工気配と参考価格の変更。原板には触れない。
    """
    for field in ('bid','ask'):account['quotes'][field][start:]+=side*distance
    account['record']['price'][start:]+=side*distance


# ----------------------------------------
def main() -> None:
    """
    機能: 初回固定・取消・即切り・次気配超過・回復勝ち喪失・保存GU復元を敵対監査する。
    引数: なし。正式結果・packet・ledger・APIの読取は行わない。
    返り値: Noneは自所有人工証跡。不合格はFalseを残し、源の修正を行わない。
    """
    names=('goal_policy.py','interface.py','catalog.py','engine.py','daily.py','order_kernel.py','policy.py',
           'fixed_goal_interface.py','fixed_loss_policy.py','common.py','reuse.py','storage.py')
    sources={str((SOURCE/n).relative_to(ROOT)).replace('\\','/'):digest(SOURCE/n) for n in names}
    scope=HERE/'loss_anchor_独立人工の源範囲事前固定_v2.json'
    target=HERE/'loss_anchor_比例停止と取消保持及び保存GU復元の独立人工_v2.json'
    assert not scope.exists() and not target.exists()
    scope.write_text(json.dumps(dict(source_SHA256=sources,正式結果=0,packet=0,ledger=0,API=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        clones={}
        for new,old in (('engine.py','engine.py'),('daily.py','daily.py'),('order_kernel.py','order_kernel.py'),
                        ('policy.py','policy.py'),('common.py','common.py'),('storage.py','storage.py'),
                        ('fixed_goal_interface.py','fixed_goal_interface.py'),('fixed_loss_policy.py','goal_policy.py')):
            assert (SOURCE/new).read_bytes()==(OLD/old).read_bytes();clones[new]=digest(OLD/old)
        cases=0;arrays=0;truths=0;counterexamples=[];reuse_tests=[]
        for config in catalog.configs():
            for symbol in ('TOPIX','NK225'):
                for side in (1,-1):
                    account=fixture(symbol,side);values,out=check(account,config);cases+=1
                    assert list(values[9][:,4])==[1,2,3] and out['goal_anchor']['数量']==1
                    stop=1000 if symbol=='TOPIX' else 200;tick=.5 if symbol=='TOPIX' else 10.
                    native=interface.execute(account,config)
                    for actual,expected in zip(native,values):np.testing.assert_array_equal(actual,expected);arrays+=1
                    # 受理取消後の実q2でも、受理q1の線を保持。初期spreadと実料だけで即切り得る。
                    canceled=clone(account);canceled['quiet'][2:5]=True
                    if symbol=='TOPIX':canceled['feed'][2,9]=1.5
                    v,result=check(canceled,config);cases+=1
                    assert result['goal_anchor']['数量']==1 and v[0][0,4]==2 and v[0][0,2]==1
                    assert result['control']['損失予算']==stop and result['control']['判断行']==7
                    assert result['control']['種別']=='損失予算' and result['summary']['収支']<0
                    counterexamples.append(dict(id=config['id'],商品=symbol,方向=side,種類='受理q1取消後実q2のspread実料即切り',
                        初回受理q=1,初回実q=2,停止線円=stop,判断行=7,収支=result['summary']['収支']))
                    # 公開q0/不明/母拒否/静観拒否はアンカーにせず、次の初受理を選ぶ。
                    for label in ('q0','不明','母拒否','静観'):
                        rejected=clone(account)
                        if symbol=='TOPIX':rejected['feed'][2,9]=1.5
                        if label=='q0':rejected['feed'][0,9]=10000.
                        elif label=='不明':rejected['quotes']['quote_valid'][1]=False
                        elif label=='母拒否':rejected['trade_features']['60'][1]['balance']=-1.
                        else:rejected['quiet'][1:5]=True
                        v,result=check(rejected,config);cases+=1
                        assert v[9][0,15]==0 and result['goal_anchor']['受理行']==6 and result['goal_anchor']['数量']==2
                        assert result['control']['損失予算']==2*stop
                    busy=clone(account);busy['feed'][1,0]=6
                    if symbol=='TOPIX':busy['feed'][2,9]=1.5
                    v,result=check(busy,config);cases+=1
                    assert v[9][1,4]>0 and v[9][1,15]==0 and result['goal_anchor']['数量']==1
                    none=clone(account)
                    for base in none['trade_features']['60'].values():base['balance']=-1.
                    v,result=check(none,config);cases+=1
                    assert not result['goal_anchor']['成立'] and result['control']['目標'] is None
                    assert result['control']['損失予算'] is None and not result['control']['発動']
                    assert result['summary']['利益割合'] is None
                    for deadline in (1.,2.):
                        expiry=clone(account);expiry['record']['limit']=deadline;v,result=check(expiry,config);cases+=1
                        assert len(v[0])==0 and result['goal_anchor']['成立']==(deadline==2.)
                        assert result['control']['損失予算']==(stop if deadline==2. else None)
                    # 初回全量では新旧goal政策は実注文・UID・全曲線exact。
                    full=clone(account);full['feed'][0,9]=.01;v,result=check(full,config);cases+=1
                    prior=old_output(full,config,v);assert result['goal_anchor']['数量']==catalog.QUANTITY[symbol]
                    for field in ('orders','order_uids','exit_target_uids','order_fees','equity_yen','liquidation_yen',
                                  'reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
                        np.testing.assert_array_equal(result[field],prior[field]);arrays+=1
                    for field in ('summary','parent','uid_accounts','actual_legs','control'):assert result[field]==prior[field]
                    # 新規fill時に通常の2tick気配差だけで比例線へ到達。後のgapで実損失が線を超える。
                    instant=clone(account)
                    if side==1:instant['quotes']['ask'][2]=instant['quotes']['bid'][2]+2*tick
                    else:instant['quotes']['bid'][2]=instant['quotes']['ask'][2]-2*tick
                    shift(instant,3,-side,4*tick)
                    v,result=check(instant,config);cases+=1
                    assert result['control']['判断行']==2 and result['control']['返済行']==3
                    assert -result['summary']['収支']>stop
                    counterexamples.append(dict(id=config['id'],商品=symbol,方向=side,種類='初期spread実料の即切りと次気配超過',
                        判断行=2,返済行=3,停止線円=stop,収支=result['summary']['収支']))
                    # 比例線を切ってから回復。紙上返済を後へ置き、旧固定L2の真の回復勝ちと比較。
                    recovery=clone(account);recovery['feed']=recovery['feed'][:2].copy();recovery['feed'][1,0]=10
                    recovery['trade_features']['60']={1:recovery['trade_features']['60'][1]}
                    shift(recovery,3,-side,tick);shift(recovery,5,side,5*tick if symbol=='TOPIX' else 7*tick)
                    v,result=check(recovery,config);cases+=1;prior=old_output(recovery,config,v)
                    assert result['control']['判断行']==3 and result['control']['返済行']==4
                    assert prior['control']['種別']=='利益目標' and prior['control']['判断行']==5
                    assert result['summary']['収支']<0<prior['summary']['収支']
                    counterexamples.append(dict(id=config['id'],商品=symbol,方向=side,種類='旧回復勝ちを先に損切り',
                        新収支=result['summary']['収支'],旧収支=prior['summary']['収支'],新判断行=3,旧判断行=5))
                    # 将来のq・票・気配は初回固定と観測済み接頭を変更しない。
                    for cut in (1,2,3,6,8,12,17):
                        past=prefix(account,cut);short=interface.execute(past,config,python=True)
                        anchor=goal_policy.observe_anchor(past,config,short)
                        if cut<=1:assert not anchor['成立']
                        else:assert anchor==out['goal_anchor']
                        for index in (2,7,10):np.testing.assert_array_equal(short[index],values[index][:cut]);arrays+=1
                        for index in (0,9):np.testing.assert_array_equal(short[index],values[index][values[index][:,0]<cut]);arrays+=1
                        changed=clone(account);shift(changed,cut,side,100.)
                        for row,base in changed['trade_features']['60'].items():
                            if row>=cut:base['balance']=-1.
                        future=interface.execute(prefix(changed,cut),config,python=True)
                        for first,second in zip(short,future):np.testing.assert_array_equal(first,second);arrays+=1
                    # 受理の真偽表はfirst actual_pendingだけで線を固定し、後q全組合せを無視する。
                    for first_accepted in (0,1):
                        for q1 in range(1,catalog.QUANTITY[symbol]+1):
                            for q2 in range(1,catalog.QUANTITY[symbol]+1):
                                events=np.zeros((2,16));events[:,0]=(1,6);events[:,1]=(0,1)
                                events[:,3]=catalog.QUANTITY[symbol];events[:,4]=(q1,q2)
                                events[:,14]=1;events[:,15]=(first_accepted,1)
                                synthetic=list(values);synthetic[0]=np.empty((0,8));synthetic[9]=events
                                anchor=goal_policy.observe_anchor(account,config,tuple(synthetic));chosen=q1 if first_accepted else q2
                                assert anchor['数量']==chosen and anchor['受理行']==(1 if first_accepted else 6)
                                assert anchor['利益目標円']==(500 if symbol=='TOPIX' else 100)*config['profit_ticks']*chosen
                                assert LOSS[symbol]*anchor['数量']/anchor['通常全量']==stop*chosen;truths+=1
                    # 二つの旧政策保存が持つ同じGU七配列だけを使い、新政策をexact復元する。
                    pair_configs=[c for c in catalog.configs() if c['mode']==config['mode']]
                    saved=[]
                    for c in pair_configs:
                        old=old_output(account,c,values)
                        old.update(shadow_GU_orders=values[0],shadow_GU_uids=values[5],execution_events=values[6],
                            execution_states=values[7],limit_events=values[8],sizing_events=values[9],sizing_fee_curve=values[10])
                        saved.append(storage.stored(old,len(account['record']['price'])))
                    restored=reuse.pair(saved[0],saved[1],len(account['record']['price']))
                    assert all(restored[i] is None for i in (1,2,3,4))
                    for index in reuse.USED:np.testing.assert_array_equal(restored[index],values[index]);arrays+=1
                    restored_output=interface.account_output('人工',account,config,restored)
                    for field in ('orders','order_uids','exit_target_uids','order_fees','equity_yen','liquidation_yen',
                                  'reserved_exit_fees','long_qty','short_qty','cumulative_fees'):
                        np.testing.assert_array_equal(restored_output[field],out[field]);arrays+=1
                    for field in ('summary','parent','control','goal_anchor','loss_anchor'):assert restored_output[field]==out[field]
                    deliberately_wrong=dict(saved[1],orders=np.empty((0,8)),equity_yen=np.full(20,999999.))
                    unchanged=reuse.pair(saved[0],deliberately_wrong,20)
                    for index in reuse.USED:np.testing.assert_array_equal(unchanged[index],restored[index]);arrays+=1
                    # NaNは同じ欠測位置だけを同値とし、数値・shape・plateau境界変更を拒否する。
                    nan_pair=copy.deepcopy(saved)
                    for ledger in nan_pair:ledger['sizing_events'][0,6]=np.nan
                    nan_shared=reuse.pair(*nan_pair,20);assert np.isnan(nan_shared[9][0,6])
                    rejects=[]
                    for label in ('片側欠測','GU値変更','normal長変更','plateau先頭欠落','plateau重複行','商品不一致'):
                        broken=copy.deepcopy(saved[1]);count=20
                        if label=='片側欠測':broken['sizing_events'][0,6]=np.nan
                        elif label=='GU値変更':broken['shadow_GU_orders'][0,5]+=tick
                        elif label=='normal長変更':count=19
                        elif label=='plateau先頭欠落':broken['execution_states']['rows'][0]=1
                        elif label=='plateau重複行':
                            block=broken['execution_states'];block['rows']=np.insert(block['rows'],1,0)
                            block['values']=np.insert(block['values'],1,block['values'][0],axis=0)
                        else:broken['key']=('人工','NK225' if symbol=='TOPIX' else 'TOPIX')
                        try:reuse.pair(saved[0],broken,count)
                        except AssertionError:rejects.append(label)
                        else:raise AssertionError('保存GU拒否漏れ:'+label)
                    assert len(rejects)==6
                    reuse_tests.append(dict(id=config['id'],商品=symbol,方向=side,七配列同値=True,未使用四槽None=True,
                        同欠測同値=True,実政策配列との取り違え無し=True,拒否例=rejects))
        assert sources=={str((SOURCE/n).relative_to(ROOT)).replace('\\','/'):digest(SOURCE/n) for n in names}
        proof=dict(全合格=True,source_SHA256=sources,独立source_SHA256=digest(Path(__file__)),源範囲SHA256=digest(scope),
            同bytes複写=clones,人工条件数=cases,配列照合数=arrays,二受理真偽表数=truths,
            初回False保持='初回人工TOP回復幅はP2目標未到達だった。経済源不変、回復幅だけ5tickへ訂正。初回script・源範囲・Falseは保持。',
            金融未測定の反例=counterexamples,保存GU復元監査=reuse_tests,
            定義='新規数量選択予算は不変。利益及び損失の線だけ初回actual_pending1のqで固定。',
            留保=['損失停止線は約定損失の上限ではない。次正常気配・spread・実料で超過できる。',
                  '取消した受理qを保持するため、後続q増加の通常spread実料だけで即切り得る。',
                  '旧回復勝ちを消す人工反例があるため、第三基準の改善と黒字平均維持は未保証。',
                  '保存七配列再利用は計算節約と同値確認であり、新たな有効性の証拠ではない。'],
            正式結果読取=0,packet=0,ledger=0,API=0,原板=0,NPZ=0,金融=0,旧source及び旧JIT変更=0)
        target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,条件=cases,配列=arrays,真偽表=truths,SHA256=digest(target)),ensure_ascii=False))
    except BaseException:
        import traceback
        failure=HERE/'loss_anchor_独立人工False_v2.json';assert not failure.exists()
        failure.write_text(json.dumps(dict(全合格=False,source_SHA256=sources,原因=traceback.format_exc(),
            正式結果=0,packet=0,ledger=0,API=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
